"""Task executor for managing complete task lifecycle."""

import logging
import time
import threading
from typing import Optional, Callable
from PyQt5.QtCore import QThread, QTimer, QObject, pyqtSignal

from .task_state import TaskState, TaskStateMachine
from .step_buffer import StepBuffer
from .data_models import TaskData, StepData
from gui.persistence import TaskRepository, StepRepository, BackupManager

logger = logging.getLogger(__name__)


class TaskExecutor(QObject):
    """Manages the complete lifecycle of a task execution.
    
    This class coordinates:
    - State machine for task states
    - Step buffer for reliable data persistence
    - Database operations through repositories
    - Backup/recovery mechanisms
    - Worker thread management
    """
    
    # Signals for UI updates
    state_changed = pyqtSignal(str, str)  # old_state, new_state
    step_saved = pyqtSignal(int)  # step_num
    task_finalized = pyqtSignal(str, int, float)  # final_state, total_steps, total_time
    error_occurred = pyqtSignal(str)  # error_message
    
    def __init__(self, task_data: TaskData, task_repo: TaskRepository, 
                 step_repo: StepRepository, backup_manager: BackupManager):
        """Initialize task executor.
        
        Args:
            task_data: Task data
            task_repo: Task repository for database operations
            step_repo: Step repository for database operations
            backup_manager: Backup manager for crash recovery
        """
        super().__init__()
        
        self.session_id = task_data.session_id
        self.task_data = task_data
        self.task_repo = task_repo
        self.step_repo = step_repo
        self.backup_manager = backup_manager
        
        # Core components
        self.state_machine = TaskStateMachine(
            self.session_id,
            persistence_callback=self._persist_state_change
        )
        self.step_buffer = StepBuffer(
            self.session_id,
            self.step_repo,
            self.backup_manager,
            async_mode=True  # Use async mode for non-blocking UI
        )
        
        # Connect step buffer callback to emit signal
        self.step_buffer.set_on_step_written(self._on_step_written_to_db)
        
        # Control flags
        self.stop_requested = threading.Event()
        self.worker_thread: Optional[QThread] = None
        self.agent_runner = None  # Will be set externally
        
        # Statistics
        self.start_time: Optional[float] = None
        self.step_count: int = 0
        self._last_error: Optional[str] = None
        
        # Connect state machine listener
        self.state_machine.add_state_change_listener(self._on_state_changed)
        
        logger.info(f"TaskExecutor initialized for session {self.session_id}")
    
    def start(self):
        """Start task execution.
        
        Raises:
            RuntimeError: If task start fails
        """
        try:
            logger.info(f"Starting task execution for session {self.session_id}")
            
            # 1. Create task record in database
            self.task_repo.create_task(self.task_data)
            logger.debug(f"Task record created in database")
            
            # 2. Save task backup
            self.backup_manager.save_task_backup(
                self.session_id,
                {
                    'session_id': self.task_data.session_id,
                    'user_id': self.task_data.user_id,
                    'timestamp': self.task_data.timestamp,
                    'description': self.task_data.description,
                    'device_id': self.task_data.device_id,
                    'base_url': self.task_data.base_url,
                    'model_name': self.task_data.model_name,
                }
            )
            
            # 3. Transition state to RUNNING
            if not self.state_machine.transition_to(TaskState.RUNNING):
                raise RuntimeError("Failed to transition to RUNNING state")
            
            # 4. Record start time
            self.start_time = time.time()
            
            # 5. Reset control flags
            self.stop_requested.clear()
            self.step_count = 0
            self._last_error = None
            
            logger.info(f"Task {self.session_id} started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start task {self.session_id}: {e}", exc_info=True)
            
            # Try to transition to FAILED state
            try:
                self.state_machine.transition_to(TaskState.FAILED)
                self.task_repo.finalize_task(
                    self.session_id, TaskState.FAILED, 0, 0, str(e)
                )
            except Exception as finalize_error:
                logger.error(f"Failed to finalize failed task: {finalize_error}")
            
            self.error_occurred.emit(f"启动任务失败: {str(e)}")
            raise
    
    def stop(self):
        """Stop task execution.
        
        This initiates the stop process. The actual finalization
        happens asynchronously via _finalize_stop().
        """
        logger.info(f"Stop requested for task {self.session_id}")
        
        # 1. Set stop flag (checked by worker thread)
        self.stop_requested.set()
        
        # 2. Transition state to STOPPING
        if not self.state_machine.transition_to(TaskState.STOPPING):
            logger.warning(f"Failed to transition to STOPPING state for {self.session_id}")
            return
        
        # 3. Stop agent runner if available
        if self.agent_runner:
            try:
                self.agent_runner.stop()
                logger.debug("Agent runner stopped")
            except Exception as e:
                logger.error(f"Error stopping agent runner: {e}")
        
        # 4. Schedule finalization (give worker thread time to finish current step)
        # Check if we're in a Qt application context
        from PyQt5.QtWidgets import QApplication
        if QApplication.instance() is not None:
            # Use QTimer in Qt context
            QTimer.singleShot(100, self._finalize_stop)
        else:
            # Use threading.Timer in non-Qt context
            timer = threading.Timer(0.1, self._finalize_stop)
            timer.start()
        
        logger.info(f"Stop process initiated for task {self.session_id}")
    
    def _finalize_stop(self):
        """Finalize the stop process.
        
        This is called asynchronously after stop() to allow the worker
        thread to finish its current step.
        """
        logger.info(f"Finalizing stop for task {self.session_id}")
        
        try:
            # 1. Flush step buffer (ensure all steps are written)
            self.step_buffer.flush()
            logger.debug("Step buffer flushed")
            
            # 2. Calculate total time
            total_time = time.time() - self.start_time if self.start_time else 0
            
            # 3. Transition state to STOPPED
            if not self.state_machine.transition_to(TaskState.STOPPED):
                logger.warning(f"Failed to transition to STOPPED state for {self.session_id}")
            
            # 4. Update task final status in database
            self.task_repo.finalize_task(
                self.session_id,
                TaskState.STOPPED,
                self.step_count,
                total_time,
                "Stopped by user"
            )
            logger.info(
                f"Task {self.session_id} finalized: "
                f"steps={self.step_count}, time={total_time:.2f}s"
            )
            
            # 5. Clean up backup files
            self.backup_manager.cleanup_backup(self.session_id)
            
            # 6. Emit signal for UI update
            self.task_finalized.emit(TaskState.STOPPED.value, self.step_count, total_time)
            
            # 7. Clean up resources
            self._cleanup()
            
        except Exception as e:
            logger.error(f"Error finalizing stopped task {self.session_id}: {e}", exc_info=True)
            self.error_occurred.emit(f"停止任务时出错: {str(e)}")
    
    def on_step_completed(self, step_num: int, screenshot_path: Optional[str],
                         screenshot_analysis: Optional[str], action: Optional[dict],
                         action_params: Optional[dict], execution_time: Optional[float],
                         success: bool, message: str, thinking: Optional[str]):
        """Handle step completion event.
        
        Args:
            step_num: Step number
            screenshot_path: Path to screenshot
            screenshot_analysis: Analysis of screenshot
            action: Action taken
            action_params: Action parameters
            execution_time: Execution time in seconds
            success: Whether step succeeded
            message: Step message
            thinking: Thinking process
        """
        # Check if stop was requested - ignore post-stop steps
        if self.stop_requested.is_set():
            logger.debug(f"Ignoring step {step_num} - stop requested")
            return
        
        # NOTE: We no longer check if task is in RUNNING state here
        # Because step_completed signal may arrive after task_completed due to async timing
        # The step data should still be saved to database for completeness
        current_state = self.state_machine.get_state()
        if current_state not in (TaskState.RUNNING, TaskState.SUCCESS, TaskState.FAILED):
            logger.warning(
                f"Ignoring step {step_num} - task in unexpected state "
                f"(current: {current_state})"
            )
            return
        
        logger.debug(f"Processing step {step_num} for task {self.session_id}")
        
        try:
            # Update step count
            self.step_count = max(self.step_count, step_num)
            
            # Create step data
            step_data = StepData(
                session_id=self.session_id,
                step_num=step_num,
                screenshot_path=screenshot_path,
                screenshot_analysis=screenshot_analysis,
                action=action,
                action_params=action_params,
                execution_time=execution_time,
                success=success,
                message=message,
                thinking=thinking,
            )
            
            # Add to buffer (async write - non-blocking)
            # Signal will be emitted by _on_step_written_to_db callback
            self.step_buffer.add_step(step_data)
            
            logger.info(f"Step {step_num} queued for task {self.session_id}")
            
        except Exception as e:
            logger.error(
                f"Error processing step {step_num} for task {self.session_id}: {e}",
                exc_info=True
            )
            # Don't raise - we want to continue processing other steps
            self.error_occurred.emit(f"保存步骤 {step_num} 失败: {str(e)}")
    
    def on_task_completed(self, success: bool, error_msg: Optional[str] = None):
        """Handle task completion event.
        
        Args:
            success: Whether task completed successfully
            error_msg: Error message if task failed
        """
        logger.info(
            f"Task {self.session_id} completed: success={success}, "
            f"steps={self.step_count}"
        )
        
        try:
            # 1. Flush step buffer
            self.step_buffer.flush()
            logger.debug("Step buffer flushed")
            
            # 2. Calculate total time
            total_time = time.time() - self.start_time if self.start_time else 0
            
            # 3. Determine final state
            final_state = TaskState.SUCCESS if success else TaskState.FAILED
            
            # 4. Transition state
            if not self.state_machine.transition_to(final_state):
                logger.warning(
                    f"Failed to transition to {final_state} state for {self.session_id}"
                )
            
            # 5. Update task final status in database
            self.task_repo.finalize_task(
                self.session_id,
                final_state,
                self.step_count,
                total_time,
                error_msg
            )
            logger.info(
                f"Task {self.session_id} finalized: "
                f"state={final_state.value}, steps={self.step_count}, time={total_time:.2f}s"
            )
            
            # 6. Clean up backup files
            self.backup_manager.cleanup_backup(self.session_id)
            
            # 7. Emit signal for UI update
            self.task_finalized.emit(final_state.value, self.step_count, total_time)
            
            # 8. Clean up resources
            self._cleanup()
            
        except Exception as e:
            logger.error(
                f"Error finalizing completed task {self.session_id}: {e}",
                exc_info=True
            )
            self.error_occurred.emit(f"完成任务时出错: {str(e)}")
    
    def _cleanup(self):
        """Clean up resources.
        
        This is called after task finalization (success, failure, or stop).
        """
        logger.debug(f"Cleaning up resources for task {self.session_id}")
        
        # Close step buffer (stops writer thread)
        if self.step_buffer:
            try:
                self.step_buffer.close()
            except Exception as e:
                logger.error(f"Error closing step buffer: {e}")
        
        # Clean up worker thread if exists
        if self.worker_thread:
            try:
                if self.worker_thread.isRunning():
                    self.worker_thread.quit()
                    if not self.worker_thread.wait(1000):  # Wait max 1 second
                        logger.warning("Worker thread did not quit in time")
                self.worker_thread = None
            except Exception as e:
                logger.error(f"Error cleaning up worker thread: {e}")
        
        # Clear agent runner reference
        self.agent_runner = None
        
        logger.debug(f"Cleanup complete for task {self.session_id}")
    
    def _on_step_written_to_db(self, step_num: int):
        """Callback when step is written to database by async writer.
        
        Args:
            step_num: Step number that was written
        """
        # Emit signal for UI update (thread-safe via Qt signal)
        self.step_saved.emit(step_num)
        logger.debug(f"Step {step_num} written to database (async)")
    
    def _persist_state_change(self, session_id: str, new_state: TaskState):
        """Callback for state machine to persist state changes.
        
        Args:
            session_id: Session identifier
            new_state: New task state
        """
        try:
            self.task_repo.update_task_state(session_id, new_state)
            logger.debug(f"Persisted state change to {new_state.value}")
        except Exception as e:
            logger.error(f"Failed to persist state change: {e}", exc_info=True)
            # Don't raise - state machine has already transitioned
            # The backup system will help recover if needed
    
    def _on_state_changed(self, old_state: TaskState, new_state: TaskState):
        """Listener for state changes.
        
        Args:
            old_state: Previous state
            new_state: New state
        """
        logger.info(f"Task {self.session_id} state changed: {old_state} -> {new_state}")
        
        # Emit signal for UI update
        self.state_changed.emit(old_state.value, new_state.value)
    
    def get_current_state(self) -> TaskState:
        """Get current task state.
        
        Returns:
            Current task state
        """
        return self.state_machine.get_state()
    
    def is_active(self) -> bool:
        """Check if task is actively running.
        
        Returns:
            True if task is running or stopping
        """
        return self.state_machine.is_active()
    
    def is_terminal(self) -> bool:
        """Check if task is in terminal state.
        
        Returns:
            True if task is finished
        """
        return self.state_machine.is_terminal()
    
    def get_step_count(self) -> int:
        """Get current step count.
        
        Returns:
            Number of steps executed
        """
        return self.step_count
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since task start.
        
        Returns:
            Elapsed time in seconds
        """
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time
