"""Task execution integration module for MainWindow.

This module provides a mixin class that can be used to integrate the new
TaskExecutor system into the existing MainWindow without major refactoring.

Usage:
    1. Import this module in main_window.py
    2. Call init_task_execution_v2() in MainWindow.__init__()
    3. Replace _start_task() and _stop_task() with the new versions
"""

import logging
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QThread, QTimer, Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

from gui.core import TaskData, TaskExecutor, TaskState
from gui.persistence import ConnectionPool, TaskRepository, StepRepository, BackupManager
from gui.utils.crash_recovery import recover_crashed_tasks

logger = logging.getLogger(__name__)


def _get_logs_dir() -> str:
    """Get the logs directory path (always in Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe (dist/GUI.exe)
        return str(Path(sys.executable).parent.parent / "logs")
    else:
        return "logs"


class TaskExecutionV2Mixin:
    """Mixin class providing new task execution functionality.
    
    This mixin can be added to MainWindow to provide the new TaskExecutor
    integration while maintaining backward compatibility.
    """
    
    def init_task_execution_v2(self):
        """Initialize the new task execution system.
        
        Call this in MainWindow.__init__() after other initialization.
        """
        # Initialize persistence layer
        self._init_persistence_layer_v2()
        
        # Task executor (created per task)
        self.task_executor: Optional[TaskExecutor] = None
        
        # Recover crashed tasks
        QTimer.singleShot(1000, self._recover_crashed_tasks_v2)
        
        logger.info("Task execution V2 initialized")
    
    def _init_persistence_layer_v2(self):
        """Initialize the persistence layer components."""
        logs_dir = _get_logs_dir()
        try:
            # Create connection pool
            self.connection_pool_v2 = ConnectionPool(f"{logs_dir}/tasks.db", pool_size=5)
            
            # Create repositories
            self.task_repo_v2 = TaskRepository(self.connection_pool_v2)
            self.step_repo_v2 = StepRepository(self.connection_pool_v2)
            
            # Create backup manager
            self.backup_manager_v2 = BackupManager(f"{logs_dir}/backup")
            
            logger.info("Persistence layer V2 initialized")
        except Exception as e:
            logger.error(f"Failed to initialize persistence layer V2: {e}", exc_info=True)
            # Don't crash - allow app to start with old system
    
    def _recover_crashed_tasks_v2(self):
        """Recover tasks that crashed in previous sessions."""
        if not hasattr(self, 'task_repo_v2'):
            return
        
        try:
            recovered = recover_crashed_tasks(
                self.task_repo_v2, 
                self.step_repo_v2, 
                self.backup_manager_v2
            )
            
            if recovered:
                logger.info(f"Recovered {len(recovered)} crashed tasks")
                self._show_recovery_notification_v2(recovered)
        except Exception as e:
            logger.error(f"Error during crash recovery: {e}", exc_info=True)
    
    def _show_recovery_notification_v2(self, recovered: list):
        """Show notification about recovered tasks."""
        if not recovered:
            return
        
        msg = f"检测到 {len(recovered)} 个上次崩溃的任务已恢复"
        
        # Log to log viewer if available
        if hasattr(self, 'log_viewer'):
            self.log_viewer.log_info(msg)
    
    def _start_task_v2(self):
        """Start task execution using new TaskExecutor.
        
        This replaces the old _start_task() method.
        """
        task = self.task_input.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "警告", "请输入任务描述")
            return
        
        # Validate task length
        if len(task) > 5000:
            QMessageBox.warning(
                self, "任务过长", 
                f"任务描述过长 ({len(task)} 字符)，请控制在 5000 字符以内"
            )
            return

        base_url = self.base_url_input.text().strip()
        model_name = self.model_input.text().strip()
        api_key = self.api_key_input.text().strip()

        # Validate configuration
        is_valid, error_msg = self._validate_config(base_url, model_name, api_key)
        if not is_valid:
            QMessageBox.critical(self, "配置错误", error_msg)
            return

        # Save settings
        self._save_settings()

        # Check if persistence layer is available
        if not hasattr(self, 'task_repo_v2'):
            logger.warning("Persistence layer V2 not available, falling back to old system")
            return self._start_task_legacy()

        # Create task data
        task_data = TaskData.create(
            description=task,
            user_id="local_pc",
            device_id=self.selected_device_id,
            base_url=base_url,
            model_name=model_name,
        )

        # Create task executor
        self.task_executor = TaskExecutor(
            task_data=task_data,
            task_repo=self.task_repo_v2,
            step_repo=self.step_repo_v2,
            backup_manager=self.backup_manager_v2,
        )

        # Connect executor signals
        self.task_executor.state_changed.connect(self._on_executor_state_changed_v2)
        self.task_executor.step_saved.connect(self._on_executor_step_saved_v2)
        self.task_executor.task_finalized.connect(self._on_executor_task_finalized_v2)
        self.task_executor.error_occurred.connect(self._on_executor_error_v2)

        # Create agent runner
        from gui.utils.agent_runner import AgentRunner
        
        self.agent_thread = QThread()
        self.agent_runner = AgentRunner(
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            device_id=self.selected_device_id,
            max_steps=100,
            lang="cn",
            notify=True,
            task_logger=self.task_logger,
        )
        self.agent_runner.moveToThread(self.agent_thread)

        # Connect agent signals
        self.agent_runner.thinking_received.connect(
            self._on_thinking_received, Qt.QueuedConnection
        )
        self.agent_runner.action_received.connect(
            self._on_action_received, Qt.QueuedConnection
        )
        self.agent_runner.step_completed.connect(
            self._on_step_completed_v2, Qt.QueuedConnection
        )
        self.agent_runner.task_completed.connect(
            self._on_task_completed_v2, Qt.QueuedConnection
        )
        self.agent_runner.error_occurred.connect(
            self._on_error_occurred, Qt.QueuedConnection
        )
        self.agent_runner.progress_updated.connect(
            self._on_progress_updated, Qt.QueuedConnection
        )

        # Set executor references
        self.task_executor.agent_runner = self.agent_runner
        self.task_executor.worker_thread = self.agent_thread

        # Connect thread signals
        self.agent_thread.started.connect(lambda: self._run_task_in_thread(task))
        self.agent_thread.finished.connect(self._on_thread_finished)

        # Start task executor
        try:
            self.task_executor.start()
        except Exception as e:
            QMessageBox.critical(self, "启动失败", f"任务启动失败: {e}")
            self._cleanup_task_v2()
            return

        # Update UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("状态: 运行中")
        self.status_label.setStyleSheet("color: #4CAF50;")
        self.log_viewer.log_system(f"开始执行任务: {task}")
        
        # Reset thinking state
        self._thinking_stream_active = False
        self._current_step_thinking = []
        
        # Disable config controls
        self._disable_config_controls()
        
        # Force UI update
        QApplication.processEvents()

        # Start thread
        self.agent_thread.start()
    
    def _stop_task_v2(self):
        """Stop task execution using TaskExecutor.
        
        This replaces the old _stop_task() method.
        """
        if not self.task_executor:
            return
        
        # Disable stop button immediately
        self.stop_btn.setEnabled(False)
        self.log_viewer.log_system("正在停止任务...")
        
        # Update UI
        self.status_label.setText("状态: 正在停止...")
        self.status_label.setStyleSheet("color: #ff9800;")
        
        # Force UI update
        QApplication.processEvents()
        
        # Stop via executor
        try:
            self.task_executor.stop()
        except Exception as e:
            logger.error(f"Error stopping task: {e}", exc_info=True)
            self.log_viewer.log_error(f"停止任务时出错: {e}")
            self._cleanup_task_v2()
    
    def _on_step_completed_v2(self, step_num: int, message: str, success: bool, screenshot_path: str = None):
        """Handle step completion using TaskExecutor."""
        if not self.task_executor:
            return
        
        # Get accumulated thinking
        thinking = "\n".join(self._current_step_thinking) if self._current_step_thinking else None
        
        # Get last action
        action = self._last_action if hasattr(self, '_last_action') else None
        
        # Forward to executor
        self.task_executor.on_step_completed(
            step_num=step_num,
            screenshot_path=screenshot_path,
            screenshot_analysis=None,
            action=action,
            action_params=None,
            execution_time=0.5,
            success=success,
            message=message,
            thinking=thinking,
        )
        
        # Reset for next step
        self._current_step_thinking = []
        self._last_action = None
        
        # Update UI (keep existing behavior)
        self.log_viewer.log_step(step_num, message, success)
        self.progress_label.setText(f"步骤 {step_num}: {message[:50]}...")
    
    def _on_task_completed_v2(self, success: bool, message: str):
        """Handle task completion using TaskExecutor."""
        if not self.task_executor:
            return
        
        # Forward to executor
        error_msg = message if not success else None
        self.task_executor.on_task_completed(success=success, error_msg=error_msg)
        
        # Log (keep existing behavior)
        if success:
            self.log_viewer.log_success(f"任务完成: {message}")
        else:
            self.log_viewer.log_error(f"任务失败: {message}")
    
    def _on_executor_state_changed_v2(self, old_state: str, new_state: str):
        """Handle state changes from executor."""
        logger.info(f"Task state: {old_state} -> {new_state}")
        self.log_viewer.log_info(f"任务状态: {old_state} -> {new_state}")
        
        # Update status label
        state_display = {
            "CREATED": ("已创建", "#2196F3"),
            "RUNNING": ("运行中", "#4CAF50"),
            "STOPPING": ("正在停止...", "#ff9800"),
            "STOPPED": ("已停止", "#ff9800"),
            "SUCCESS": ("成功", "#4CAF50"),
            "FAILED": ("失败", "#f44336"),
            "CRASHED": ("崩溃", "#f44336"),
        }
        
        display_text, color = state_display.get(new_state, (new_state, "#666"))
        self.status_label.setText(f"状态: {display_text}")
        self.status_label.setStyleSheet(f"color: {color};")
    
    def _on_executor_step_saved_v2(self, step_num: int):
        """Handle step saved notification."""
        logger.debug(f"Step {step_num} saved to database")
        self.log_viewer.log_success(f"✅ 步骤 {step_num} 已保存")
    
    def _on_executor_task_finalized_v2(self, final_state: str, total_steps: int, total_time: float):
        """Handle task finalization."""
        logger.info(f"Task finalized: {final_state}, {total_steps} steps, {total_time:.2f}s")
        
        # Update UI
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._enable_config_controls()
        
        # Show completion message
        if final_state == "SUCCESS":
            self.log_viewer.log_success(f"✅ 任务完成: {total_steps} 步, 耗时 {total_time:.2f} 秒")
            self.progress_label.setText(f"任务完成 ({total_steps} 步)")
        elif final_state == "STOPPED":
            self.log_viewer.log_info(f"⏹️ 任务已停止: {total_steps} 步, 耗时 {total_time:.2f} 秒")
            self.progress_label.setText(f"任务已停止 ({total_steps} 步)")
        elif final_state == "FAILED":
            self.log_viewer.log_error(f"❌ 任务失败: {total_steps} 步, 耗时 {total_time:.2f} 秒")
            self.progress_label.setText(f"任务失败 ({total_steps} 步)")
        
        # Refresh data storage
        if hasattr(self, 'data_storage_widget'):
            self.data_storage_widget.refresh_task_list()
        
        # Cleanup
        self._cleanup_task_v2()
    
    def _on_executor_error_v2(self, error_msg: str):
        """Handle error from executor."""
        logger.error(f"Executor error: {error_msg}")
        self.log_viewer.log_error(f"❌ {error_msg}")
    
    def _cleanup_task_v2(self):
        """Clean up task resources."""
        # Disconnect agent signals
        if self.agent_runner:
            try:
                self.agent_runner.thinking_received.disconnect()
            except:
                pass
            try:
                self.agent_runner.action_received.disconnect()
            except:
                pass
            try:
                self.agent_runner.step_completed.disconnect()
            except:
                pass
            try:
                self.agent_runner.task_completed.disconnect()
            except:
                pass
            try:
                self.agent_runner.error_occurred.disconnect()
            except:
                pass
            try:
                self.agent_runner.progress_updated.disconnect()
            except:
                pass
            
            self.agent_runner.deleteLater()
            self.agent_runner = None
        
        # Clean up thread
        if self.agent_thread:
            if self.agent_thread.isRunning():
                self.agent_thread.quit()
                self.agent_thread.wait(1000)
            self.agent_thread.deleteLater()
            self.agent_thread = None
        
        # Disconnect executor signals
        if self.task_executor:
            try:
                self.task_executor.state_changed.disconnect()
            except:
                pass
            try:
                self.task_executor.step_saved.disconnect()
            except:
                pass
            try:
                self.task_executor.task_finalized.disconnect()
            except:
                pass
            try:
                self.task_executor.error_occurred.disconnect()
            except:
                pass
            
            self.task_executor = None
        
        # Reset state
        self._thinking_stream_active = False
        self._current_step_thinking = []
        if hasattr(self, '_last_action'):
            self._last_action = None
    
    def _start_task_legacy(self):
        """Fallback to legacy task execution if V2 not available."""
        # This should call the original _start_task implementation
        # For now, just log a warning
        logger.warning("Legacy task execution not implemented in mixin")
        QMessageBox.warning(self, "警告", "新任务系统未初始化，请重启应用")
    
    def close_persistence_v2(self):
        """Close persistence layer on app exit.
        
        Call this in MainWindow.closeEvent().
        """
        if hasattr(self, 'connection_pool_v2'):
            self.connection_pool_v2.close_all()
