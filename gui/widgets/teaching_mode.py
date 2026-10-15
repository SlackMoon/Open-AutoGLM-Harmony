"""Teaching mode widget for Open-AutoGLM GUI.

This module provides a human-in-the-loop teaching interface where:
1. AI analyzes screenshots and suggests actions
2. User confirms or corrects the suggestion
3. Confirmed steps are saved as golden path for future automation
"""

import base64
import json
import sqlite3
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt5.QtCore import Qt, pyqtSignal, QThread, QObject, QMutex, QWaitCondition
from PyQt5.QtGui import QFont, QPixmap, QImage
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QGroupBox,
    QScrollArea,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QMessageBox,
    QFrame,
    QComboBox,
)


def _get_project_root() -> Path:
    """Get the project root directory (Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.parent
    else:
        return Path(__file__).parent.parent.parent


def _get_logs_dir() -> Path:
    """Get the logs directory."""
    return _get_project_root() / "logs"



class TeachingWorker(QObject):
    """Background worker for teaching mode operations."""
    
    # Signals
    screenshot_ready = pyqtSignal(QPixmap, str)  # pixmap, base64_data
    suggestion_ready = pyqtSignal(str, dict)  # thinking, action
    action_executed = pyqtSignal(bool, str)  # success, message
    error_occurred = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._device_manager = None
        self._model_client = None
        self._action_handler = None
        self._context = []
        self._should_stop = False
        self._current_screenshot = None
        self._current_screenshot_base64 = None
        
        # Synchronization for user confirmation
        self._mutex = QMutex()
        self._wait_condition = QWaitCondition()
        self._user_confirmed = False
        self._user_correction = None
        
    def setup(self, base_url: str, model_name: str, api_key: str, 
              device_id: str = None, device_mode: str = "android"):
        """Setup the worker with model and device configuration."""
        try:
            from phone_agent.model import ModelClient, ModelConfig
            from phone_agent.device_manager import DeviceManager, DeviceMode
            from phone_agent.actions import ActionHandler
            from phone_agent.config import get_system_prompt
            
            # Setup model client
            model_config = ModelConfig(
                base_url=base_url,
                model_name=model_name,
                api_key=api_key,
            )
            self._model_client = ModelClient(model_config)
            
            # Setup device manager
            mode = DeviceMode.HARMONYOS if device_mode == "harmonyos" else DeviceMode.ANDROID
            self._device_manager = DeviceManager(mode=mode, device_id=device_id)
            
            # Setup action handler
            self._action_handler = ActionHandler(
                device_id=device_id,
                device_manager=self._device_manager,
            )
            
            # Get system prompt
            self._system_prompt = get_system_prompt("cn")
            
            self.status_updated.emit("✅ 初始化完成")
            return True
            
        except Exception as e:
            self.error_occurred.emit(f"初始化失败: {e}")
            return False
    
    def capture_screenshot(self):
        """Capture current screen and emit signal."""
        try:
            if not self._device_manager:
                self.error_occurred.emit("设备管理器未初始化")
                return
            
            self.status_updated.emit("📸 正在截图...")
            screenshot = self._device_manager.get_screenshot()
            
            if screenshot.is_sensitive:
                self.error_occurred.emit("检测到敏感屏幕，无法截图")
                return
            
            # Convert to QPixmap
            image_data = base64.b64decode(screenshot.base64_data)
            image = QImage.fromData(image_data)
            pixmap = QPixmap.fromImage(image)
            
            self._current_screenshot = screenshot
            self._current_screenshot_base64 = screenshot.base64_data
            
            self.screenshot_ready.emit(pixmap, screenshot.base64_data)
            
        except Exception as e:
            self.error_occurred.emit(f"截图失败: {e}")
    
    def analyze_and_suggest(self, task: str, step_num: int, user_feedback: str = None):
        """Analyze current screen and suggest action.
        
        Args:
            task: Task description
            step_num: Current step number
            user_feedback: Optional user feedback/correction from previous step
        """
        try:
            if not self._model_client or not self._current_screenshot:
                self.error_occurred.emit("模型或截图未准备好")
                return
            
            self.status_updated.emit(f"🤔 AI 正在分析第 {step_num} 步...")
            
            from phone_agent.model.client import MessageBuilder
            
            # Build context
            if step_num == 1:
                # First step - include system prompt and task
                self._context = [
                    MessageBuilder.create_system_message(self._system_prompt)
                ]
                
                current_app = self._device_manager.get_current_app()
                screen_info = MessageBuilder.build_screen_info(current_app)
                text_content = f"{task}\n\n{screen_info}"
                
                self._context.append(
                    MessageBuilder.create_user_message(
                        text=text_content,
                        image_base64=self._current_screenshot_base64
                    )
                )
            else:
                # Subsequent steps - add screen info and optional user feedback
                current_app = self._device_manager.get_current_app()
                screen_info = MessageBuilder.build_screen_info(current_app)
                
                if user_feedback:
                    # Include user feedback about previous action
                    text_content = f"用户反馈：{user_feedback}\n\n** Screen Info **\n\n{screen_info}"
                else:
                    text_content = f"** Screen Info **\n\n{screen_info}"
                
                self._context.append(
                    MessageBuilder.create_user_message(
                        text=text_content,
                        image_base64=self._current_screenshot_base64
                    )
                )
            
            # Request model
            response = self._model_client.request(self._context)
            
            # Parse action
            from phone_agent.actions.handler import parse_action, finish
            try:
                action = parse_action(response.action)
            except ValueError:
                action = finish(message=response.action)
            
            # Remove image from context to save space
            self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])
            
            # Add assistant response to context
            self._context.append(
                MessageBuilder.create_assistant_message(
                    f"<think>{response.thinking}</think><answer>{response.action}</answer>"
                )
            )
            
            self.suggestion_ready.emit(response.thinking, action)
            
        except Exception as e:
            self.error_occurred.emit(f"分析失败: {e}\n{traceback.format_exc()}")
    
    def analyze_with_instruction(self, user_instruction: str):
        """Let model analyze screen with user's specific instruction.
        
        When user provides a correction like "点击设置按钮", we ask the model
        to find and execute that specific action.
        """
        try:
            if not self._model_client or not self._current_screenshot:
                self.error_occurred.emit("模型或截图未准备好")
                return
            
            self.status_updated.emit(f"🤔 AI 正在根据您的指令分析...")
            
            from phone_agent.model.client import MessageBuilder
            
            # Add user instruction to context
            current_app = self._device_manager.get_current_app()
            screen_info = MessageBuilder.build_screen_info(current_app)
            
            # Create a specific instruction for the model
            text_content = (
                f"用户纠正了我的操作，要求执行：{user_instruction}\n"
                f"请根据当前屏幕截图，找到并执行用户要求的操作。\n\n"
                f"** Screen Info **\n\n{screen_info}"
            )
            
            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content,
                    image_base64=self._current_screenshot_base64
                )
            )
            
            # Request model
            response = self._model_client.request(self._context)
            
            # Parse action
            from phone_agent.actions.handler import parse_action, finish
            try:
                action = parse_action(response.action)
            except ValueError:
                action = finish(message=response.action)
            
            # Remove image from context
            self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])
            
            # Add assistant response to context
            self._context.append(
                MessageBuilder.create_assistant_message(
                    f"<think>{response.thinking}</think><answer>{response.action}</answer>"
                )
            )
            
            self.suggestion_ready.emit(response.thinking, action)
            
        except Exception as e:
            self.error_occurred.emit(f"分析失败: {e}\n{traceback.format_exc()}")
    
    def add_feedback_to_context(self, feedback: str):
        """Add user feedback to the conversation context."""
        from phone_agent.model.client import MessageBuilder
        
        # Add user feedback as a message
        self._context.append(
            MessageBuilder.create_user_message(text=f"用户反馈：{feedback}")
        )
    
    def execute_action(self, action: dict):
        """Execute the confirmed action."""
        try:
            if not self._action_handler or not self._current_screenshot:
                self.error_occurred.emit("动作处理器未初始化")
                return
            
            self.status_updated.emit("⚡ 正在执行操作...")
            
            result = self._action_handler.execute(
                action,
                self._current_screenshot.width,
                self._current_screenshot.height
            )
            
            self.action_executed.emit(result.success, result.message or "")
            
        except Exception as e:
            self.error_occurred.emit(f"执行失败: {e}")
    
    def stop(self):
        """Stop the worker."""
        self._should_stop = True
        self._mutex.lock()
        self._wait_condition.wakeAll()
        self._mutex.unlock()
    
    def reset(self):
        """Reset worker state for new task."""
        self._context = []
        self._should_stop = False
        self._current_screenshot = None
        self._current_screenshot_base64 = None



class TeachingModeWidget(QWidget):
    """Widget for teaching mode - human-AI collaborative task execution."""
    
    def __init__(self, task_logger=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.task_logger = task_logger
        self.current_task = None
        self.recorded_steps: List[Dict[str, Any]] = []
        self.is_teaching = False
        self.step_num = 0
        self.current_action = None
        self.current_thinking = None
        self._pending_correction = None  # Pending user correction for AI to analyze
        self._last_correction_text = None  # Last correction text for recording
        self._finish_message = None  # AI's finish message for extracting completion conditions
        self._finish_thinking = None  # AI's thinking when finishing
        
        # Worker thread
        self._worker = None
        self._worker_thread = None
        
        # Model config (will be set from main window)
        self._base_url = ""
        self._model_name = ""
        self._api_key = ""
        self._device_id = None
        self._device_mode = "android"
        
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the teaching mode UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Header with description
        header = QLabel(
            "📚 教学模式\n"
            "首次执行任务时，AI 会分析屏幕并建议操作，您确认后才会执行。\n"
            "确认的步骤会自动保存为黄金路径，后续可直接自动执行。"
        )
        header.setWordWrap(True)
        header.setStyleSheet("color: #1976D2; padding: 8px; background: #E3F2FD; border-radius: 4px;")
        layout.addWidget(header)
        
        # Main content splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel: Screenshot and AI suggestion
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Recorded steps
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)
        
        splitter.setSizes([600, 300])
        layout.addWidget(splitter, 1)
        
        # Bottom: Task input and controls
        bottom_panel = self._create_bottom_panel()
        layout.addWidget(bottom_panel)
    
    def _create_left_panel(self) -> QWidget:
        """Create the left panel with screenshot and AI suggestion."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Screenshot display
        screenshot_group = QGroupBox("当前屏幕")
        screenshot_layout = QVBoxLayout()
        
        self.screenshot_label = QLabel("等待开始教学...")
        self.screenshot_label.setAlignment(Qt.AlignCenter)
        self.screenshot_label.setMinimumSize(300, 400)
        self.screenshot_label.setStyleSheet(
            "background: #f5f5f5; border: 1px solid #ddd; border-radius: 4px;"
        )
        screenshot_layout.addWidget(self.screenshot_label)
        
        screenshot_group.setLayout(screenshot_layout)
        layout.addWidget(screenshot_group)
        
        # AI suggestion
        suggestion_group = QGroupBox("AI 建议")
        suggestion_layout = QVBoxLayout()
        
        self.suggestion_text = QTextEdit()
        self.suggestion_text.setReadOnly(True)
        self.suggestion_text.setPlaceholderText("AI 分析结果将显示在这里...")
        self.suggestion_text.setMaximumHeight(150)
        suggestion_layout.addWidget(self.suggestion_text)
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        self.confirm_btn = QPushButton("✓ 确认执行")
        self.confirm_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #45a049; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self.confirm_btn.clicked.connect(self._on_confirm)
        self.confirm_btn.setEnabled(False)
        btn_layout.addWidget(self.confirm_btn)
        
        self.correct_btn = QPushButton("✏️ 纠正操作")
        self.correct_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #F57C00; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self.correct_btn.clicked.connect(self._on_show_correction)
        self.correct_btn.setEnabled(False)
        btn_layout.addWidget(self.correct_btn)
        
        self.reject_btn = QPushButton("✗ 跳过此步")
        self.reject_btn.setStyleSheet(
            "QPushButton { background: #9E9E9E; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #757575; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self.reject_btn.clicked.connect(self._on_reject)
        self.reject_btn.setEnabled(False)
        btn_layout.addWidget(self.reject_btn)
        
        self.finish_btn = QPushButton("🏁 任务完成")
        self.finish_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #1976D2; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self.finish_btn.clicked.connect(self._on_finish_task)
        self.finish_btn.setEnabled(False)
        btn_layout.addWidget(self.finish_btn)
        
        btn_layout.addStretch()
        suggestion_layout.addLayout(btn_layout)
        
        # User correction input (hidden by default)
        self.correction_frame = QFrame()
        correction_layout = QVBoxLayout(self.correction_frame)
        correction_layout.setContentsMargins(0, 8, 0, 0)
        
        correction_label = QLabel("📝 请输入正确的操作指令：")
        correction_layout.addWidget(correction_label)
        
        self.correction_input = QLineEdit()
        self.correction_input.setPlaceholderText("例如：点击右上角的设置按钮 / 向下滑动查找xxx / 输入文字xxx")
        self.correction_input.returnPressed.connect(self._on_submit_correction)
        correction_layout.addWidget(self.correction_input)
        
        correction_btn_layout = QHBoxLayout()
        self.submit_correction_btn = QPushButton("✓ 提交纠正")
        self.submit_correction_btn.setStyleSheet(
            "QPushButton { background: #4CAF50; color: white; padding: 6px 12px; "
            "border-radius: 4px; }"
        )
        self.submit_correction_btn.clicked.connect(self._on_submit_correction)
        correction_btn_layout.addWidget(self.submit_correction_btn)
        
        self.cancel_correction_btn = QPushButton("取消")
        self.cancel_correction_btn.clicked.connect(self._on_cancel_correction)
        correction_btn_layout.addWidget(self.cancel_correction_btn)
        correction_btn_layout.addStretch()
        correction_layout.addLayout(correction_btn_layout)
        
        self.correction_frame.setVisible(False)
        suggestion_layout.addWidget(self.correction_frame)
        
        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        suggestion_layout.addWidget(self.status_label)
        
        suggestion_group.setLayout(suggestion_layout)
        layout.addWidget(suggestion_group)
        
        return panel
    
    def _create_right_panel(self) -> QWidget:
        """Create the right panel with recorded steps."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Recorded steps list
        steps_group = QGroupBox("已记录步骤")
        steps_layout = QVBoxLayout()
        
        self.steps_list = QListWidget()
        self.steps_list.setAlternatingRowColors(True)
        steps_layout.addWidget(self.steps_list)
        
        # Step count
        self.step_count_label = QLabel("共 0 步")
        self.step_count_label.setAlignment(Qt.AlignRight)
        steps_layout.addWidget(self.step_count_label)
        
        steps_group.setLayout(steps_layout)
        layout.addWidget(steps_group)
        
        # Save as golden path button
        self.save_golden_btn = QPushButton("💾 保存为黄金路径")
        self.save_golden_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; padding: 8px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #F57C00; }"
            "QPushButton:disabled { background: #ccc; }"
        )
        self.save_golden_btn.clicked.connect(self._on_save_golden_path)
        self.save_golden_btn.setEnabled(False)
        layout.addWidget(self.save_golden_btn)
        
        return panel
    
    def _create_bottom_panel(self) -> QWidget:
        """Create the bottom panel with task input and controls."""
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 0)
        
        # Task input
        task_label = QLabel("任务：")
        layout.addWidget(task_label)
        
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("输入要教学的任务，例如：打开微信发送消息给张三")
        self.task_input.returnPressed.connect(self._on_start_teaching)
        layout.addWidget(self.task_input, 1)
        
        # Start/Stop button
        self.start_btn = QPushButton("▶ 开始教学")
        self.start_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #1976D2; }"
        )
        self.start_btn.clicked.connect(self._on_start_teaching)
        layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet(
            "QPushButton { background: #9E9E9E; color: white; padding: 8px 16px; "
            "border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #757575; }"
        )
        self.stop_btn.clicked.connect(self._on_stop_teaching)
        self.stop_btn.setEnabled(False)
        layout.addWidget(self.stop_btn)
        
        return panel


    
    def set_config(self, base_url: str, model_name: str, api_key: str,
                   device_id: str = None, device_mode: str = "android"):
        """Set model and device configuration."""
        self._base_url = base_url
        self._model_name = model_name
        self._api_key = api_key
        self._device_id = device_id
        self._device_mode = device_mode
    
    def _setup_worker(self):
        """Setup the background worker thread."""
        if self._worker_thread is not None:
            self._cleanup_worker()
        
        self._worker = TeachingWorker()
        self._worker_thread = QThread()
        self._worker.moveToThread(self._worker_thread)
        
        # Connect signals
        self._worker.screenshot_ready.connect(self._on_screenshot_ready)
        self._worker.suggestion_ready.connect(self._on_suggestion_ready)
        self._worker.action_executed.connect(self._on_action_executed)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.status_updated.connect(self._on_status_update)
        
        self._worker_thread.start()
        
        # Initialize worker
        return self._worker.setup(
            self._base_url, self._model_name, self._api_key,
            self._device_id, self._device_mode
        )
    
    def _cleanup_worker(self):
        """Cleanup worker thread."""
        if self._worker:
            self._worker.stop()
        if self._worker_thread:
            self._worker_thread.quit()
            self._worker_thread.wait(3000)
            self._worker_thread = None
        self._worker = None
    
    # --- Event handlers ---
    
    def _on_start_teaching(self):
        """Start teaching mode."""
        task = self.task_input.text().strip()
        if not task:
            QMessageBox.warning(self, "提示", "请输入任务描述")
            return
        
        # Check config
        if not self._base_url or not self._model_name or not self._api_key:
            QMessageBox.warning(
                self, "配置缺失",
                "请先在主界面配置模型 API 信息（Base URL、Model Name、API Key）"
            )
            return
        
        # Setup worker
        if not self._setup_worker():
            return
        
        self.current_task = task
        self.recorded_steps = []
        self.is_teaching = True
        self.step_num = 0
        
        # Update UI state
        self.task_input.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.finish_btn.setEnabled(True)
        self.steps_list.clear()
        self.step_count_label.setText("共 0 步")
        self.save_golden_btn.setEnabled(False)
        
        self.screenshot_label.setText("正在获取屏幕截图...")
        self.suggestion_text.setPlainText("准备中...")
        
        # Start first step
        self._next_step()
    
    def _next_step(self):
        """Proceed to next step."""
        if not self.is_teaching or not self._worker:
            return
        
        self.step_num += 1
        self.status_label.setText(f"步骤 {self.step_num}...")
        
        # Capture screenshot
        self._worker.capture_screenshot()
    
    def _on_screenshot_ready(self, pixmap: QPixmap, base64_data: str):
        """Handle screenshot ready."""
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.screenshot_label.width() - 10,
                self.screenshot_label.height() - 10,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.screenshot_label.setPixmap(scaled)
        
        # Request AI analysis
        if self._worker and self.is_teaching:
            self._worker.analyze_and_suggest(self.current_task, self.step_num)
    
    def _on_suggestion_ready(self, thinking: str, action: dict):
        """Handle AI suggestion ready."""
        self.current_thinking = thinking
        self.current_action = action
        
        # Hide correction frame
        self.correction_frame.setVisible(False)
        
        # Check if this is a response to user correction
        if hasattr(self, '_pending_correction') and self._pending_correction:
            correction_text = self._pending_correction
            self._pending_correction = None
            
            # 不要自动执行！让用户确认 AI 根据纠正指令分析出的动作
            action_desc = self._format_action(action)
            self.suggestion_text.setPlainText(
                f"💭 根据您的纠正「{correction_text}」，AI 分析结果：\n\n"
                f"🎯 建议操作：{action_desc}\n\n"
                f"请确认这是否是您想要的操作。"
            )
            self.confirm_btn.setEnabled(True)
            self.confirm_btn.setText("✓ 确认执行")
            self.correct_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
            self.reject_btn.setText("✗ 跳过此步")
            self.status_label.setText("请确认 AI 根据您的纠正分析出的操作")
            
            # 保存纠正信息，以便确认时使用
            self._last_correction_text = correction_text
            return
        
        # Check if task is finished
        if action.get("_metadata") == "finish":
            message = action.get("message", "任务完成")
            self.suggestion_text.setPlainText(
                f"💭 思考：{thinking}\n\n"
                f"🏁 AI 认为任务已完成：{message}"
            )
            self.confirm_btn.setEnabled(True)
            self.confirm_btn.setText("✓ 确认完成")
            self.correct_btn.setEnabled(False)
            self.reject_btn.setEnabled(True)
            self.reject_btn.setText("✗ 还没完成")
            self.status_label.setText("AI 认为任务已完成，请确认")
            return
        
        # Format suggestion
        action_type = action.get("action", "unknown")
        action_desc = self._format_action(action)
        
        suggestion = f"💭 思考：{thinking[:500]}{'...' if len(thinking) > 500 else ''}\n\n"
        suggestion += f"🎯 建议操作：{action_desc}"
        
        self.suggestion_text.setPlainText(suggestion)
        
        # Enable buttons
        self.confirm_btn.setEnabled(True)
        self.confirm_btn.setText("✓ 确认执行")
        self.correct_btn.setEnabled(True)
        self.reject_btn.setEnabled(True)
        self.reject_btn.setText("✗ 跳过此步")
        self.status_label.setText("请确认、纠正或跳过 AI 的建议")
    
    def _format_action(self, action: dict) -> str:
        """Format action for display."""
        action_type = action.get("action", "unknown")
        
        if action_type == "Tap":
            # Model returns 'element', not 'point'
            element = action.get("element", action.get("point", [0, 0]))
            if isinstance(element, list) and len(element) >= 2:
                return f"点击屏幕 ({element[0]}, {element[1]})"
            return f"点击屏幕"
        elif action_type == "Double Tap":
            element = action.get("element", [0, 0])
            if isinstance(element, list) and len(element) >= 2:
                return f"双击屏幕 ({element[0]}, {element[1]})"
            return f"双击屏幕"
        elif action_type == "Long Press":
            element = action.get("element", [0, 0])
            if isinstance(element, list) and len(element) >= 2:
                return f"长按屏幕 ({element[0]}, {element[1]})"
            return f"长按屏幕"
        elif action_type == "Type":
            text = action.get("text", "")
            return f"输入文字「{text}」"
        elif action_type == "Swipe":
            start = action.get("start", [0, 0])
            end = action.get("end", [0, 0])
            # Determine swipe direction
            if isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2:
                dy = end[1] - start[1]
                dx = end[0] - start[0]
                if abs(dy) > abs(dx):
                    direction = "向下滑动" if dy > 0 else "向上滑动"
                else:
                    direction = "向右滑动" if dx > 0 else "向左滑动"
                return f"{direction} ({start[0]},{start[1]}) → ({end[0]},{end[1]})"
            return f"滑动屏幕"
        elif action_type == "Launch":
            app = action.get("app", "")
            return f"打开应用「{app}」"
        elif action_type == "Back":
            return "返回上一页"
        elif action_type == "Home":
            return "返回桌面"
        elif action_type == "Wait":
            return "等待页面加载"
        elif action_type == "Take_over":
            message = action.get("message", "")
            return f"请求接管: {message}"
        else:
            return f"{action_type}: {json.dumps(action, ensure_ascii=False)}"
    
    def _on_confirm(self):
        """Confirm the current AI suggestion."""
        if not self.current_action:
            return
        
        self.confirm_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.correction_frame.setVisible(False)
        
        # Check if finish action
        if self.current_action.get("_metadata") == "finish":
            finish_message = self.current_action.get("message", "任务完成")
            # Save finish message for extracting completion conditions
            self._finish_message = finish_message
            self._finish_thinking = self.current_thinking
            self._finish_teaching(finish_message)
            return
        
        # Check if this is confirming a corrected action
        correction_text = getattr(self, '_last_correction_text', None)
        if correction_text:
            self._last_correction_text = None  # Clear it
            # Record as corrected step
            step_data = {
                "step_num": self.step_num,
                "action": self.current_action,
                "original_action": None,  # We don't have the original in this flow
                "thinking": self.current_thinking,
                "user_correction": correction_text,
                "label": "corrected",
                "timestamp": datetime.now().isoformat()
            }
        else:
            # Record as normal correct step
            step_data = {
                "step_num": self.step_num,
                "action": self.current_action,
                "thinking": self.current_thinking,
                "label": "correct",
                "timestamp": datetime.now().isoformat()
            }
        
        self.recorded_steps.append(step_data)
        self._update_steps_list()
        
        # Execute action
        if self._worker:
            self._worker.execute_action(self.current_action)
    
    def _on_show_correction(self):
        """Show correction input frame."""
        self.correction_frame.setVisible(True)
        self.correction_input.setFocus()
        self.status_label.setText("请输入正确的操作指令")
    
    def _on_cancel_correction(self):
        """Cancel correction input."""
        self.correction_frame.setVisible(False)
        self.correction_input.clear()
        self.status_label.setText("请确认、纠正或跳过 AI 的建议")
    
    def _on_submit_correction(self):
        """Submit user correction and execute."""
        correction_text = self.correction_input.text().strip()
        if not correction_text:
            QMessageBox.warning(self, "提示", "请输入正确的操作指令")
            return
        
        # Hide correction frame and disable buttons
        self.correction_frame.setVisible(False)
        self.correction_input.clear()
        self.confirm_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        
        # Try to parse user correction into action
        corrected_action = self._parse_user_correction(correction_text)
        
        if corrected_action and not corrected_action.get("needs_ai"):
            # Direct action (like coordinates, swipe, back, etc.) - execute directly
            self._execute_corrected_action(corrected_action, correction_text)
        else:
            # Descriptive action (like "点击设置按钮") - let AI analyze
            self.status_label.setText(f"🤔 让 AI 根据您的指令分析...")
            self._pending_correction = correction_text
            if self._worker:
                self._worker.analyze_with_instruction(correction_text)
    
    def _execute_corrected_action(self, action: dict, correction_text: str):
        """Execute a corrected action directly."""
        # Record step with correction
        step_data = {
            "step_num": self.step_num,
            "action": action,
            "original_action": self.current_action,
            "thinking": self.current_thinking,
            "user_correction": correction_text,
            "label": "corrected",
            "timestamp": datetime.now().isoformat()
        }
        self.recorded_steps.append(step_data)
        self._update_steps_list()
        
        # Add feedback to model context so it knows what happened
        if self._worker:
            self._worker.add_feedback_to_context(
                f"用户纠正了操作，执行了：{correction_text}"
            )
        
        # Execute corrected action
        self.status_label.setText(f"执行纠正操作: {self._format_action(action)}")
        if self._worker:
            self._worker.execute_action(action)
    
    def _parse_user_correction(self, text: str) -> Optional[dict]:
        """Parse user correction text into action dict."""
        import re
        text = text.strip().lower()
        
        # 点击操作
        # 格式: 点击(x,y) 或 点击 x,y
        tap_coord_match = re.search(r'点击\s*[\(（]?\s*(\d+)\s*[,，]\s*(\d+)\s*[\)）]?', text)
        if tap_coord_match:
            x, y = int(tap_coord_match.group(1)), int(tap_coord_match.group(2))
            return {"action": "Tap", "element": [x, y], "_metadata": "do"}
        
        # 点击某个元素（需要 AI 重新分析，这里记录为描述）
        if text.startswith('点击'):
            target = text[2:].strip()
            if target:
                # 返回一个特殊的 Tap 动作，让 AI 重新分析
                return {"action": "Tap", "target_description": target, "element": [0, 0], "_metadata": "do", "needs_ai": True}
        
        # 输入操作
        # 格式: 输入xxx
        if text.startswith('输入'):
            input_text = text[2:].strip()
            if input_text:
                return {"action": "Type", "text": input_text, "_metadata": "do"}
        
        # 滑动操作
        if '向上滑' in text or '上滑' in text:
            return {"action": "Swipe", "start": [540, 1500], "end": [540, 500], "_metadata": "do"}
        if '向下滑' in text or '下滑' in text:
            return {"action": "Swipe", "start": [540, 500], "end": [540, 1500], "_metadata": "do"}
        if '向左滑' in text or '左滑' in text:
            return {"action": "Swipe", "start": [900, 1000], "end": [100, 1000], "_metadata": "do"}
        if '向右滑' in text or '右滑' in text:
            return {"action": "Swipe", "start": [100, 1000], "end": [900, 1000], "_metadata": "do"}
        
        # 返回操作
        if text in ['返回', '后退', '回退']:
            return {"action": "Back", "_metadata": "do"}
        
        # 回到桌面
        if text in ['桌面', '回到桌面', '主页', '回到主页']:
            return {"action": "Home", "_metadata": "do"}
        
        # 打开应用
        if text.startswith('打开'):
            app_name = text[2:].strip()
            if app_name:
                return {"action": "Launch", "app": app_name, "_metadata": "do"}
        
        # 等待
        if text in ['等待', '等一下', '稍等']:
            return {"action": "Wait", "_metadata": "do"}
        
        # 如果无法解析为具体动作，让 AI 来分析
        return {"action": "unknown", "instruction": text, "_metadata": "do", "needs_ai": True}

    def _on_reject(self):
        """Reject the current AI suggestion."""
        if not self.current_action:
            return
        
        # Hide correction frame
        self.correction_frame.setVisible(False)
        
        # Check if rejecting finish
        if self.current_action.get("_metadata") == "finish":
            # Continue with next step
            self.confirm_btn.setEnabled(False)
            self.correct_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self._next_step()
            return
        
        # Record as skipped
        step_data = {
            "step_num": self.step_num,
            "action": self.current_action,
            "thinking": self.current_thinking,
            "label": "skip",
            "timestamp": datetime.now().isoformat()
        }
        self.recorded_steps.append(step_data)
        self._update_steps_list()
        
        self.confirm_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        
        # Continue to next step
        self._next_step()
    
    def _on_finish_task(self):
        """User manually finishes the task."""
        reply = QMessageBox.question(
            self, "确认完成",
            "确定任务已完成吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self._finish_teaching("用户手动完成任务")
    
    def _finish_teaching(self, message: str):
        """Finish teaching and enable save."""
        self.is_teaching = False
        
        # Update UI
        self.task_input.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)
        self.correction_frame.setVisible(False)
        
        self.status_label.setText(f"✅ {message}")
        self.suggestion_text.setPlainText(f"教学完成：{message}\n\n可以保存为黄金路径")
        
        # Enable save if we have steps
        if self.recorded_steps:
            self.save_golden_btn.setEnabled(True)
        
        self._cleanup_worker()
    
    def _on_action_executed(self, success: bool, message: str):
        """Handle action execution result."""
        if success:
            self.status_label.setText(f"✅ 执行成功")
            # Small delay then next step
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(500, self._next_step)
        else:
            self.status_label.setText(f"❌ 执行失败: {message}")
            # Still continue to next step
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(1000, self._next_step)
    
    def _on_error(self, error: str):
        """Handle error from worker."""
        self.status_label.setText(f"❌ {error}")
        QMessageBox.warning(self, "错误", error)
    
    def _on_status_update(self, status: str):
        """Handle status update from worker."""
        self.status_label.setText(status)
    
    def _on_stop_teaching(self):
        """Stop teaching mode."""
        self.is_teaching = False
        
        # Update UI state
        self.task_input.setEnabled(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.confirm_btn.setEnabled(False)
        self.correct_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.finish_btn.setEnabled(False)
        self.correction_frame.setVisible(False)
        
        self.screenshot_label.setText("教学已停止")
        self.suggestion_text.clear()
        self.status_label.setText("已停止")
        
        # Enable save if we have steps
        if self.recorded_steps:
            self.save_golden_btn.setEnabled(True)
        
        self._cleanup_worker()
    
    def _update_steps_list(self):
        """Update the steps list display."""
        self.steps_list.clear()
        
        for step in self.recorded_steps:
            step_num = step.get("step_num", 0)
            label = step.get("label", "")
            action = step.get("action", {})
            
            action_desc = self._format_action(action)
            
            if label == "correct":
                icon = "✅"
            elif label == "corrected":
                icon = "✏️"
                # Show user correction
                user_correction = step.get("user_correction", "")
                if user_correction:
                    action_desc = f"{action_desc} (纠正: {user_correction})"
            elif label == "skip":
                icon = "⏭️"
            else:
                icon = "❓"
            
            item_text = f"{icon} 步骤 {step_num}: {action_desc}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, step)
            self.steps_list.addItem(item)
        
        self.step_count_label.setText(f"共 {len(self.recorded_steps)} 步")
        self.steps_list.scrollToBottom()

    def _extract_completion_conditions_from_finish(self) -> List[str]:
        """
        从 AI 的 finish 消息中提取完成条件。
        
        例如：
        - "点赞按钮已经从空心变成了红色实心" -> "点赞按钮变成红色实心"
        - "显示点赞成功" -> "看到点赞成功提示"
        """
        import re
        
        conditions = []
        
        finish_message = getattr(self, '_finish_message', None) or ""
        finish_thinking = getattr(self, '_finish_thinking', None) or ""
        
        combined_text = f"{finish_message} {finish_thinking}"
        
        if not combined_text.strip():
            return conditions
        
        # 模式1: "xxx已经从xxx变成了xxx" - 状态变化
        pattern1 = r'([^\s,，。]+)已经从[^\s,，。]*变成了([^\s,，。]+)'
        matches1 = re.findall(pattern1, combined_text)
        for element, new_state in matches1:
            conditions.append(f"{element}变成{new_state}")
        
        # 模式2: "显示xxx成功" / "xxx成功"
        pattern2 = r'(?:显示|看到)?([^\s,，。]*(?:成功|完成)[^\s,，。]*)'
        matches2 = re.findall(pattern2, combined_text)
        for m in matches2:
            m = m.strip()
            if m and len(m) > 2 and len(m) < 20:
                conditions.append(f"看到「{m}」")
        
        # 模式3: "可以看到xxx" - 视觉确认
        pattern3 = r'可以看到([^,，。]{3,30})'
        matches3 = re.findall(pattern3, combined_text)
        for m in matches3:
            m = m.strip()
            # 过滤掉太长或太短的
            if 3 <= len(m) <= 25:
                conditions.append(f"看到{m}")
        
        # 模式4: "xxx变成了xxx" - 简单状态变化
        pattern4 = r'([^\s,，。]{2,10})变成了([^\s,，。]{2,15})'
        matches4 = re.findall(pattern4, combined_text)
        for element, new_state in matches4:
            cond = f"{element}变成{new_state}"
            if cond not in conditions:
                conditions.append(cond)
        
        # 模式5: 从 thinking 中提取关键判断
        # "底部的点赞按钮已经从空心变成了红色实心"
        if '红色' in combined_text and '点赞' in combined_text:
            conditions.append("点赞按钮变成红色")
        
        if '实心' in combined_text:
            conditions.append("按钮变成实心状态")
        
        # 去重
        conditions = list(dict.fromkeys(conditions))
        
        # 限制数量
        return conditions[:5]


    
    def _on_save_golden_path(self):
        """Save recorded steps as golden path."""
        if not self.recorded_steps:
            QMessageBox.warning(self, "提示", "没有可保存的步骤")
            return
        
        if not self.current_task:
            QMessageBox.warning(self, "提示", "任务描述为空")
            return
        
        # Extract correct and corrected steps
        correct_steps = []
        forbidden = []
        hints = []
        
        for step in self.recorded_steps:
            label = step.get("label", "")
            action = step.get("action", {})
            
            if label in ["correct", "corrected"]:
                action_desc = self._format_action(action)
                correct_steps.append(action_desc)
                
                # If corrected, record the original wrong action as forbidden
                if label == "corrected":
                    original_action = step.get("original_action", {})
                    if original_action:
                        original_desc = self._format_action(original_action)
                        forbidden.append(f"不要{original_desc}")
                    
                    # Add user correction as hint
                    user_correction = step.get("user_correction", "")
                    if user_correction:
                        hints.append(f"正确操作: {user_correction}")
        
        if not correct_steps:
            QMessageBox.warning(self, "提示", "没有确认的正确步骤")
            return
        
        # Extract completion conditions from finish message
        completion_conditions = self._extract_completion_conditions_from_finish()
        
        # Save to database using GoldenPathRepository
        try:
            from gui.utils.golden_path_repository import GoldenPathRepository
            from gui.utils.golden_path_extractor import GoldenPath
            
            db_path = str(_get_logs_dir() / "tasks.db")
            repo = GoldenPathRepository(db_path)
            
            # Extract apps from steps
            apps = []
            for step in self.recorded_steps:
                action = step.get("action", {})
                if action.get("action") == "Launch":
                    app = action.get("app", "")
                    if app and app not in apps:
                        apps.append(app)
            
            # Assess difficulty
            if len(correct_steps) <= 3:
                difficulty = "simple"
            elif len(correct_steps) <= 6:
                difficulty = "medium"
            else:
                difficulty = "complex"
            
            # Generate natural SOP
            natural_sop_lines = ["【正确步骤】"]
            for i, step_desc in enumerate(correct_steps, 1):
                natural_sop_lines.append(f"{i}. {step_desc}")
            
            if forbidden:
                natural_sop_lines.append("\n【禁止操作】")
                for f in forbidden:
                    natural_sop_lines.append(f"❌ {f}")
            
            if hints:
                natural_sop_lines.append("\n【关键提示】")
                for h in hints:
                    natural_sop_lines.append(f"💡 {h}")
            
            if completion_conditions:
                natural_sop_lines.append("\n【完成条件】")
                for c in completion_conditions:
                    natural_sop_lines.append(f"✓ {c}")
            
            natural_sop = "\n".join(natural_sop_lines)
            
            # Create GoldenPath object
            now = datetime.now().isoformat()
            golden_path = GoldenPath(
                task_pattern=self.current_task,
                apps=apps,
                difficulty=difficulty,
                can_replay=True,
                correct_path=correct_steps,
                forbidden=forbidden,
                hints=hints,
                natural_sop=natural_sop,
                action_sop=[],  # Will be populated from recorded_steps
                common_errors=[],
                success_rate=1.0,
                usage_count=0,
                source_sessions=[],
                created_at=now,
                updated_at=now
            )
            
            # Save action_sop with full action data
            action_sop = []
            step_num = 0
            for step in self.recorded_steps:
                if step.get("label") in ["correct", "corrected"]:
                    step_num += 1
                    action_sop.append({
                        "step_num": step_num,
                        "label": "correct",
                        "action": step.get("action", {}),
                        "thinking": step.get("thinking", "")[:200]
                    })
            golden_path.action_sop = action_sop
            
            # Save to repository
            path_id = repo.save(golden_path)
            
            # Update completion conditions separately (since GoldenPath dataclass may not have this field)
            if completion_conditions:
                repo.update(path_id, {
                    'completion_conditions': json.dumps(completion_conditions, ensure_ascii=False)
                })
            
            # Build success message
            success_msg = f"已保存黄金路径：{self.current_task}\n"
            success_msg += f"共 {len(correct_steps)} 个正确步骤\n"
            if completion_conditions:
                success_msg += f"完成条件：{len(completion_conditions)} 个\n"
                for c in completion_conditions[:3]:
                    success_msg += f"  • {c}\n"
            success_msg += f"路径 ID: {path_id}"
            
            QMessageBox.information(self, "保存成功", success_msg)
            
            self.save_golden_btn.setEnabled(False)
            
        except ImportError as e:
            # Fallback to simple database save
            self._save_golden_path_simple()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存黄金路径时出错：{e}\n{traceback.format_exc()}")
    
    def _save_golden_path_simple(self):
        """Simple fallback save method."""
        try:
            db_path = _get_logs_dir() / "tasks.db"
            conn = sqlite3.connect(str(db_path), timeout=5.0)
            conn.execute("PRAGMA journal_mode=WAL")
            cur = conn.cursor()
            
            # Create golden_paths table if not exists
            cur.execute("""
                CREATE TABLE IF NOT EXISTS golden_paths (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_pattern TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    correct_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0
                )
            """)
            
            # Extract correct steps
            correct_steps = []
            for step in self.recorded_steps:
                if step.get("label") == "correct":
                    action_desc = self._format_action(step.get("action", {}))
                    correct_steps.append(action_desc)
            
            # Check if pattern already exists
            cur.execute(
                "SELECT id FROM golden_paths WHERE task_pattern = ?",
                (self.current_task,)
            )
            existing = cur.fetchone()
            
            steps_json = json.dumps(self.recorded_steps, ensure_ascii=False)
            correct_path_json = json.dumps(correct_steps, ensure_ascii=False)
            now = datetime.now().isoformat()
            
            if existing:
                cur.execute(
                    "UPDATE golden_paths SET steps = ?, correct_path = ?, updated_at = ? WHERE id = ?",
                    (steps_json, correct_path_json, now, existing[0])
                )
            else:
                cur.execute(
                    "INSERT INTO golden_paths (task_pattern, steps, correct_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (self.current_task, steps_json, correct_path_json, now, now)
                )
            
            conn.commit()
            conn.close()
            
            QMessageBox.information(
                self, "保存成功",
                f"已保存黄金路径：{self.current_task}\n共 {len(correct_steps)} 个正确步骤"
            )
            
            self.save_golden_btn.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存黄金路径时出错：{e}")

