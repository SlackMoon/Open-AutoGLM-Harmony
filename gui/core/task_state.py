"""Task state machine for managing task lifecycle."""

import logging
import threading
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class TaskState(Enum):
    """Task execution states."""
    
    CREATED = "CREATED"       # Task has been created
    RUNNING = "RUNNING"       # Task is executing
    STOPPING = "STOPPING"     # Task is being stopped
    STOPPED = "STOPPED"       # Task has been stopped by user
    SUCCESS = "SUCCESS"       # Task completed successfully
    FAILED = "FAILED"         # Task failed with error
    CRASHED = "CRASHED"       # System crashed during execution
    
    def __str__(self):
        return self.value
    
    @property
    def display_name(self):
        """Get display name for UI."""
        names = {
            TaskState.CREATED: "已创建",
            TaskState.RUNNING: "执行中",
            TaskState.STOPPING: "停止中",
            TaskState.STOPPED: "已停止",
            TaskState.SUCCESS: "成功",
            TaskState.FAILED: "失败",
            TaskState.CRASHED: "崩溃",
        }
        return names.get(self, self.value)
    
    @property
    def is_terminal(self):
        """Check if this is a terminal state (task finished)."""
        return self in (TaskState.STOPPED, TaskState.SUCCESS, TaskState.FAILED, TaskState.CRASHED)
    
    @property
    def is_active(self):
        """Check if task is actively running."""
        return self in (TaskState.RUNNING, TaskState.STOPPING)


class TaskStateMachine:
    """Manages task state transitions with validation and persistence."""
    
    # Valid state transitions
    VALID_TRANSITIONS = {
        TaskState.CREATED: [TaskState.RUNNING, TaskState.FAILED],
        TaskState.RUNNING: [TaskState.STOPPING, TaskState.SUCCESS, TaskState.FAILED],
        TaskState.STOPPING: [TaskState.STOPPED, TaskState.FAILED],
        # Terminal states can only transition to CRASHED (system crash)
        TaskState.STOPPED: [TaskState.CRASHED],
        TaskState.SUCCESS: [TaskState.CRASHED],
        TaskState.FAILED: [TaskState.CRASHED],
    }
    
    def __init__(self, session_id: str, persistence_callback: Optional[Callable] = None):
        """Initialize state machine.
        
        Args:
            session_id: Unique session identifier
            persistence_callback: Function to call when state changes (session_id, new_state)
        """
        self.session_id = session_id
        self.current_state = TaskState.CREATED
        self.persistence_callback = persistence_callback
        self.lock = threading.Lock()
        self._state_change_listeners = []
        
        logger.info(f"TaskStateMachine initialized for session {session_id} in state {self.current_state}")
    
    def transition_to(self, new_state: TaskState) -> bool:
        """Attempt to transition to a new state.
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition successful, False otherwise
        """
        with self.lock:
            if not self._is_valid_transition(new_state):
                logger.warning(
                    f"Invalid state transition: {self.current_state} -> {new_state} "
                    f"for session {self.session_id}"
                )
                return False
            
            old_state = self.current_state
            self.current_state = new_state
            
            logger.info(
                f"State transition: {old_state} -> {new_state} "
                f"for session {self.session_id}"
            )
            
            # Persist state change immediately
            if self.persistence_callback:
                try:
                    self.persistence_callback(self.session_id, new_state)
                except Exception as e:
                    logger.error(
                        f"Failed to persist state change for session {self.session_id}: {e}",
                        exc_info=True
                    )
                    # Don't rollback state - we've already transitioned
                    # The persistence layer should handle retries/backups
            
            # Notify listeners
            self._emit_state_changed(old_state, new_state)
            
            return True
    
    def _is_valid_transition(self, new_state: TaskState) -> bool:
        """Check if transition to new state is valid.
        
        Args:
            new_state: Target state
            
        Returns:
            True if transition is valid
        """
        # Allow transition to CRASHED from any state (system crash)
        if new_state == TaskState.CRASHED:
            return True
        
        valid_next_states = self.VALID_TRANSITIONS.get(self.current_state, [])
        return new_state in valid_next_states
    
    def get_state(self) -> TaskState:
        """Get current state (thread-safe).
        
        Returns:
            Current task state
        """
        with self.lock:
            return self.current_state
    
    def is_terminal(self) -> bool:
        """Check if current state is terminal.
        
        Returns:
            True if task is finished
        """
        with self.lock:
            return self.current_state.is_terminal
    
    def is_active(self) -> bool:
        """Check if task is actively running.
        
        Returns:
            True if task is running or stopping
        """
        with self.lock:
            return self.current_state.is_active
    
    def add_state_change_listener(self, listener: Callable):
        """Add a listener for state changes.
        
        Args:
            listener: Callback function(old_state, new_state)
        """
        self._state_change_listeners.append(listener)
    
    def _emit_state_changed(self, old_state: TaskState, new_state: TaskState):
        """Notify all listeners of state change.
        
        Args:
            old_state: Previous state
            new_state: New state
        """
        for listener in self._state_change_listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                logger.error(f"Error in state change listener: {e}", exc_info=True)
