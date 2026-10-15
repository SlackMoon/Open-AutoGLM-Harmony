"""Main window for Open-AutoGLM GUI application - V2 with new task execution system.

This version integrates the new TaskExecutor for reliable task execution and data persistence.
"""

import base64
import json
import re
import time
import uuid
import logging
from typing import Optional
from pathlib import Path

from PyQt5.QtCore import QObject, QSettings, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.utils.agent_runner import AgentRunner
from gui.utils.system_checker import check_model_api, run_all_checks, CheckResult
from gui.utils.task_logger import TaskLogger
from gui.widgets.log_viewer import LogViewer
from gui.widgets.data_storage import DataStorageWidget
from phone_agent.adb import ADBConnection, list_devices

# New task execution system imports
from gui.core import TaskData, TaskExecutor, TaskState
from gui.persistence import ConnectionPool, TaskRepository, StepRepository, BackupManager
from gui.utils.crash_recovery import recover_crashed_tasks

logger = logging.getLogger(__name__)


class ModelAPICheckWorker(QThread):
    """后台线程用于执行模型 API 检查"""
    finished = pyqtSignal(bool, object)  # success, CheckResult

    def __init__(self, base_url: str, model_name: str, api_key: str):
        super().__init__()
        self.base_url = base_url
        self.model_name = model_name
        self.api_key = api_key

    def run(self):
        """执行 API 检查"""
        try:
            result = check_model_api(self.base_url, self.model_name, self.api_key)
            self.finished.emit(result.success, result)
        except Exception as e:
            error_result = CheckResult(
                success=False,
                message=f"检查异常: {str(e)}",
                details=str(e),
            )
            self.finished.emit(False, error_result)


