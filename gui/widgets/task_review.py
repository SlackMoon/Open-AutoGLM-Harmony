"""Task review and annotation widgets for Open-AutoGLM GUI."""

import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QGroupBox,
    QMessageBox,
)

from gui.utils.task_logger import TaskLogger

# 创建日志记录器
logger = logging.getLogger(__name__)


def _get_project_root() -> Path:
    """Get the project root directory (Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe (dist/GUI.exe)
        return Path(sys.executable).parent.parent
    else:
        # Running as script - gui/widgets/task_review.py
        return Path(__file__).parent.parent.parent


class StepPlayerWidget(QWidget):
    """Widget for displaying and annotating individual steps."""
    
    # Signals
    step_annotated = pyqtSignal(int, str, str)  # step_num, label, correction
    prev_step_requested = pyqtSignal()
    next_step_requested = pyqtSignal()
    
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.current_step: Optional[Dict[str, Any]] = None
        self.current_step_index: int = 0
        self.total_steps: int = 0
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Screenshot display area
        screenshot_group = QGroupBox("截图")
        screenshot_layout = QVBoxLayout()
        
        self.screenshot_label = QLabel("暂无截图")
        self.screenshot_label.setAlignment(Qt.AlignCenter)
        self.screenshot_label.setMinimumHeight(300)
        self.screenshot_label.setStyleSheet(
            "QLabel { background-color: #f0f0f0; border: 1px solid #ddd; }"
        )
        self.screenshot_label.setCursor(Qt.PointingHandCursor)
        self.screenshot_label.mousePressEvent = self._on_screenshot_click
        screenshot_layout.addWidget(self.screenshot_label)
        
        screenshot_group.setLayout(screenshot_layout)
        layout.addWidget(screenshot_group)
        
        # Thinking display area
        thinking_group = QGroupBox("思考过程 (Thinking)")
        thinking_layout = QVBoxLayout()
        
        self.thinking_text = QTextEdit()
        self.thinking_text.setReadOnly(True)
        self.thinking_text.setMaximumHeight(150)
        self.thinking_text.setPlaceholderText("暂无思考过程...")
        thinking_layout.addWidget(self.thinking_text)
        
        thinking_group.setLayout(thinking_layout)
        layout.addWidget(thinking_group)
        
        # Action display area
        action_group = QGroupBox("执行动作 (Action)")
        action_layout = QVBoxLayout()
        
        self.action_text = QTextEdit()
        self.action_text.setReadOnly(True)
        self.action_text.setMaximumHeight(100)
        self.action_text.setPlaceholderText("暂无动作信息...")
        action_layout.addWidget(self.action_text)
        
        action_group.setLayout(action_layout)
        layout.addWidget(action_group)
        
        # Navigation buttons
        nav_group = QGroupBox("步骤导航")
        nav_layout = QHBoxLayout()
        
        self.prev_btn = QPushButton("← 上一步")
        self.prev_btn.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #546E7A; }"
            "QPushButton:disabled { background-color: #BDBDBD; }"
        )
        self.prev_btn.clicked.connect(self._on_prev_step)
        nav_layout.addWidget(self.prev_btn)
        
        self.step_label = QLabel("步骤 0/0")
        self.step_label.setAlignment(Qt.AlignCenter)
        self.step_label.setStyleSheet("QLabel { font-weight: bold; font-size: 14px; }")
        nav_layout.addWidget(self.step_label)
        
        self.next_btn = QPushButton("下一步 →")
        self.next_btn.setStyleSheet(
            "QPushButton { background-color: #607D8B; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #546E7A; }"
            "QPushButton:disabled { background-color: #BDBDBD; }"
        )
        self.next_btn.clicked.connect(self._on_next_step)
        nav_layout.addWidget(self.next_btn)
        
        nav_group.setLayout(nav_layout)
        layout.addWidget(nav_group)
        
        # Annotation buttons
        annotation_group = QGroupBox("标注")
        annotation_layout = QVBoxLayout()
        
        btn_layout = QHBoxLayout()
        
        self.correct_btn = QPushButton("✓ 正确")
        self.correct_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.correct_btn.clicked.connect(lambda: self._on_annotate('correct'))
        btn_layout.addWidget(self.correct_btn)
        
        self.wrong_btn = QPushButton("✗ 错误")
        self.wrong_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #da190b; }"
        )
        self.wrong_btn.clicked.connect(lambda: self._on_annotate('wrong'))
        btn_layout.addWidget(self.wrong_btn)
        
        self.skip_btn = QPushButton("→ 跳过")
        self.skip_btn.setStyleSheet(
            "QPushButton { background-color: #9E9E9E; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #757575; }"
        )
        self.skip_btn.clicked.connect(lambda: self._on_annotate('skip'))
        btn_layout.addWidget(self.skip_btn)
        
        annotation_layout.addLayout(btn_layout)
        
        # Correction input (hidden by default)
        self.correction_input = QTextEdit()
        self.correction_input.setPlaceholderText("请输入纠正说明（例如：应该点击右下角的微信图标）")
        self.correction_input.setMaximumHeight(80)
        self.correction_input.setVisible(False)
        annotation_layout.addWidget(self.correction_input)
        
        # Save correction button (hidden by default)
        self.save_correction_btn = QPushButton("💾 保存纠正说明")
        self.save_correction_btn.setStyleSheet(
            "QPushButton { background-color: #FF5722; color: white; font-weight: bold; padding: 8px; }"
            "QPushButton:hover { background-color: #E64A19; }"
        )
        self.save_correction_btn.clicked.connect(self.save_wrong_annotation)
        self.save_correction_btn.setVisible(False)
        annotation_layout.addWidget(self.save_correction_btn)
        
        annotation_group.setLayout(annotation_layout)
        layout.addWidget(annotation_group)
        
        # Batch operation buttons (moved from left panel)
        batch_group = QGroupBox("批量操作")
        batch_layout = QHBoxLayout()
        
        self.mark_all_correct_btn = QPushButton("✓ 全部正确")
        self.mark_all_correct_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; padding: 8px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        batch_layout.addWidget(self.mark_all_correct_btn)
        
        self.clear_annotations_btn = QPushButton("🗑️ 清除标注")
        self.clear_annotations_btn.setStyleSheet(
            "QPushButton { background-color: #FF9800; color: white; padding: 8px; }"
            "QPushButton:hover { background-color: #F57C00; }"
        )
        batch_layout.addWidget(self.clear_annotations_btn)
        
        self.extract_golden_path_btn = QPushButton("⭐ 提取黄金路径")
        self.extract_golden_path_btn.setStyleSheet(
            "QPushButton { background-color: #2196F3; color: white; padding: 8px; }"
            "QPushButton:hover { background-color: #1976D2; }"
        )
        batch_layout.addWidget(self.extract_golden_path_btn)
        
        batch_group.setLayout(batch_layout)
        layout.addWidget(batch_group)
        
        layout.addStretch()
    
    def _clean_text(self, text: str) -> str:
        """Clean up excessive newlines and whitespace in text.
        
        Args:
            text: Raw text with potential excessive newlines
            
        Returns:
            Cleaned text with normalized whitespace (excessive newlines collapsed to spaces)
        """
        if not text:
            return text
        
        import re
        
        # Collapse all consecutive whitespace (including newlines, spaces, tabs) into single spaces
        # This converts text like "用户要求\n\n\n：\n1.\n 打\n开微信" 
        # into "用户要求 ： 1. 打开微信" for better readability
        text = re.sub(r'\s+', ' ', text)
        
        # Trim leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def set_step_info(self, current_index: int, total: int):
        """Update step navigation info.
        
        Args:
            current_index: Current step index (0-based)
            total: Total number of steps
        """
        self.current_step_index = current_index
        self.total_steps = total
        self.step_label.setText(f"步骤 {current_index + 1}/{total}")
        
        # Enable/disable navigation buttons
        self.prev_btn.setEnabled(current_index > 0)
        self.next_btn.setEnabled(current_index < total - 1)
    
    def _on_prev_step(self):
        """Handle previous step button click."""
        self.prev_step_requested.emit()
    
    def _on_next_step(self):
        """Handle next step button click."""
        self.next_step_requested.emit()
    
    def _on_screenshot_click(self, event):
        """Handle screenshot click to view full size."""
        # TODO: Implement full-size screenshot viewer
        pass
    
    def load_step(self, step_data: Dict[str, Any]):
        """Load and display step data.
        
        Args:
            step_data: Dictionary containing step information
        """
        logger.info(f"加载步骤: step_num={step_data.get('step_num')}")
        logger.debug(f"步骤数据: user_label={step_data.get('user_label')}, user_correction={repr(step_data.get('user_correction'))}")
        
        self.current_step = step_data
        
        # Load screenshot
        screenshot_path = step_data.get('screenshot_path')
        if screenshot_path:
            # Convert relative path to absolute path
            screenshot_path = Path(screenshot_path)
            if not screenshot_path.is_absolute():
                screenshot_path = _get_project_root() / screenshot_path
            
            if screenshot_path.exists():
                pixmap = QPixmap(str(screenshot_path))
                if not pixmap.isNull():
                    # Scale to fit while maintaining aspect ratio
                    scaled_pixmap = pixmap.scaled(
                        self.screenshot_label.width() - 20,
                        self.screenshot_label.height() - 20,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                    self.screenshot_label.setPixmap(scaled_pixmap)
                else:
                    self.screenshot_label.setText("无法加载截图")
            else:
                self.screenshot_label.setText(f"截图文件不存在: {screenshot_path}")
        else:
            self.screenshot_label.setText("暂无截图")
        
        # Load thinking with cleaned text
        thinking = step_data.get('thinking', '')
        cleaned_thinking = self._clean_text(thinking) if thinking else "暂无思考过程"
        self.thinking_text.setPlainText(cleaned_thinking)
        
        # Load action
        action = step_data.get('action')
        if action:
            if isinstance(action, dict):
                action_text = f"动作类型: {action.get('action', 'unknown')}\n"
                params = action.get('params', {})
                if params:
                    action_text += "参数:\n"
                    for key, value in params.items():
                        action_text += f"  {key}: {value}\n"
                self.action_text.setPlainText(action_text)
            else:
                self.action_text.setPlainText(str(action))
        else:
            self.action_text.setPlainText("暂无动作信息")
        
        # Show existing annotation if any
        user_label = step_data.get('user_label')
        if user_label:
            self._highlight_button(user_label)
            if user_label == 'wrong':
                correction = step_data.get('user_correction', '')
                self.correction_input.setPlainText(correction)
                self.correction_input.setVisible(True)
        else:
            self._reset_buttons()
            self.correction_input.setVisible(False)
    
    def _on_annotate(self, label: str):
        """Handle annotation button click.
        
        Args:
            label: 'correct', 'wrong', or 'skip'
        """
        logger.info(f"标注按钮点击: label={label}")
        
        if not self.current_step:
            logger.warning("当前步骤为空，无法标注")
            return
        
        step_num = self.current_step.get('step_num')
        if step_num is None:
            logger.warning("步骤号为空，无法标注")
            return
        
        logger.debug(f"当前步骤号: {step_num}")
        
        if label == 'wrong':
            # Show correction input and save button
            logger.info("显示纠正输入框和保存按钮")
            self.correction_input.setVisible(True)
            self.save_correction_btn.setVisible(True)
            self.correction_input.setFocus()
            # Don't emit signal yet, wait for user to enter correction and click save
            return
        elif label == 'skip':
            # Skip means no annotation
            logger.info("跳过标注")
            correction = ''
            actual_label = None
            # Hide correction input and save button
            self.correction_input.setVisible(False)
            self.save_correction_btn.setVisible(False)
        else:  # correct
            logger.info("标注为正确")
            correction = ''
            actual_label = label
            # Hide correction input and save button
            self.correction_input.setVisible(False)
            self.save_correction_btn.setVisible(False)
        
        # Emit signal (but don't auto-navigate)
        logger.info(f"发送标注信号: step_num={step_num}, label={actual_label}, correction={repr(correction)}")
        self.step_annotated.emit(step_num, actual_label or '', correction)
    
    def save_wrong_annotation(self):
        """Save wrong annotation with correction text."""
        logger.info("保存错误标注")
        
        if not self.current_step:
            logger.warning("当前步骤为空，无法保存")
            return
        
        step_num = self.current_step.get('step_num')
        if step_num is None:
            logger.warning("步骤号为空，无法保存")
            return
        
        correction = self.correction_input.toPlainText().strip()
        logger.info(f"发送错误标注信号: step_num={step_num}, correction={repr(correction)}")
        
        # Hide correction input and save button after saving
        self.correction_input.setVisible(False)
        self.save_correction_btn.setVisible(False)
        
        self.step_annotated.emit(step_num, 'wrong', correction)
    
    def _highlight_button(self, label: str):
        """Highlight the button corresponding to the label."""
        self._reset_buttons()
        if label == 'correct':
            self.correct_btn.setStyleSheet(
                "QPushButton { background-color: #2E7D32; color: white; font-weight: bold; padding: 10px; border: 3px solid #1B5E20; }"
            )
        elif label == 'wrong':
            self.wrong_btn.setStyleSheet(
                "QPushButton { background-color: #C62828; color: white; font-weight: bold; padding: 10px; border: 3px solid #B71C1C; }"
            )
    
    def _reset_buttons(self):
        """Reset button styles to default."""
        self.correct_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #45a049; }"
        )
        self.wrong_btn.setStyleSheet(
            "QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #da190b; }"
        )
        self.skip_btn.setStyleSheet(
            "QPushButton { background-color: #9E9E9E; color: white; font-weight: bold; padding: 10px; }"
            "QPushButton:hover { background-color: #757575; }"
        )


class TaskReviewWidget(QWidget):
    """Main widget for task review and annotation."""
    
    def __init__(self, task_logger: TaskLogger, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.task_logger = task_logger
        self.current_session_id: Optional[str] = None
        self.current_steps: List[Dict[str, Any]] = []
        self.current_step_index: int = 0
        self._setup_ui()
        self.load_tasks()
    
    def _setup_ui(self):
        """Set up the UI layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create splitter for resizable panels
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel: Task list
        left_panel = self._create_task_list_panel()
        splitter.addWidget(left_panel)
        
        # Right panel: Step player
        self.step_player = StepPlayerWidget()
        self.step_player.step_annotated.connect(self._on_step_annotated)
        self.step_player.prev_step_requested.connect(self._load_prev_step)
        self.step_player.next_step_requested.connect(self._load_next_step)
        
        # Connect batch operation buttons
        self.step_player.mark_all_correct_btn.clicked.connect(self._mark_all_correct)
        self.step_player.clear_annotations_btn.clicked.connect(self._clear_all_annotations)
        self.step_player.extract_golden_path_btn.clicked.connect(self._extract_golden_path)
        
        splitter.addWidget(self.step_player)
        
        # Set initial sizes (30% left, 70% right)
        splitter.setSizes([300, 700])
        
        layout.addWidget(splitter)
    
    def _create_task_list_panel(self) -> QWidget:
        """Create the task list panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Title with refresh button
        title_layout = QHBoxLayout()
        title_label = QLabel("历史任务列表")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.setStyleSheet(
            "QPushButton { padding: 4px 8px; }"
        )
        refresh_btn.clicked.connect(self.load_tasks)
        title_layout.addWidget(refresh_btn)
        
        layout.addLayout(title_layout)
        
        # Task list
        self.task_list = QListWidget()
        self.task_list.itemSelectionChanged.connect(self._on_task_selected)
        layout.addWidget(self.task_list)
        
        return panel
    
    def load_tasks(self):
        """Load all tasks into the list."""
        self.task_list.clear()
        
        # Get all sessions
        sessions = self.task_logger.get_all_sessions(limit=100)
        
        for session in sessions:
            session_id = session.get('session_id', '')
            task_desc = session.get('task_description', '未知任务')
            final_status = session.get('final_status', 'UNKNOWN')
            total_steps = session.get('total_steps', 0)
            timestamp = session.get('timestamp', '')
            
            # Format display text
            status_icon = "✓" if final_status == "SUCCESS" else "✗"
            item_text = f"{status_icon} {task_desc[:40]}... ({total_steps}步) - {timestamp}"
            
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, session_id)
            
            # Color code by status
            if final_status == "SUCCESS":
                item.setForeground(Qt.darkGreen)
            else:
                item.setForeground(Qt.darkRed)
            
            self.task_list.addItem(item)
    
    def _on_task_selected(self):
        """Handle task selection."""
        current_item = self.task_list.currentItem()
        if not current_item:
            return
        
        session_id = current_item.data(Qt.UserRole)
        self.current_session_id = session_id
        
        # Load steps for this session
        self.current_steps = self.task_logger.get_session_steps(session_id)
        self.current_step_index = 0
        
        if self.current_steps:
            self._load_current_step()
        else:
            QMessageBox.information(self, "提示", "该任务没有步骤记录")
    
    def _on_step_annotated(self, step_num: int, label: str, correction: str):
        """Handle step annotation.
        
        Args:
            step_num: Step number
            label: 'correct', 'wrong', or empty string for skip
            correction: Correction text (for wrong steps)
        """
        logger.info(f"收到标注信号: step_num={step_num}, label={label}, correction={repr(correction)}")
        
        if not self.current_session_id:
            logger.warning("当前会话ID为空，无法保存标注")
            return
        
        logger.debug(f"当前会话ID: {self.current_session_id}")
        
        try:
            # Save annotation to database
            if label:  # Only save if not skip
                logger.info(f"保存标注到数据库: session_id={self.current_session_id}, step_num={step_num}, label={label}")
                self.task_logger.add_user_feedback(
                    self.current_session_id,
                    step_num,
                    label,
                    correction
                )
                logger.info("✓ 标注保存成功")
                
                # 重新加载步骤数据以更新标注状态
                logger.debug("重新加载步骤数据...")
                self.current_steps = self.task_logger.get_session_steps(self.current_session_id)
                logger.debug(f"步骤数据已刷新，共 {len(self.current_steps)} 个步骤")
                
                # 重新加载当前步骤以更新UI显示
                self._load_current_step()
                logger.info("✓ UI已更新")
            else:
                logger.info("跳过标注，不保存到数据库")
        except Exception as e:
            logger.error(f"保存标注失败: {e}", exc_info=True)
            QMessageBox.critical(self, "错误", f"保存标注失败: {e}")
    
    def _load_current_step(self):
        """Load the current step based on current_step_index."""
        if not self.current_steps:
            return
        
        if 0 <= self.current_step_index < len(self.current_steps):
            self.step_player.load_step(self.current_steps[self.current_step_index])
            self.step_player.set_step_info(self.current_step_index, len(self.current_steps))
    
    def _load_prev_step(self):
        """Load the previous step."""
        if not self.current_steps:
            return
        
        if self.current_step_index > 0:
            self.current_step_index -= 1
            self._load_current_step()
    
    def _load_next_step(self):
        """Load the next step."""
        if not self.current_steps:
            return
        
        if self.current_step_index < len(self.current_steps) - 1:
            self.current_step_index += 1
            self._load_current_step()
        else:
            QMessageBox.information(self, "提示", "已到达最后一步")

    def _mark_all_correct(self):
        """Mark all steps in current task as correct."""
        if not self.current_session_id or not self.current_steps:
            QMessageBox.warning(self, "警告", "请先选择一个任务")
            return
        
        # Confirm action
        reply = QMessageBox.question(
            self,
            "确认批量标注",
            f"确定要将当前任务的所有 {len(self.current_steps)} 个步骤标记为正确吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # Mark all steps as correct
            for step in self.current_steps:
                step_num = step.get('step_num')
                if step_num is not None:
                    self.task_logger.add_user_feedback(
                        self.current_session_id,
                        step_num,
                        'correct',
                        ''
                    )
            
            QMessageBox.information(
                self,
                "成功",
                f"已将 {len(self.current_steps)} 个步骤标记为正确"
            )
            
            # Reload current task to show updated annotations
            self.current_steps = self.task_logger.get_session_steps(self.current_session_id)
            self._load_current_step()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"批量标注失败: {e}")
    
    def _clear_all_annotations(self):
        """Clear all annotations for current task."""
        if not self.current_session_id or not self.current_steps:
            QMessageBox.warning(self, "警告", "请先选择一个任务")
            return
        
        # Confirm action
        reply = QMessageBox.question(
            self,
            "确认清除标注",
            f"确定要清除当前任务的所有标注吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            # Clear all annotations by setting user_label to NULL
            conn = self.task_logger._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                UPDATE steps
                SET user_label = NULL, user_correction = NULL
                WHERE session_id = ?
            """, (self.current_session_id,))
            
            conn.commit()
            conn.close()
            
            QMessageBox.information(
                self,
                "成功",
                "已清除所有标注"
            )
            
            # Reload current task to show cleared annotations
            self.current_steps = self.task_logger.get_session_steps(self.current_session_id)
            self._load_current_step()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"清除标注失败: {e}")
    
    def _extract_golden_path(self):
        """Extract golden path from current task."""
        if not self.current_session_id:
            QMessageBox.warning(self, "警告", "请先选择一个任务")
            return
        
        try:
            # Import here to avoid circular dependency
            from gui.utils.golden_path_extractor import GoldenPathExtractor
            from gui.utils.golden_path_repository import GoldenPathRepository
            from gui.utils.steering_file_manager import SteeringFileManager
            from pathlib import Path
            
            # Extract golden path
            extractor = GoldenPathExtractor(self.task_logger)
            golden_path = extractor.extract_from_session(self.current_session_id)
            
            if not golden_path:
                QMessageBox.warning(
                    self,
                    "提取失败",
                    "无法从当前任务提取黄金路径。\n\n"
                    "请确保：\n"
                    "1. 至少有 2-3 个步骤被标记为正确\n"
                    "2. 任务已成功完成"
                )
                return
            
            # Save to database
            db_path = str(Path(self.task_logger.log_dir) / "tasks.db")
            repository = GoldenPathRepository(db_path)
            path_id = repository.save(golden_path)
            
            # Save to YAML file
            manager = SteeringFileManager()
            yaml_path = manager.save_golden_path(golden_path.to_dict())
            
            # Show success message
            msg = f"✅ 成功提取黄金路径！\n\n"
            msg += f"任务模式: {golden_path.task_pattern}\n"
            msg += f"难度: {golden_path.difficulty}\n"
            msg += f"步骤数: {len(golden_path.action_sop)}\n"
            msg += f"可重放: {'是' if golden_path.can_replay else '否'}\n\n"
            msg += f"数据库 ID: {path_id}\n"
            if yaml_path:
                msg += f"YAML 文件: {yaml_path}"
            
            QMessageBox.information(self, "成功", msg)
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"提取黄金路径失败: {e}")
            import traceback
            traceback.print_exc()
