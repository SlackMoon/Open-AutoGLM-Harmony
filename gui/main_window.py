"""
Main window for Open-AutoGLM GUI application.
"""

import base64
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QSettings, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont, QIcon, QPainter, QColor
from PyQt5.QtWidgets import (
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
    QTabWidget,
    QSizePolicy,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.utils.agent_runner import AgentRunner
from gui.utils.task_thread import AgentTaskThread
from gui.utils.layout import scroll_panel, fit_initial_window, size_controls_to_text
from gui.utils.theme import light_palette
from gui.utils.runtime_diagnostics import log_task_error
from gui.utils.system_checker import check_model_api, run_all_checks, CheckResult
from gui.utils.task_logger import TaskLogger
from gui.widgets.log_viewer import LogViewer
from gui.widgets.device_mirror import DeviceMirrorWidget
from gui.widgets.data_storage import DataStorageWidget
from phone_agent.adb import ADBConnection, list_devices


def _get_logs_dir() -> str:
    """Get the logs directory path (always in Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe (dist/GUI.exe)
        # Go up from dist/ to Open-AutoGLM-main/
        return str(Path(sys.executable).parent.parent / "logs")
    else:
        # Running as script - gui/main_window.py
        # Go up to Open-AutoGLM-main/logs
        return str(Path(__file__).parent.parent / "logs")


class ModelAPICheckWorker(QThread):
    """后台线程用于执行模型 API 检查"""
    result_ready = pyqtSignal(bool, object)  # success, CheckResult

    def __init__(self, base_url: str, model_name: str, api_key: str):
        super().__init__()
        self.base_url = base_url
        self.model_name = model_name
        self.api_key = api_key
        self.cancelled = False

    def run(self):
        """执行 API 检查"""
        try:
            result = check_model_api(self.base_url, self.model_name, self.api_key)
            self.result_ready.emit(result.success, result)
        except Exception as e:
            # 如果检查函数本身抛出异常，创建一个错误结果
            error_result = CheckResult(
                success=False,
                message=f"检查异常: {str(e)}",
                details=str(e),
            )
            self.result_ready.emit(False, error_result)


class MainWindow(QWidget):
    """Main window for the Open-AutoGLM GUI application."""

    def __init__(self):
        """Initialize the main window."""
        super().__init__()

        self.settings = QSettings("Open-AutoGLM", "GUI")
        self.adb_connection = ADBConnection()
        self.agent_runner: Optional[AgentRunner] = None
        self.agent_thread: Optional[QThread] = None
        self.selected_device_id: Optional[str] = None
        # Track checking status for each check type
        self.check_status: dict[str, bool] = {}  # True if checking, False otherwise
        self.check_timers: dict[str, QTimer] = {}  # Store timers for quick checks
        self.check_threads: dict[str, object] = {}  # Store thread references for slow checks
        # Track thinking stream state for incremental updates
        self._thinking_stream_active = False
        self._close_requested = False
        self._close_timer = QTimer(self)
        self._close_timer.setInterval(100)
        self._close_timer.timeout.connect(self.close)
        # Task logging state
        self.task_logger = TaskLogger(log_dir=_get_logs_dir())
        self._current_session_id: Optional[str] = None
        self._task_start_time: Optional[float] = None
        self._last_step_start: Optional[float] = None
        self._step_count: int = 0
        self._last_action: Optional[dict] = None
        self._current_step_thinking: list[str] = []  # Accumulate thinking for current step
        self._session_finalized: bool = False
        self._pending_step_logs: int = 0  # Track pending step log operations
        self._is_stopping: bool = False  # Track if task is being stopped

        self._setup_ui()
        self._load_settings()
        # Initialize mode-related UI state after loading settings (without refreshing devices yet)
        mode = self.device_mode_combo.currentText()
        is_harmonyos = "鸿蒙" in mode
        tool_name = "HDC" if is_harmonyos else "ADB"
        self.adb_status_label.setText(f"{tool_name} 安装: 未检查")
        self.keyboard_status_label.setEnabled(not is_harmonyos)
        self.keyboard_check_btn.setEnabled(not is_harmonyos)
        if is_harmonyos:
            self.keyboard_status_label.setText("ADB Keyboard: 鸿蒙模式不需要")
            self.keyboard_status_label.setStyleSheet("color: #475569;")
        else:
            self.keyboard_status_label.setText("ADB Keyboard: 未检查")
            self.keyboard_status_label.setStyleSheet("")
        self._setup_timers()
        self._connect_signals()
        self._init_check_status()
        self._sync_mirror_device()

    def _setup_ui(self):
        self.setWindowTitle("Open-AutoGLM GUI")
        icon_path = Path(__file__).parent.parent / "resources" / "LOG.ico"
        self.setWindowIcon(QIcon(str(icon_path)))
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 6)
        outer_layout.setSpacing(8)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(6)
        self.config_scroll = scroll_panel(self._create_left_panel(), "configurationScroll")
        self.config_scroll.setMinimumWidth(240)
        self.main_splitter.addWidget(self.config_scroll)

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setUsesScrollButtons(True)
        self.workspace_tabs.setElideMode(Qt.ElideNone)
        self.workspace_tabs.addTab(scroll_panel(self._create_middle_panel(), "taskScroll"), "任务执行")
        self.workspace_tabs.addTab(scroll_panel(self._create_right_panel(), "historyScroll"), "历史与教学")
        self.main_splitter.addWidget(self.workspace_tabs)
        self.device_mirror = DeviceMirrorWidget()
        self.device_mirror.message.connect(self._on_device_mirror_message)
        self.device_mirror.setMinimumWidth(240)
        self.main_splitter.addWidget(self.device_mirror)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 1)
        self.main_splitter.setSizes([300, 480, 540])
        outer_layout.addWidget(self.main_splitter, 1)

        disclaimer = QLabel("本软件仅供学习研究，使用者应遵守法律法规。")
        disclaimer.setWordWrap(True)
        disclaimer.setAlignment(Qt.AlignCenter)
        disclaimer.setStyleSheet("color: #888; padding: 2px;")
        outer_layout.addWidget(disclaimer)
        self._apply_styles()
        self._fit_controls()
        fit_initial_window(self)

    def _apply_styles(self):
        """Apply light blue/white theme without changing functionality."""
        self.setPalette(light_palette())
        self.setStyleSheet(
            """
            QWidget {
                background: #f6f8fb;
                color: #1f2933;
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
                font-size: 10pt;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #dbe2ea;
                border-radius: 6px;
                margin-top: 8px;
                padding: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
                color: #1d4ed8;
                font-weight: 600;
            }
            QLabel#errorHint {
                color: #d32f2f;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#statusLabel {
                font-size: 16px;
                font-weight: 700;
                color: #0f172a;
            }
            QLabel, QCheckBox { color: #1f2933; }
            QLabel:disabled, QCheckBox:disabled { color: #475569; }
            QLineEdit, QTextEdit, QListWidget, QPlainTextEdit {
                color: #1f2933;
                selection-color: #0f172a;
                selection-background-color: #dbeafe;
                background: #ffffff;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 6px;
            }
            QComboBox {
                color: #1f2933;
                selection-color: #0f172a;
                selection-background-color: #dbeafe;
                background: #ffffff;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 6px 28px 6px 8px;
            }
            QComboBox::drop-down {
                width: 24px;
                border-left: 1px solid #dbe2ea;
            }
            QComboBox QAbstractItemView {
                color: #1f2933;
                background: #ffffff;
                padding: 4px;
                selection-color: #0f172a;
                selection-background-color: #dbeafe;
            }
            QComboBox QAbstractItemView::item:selected {
                color: #0f172a;
                background: #dbeafe;
            }
            QComboBox:disabled, QLineEdit:disabled, QTextEdit:disabled,
            QPlainTextEdit:disabled, QListWidget:disabled, QPushButton:disabled {
                color: #475569;
                background: #f1f5f9;
            }
            QLineEdit:focus, QTextEdit:focus, QListWidget:focus, QPlainTextEdit:focus {
                border: 1px solid #3b82f6;
            }
            QPushButton {
                color: #1f2933;
                background: #e5ecf7;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #dbeafe;
                border-color: #b6c5e0;
            }
            QPushButton:pressed {
                background: #c7dafc;
            }
            QPushButton#startBtn {
                background: #3b82f6;
                color: white;
                border: 1px solid #2563eb;
            }
            QPushButton#startBtn:hover {
                background: #2563eb;
            }
            QPushButton#stopBtn {
                background: #ef4444;
                color: white;
                border: 1px solid #dc2626;
            }
            QPushButton#stopBtn:hover {
                background: #dc2626;
            }
            QPushButton#helpBtn {
                background: #0ea5e9;
                color: white;
                border: 1px solid #0284c7;
            }
            QPushButton#helpBtn:hover {
                background: #0284c7;
            }
            QListWidget::item {
                padding: 6px;
            }
            QListWidget::item:selected {
                background: #e0ecff;
                color: #0f172a;
            }
            QSplitter::handle {
                background: #dbe2ea;
            }
            """
        )

    def _create_left_panel(self) -> QWidget:
        """Create the left configuration panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # Model configuration group
        model_group = QGroupBox("模型配置")
        model_layout = QVBoxLayout()

        # Preset selection
        preset_label = QLabel("预设配置:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["自定义", "智谱-Phone", "IP99-Qwen视觉"])
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        model_layout.addWidget(preset_label)
        model_layout.addWidget(self.preset_combo)

        # Online-only hint
        online_hint = QLabel("支持兼容 OpenAI 的视觉模型 API（含本地服务）")
        online_hint.setWordWrap(True)
        online_hint.setStyleSheet("color: #f44336; font-size: 11px;")
        model_layout.addWidget(online_hint)

        # Base URL
        base_url_label = QLabel("Base URL:")
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api-inference.modelscope.cn/v1")
        model_layout.addWidget(base_url_label)
        model_layout.addWidget(self.base_url_input)

        # Model name
        model_label = QLabel("Model 名称:")
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("ZhipuAI/AutoGLM-Phone-9B")
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_input)

        # API Key + remember option
        api_key_layout = QHBoxLayout()
        api_key_label = QLabel("API Key:")
        self.remember_key_checkbox = QCheckBox("记住")
        self.remember_key_checkbox.setToolTip("勾选后会加密存储 API Key，下次启动自动填充")
        api_key_layout.addWidget(api_key_label)
        api_key_layout.addStretch()
        api_key_layout.addWidget(self.remember_key_checkbox)
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("输入你的 API Key")
        model_layout.addLayout(api_key_layout)
        model_layout.addWidget(self.api_key_input)
        
        # Store original placeholder for restoration
        self.api_key_placeholder_default = "输入你的 API Key"

        model_group.setLayout(model_layout)
        layout.addWidget(model_group)

        # Device configuration group
        device_group = QGroupBox("设备配置")
        device_layout = QVBoxLayout()

        # Device mode selection (Android/HarmonyOS)
        mode_label = QLabel("设备模式:")
        self.device_mode_combo = QComboBox()
        self.device_mode_combo.addItems(["安卓模式 (ADB)", "鸿蒙模式 (HDC)"])
        self.device_mode_combo.currentTextChanged.connect(self._on_device_mode_changed)
        device_layout.addWidget(mode_label)
        device_layout.addWidget(self.device_mode_combo)

        # Device list
        device_list_label = QLabel("已连接设备:")
        self.device_list = QListWidget()
        self.device_list.setMaximumHeight(150)
        self.device_list.itemSelectionChanged.connect(self._on_device_selected)
        device_layout.addWidget(device_list_label)
        device_layout.addWidget(self.device_list)

        # Refresh button
        refresh_btn = QPushButton("刷新设备列表")
        refresh_btn.clicked.connect(self._refresh_devices)
        device_layout.addWidget(refresh_btn)

        # Remote connection (Wireless debugging)
        remote_label_layout = QHBoxLayout()
        remote_label = QLabel("无线调试 (IP:Port):")
        open_path_btn = QPushButton("打开路径")
        open_path_btn.setToolTip("查看手机中开启无线调试的路径说明")
        open_path_btn.clicked.connect(self._show_wireless_debug_path)
        remote_label_layout.addWidget(remote_label)
        remote_label_layout.addStretch()
        remote_label_layout.addWidget(open_path_btn)

        remote_layout = QHBoxLayout()
        self.remote_input = QLineEdit()
        self.remote_input.setPlaceholderText("192.168.1.100:5555")
        connect_btn = QPushButton("连接")
        connect_btn.clicked.connect(self._connect_remote)
        remote_layout.addWidget(self.remote_input)
        remote_layout.addWidget(connect_btn)
        device_layout.addLayout(remote_label_layout)
        device_layout.addLayout(remote_layout)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # Environment check group
        check_group = QGroupBox("环境检查")
        check_layout = QVBoxLayout()

        # Individual check items
        check_items_layout = QVBoxLayout()
        
        # ADB/HDC 安装检查
        adb_item_layout = QHBoxLayout()
        self.adb_status_label = QLabel("ADB/HDC 安装")
        self.adb_check_btn = QPushButton("检查")
        self.adb_check_btn.clicked.connect(lambda: self._toggle_check("adb"))
        adb_item_layout.addWidget(self.adb_status_label, 1)
        adb_item_layout.addWidget(self.adb_check_btn)
        check_items_layout.addLayout(adb_item_layout)
        
        # 设备连接检查
        device_item_layout = QHBoxLayout()
        self.device_status_label = QLabel("设备连接")
        self.device_check_btn = QPushButton("检查")
        self.device_check_btn.clicked.connect(lambda: self._toggle_check("devices"))
        device_item_layout.addWidget(self.device_status_label, 1)
        device_item_layout.addWidget(self.device_check_btn)
        check_items_layout.addLayout(device_item_layout)
        
        # ADB Keyboard 检查 (仅安卓模式)
        keyboard_item_layout = QHBoxLayout()
        self.keyboard_status_label = QLabel("ADB Keyboard")
        self.keyboard_check_btn = QPushButton("检查")
        self.keyboard_check_btn.clicked.connect(lambda: self._toggle_check("keyboard"))
        keyboard_item_layout.addWidget(self.keyboard_status_label, 1)
        keyboard_item_layout.addWidget(self.keyboard_check_btn)
        check_items_layout.addLayout(keyboard_item_layout)
        
        # 模型 API 检查
        api_item_layout = QHBoxLayout()
        self.api_status_label = QLabel("模型 API")
        self.api_check_btn = QPushButton("检查")
        self.api_check_btn.clicked.connect(lambda: self._toggle_check("model_api"))
        api_item_layout.addWidget(self.api_status_label, 1)
        api_item_layout.addWidget(self.api_check_btn)
        check_items_layout.addLayout(api_item_layout)
        
        check_layout.addLayout(check_items_layout)
        
        # All check button
        self.check_all_btn = QPushButton("检查全部")
        self.check_all_btn.clicked.connect(self._run_all_environment_checks)
        check_layout.addWidget(self.check_all_btn)

        check_group.setLayout(check_layout)
        layout.addWidget(check_group)

        layout.addStretch()

        # Help button
        help_btn = QPushButton("📖 使用必读")
        help_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 8px;")
        help_btn.clicked.connect(self._show_usage_guide)
        layout.addWidget(help_btn)

        return panel

    def _create_middle_panel(self) -> QWidget:
        """Create the middle task execution panel (including status and runtime logs)."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # Task input group
        task_group = QGroupBox("任务输入")
        task_layout = QVBoxLayout()

        self.task_input = QTextEdit()
        self.task_input.setPlaceholderText(
            "输入你的任务描述，例如：\n"
            "打开微信，对文件传输助手发送消息：部署成功\n\n"
            "💡 第一次命令请尽量详细，例如(vivo):\n"
            "打开设置,找到游戏魔盒打开,关闭游戏魔盒按钮\n\n"
            "⚡ 设置快捷命令后，可直接输入简短命令，如:\n"
            "关闭游戏魔盒"
        )
        self.task_input.setMinimumHeight(96)
        self.task_input.setMaximumHeight(200)
        task_layout.addWidget(self.task_input)

        task_group.setLayout(task_layout)
        layout.addWidget(task_group)

        # Control buttons
        control_layout = QHBoxLayout()

        self.start_btn = QPushButton("开始执行")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.start_btn.clicked.connect(self._start_task)
        self.start_btn.setMinimumHeight(40)

        self.stop_btn = QPushButton("停止执行")
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-weight: bold;")
        self.stop_btn.clicked.connect(self._stop_task)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(40)

        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.stop_btn)
        layout.addLayout(control_layout)

        # Status display
        status_group = QGroupBox("任务状态")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("状态: 空闲")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont()
        status_font.setPointSize(12)
        status_font.setBold(True)
        self.status_label.setFont(status_font)
        status_layout.addWidget(self.status_label)

        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        status_layout.addWidget(self.progress_label)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Runtime log viewer (moved from right panel)
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()

        self.log_viewer = LogViewer()
        self.log_viewer.setMinimumHeight(160)
        log_layout.addWidget(self.log_viewer)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group, 1)

        return panel

    def _create_right_panel(self) -> QWidget:
        """Create the right panel for data storage / history overview."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        data_group = QGroupBox("数据存储 / 历史记录")
        data_layout = QVBoxLayout()

        self.data_storage_widget = DataStorageWidget(task_logger=self.task_logger)
        data_layout.addWidget(self.data_storage_widget)

        data_group.setLayout(data_layout)
        layout.addWidget(data_group, 1)

        return panel

    def _setup_timers(self):
        """Set up automatic refresh timers."""
        # Device list refresh timer (every 5 seconds to reduce overhead)
        self.device_timer = QTimer()
        self.device_timer.timeout.connect(self._refresh_devices_silent)
        self.device_timer.start(5000)  # 5 seconds (reduced from 3)

        # Initial device refresh
        self._refresh_devices()

    def _connect_signals(self):
        """Connect agent runner signals to UI slots."""
        # Signals will be connected when agent runner is created
    
    def _init_check_status(self):
        """Initialize check status labels."""
        if hasattr(self, 'adb_status_label'):
            mode = self.device_mode_combo.currentText()
            tool_name = "HDC" if "鸿蒙" in mode else "ADB"
            self.adb_status_label.setText(f"{tool_name} 安装: 未检查")
            self.device_status_label.setText("设备连接: 未检查")
            self.keyboard_status_label.setText("ADB Keyboard: 未检查")
            self.api_status_label.setText("模型 API: 未检查")

    def _load_settings(self):
        """Load saved settings."""
        self.base_url_input.setText(
            self.settings.value("base_url", "https://api-inference.modelscope.cn/v1")
        )
        self.model_input.setText(
            self.settings.value("model", "ZhipuAI/AutoGLM-Phone-9B")
        )
        # 加载设备模式设置
        device_mode = self.settings.value("device_mode", "安卓模式 (ADB)")
        mode_index = self.device_mode_combo.findText(device_mode)
        if mode_index >= 0:
            self.device_mode_combo.setCurrentIndex(mode_index)
        # 加载是否记住 API Key
        remember_key = self.settings.value("remember_api_key", False, type=bool)
        self.remember_key_checkbox.setChecked(remember_key)
        if remember_key:
            encrypted_key = self.settings.value("api_key", "")
            if encrypted_key:
                try:
                    decrypted_key = self._decrypt_api_key(encrypted_key)
                    self.api_key_input.setText(decrypted_key)
                except Exception:
                    # 如果解密失败，尝试直接使用原值（兼容早期明文）
                    self.api_key_input.setText(encrypted_key)
            else:
                self.api_key_input.setText("")
        else:
            self.api_key_input.setText("")
        
        # Update teaching mode config after loading settings
        # Use QTimer to ensure widgets are fully initialized
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(100, self._update_teaching_mode_config)

    def _save_settings(self):
        """Save current settings."""
        self.settings.setValue("base_url", self.base_url_input.text())
        self.settings.setValue("model", self.model_input.text())
        # 保存设备模式设置
        self.settings.setValue("device_mode", self.device_mode_combo.currentText())
        # 保存 API Key（加密）仅在用户勾选时
        if self.remember_key_checkbox.isChecked():
            api_key = self.api_key_input.text()
            self.settings.setValue("remember_api_key", True)
            if api_key:
                encrypted_key = self._encrypt_api_key(api_key)
                self.settings.setValue("api_key", encrypted_key)
            else:
                self.settings.setValue("api_key", "")
        else:
            self.settings.setValue("remember_api_key", False)
            self.settings.setValue("api_key", "")
        
        # Update teaching mode config
        self._update_teaching_mode_config()
    
    def _update_teaching_mode_config(self):
        """Update teaching mode widget with current configuration."""
        if hasattr(self, 'data_storage_widget') and self.data_storage_widget:
            base_url = self.base_url_input.text().strip()
            model_name = self.model_input.text().strip()
            api_key = self.api_key_input.text().strip()
            device_id = getattr(self, 'selected_device_id', None)
            mode = self.device_mode_combo.currentText()
            device_mode = "harmonyos" if "鸿蒙" in mode else "android"
            
            self.data_storage_widget.set_teaching_mode_config(
                base_url, model_name, api_key, device_id, device_mode
            )
    
    def _encrypt_api_key(self, api_key: str) -> str:
        """
        Simple encryption for API key storage.
        Note: This is basic obfuscation, not military-grade encryption.
        For production, consider using keyring library.
        """
        try:
            # Convert to UTF-8 bytes first to handle Unicode properly
            key = "OpenAutoGLM2024"
            api_key_bytes = api_key.encode('utf-8')
            key_bytes = key.encode('utf-8')
            
            # XOR encryption
            encrypted = bytearray()
            for i, byte in enumerate(api_key_bytes):
                encrypted.append(byte ^ key_bytes[i % len(key_bytes)])
            
            return base64.b64encode(bytes(encrypted)).decode('utf-8')
        except Exception:
            # If encryption fails, return original (fallback)
            return api_key
    
    def _decrypt_api_key(self, encrypted_key: str) -> str:
        """
        Decrypt API key from storage.
        """
        try:
            # Reverse the XOR encryption
            key = "OpenAutoGLM2024"
            key_bytes = key.encode('utf-8')
            decoded = base64.b64decode(encrypted_key.encode('utf-8'))
            
            # XOR decryption
            decrypted_bytes = bytearray()
            for i, byte in enumerate(decoded):
                decrypted_bytes.append(byte ^ key_bytes[i % len(key_bytes)])
            
            return decrypted_bytes.decode('utf-8')
        except Exception:
            # If decryption fails, return original (fallback)
            return encrypted_key

    def _on_preset_changed(self, preset: str):
        """Handle preset configuration change."""
        if preset == "智谱-Phone":
            self.base_url_input.setText("https://api-inference.modelscope.cn/v1")
            self.model_input.setText("ZhipuAI/AutoGLM-Phone-9B")
            self.api_key_input.setPlaceholderText("ms-xxxxxx (ModelScope API Key 格式)")
        elif preset == "IP99-Qwen视觉":
            if self.base_url_input.text().rstrip("/") != "https://llm.ip99.com/v1":
                self.api_key_input.clear()
            self.base_url_input.setText("https://llm.ip99.com/v1")
            self.model_input.setText("qwen3.8-flash-next-uncensored")
            self.api_key_input.setPlaceholderText("填写 IP99 API Key")
        else:  # 自定义
            self.api_key_input.setPlaceholderText(self.api_key_placeholder_default)

    def _on_device_mode_changed(self, mode: str):
        """Handle device mode change (Android/HarmonyOS)."""
        is_harmonyos = "鸿蒙" in mode
        # 更新状态标签文本
        tool_name = "HDC" if is_harmonyos else "ADB"
        self.adb_status_label.setText(f"{tool_name} 安装: 未检查")
        # 鸿蒙模式不需要检查ADB Keyboard
        self.keyboard_status_label.setEnabled(not is_harmonyos)
        self.keyboard_check_btn.setEnabled(not is_harmonyos)
        if is_harmonyos:
            self.keyboard_status_label.setText("ADB Keyboard: 鸿蒙模式不需要")
            self.keyboard_status_label.setStyleSheet("color: #475569;")
        else:
            self.keyboard_status_label.setText("ADB Keyboard: 未检查")
            self.keyboard_status_label.setStyleSheet("")
        # 保存设置
        self.settings.setValue("device_mode", mode)
        # 刷新设备列表
        self._refresh_devices()
        self._sync_mirror_device()

    def _refresh_devices(self):
        """Refresh the device list (with logging)."""
        try:
            # Get current device mode
            mode = self.device_mode_combo.currentText()
            is_harmonyos = "鸿蒙" in mode
            
            if is_harmonyos:
                # Use HDC for HarmonyOS
                devices = self._list_hdc_devices()
            else:
                # Use ADB for Android
                devices = list_devices()
            
            # Block signals to prevent triggering selection event during refresh
            self.device_list.blockSignals(True)
            
            self.device_list.clear()

            for device in devices:
                if isinstance(device, dict):
                    # HDC device format
                    device_id = device.get("device_id", "")
                    status = device.get("status", "unknown")
                    if status == "device" or status == "connected":
                        item_text = f"{device_id}"
                        item = QListWidgetItem(item_text)
                        item.setData(Qt.UserRole, device_id)
                        self.device_list.addItem(item)
                elif hasattr(device, 'status') and device.status == "device":
                    # ADB device format
                    item_text = f"{device.device_id} ({device.connection_type.value})"
                    if device.model:
                        item_text += f" - {device.model}"
                    item = QListWidgetItem(item_text)
                    item.setData(Qt.UserRole, device.device_id)
                    self.device_list.addItem(item)

            # Restore selection if device still exists
            if self.selected_device_id:
                for i in range(self.device_list.count()):
                    item = self.device_list.item(i)
                    if item.data(Qt.UserRole) == self.selected_device_id:
                        self.device_list.setCurrentItem(item)
                        break
            
            # Unblock signals after refresh
            self.device_list.blockSignals(False)
            self._restore_device_selection()
            self.log_viewer.log_system(f"设备列表已刷新，找到 {self.device_list.count()} 个设备")
        except Exception as e:
            self.device_list.blockSignals(False)
            self.log_viewer.log_error(f"刷新设备列表失败: {e}")
        self._sync_mirror_device()
    
    def _list_hdc_devices(self) -> list:
        """List HarmonyOS devices using HDC."""
        import subprocess
        import shutil
        
        # Find HDC executable
        hdc_path = self._get_hdc_path()
        
        if not hdc_path:
            return []
        
        try:
            result = subprocess.run(
                [hdc_path, "list", "targets"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            devices = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith(("List", "[", "ErrorMessage:")) and line.lower() != "empty":
                    # Parse HDC device format (usually just IP:Port)
                    device_id = line.split()[0] if line.split() else line
                    devices.append({
                        "device_id": device_id,
                        "status": "device",
                    })
            
            return devices
        except Exception:
            return []
    
    def _refresh_devices_silent(self):
        """Refresh the device list silently (without logging, for auto-refresh)."""
        try:
            # Get current device mode
            mode = self.device_mode_combo.currentText()
            is_harmonyos = "鸿蒙" in mode
            
            if is_harmonyos:
                devices = self._list_hdc_devices()
                new_device_ids = {d.get("device_id", "") for d in devices if d.get("status") == "device"}
            else:
                devices = list_devices()
                new_device_ids = {d.device_id for d in devices if d.status == "device"}
            
            # Block signals to prevent triggering selection event during refresh
            self.device_list.blockSignals(True)
            
            # Store current device IDs to detect changes
            old_device_ids = set()
            for i in range(self.device_list.count()):
                item = self.device_list.item(i)
                old_device_ids.add(item.data(Qt.UserRole))
            
            # Only update if device list changed
            if old_device_ids != new_device_ids:
                self.device_list.clear()

                for device in devices:
                    if is_harmonyos:
                        # HDC device format
                        if isinstance(device, dict):
                            device_id = device.get("device_id", "")
                            status = device.get("status", "unknown")
                            if status == "device" or status == "connected":
                                item_text = f"{device_id}"
                                item = QListWidgetItem(item_text)
                                item.setData(Qt.UserRole, device_id)
                                self.device_list.addItem(item)
                    else:
                        # ADB device format
                        if hasattr(device, 'status') and device.status == "device":
                            item_text = f"{device.device_id} ({device.connection_type.value})"
                            if device.model:
                                item_text += f" - {device.model}"
                            item = QListWidgetItem(item_text)
                            item.setData(Qt.UserRole, device.device_id)
                            self.device_list.addItem(item)

                # Restore selection if device still exists
                if self.selected_device_id:
                    for i in range(self.device_list.count()):
                        item = self.device_list.item(i)
                        if item.data(Qt.UserRole) == self.selected_device_id:
                            self.device_list.setCurrentItem(item)
                            break
            
            # Unblock signals after refresh
            self.device_list.blockSignals(False)
            self._restore_device_selection()
        except Exception:
            # Silent refresh - don't log errors
            self.device_list.blockSignals(False)
        self._sync_mirror_device()

    def _restore_device_selection(self):
        """Keep the selected ID in sync even when refresh blocks Qt signals."""
        expected = self.selected_device_id
        if self.agent_thread is not None and self.agent_runner is not None:
            expected = getattr(self.agent_runner, 'device_id', expected)
        self.device_list.blockSignals(True)
        try:
            selected = next((self.device_list.item(i) for i in range(self.device_list.count())
                             if self.device_list.item(i).data(Qt.UserRole) == expected), None)
            if selected is not None:
                self.device_list.setCurrentItem(selected)
            elif self.device_list.count() == 1 and self.agent_thread is None:
                self.device_list.setCurrentRow(0)
            elif expected is not None:
                self.device_list.setCurrentRow(-1)
        finally:
            self.device_list.blockSignals(False)
        self._on_device_selected()

    def _on_device_selected(self):
        """Handle device selection."""
        current_item = self.device_list.currentItem()
        if current_item:
            new_device_id = current_item.data(Qt.UserRole)
            # Only log if device actually changed
            if new_device_id != self.selected_device_id:
                self.selected_device_id = new_device_id
                self.log_viewer.log_info(f"已选择设备: {self.selected_device_id}")
        else:
            if self.selected_device_id is not None:
                self.selected_device_id = None
                self.log_viewer.log_info("已取消选择设备")
        self._sync_mirror_device()

    def _connect_remote(self):
        """Connect to remote device."""
        address = self.remote_input.text().strip()
        if not address:
            QMessageBox.warning(self, "警告", "请输入远程设备地址 (IP:Port)")
            return
        
        # Validate IP:Port format
        if not self._validate_ip_port(address):
            QMessageBox.warning(
                self, 
                "格式错误", 
                "请输入正确的地址格式: IP:Port\n例如: 192.168.1.100:5555"
            )
            return

        # Get current device mode
        mode = self.device_mode_combo.currentText()
        is_harmonyos = "鸿蒙" in mode

        self.log_viewer.log_system(f"正在连接到远程设备: {address} ({mode})")
        
        if is_harmonyos:
            # Use HDC for HarmonyOS
            success, message = self._connect_hdc(address)
        else:
            # Use ADB for Android
            success, message = self.adb_connection.connect(address)
        
        if success:
            self.log_viewer.log_success(f"连接成功: {message}")
            self._refresh_devices()
        else:
            self.log_viewer.log_error(f"连接失败: {message}")
    
    def _get_hdc_path(self) -> str | None:
        """Get HDC executable path."""
        import shutil
        import os
        
        # Try PATH first
        hdc_path = shutil.which("hdc")
        if hdc_path:
            return hdc_path
        
        # Try common HDC installation paths on Windows
        username = os.getenv("USERNAME", "")
        common_paths = [
            # Open-AutoGLM bundled HDC (recommended)
            r".\toolchains\hdc.exe",
            r"toolchains\hdc.exe",
            # DevEco Studio default paths
            r"C:\HuaWei\Sdk\20\toolchains\hdc.exe",
            # User-specific paths
            rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\ohos\base\toolchains\hdc.exe",
            rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\10\toolchains\hdc.exe",
            rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\11\toolchains\hdc.exe",
            rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\12\toolchains\hdc.exe",
            # Program Files paths
            r"C:\Program Files\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
            r"C:\Program Files (x86)\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None

    def _connect_hdc(self, address: str) -> tuple[bool, str]:
        """Connect to HarmonyOS device using HDC."""
        import subprocess
        
        # Find HDC executable
        hdc_path = self._get_hdc_path()
        
        if not hdc_path:
            return False, "HDC 未找到，请确保 HDC 已安装并在 PATH 中，或配置正确的路径"
        
        try:
            # Use hdc tconn command for HarmonyOS
            result = subprocess.run(
                [hdc_path, "tconn", address],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode == 0 or "success" in output.lower() or address in output:
                return True, f"已连接到 {address}"
            else:
                return False, output.strip() or "连接失败"
                
        except subprocess.TimeoutExpired:
            return False, "连接超时"
        except Exception as e:
            return False, f"连接错误: {e}"
    
    def _validate_ip_port(self, address: str) -> bool:
        """
        Validate IP:Port format.
        
        Args:
            address: Address string to validate
            
        Returns:
            True if valid, False otherwise
        """
        # Pattern for IP:Port (IPv4)
        pattern = r'^(\d{1,3}\.){3}\d{1,3}:\d{1,5}$'
        if not re.match(pattern, address):
            return False
        
        # Validate IP octets and port range
        try:
            ip, port = address.split(':')
            octets = [int(x) for x in ip.split('.')]
            port_num = int(port)
            
            # Check IP octets (0-255)
            if not all(0 <= octet <= 255 for octet in octets):
                return False
            
            # Check port range (1-65535)
            if not (1 <= port_num <= 65535):
                return False
            
            return True
        except (ValueError, AttributeError):
            return False

    def _update_check_result(
        self, check_name: str, status_label: QLabel, check_btn: QPushButton, result, check_type: str
    ):
        """Update UI with check result."""
        try:
            # Mark as not checking
            self.check_status[check_type] = False
            
            # Clean up timer if exists
            if check_type in self.check_timers:
                del self.check_timers[check_type]
            
            check_btn.setText("检查")
            if result.success:
                status_label.setText(f"{check_name}: ✅ 通过")
                status_label.setStyleSheet("color: green;")
                self.log_viewer.log_success(f"{check_name}: {result.message}")
            else:
                status_label.setText(f"{check_name}: ❌ 失败")
                status_label.setStyleSheet("color: red;")
                self.log_viewer.log_error(f"{check_name}: {result.message}")
                if result.solution:
                    self.log_viewer.log_info(f"解决方案: {result.solution}")
        except Exception as e:
            self.log_viewer.log_error(f"更新检查结果时出错: {str(e)}")
            self.check_status[check_type] = False
            check_btn.setText("检查")
            status_label.setText(f"{check_name}: ❌ 错误")
    
    def _update_check_error(
        self, check_name: str, status_label: QLabel, check_btn: QPushButton, check_type: str
    ):
        """Update UI with check error."""
        self.check_status[check_type] = False
        if check_type in self.check_timers:
            del self.check_timers[check_type]
        check_btn.setText("检查")
        status_label.setText(f"{check_name}: ❌ 错误")
        status_label.setStyleSheet("color: red;")
    
    def _on_model_api_check_finished(
        self, check_type: str, check_name: str, status_label: QLabel, 
        check_btn: QPushButton, success: bool, result: CheckResult
    ):
        """Handle model API check completion (called from main thread via signal)."""
        # Ownership is released by QThread.finished, after run() returns.
        # Update status
        self.check_status[check_type] = False
        
        # Update UI directly (we're already in main thread)
        check_btn.setText("检查")
        
        if success:
            status_label.setText(f"{check_name}: ✅ 通过")
            status_label.setStyleSheet("color: green;")
            self.log_viewer.log_success(f"{check_name}: {result.message}")
            # Display full response in log (like test_api.py)
            if result.details:
                self.log_viewer.log_info(f"详细信息:\n{result.details}")
        else:
            status_label.setText(f"{check_name}: ❌ 失败")
            status_label.setStyleSheet("color: red;")
            self.log_viewer.log_error(f"{check_name}: {result.message}")
            if result.details:
                self.log_viewer.log_error(f"错误详情: {result.details}")
            if result.solution:
                self.log_viewer.log_info(f"解决方案:\n{result.solution}")

    def _toggle_check(self, check_type: str):
        """Toggle check: start if not checking, stop if checking."""
        # Check if already checking
        if self.check_status.get(check_type, False):
            # Stop the check
            self._stop_check(check_type)
        else:
            # Start the check
            self._run_single_check(check_type)
    
    def _stop_check(self, check_type: str):
        """Stop a running check."""
        mode = self.device_mode_combo.currentText()
        is_harmonyos = "鸿蒙" in mode
        tool_name = "HDC" if is_harmonyos else "ADB"
        check_name_map = {
            "adb": f"{tool_name} 安装",
            "devices": "设备连接",
            "keyboard": "ADB Keyboard",
            "model_api": "模型 API",
        }
        check_name = check_name_map.get(check_type, check_type)
        
        # Get UI elements
        if check_type == "adb":
            status_label = self.adb_status_label
            check_btn = self.adb_check_btn
        elif check_type == "devices":
            status_label = self.device_status_label
            check_btn = self.device_check_btn
        elif check_type == "keyboard":
            status_label = self.keyboard_status_label
            check_btn = self.keyboard_check_btn
        elif check_type == "model_api":
            status_label = self.api_status_label
            check_btn = self.api_check_btn
        else:
            return
        
        # Cancel timer if exists (for quick checks)
        if check_type in self.check_timers:
            timer = self.check_timers[check_type]
            timer.stop()
            del self.check_timers[check_type]
        
        thread = self.check_threads.get(check_type)
        if isinstance(thread, QThread):
            thread.cancelled = True
            thread.requestInterruption()

        # Mark as stopped
        self.check_status[check_type] = False
        
        # Update UI
        check_btn.setText("检查")
        status_label.setText(f"{check_name}: 已取消")
        status_label.setStyleSheet("color: #92400e;")
        self.log_viewer.log_system(f"{check_name} 检查已取消")

    def _run_single_check(self, check_type: str):
        """Run a single environment check using simple QTimer approach."""
        if self._close_requested or check_type in self.check_threads:
            self.log_viewer.log_warning("上一次检查尚未退出，请稍候")
            return
        # Get current device mode
        mode = self.device_mode_combo.currentText()
        is_harmonyos = "鸿蒙" in mode
        
        # Get UI elements and check function
        if check_type == "adb":
            status_label = self.adb_status_label
            check_btn = self.adb_check_btn
            tool_name = "HDC" if is_harmonyos else "ADB"
            check_name = f"{tool_name} 安装"
            if is_harmonyos:
                from gui.utils.system_checker import check_hdc_installation
                check_func = check_hdc_installation
            else:
                from gui.utils.system_checker import check_adb_installation
                check_func = check_adb_installation
            is_slow_check = False
        elif check_type == "devices":
            status_label = self.device_status_label
            check_btn = self.device_check_btn
            check_name = "设备连接"
            if is_harmonyos:
                from gui.utils.system_checker import check_hdc_devices
                check_func = check_hdc_devices
            else:
                from gui.utils.system_checker import check_devices
                check_func = check_devices
            is_slow_check = False
        elif check_type == "keyboard":
            status_label = self.keyboard_status_label
            check_btn = self.keyboard_check_btn
            check_name = "ADB Keyboard"
            # 鸿蒙模式不需要检查ADB Keyboard
            if is_harmonyos:
                from gui.utils.system_checker import CheckResult
                check_func = lambda: CheckResult(
                    success=True,
                    message="鸿蒙模式不需要 ADB Keyboard（使用原生输入法）",
                    details="HarmonyOS uses native input method"
                )
            else:
                from gui.utils.system_checker import check_adb_keyboard
                check_func = lambda: check_adb_keyboard(self.selected_device_id)
            is_slow_check = False
        elif check_type == "model_api":
            status_label = self.api_status_label
            check_btn = self.api_check_btn
            check_name = "模型 API"
            base_url = self.base_url_input.text().strip()
            model_name = self.model_input.text().strip()
            api_key = self.api_key_input.text().strip() or "EMPTY"
            if not base_url or not model_name:
                QMessageBox.warning(self, "警告", "请先配置 Base URL 和 Model 名称")
                return
            is_slow_check = True
        else:
            return

        # Mark as checking
        self.check_status[check_type] = True

        # Update UI to "checking" state
        check_btn.setText("终止")
        status_label.setText(f"{check_name}: 检查中...")
        self.log_viewer.log_system(f"开始检查 {check_name}...")

        if is_slow_check:
            # For slow checks (model API), use QThread (like test_api.py)
            # Get parameters for the check
            base_url = self.base_url_input.text().strip()
            model_name = self.model_input.text().strip()
            api_key = self.api_key_input.text().strip() or "EMPTY"
            
            # Create and start worker thread
            worker = ModelAPICheckWorker(base_url, model_name, api_key)
            worker.setParent(self)
            worker.check_context = (check_type, check_name, status_label, check_btn)
            worker.result_ready.connect(self._handle_model_api_result, Qt.QueuedConnection)
            worker.finished.connect(self._handle_model_api_thread_finished, Qt.QueuedConnection)
            self.check_threads[check_type] = worker
            worker.start()
        else:
            # For quick checks, use QTimer to delay execution slightly
            # This allows UI to update first
            def execute_check():
                try:
                    # Check if stopped
                    if not self.check_status.get(check_type, False):
                        return
                    
                    self.log_viewer.log_system(f"正在执行 {check_name} 检查...")
                    result = check_func()
                    
                    # Check if stopped before updating UI
                    if not self.check_status.get(check_type, False):
                        return
                    
                    self._update_check_result(check_name, status_label, check_btn, result, check_type)
                except Exception as e:
                    # Check if stopped
                    if not self.check_status.get(check_type, False):
                        return
                    
                    import traceback
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    error_details = traceback.format_exc()
                    self.log_viewer.log_error(f"{check_name} 检查异常: {error_msg}")
                    self.log_viewer.log_error(f"错误详情: {error_details}")
                    self._update_check_error(check_name, status_label, check_btn, check_type)

            # Delay by 10ms to allow UI to update
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(execute_check)
            timer.start(10)
            self.check_timers[check_type] = timer
    
    def _run_all_environment_checks(self):
        """Run all environment checks sequentially."""
        self.log_viewer.log_system("开始运行全部环境检查...")
        # Run checks one by one
        self._run_single_check("adb")
        # Use QTimer to chain the checks
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1000, lambda: self._run_single_check("devices"))
        QTimer.singleShot(2000, lambda: self._run_single_check("keyboard"))
        QTimer.singleShot(3000, lambda: self._run_single_check("model_api"))


    def _validate_config(self, base_url: str, model_name: str, api_key: str) -> tuple[bool, str]:
        """
        Validate configuration before starting task.

        Args:
            base_url: Model API base URL
            model_name: Model name
            api_key: API key

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check if base_url is empty
        if not base_url:
            return False, "Base URL 不能为空"

        # Validate URL format
        try:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            if not parsed.scheme or not parsed.netloc:
                return False, f"Base URL 格式无效: {base_url}\n请使用完整 URL，例如: https://api-inference.modelscope.cn/v1"
        except Exception as e:
            return False, f"Base URL 解析失败: {str(e)}"

        # Check if model_name is empty
        if not model_name:
            return False, "Model 名称不能为空"

        # Validate API key format for specific presets
        preset = self.preset_combo.currentText()
        if preset == "智谱-Phone" and api_key:
            if not api_key.startswith("ms-"):
                return False, (
                    "API Key 格式不正确\n\n"
                    "智谱-Phone 预设需要使用 ModelScope API Key，格式为: ms-xxxxxx\n"
                    "请参考 使用必读.txt 获取免费 API Key"
                )

        return True, ""

    def _disable_config_controls(self):
        """Disable configuration controls during task execution."""
        # Disable model configuration
        self.base_url_input.setEnabled(False)
        self.model_input.setEnabled(False)
        self.api_key_input.setEnabled(False)
        self.preset_combo.setEnabled(False)
        self.remember_key_checkbox.setEnabled(False)
        
        # Disable device configuration
        self.device_mode_combo.setEnabled(False)
        self.device_list.setEnabled(False)
        self.remote_input.setEnabled(False)
        
        # Disable environment checks
        self.check_all_btn.setEnabled(False)
        self.adb_check_btn.setEnabled(False)
        self.device_check_btn.setEnabled(False)
        self.keyboard_check_btn.setEnabled(False)
        self.api_check_btn.setEnabled(False)
    
    def _enable_config_controls(self):
        """Enable configuration controls after task completion."""
        # Enable model configuration
        self.base_url_input.setEnabled(True)
        self.model_input.setEnabled(True)
        self.api_key_input.setEnabled(True)
        self.preset_combo.setEnabled(True)
        self.remember_key_checkbox.setEnabled(True)
        
        # Enable device configuration
        self.device_mode_combo.setEnabled(True)
        self.device_list.setEnabled(True)
        self.remote_input.setEnabled(True)
        
        # Enable environment checks
        self.check_all_btn.setEnabled(True)
        self.adb_check_btn.setEnabled(True)
        self.device_check_btn.setEnabled(True)
        self.keyboard_check_btn.setEnabled(True)
        self.api_check_btn.setEnabled(True)

    def _start_task(self):
        """Start task execution."""
        if self.agent_thread is not None or self._close_requested:
            self.log_viewer.log_warning("上一个任务尚未退出，请稍候")
            return
        task = self.task_input.toPlainText().strip()
        if not task:
            QMessageBox.warning(self, "警告", "请输入任务描述")
            return
        
        # Validate task length (prevent extremely long inputs)
        if len(task) > 5000:
            QMessageBox.warning(
                self, 
                "任务过长", 
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

        if not self.selected_device_id and self.device_list.count() == 0:
            self._refresh_devices()
        self._restore_device_selection()
        if not self.selected_device_id and self.device_list.count() > 1:
            self.log_viewer.log_warning("已连接多个设备，请先选择要执行任务的设备")
            return
        self._sync_mirror_device()
        if not self.device_mirror.prepare_ai():
            self.log_viewer.log_warning("投屏正在连接或手动操作尚未结束，请稍后开始任务")
            return

        # Save settings
        self._save_settings()

        # Initialize structured task logging for this run
        self._current_session_id = str(uuid.uuid4())
        self._task_start_time = time.time()
        self._last_step_start = self._task_start_time
        self._step_count = 0
        self._last_action = None
        self._current_step_thinking = []
        self._session_finalized = False
        self._pending_step_logs = 0  # Reset pending logs counter
        self._is_stopping = False  # Reset stopping flag

        try:
            self.task_logger.log_task_start(
                session_id=self._current_session_id,
                task_description=task,
                user_id="local_pc",
                device_id=self.selected_device_id,
                base_url=base_url,
                model_name=model_name,
            )
        except Exception as e:
            # Do not block task execution if logging fails
            self.log_viewer.log_error(f"初始化任务日志失败: {e}")

        # Determine device mode
        mode = self.device_mode_combo.currentText()
        device_mode = "harmonyos" if "鸿蒙" in mode else "android"
        
        # Create agent runner in a new thread
        self.agent_runner = AgentRunner(
            base_url=base_url,
            model_name=model_name,
            api_key=api_key,
            device_id=self.selected_device_id,
            max_steps=100,
            lang="cn",
            notify=True,
            task_logger=self.task_logger,  # Pass task_logger for golden path integration
            device_mode=device_mode,  # Pass device mode for HarmonyOS support
        )
        self.agent_thread = AgentTaskThread(self.agent_runner, task, self)

        # Connect signals with QueuedConnection to ensure thread-safe delivery
        self.agent_runner.thinking_received.connect(
            self._on_thinking_received, Qt.QueuedConnection
        )
        self.agent_runner.action_received.connect(
            self._on_action_received, Qt.QueuedConnection
        )
        self.agent_runner.step_completed.connect(
            self._on_step_completed, Qt.QueuedConnection
        )
        self.agent_runner.task_completed.connect(
            self._on_task_completed, Qt.QueuedConnection
        )
        self.agent_runner.error_occurred.connect(
            self._on_error_occurred, Qt.QueuedConnection
        )
        self.agent_runner.progress_updated.connect(
            self._on_progress_updated, Qt.QueuedConnection
        )

        self.agent_thread.finished.connect(self._on_thread_finished, Qt.QueuedConnection)

        # Update UI immediately before starting thread
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("状态: 运行中")
        self.status_label.setStyleSheet("color: #4CAF50;")
        self.log_viewer.log_system(f"开始执行任务: {task}")
        # Reset thinking stream state when starting new task
        self._thinking_stream_active = False
        
        # Disable configuration controls (but keep task input and data storage enabled)
        self._disable_config_controls()
        
        # Force UI update before starting thread
        from PyQt5.QtWidgets import QApplication

        # Start thread
        self.device_mirror.start_preview()
        self.device_mirror.set_ai_running(True)
        self.agent_thread.start()
        
        # Force another UI update after starting thread

    def _run_task_in_thread(self, task: str):
        """Run task in the background thread (called from thread.started signal)."""
        try:
            # Emit initial progress immediately
            self.agent_runner.progress_updated.emit("任务已启动，正在初始化...")
            # Small delay to ensure signal is delivered and UI updates
            QThread.currentThread().msleep(100)
            # Start the task
            self.agent_runner.run_task(task)
        except Exception as e:
            # Emit error signal if task fails to start
            error_msg = f"任务启动失败: {str(e)}"
            self.agent_runner.error_occurred.emit(error_msg)
            import traceback
            self.agent_runner.progress_updated.emit(f"错误详情:\n{traceback.format_exc()}")
        finally:
            # Ensure thread exits after task completion or error
            # Simply call quit() - it's thread-safe
            if self.agent_thread:
                self.agent_thread.quit()

    def _stop_task(self):
        if not self.agent_runner or not self.agent_thread:
            return
        self._is_stopping = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("状态: 正在停止...")
        self.status_label.setStyleSheet("color: #ff9800;")
        self.progress_label.setText("等待当前请求退出，停止后可开始新任务")
        self.log_viewer.log_system("正在停止任务；等待当前网络或设备请求返回")
        self.agent_runner.stop()
        self.agent_thread.requestInterruption()
    
    def _check_thread_finished(self):
        """Check if thread has finished, log warning if not."""
        if self.agent_thread and self.agent_thread.isRunning():
            # Thread still running, log warning but don't block
            self.log_viewer.log_warning("线程仍在运行中，将在后台完成...")
        else:
            # Thread finished, clean up safely
            self._cleanup_agent_thread()
    
    def _cleanup_agent_thread(self):
        thread = self.agent_thread
        if thread is not None and thread.isRunning():
            return False
        self.agent_runner = None
        self.agent_thread = None
        if thread is not None:
            thread.deleteLater()
        return True
    
    def _finalize_stopped_task(self, wait_count=0):
        """Finalize task logging after stop (called asynchronously).
        
        Args:
            wait_count: Number of times we've waited (for timeout protection)
        """
        # Save session_id to prevent it from being cleared during wait
        session_id_to_finalize = self._current_session_id
        
        # Check if we should finalize - do this first to avoid unnecessary work
        if not session_id_to_finalize or self._session_finalized:
            # Already finalized or no session to finalize
            return
        
        # Now safe to finalize (steps are saved synchronously now)
        total_time = None
        if self._task_start_time is not None:
            total_time = time.time() - self._task_start_time
        
        # Log that we're finalizing
        try:
            self.log_viewer.log_info(
                f"📝 正在最终化停止任务... (session_id={session_id_to_finalize[:8]}..., "
                f"total_steps={self._step_count}, total_time={total_time or 0:.2f}s)"
            )
        except:
            pass
        
        # Wrap database operation in try-except to prevent crashes
        try:
            self.task_logger.log_task_end(
                session_id=session_id_to_finalize,
                final_status="STOPPED",
                total_steps=self._step_count,
                total_time=total_time,
                error_message="Stopped by user",
            )
            # Log success
            try:
                self.log_viewer.log_success(
                    f"✅ 停止任务已保存到数据库 (status=STOPPED, steps={self._step_count})"
                )
            except:
                pass
            # Mark as finalized only after successful database operation
            self._session_finalized = True
        except Exception as e:
            # Log error but still mark as finalized to prevent repeated attempts
            try:
                self.log_viewer.log_error(f"❌ 更新停止任务日志出错: {e}")
                import traceback
                self.log_viewer.log_error(f"错误详情:\n{traceback.format_exc()}")
            except:
                print(f"Failed to log task end: {e}")
            self._session_finalized = True
        
        # Clear session ID after finalization
        if self._current_session_id == session_id_to_finalize:
            self._current_session_id = None

    @pyqtSlot(str)
    def _on_thinking_received(self, thinking: str):
        """Handle thinking process update with incremental support."""
        # Log thinking immediately when received
        # Qt.QueuedConnection ensures this runs on main thread safely
        # Use incremental mode if we're already in a thinking stream
        is_incremental = self._thinking_stream_active
        if thinking:  # Only process if there's actual content
            self.log_viewer.log_thinking(thinking, is_incremental=is_incremental)
            # Accumulate thinking for structured logging
            if self._current_session_id:
                self._current_step_thinking.append(thinking)
            # Mark that we're in a thinking stream
            self._thinking_stream_active = True
            # Force immediate UI update to show the thinking in real-time
            from PyQt5.QtWidgets import QApplication

    @pyqtSlot(dict)
    def _on_action_received(self, action: dict):
        """Handle action update."""
        # Cache last action for step-level logging
        self._last_action = action

        action_json = json.dumps(action, ensure_ascii=False, indent=2)
        # Log action immediately when received
        # Qt.QueuedConnection ensures this runs on main thread safely
        self.log_viewer.log_action(action_json)

    @pyqtSlot(int, bool, str, str)
    @pyqtSlot(int, bool, str, str, str)
    def _on_step_completed(self, step_num: int, success: bool, message: str, screenshot_path: str, thinking: str = ""):
        """Handle step completion."""
        # Ignore steps that arrive after stopping, if session is finalized, or if no session exists
        # This prevents counting steps that won't be logged
        if self._is_stopping or self._session_finalized or not self._current_session_id:
            try:
                if self._is_stopping:
                    self.log_viewer.log_warning(
                        f"⚠️ 忽略停止后到达的步骤信号 (步骤 {step_num})"
                    )
            except:
                pass
            return
        
        # Reset thinking stream state when step completes
        self._thinking_stream_active = False
        
        # Structured step logging - do it synchronously to ensure it completes
        if self._current_session_id:
            now = time.time()
            execution_time = None
            if self._last_step_start is not None:
                execution_time = now - self._last_step_start
            self._last_step_start = now
            self._step_count = max(self._step_count, step_num)

            # Use thinking from signal parameter, or combine accumulated thinking content
            thinking_content = thinking if thinking else ("\n".join(self._current_step_thinking) if self._current_step_thinking else None)

            # Save step to database synchronously
            try:
                self.task_logger.log_step(
                    session_id=self._current_session_id,
                    step_num=step_num,
                    screenshot_path=screenshot_path or None,
                    action=self._last_action,
                    execution_time=execution_time,
                    success=success,
                    message=message or "",
                    thinking=thinking_content,
                )
                self.log_viewer.log_info(f"📝 步骤 {step_num} 已保存到数据库")
            except Exception as e:
                # Log error but don't interrupt task execution
                try:
                    self.log_viewer.log_error(f"写入步骤日志失败: {e}")
                except:
                    print(f"Failed to log step: {e}")

            # Clear accumulated thinking for next step
            self._current_step_thinking = []

        # Clear cached action after logging
        self._last_action = None

        status = "成功" if success else "失败"
        self.log_viewer.log_info(f"步骤 {step_num} {status}: {message}")

    @pyqtSlot(str)
    def _on_task_completed(self, message: str):
        """Handle task completion."""
        if self._is_stopping:
            return
        # Update UI immediately
        self.log_viewer.log_success(f"✅ 任务完成: {message}")
        self.status_label.setText("状态: 已完成")
        self.status_label.setStyleSheet("color: #2196F3;")
        self.progress_label.setText(f"✅ {message}")
        self.start_btn.setEnabled(self.agent_thread is None)
        self.stop_btn.setEnabled(False)
        
        # Re-enable configuration controls
        if self.agent_thread is None:
            self._enable_config_controls()
        
        # Force UI update before database operation
        from PyQt5.QtWidgets import QApplication
        
        # Finalize structured task logging synchronously to ensure it completes
        if self._current_session_id and not self._session_finalized:
            total_time = None
            if self._task_start_time is not None:
                total_time = time.time() - self._task_start_time
            
            # Save session_id before operation
            session_id_to_finalize = self._current_session_id
            
            try:
                self.task_logger.log_task_end(
                    session_id=session_id_to_finalize,
                    final_status="SUCCESS",
                    total_steps=self._step_count,
                    total_time=total_time,
                    error_message=None,
                )
                # Mark as finalized only after successful database operation
                self._session_finalized = True
                self.log_viewer.log_info(f"✅ 任务状态已保存: SUCCESS")
            except Exception as e:
                # Log error but still mark as finalized to prevent repeated attempts
                try:
                    self.log_viewer.log_error(f"更新任务日志失败: {e}")
                except:
                    print(f"Failed to log task end: {e}")
                self._session_finalized = True
            
            # Clear session ID after finalization (whether success or failure)
            self._current_session_id = None
        
        # Clean up thread asynchronously (non-blocking)
        if self.agent_thread:
            self.agent_thread.quit()
            # References are released only by _on_thread_finished.

    def _parse_error_type(self, error: str) -> tuple[str, str]:
        """
        Parse error message and determine error type and help message.

        Args:
            error: Error message string

        Returns:
            Tuple of (error_type, help_message)
        """
        error_lower = error.lower()

        # Connection errors
        if "连接错误" in error or "cannot connect" in error_lower or "connect call failed" in error_lower:
            if "127.0.0.1" in error or "localhost" in error_lower:
                return (
                    "本地连接错误",
                    (
                        "无法连接到本地服务。\n\n"
                        "如果您使用 ModelScope 或智谱 BigModel，请：\n"
                        "1. 检查模型配置中的 Base URL\n"
                        "2. 确保使用正确的服务地址：\n"
                        "   - ModelScope: https://api-inference.modelscope.cn/v1\n"
                        "   - 智谱 BigModel: https://open.bigmodel.cn/api/paas/v4\n\n"
                        "如果您确实需要本地服务，请确保服务正在运行。"
                    )
                )
            else:
                return (
                    "网络连接错误",
                    (
                        "无法连接到模型服务。\n\n"
                        "请检查：\n"
                        "1. Base URL 是否正确\n"
                        "2. 网络连接是否正常\n"
                        "3. 防火墙设置是否阻止连接\n"
                        "4. 模型服务是否正在运行"
                    )
                )

        # Authentication errors
        if "认证错误" in error or "401" in error or "unauthorized" in error_lower or "api key" in error_lower:
            return (
                "认证错误",
                (
                    "API Key 验证失败。\n\n"
                    "请检查：\n"
                    "1. API Key 是否正确输入\n"
                    "2. API Key 是否已过期\n"
                    "3. API Key 格式是否正确（智谱-Phone 应为 ms- 开头）\n\n"
                    "请参考 使用必读.txt 重新获取 API Key"
                )
            )

        # API errors
        if "error code" in error_lower or "api error" in error_lower:
            return (
                "API 错误",
                (
                    "模型服务返回错误。\n\n"
                    "请检查：\n"
                    "1. Base URL 和 Model 名称是否正确\n"
                    "2. API Key 是否有效\n"
                    "3. 模型服务是否正常运行\n\n"
                    "如果问题持续，请查看详细错误信息。"
                )
            )

        # Default
        return ("错误", "任务执行过程中发生错误，请查看详细错误信息。")

    @pyqtSlot(str)
    def _on_error_occurred(self, error: str):
        """Handle error."""
        log_task_error(error)
        if self._is_stopping:
            return
        # Parse error type and get help message
        error_type, help_message = self._parse_error_type(error)

        # Log error with clear indication
        self.log_viewer.log_error(f"❌ {error_type}: {error}")
        self.status_label.setText("状态: 错误")
        self.status_label.setStyleSheet("color: #f44336;")
        
        # Truncate error message for progress label if too long
        display_error = error
        if len(display_error) > 100:
            display_error = display_error[:100] + "..."
        self.progress_label.setText(f"❌ {error_type}: {display_error}")
        self.start_btn.setEnabled(self.agent_thread is None)
        self.stop_btn.setEnabled(False)
        
        # Re-enable configuration controls
        if self.agent_thread is None:
            self._enable_config_controls()
        
        # Keep the failure visible without opening a second event loop/dialog
        # while task completion and worker deletion signals are being delivered.
        self.log_viewer.log_info(help_message)
        
        # Finalize structured task logging as FAILED (synchronously)
        if self._current_session_id and not self._session_finalized:
            total_time = None
            if self._task_start_time is not None:
                total_time = time.time() - self._task_start_time
            
            # Save session_id before operation
            session_id_to_finalize = self._current_session_id
            
            try:
                self.task_logger.log_task_end(
                    session_id=session_id_to_finalize,
                    final_status="FAILED",
                    total_steps=self._step_count,
                    total_time=total_time,
                    error_message=error,
                )
                # Mark as finalized only after successful database operation
                self._session_finalized = True
                self.log_viewer.log_info(f"✅ 任务状态已保存: FAILED")
            except Exception as e:
                # Log error but still mark as finalized to prevent repeated attempts
                try:
                    self.log_viewer.log_error(f"更新失败任务日志出错: {e}")
                except:
                    print(f"Failed to log task end: {e}")
                self._session_finalized = True
            
            # Clear session ID after finalization (whether success or failure)
            self._current_session_id = None

        # Clean up thread asynchronously (non-blocking)
        if self.agent_thread:
            self.agent_thread.quit()
            # References are released only by _on_thread_finished.

    @pyqtSlot(str)
    def _on_progress_updated(self, progress: str):
        """Handle progress update."""
        self.progress_label.setText(progress)
        self.log_viewer.log_raw(progress, "info")
        # Qt.QueuedConnection ensures this runs on main thread safely

    @pyqtSlot()
    def _on_thread_finished(self):
        if self.sender() is not self.agent_thread:
            return
        if self._is_stopping:
            self._finalize_stopped_task()
            self.status_label.setText("状态: 已停止")
            self.progress_label.setText("任务已停止")
        self._cleanup_agent_thread()
        self._thinking_stream_active = False
        self.start_btn.setEnabled(not self._close_requested)
        self.stop_btn.setEnabled(False)
        self._enable_config_controls()
        self.device_mirror.set_ai_running(False)

    def _show_usage_guide(self):
        """Show the usage guide dialog."""
        import os
        from pathlib import Path
        
        # Get the path to 使用必读.txt
        current_dir = Path(__file__).parent.parent
        guide_file = current_dir / "使用必读.txt"
        
        # Read the file content
        try:
            if guide_file.exists():
                with open(guide_file, "r", encoding="utf-8") as f:
                    content = f.read()
            else:
                content = "文件未找到：使用必读.txt\n\n请确保文件存在于项目根目录。"
        except Exception as e:
            content = f"读取文件时出错：{str(e)}"
        
        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle("使用必读 - 获取免费 API Key")
        dialog.setMinimumSize(700, 600)
        
        layout = QVBoxLayout(dialog)
        
        # Title
        title_label = QLabel("使用必读 - 获取免费 API Key")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Content text area
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        text_edit.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(text_edit)
        
        # Close button
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.close)
        layout.addWidget(button_box)
        
        # Show dialog
        dialog.exec_()

    def _show_wireless_debug_path(self):
        """Show instructions for enabling wireless debugging (dialog style like usage guide)."""
        dialog = QDialog(self)
        dialog.setWindowTitle("无线调试路径")
        dialog.setMinimumSize(480, 400)

        layout = QVBoxLayout(dialog)

        title_label = QLabel("无线调试 - 开启与获取 IP:端口")
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Get current device mode
        mode = self.device_mode_combo.currentText()
        is_harmonyos = "鸿蒙" in mode
        
        if is_harmonyos:
            content = (
                "【鸿蒙设备】请在手机上按以下路径操作：\n"
                "设置 > 系统和更新 > 开发者选项 > USB 调试和无线调试\n\n"
                "步骤说明：\n"
                "1. 打开开发者选项（如未开启，请先在关于手机连续点击版本号启用）\n"
                "2. 开启 USB 调试和无线调试\n"
                "3. 查看并记录显示的 IP:端口（例如 192.168.1.100:5555）\n"
                "4. 回到本界面，填写 IP:端口，点击\"连接\"\n"
                "5. 使用命令验证: hdc list targets\n\n"
                "提示：\n"
                "- 确保手机与电脑在同一局域网内\n"
                "- 鸿蒙设备使用原生输入法，无需安装 ADB Keyboard"
            )
        else:
            content = (
                "【安卓设备】请在手机上按以下路径操作：\n"
                "设置 > 开发者选项 > 无线调试 > IP地址\n\n"
                "步骤说明：\n"
                "1. 打开开发者选项（如未开启，请先在关于手机连续点击版本号启用）\n"
                "2. 进入\"无线调试\"\n"
                "3. 查看并复制显示的 IP:端口（例如 192.168.1.100:5555）\n"
                "4. 回到本界面，填写 IP:端口，点击\"连接\"\n"
                "5. 使用命令验证: adb devices\n\n"
                "提示：确保手机与电脑在同一局域网内。"
            )

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(content)
        text_edit.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(text_edit)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(dialog.close)
        layout.addWidget(button_box)

        dialog.exec_()

    def closeEvent(self, event):
        self._save_settings()
        self._close_requested = True
        self.device_mirror.request_shutdown()
        if self.agent_thread is not None and self.agent_thread.isRunning():
            if not self._is_stopping:
                self._stop_task()
        running_checks = [t for t in self.check_threads.values() if t.isRunning()]
        for thread in running_checks:
            thread.requestInterruption()
        if ((self.agent_thread is not None and self.agent_thread.isRunning())
                or running_checks or self.device_mirror.has_workers()):
            self.status_label.setText("状态: 正在关闭，等待后台请求退出...")
            self._close_timer.start()
            event.ignore()
            return
        self._close_timer.stop()
        if self._current_session_id and not self._session_finalized:
            self._finalize_stopped_task()
        self._cleanup_agent_thread()
        event.accept()

    @pyqtSlot(bool, object)
    def _handle_model_api_result(self, success, result):
        worker = self.sender()
        if worker is None or worker.cancelled or self._close_requested:
            return
        check_type, check_name, status_label, check_btn = worker.check_context
        if self.check_threads.get(check_type) is worker:
            self._on_model_api_check_finished(check_type, check_name, status_label, check_btn, success, result)

    @pyqtSlot()
    def _handle_model_api_thread_finished(self):
        worker = self.sender()
        if worker is None:
            return
        check_type = worker.check_context[0]
        if self.check_threads.get(check_type) is worker:
            self.check_threads.pop(check_type)
        worker.deleteLater()

    def _fit_controls(self):
        # Fixed 100% application scale; Windows DPI scaling still applies.
        for label in (self.adb_status_label, self.device_status_label, self.keyboard_status_label, self.api_status_label):
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            label.setMinimumWidth(label.fontMetrics().horizontalAdvance("设备连接"))
        size_controls_to_text(self)
        content_width = self.config_scroll.widget().minimumSizeHint().width()
        scrollbar_width = self.config_scroll.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        self.config_scroll.setMinimumWidth(max(240, content_width + scrollbar_width + 4))

    def _sync_mirror_device(self):
        if hasattr(self, "device_mirror"):
            mode = "harmonyos" if "鸿蒙" in self.device_mode_combo.currentText() else "android"
            self.device_mirror.set_device(mode, self.selected_device_id)

    @pyqtSlot(str)
    def _on_device_mirror_message(self, message):
        self.log_viewer.log_system(message)