class MainWindowV2(QWidget):
    """Main window with new task execution system."""

    def __init__(self):
        """Initialize the main window."""
        super().__init__()

        self.settings = QSettings("Open-AutoGLM", "GUI")
        self.adb_connection = ADBConnection()
        self.agent_runner: Optional[AgentRunner] = None
        self.agent_thread: Optional[QThread] = None
        self.selected_device_id: Optional[str] = None
        
        # Check status tracking
        self.check_status: dict[str, bool] = {}
        self.check_timers: dict[str, QTimer] = {}
        self.check_threads: dict[str, object] = {}
        
        # Thinking stream state
        self._thinking_stream_active = False
        self._current_step_thinking: list[str] = []
        self._last_action: Optional[dict] = None
        
        # Initialize new persistence layer
        self._init_persistence_layer()
        
        # Task executor (created per task)
        self.task_executor: Optional[TaskExecutor] = None
        
        # Legacy task logger (for compatibility with existing code)
        self.task_logger = TaskLogger(log_dir="logs")

        self._setup_ui()
        self._load_settings()
        self._setup_timers()
        self._connect_signals()
        self._init_check_status()
        
        # Recover any crashed tasks from previous sessions
        self._recover_crashed_tasks()

    def _init_persistence_layer(self):
        """Initialize the new persistence layer components."""
        try:
            # Create connection pool
            self.connection_pool = ConnectionPool("logs/tasks.db", pool_size=5)
            
            # Create repositories
            self.task_repo = TaskRepository(self.connection_pool)
            self.step_repo = StepRepository(self.connection_pool)
            
            # Create backup manager
            self.backup_manager = BackupManager("logs/backup")
            
            logger.info("Persistence layer initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize persistence layer: {e}", exc_info=True)
            # Show error but don't crash - allow app to start
            QTimer.singleShot(1000, lambda: QMessageBox.warning(
                self, "警告", f"数据持久化层初始化失败: {e}\n任务数据可能无法保存。"
            ))

    def _recover_crashed_tasks(self):
        """Recover tasks that crashed in previous sessions."""
        try:
            recovered = recover_crashed_tasks(
                self.task_repo, 
                self.step_repo, 
                self.backup_manager
            )
            
            if recovered:
                logger.info(f"Recovered {len(recovered)} crashed tasks")
                # Show notification after UI is ready
                QTimer.singleShot(2000, lambda: self._show_recovery_notification(recovered))
        except Exception as e:
            logger.error(f"Error during crash recovery: {e}", exc_info=True)

    def _show_recovery_notification(self, recovered: list):
        """Show notification about recovered tasks."""
        if not recovered:
            return
        
        msg = f"检测到 {len(recovered)} 个上次崩溃的任务已恢复:\n\n"
        for task in recovered[:5]:  # Show max 5
            msg += f"• {task.get('description', '未知任务')[:30]}... ({task.get('total_steps', 0)} 步)\n"
        
        if len(recovered) > 5:
            msg += f"\n... 还有 {len(recovered) - 5} 个任务"
        
        QMessageBox.information(self, "任务恢复", msg)

    # ==================== Task Execution Methods (New System) ====================

    def _start_task(self):
        """Start task execution using new TaskExecutor."""
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
            task_repo=self.task_repo,
            step_repo=self.step_repo,
            backup_manager=self.backup_manager,
        )

        # Connect executor signals
        self.task_executor.state_changed.connect(self._on_executor_state_changed)
        self.task_executor.step_saved.connect(self._on_executor_step_saved)
        self.task_executor.task_finalized.connect(self._on_executor_task_finalized)
        self.task_executor.error_occurred.connect(self._on_executor_error)

        # Create agent runner
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
            self._cleanup_task()
            return

        # Update UI
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("状态: 运行中")
        self.status_label.setStyleSheet("color: #4CAF50;")
        self.log_viewer.log_system(f"开始执行任务: {task}")
        self._thinking_stream_active = False
        self._current_step_thinking = []
        
        # Disable config controls
        self._disable_config_controls()
        
        # Force UI update
        QApplication.processEvents()

        # Start thread
        self.agent_thread.start()

    def _stop_task(self):
        """Stop task execution using TaskExecutor."""
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
        
        # Stop via executor (handles everything)
        try:
            self.task_executor.stop()
        except Exception as e:
            logger.error(f"Error stopping task: {e}", exc_info=True)
            self.log_viewer.log_error(f"停止任务时出错: {e}")
            # Force cleanup
            self._cleanup_task()

    def _run_task_in_thread(self, task: str):
        """Run task in background thread."""
        try:
            self.agent_runner.progress_updated.emit("任务已启动，正在初始化...")
            QThread.currentThread().msleep(100)
            self.agent_runner.run_task(task)
        except Exception as e:
            error_msg = f"任务启动失败: {str(e)}"
            self.agent_runner.error_occurred.emit(error_msg)
            import traceback
            self.agent_runner.progress_updated.emit(f"错误详情:\n{traceback.format_exc()}")
        finally:
            if self.agent_thread:
                self.agent_thread.quit()

    # ==================== Executor Signal Handlers ====================

    def _on_executor_state_changed(self, old_state: str, new_state: str):
        """Handle task state changes from executor."""
        logger.info(f"Task state changed: {old_state} -> {new_state}")
        self.log_viewer.log_info(f"任务状态: {old_state} -> {new_state}")
        
        # Update status label based on state
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

    def _on_executor_step_saved(self, step_num: int):
        """Handle step saved notification from executor."""
        logger.debug(f"Step {step_num} saved")
        self.log_viewer.log_success(f"✅ 步骤 {step_num} 已保存到数据库")

    def _on_executor_task_finalized(self, final_state: str, total_steps: int, total_time: float):
        """Handle task finalization from executor."""
        logger.info(f"Task finalized: state={final_state}, steps={total_steps}, time={total_time:.2f}s")
        
        # Update UI
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._enable_config_controls()
        
        # Show completion message
        if final_state == "SUCCESS":
            self.log_viewer.log_success(
                f"✅ 任务完成: {total_steps} 步, 耗时 {total_time:.2f} 秒"
            )
            self.progress_label.setText(f"任务完成 ({total_steps} 步)")
        elif final_state == "STOPPED":
            self.log_viewer.log_info(
                f"⏹️ 任务已停止: {total_steps} 步, 耗时 {total_time:.2f} 秒"
            )
            self.progress_label.setText(f"任务已停止 ({total_steps} 步)")
        elif final_state == "FAILED":
            self.log_viewer.log_error(
                f"❌ 任务失败: {total_steps} 步, 耗时 {total_time:.2f} 秒"
            )
            self.progress_label.setText(f"任务失败 ({total_steps} 步)")
        
        # Refresh data storage widget
        if hasattr(self, 'data_storage_widget'):
            self.data_storage_widget.refresh_task_list()
        
        # Cleanup
        self._cleanup_task()

    def _on_executor_error(self, error_msg: str):
        """Handle error from executor."""
        logger.error(f"Executor error: {error_msg}")
        self.log_viewer.log_error(f"❌ {error_msg}")

    # ==================== Agent Signal Handlers (V2) ====================

    def _on_step_completed_v2(self, step_num: int, message: str, success: bool, screenshot_path: str = None):
        """Handle step completion - V2 using TaskExecutor."""
        if not self.task_executor:
            return
        
        # Get accumulated thinking for this step
        thinking = "\n".join(self._current_step_thinking) if self._current_step_thinking else None
        
        # Get last action
        action = self._last_action
        
        # Calculate execution time (approximate)
        execution_time = 0.5  # Default
        
        # Forward to executor
        self.task_executor.on_step_completed(
            step_num=step_num,
            screenshot_path=screenshot_path,
            screenshot_analysis=None,  # Not available from current signal
            action=action,
            action_params=None,
            execution_time=execution_time,
            success=success,
            message=message,
            thinking=thinking,
        )
        
        # Reset thinking accumulator for next step
        self._current_step_thinking = []
        self._last_action = None
        
        # Update UI
        self.log_viewer.log_step(step_num, message, success)
        self.progress_label.setText(f"步骤 {step_num}: {message[:50]}...")

    def _on_task_completed_v2(self, success: bool, message: str):
        """Handle task completion - V2 using TaskExecutor."""
        if not self.task_executor:
            return
        
        # Forward to executor
        error_msg = message if not success else None
        self.task_executor.on_task_completed(success=success, error_msg=error_msg)
        
        # Log
        if success:
            self.log_viewer.log_success(f"任务完成: {message}")
        else:
            self.log_viewer.log_error(f"任务失败: {message}")

    def _on_thinking_received(self, thinking: str):
        """Handle thinking stream from agent."""
        # Accumulate thinking for current step
        self._current_step_thinking.append(thinking)
        
        # Update log viewer
        if not self._thinking_stream_active:
            self._thinking_stream_active = True
            self.log_viewer.log_thinking_start()
        
        self.log_viewer.log_thinking_chunk(thinking)

    def _on_action_received(self, action: dict):
        """Handle action from agent."""
        self._last_action = action
        
        # End thinking stream
        if self._thinking_stream_active:
            self._thinking_stream_active = False
            self.log_viewer.log_thinking_end()
        
        # Log action
        action_type = action.get("type", "unknown")
        self.log_viewer.log_action(action_type, action)

    def _on_error_occurred(self, error: str):
        """Handle error from agent."""
        self.log_viewer.log_error(error)

    def _on_progress_updated(self, progress: str):
        """Handle progress update from agent."""
        self.progress_label.setText(progress)

    def _on_thread_finished(self):
        """Handle thread finished."""
        logger.debug("Agent thread finished")

    # ==================== Cleanup ====================

    def _cleanup_task(self):
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
        self._last_action = None

    def closeEvent(self, event):
        """Handle window close."""
        # Stop any running task
        if self.task_executor and self.task_executor.is_active():
            reply = QMessageBox.question(
                self, "确认退出",
                "任务正在运行中，确定要退出吗？\n任务数据将被保存。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                event.ignore()
                return
            
            # Stop task
            self.task_executor.stop()
            # Wait a bit for finalization
            QApplication.processEvents()
            QThread.msleep(500)
        
        # Close connection pool
        if hasattr(self, 'connection_pool'):
            self.connection_pool.close_all()
        
        # Save settings
        self._save_settings()
        
        event.accept()

    # ==================== UI Control Methods ====================

    def _disable_config_controls(self):
        """Disable configuration controls during task execution."""
        self.base_url_input.setEnabled(False)
        self.model_input.setEnabled(False)
        self.api_key_input.setEnabled(False)
        self.device_combo.setEnabled(False)
        self.refresh_devices_btn.setEnabled(False)
        self.adb_check_btn.setEnabled(False)
        self.keyboard_check_btn.setEnabled(False)
        self.api_check_btn.setEnabled(False)

    def _enable_config_controls(self):
        """Enable configuration controls after task completion."""
        self.base_url_input.setEnabled(True)
        self.model_input.setEnabled(True)
        self.api_key_input.setEnabled(True)
        self.device_combo.setEnabled(True)
        self.refresh_devices_btn.setEnabled(True)
        self.adb_check_btn.setEnabled(True)
        self.keyboard_check_btn.setEnabled(True)
        self.api_check_btn.setEnabled(True)

    # ==================== Placeholder Methods (to be copied from original) ====================
    # These methods need to be copied from the original main_window.py:
    # - _setup_ui()
    # - _load_settings()
    # - _save_settings()
    # - _setup_timers()
    # - _connect_signals()
    # - _init_check_status()
    # - _validate_config()
    # - All UI setup methods
    # - All check methods (ADB, keyboard, API)
    # - etc.

    def _setup_ui(self):
        """Set up the UI layout - placeholder."""
        # This should be copied from original main_window.py
        pass

    def _load_settings(self):
        """Load settings - placeholder."""
        pass

    def _save_settings(self):
        """Save settings - placeholder."""
        pass

    def _setup_timers(self):
        """Setup timers - placeholder."""
        pass

    def _connect_signals(self):
        """Connect signals - placeholder."""
        pass

    def _init_check_status(self):
        """Init check status - placeholder."""
        pass

    def _validate_config(self, base_url, model_name, api_key):
        """Validate config - placeholder."""
        return True, None
