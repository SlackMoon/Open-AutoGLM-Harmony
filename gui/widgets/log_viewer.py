"""Log viewer widget with color coding and auto-scroll."""

from datetime import datetime
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QTextCharFormat, QTextCursor, QTextOption
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogViewer(QWidget):
    """Custom log viewer widget with color coding and search functionality."""

    # Color definitions for different log levels
    COLORS = {
        "thinking": QColor(100, 150, 255),  # Light blue
        "action": QColor(255, 200, 100),  # Orange
        "success": QColor(100, 255, 100),  # Green
        "error": QColor(255, 100, 100),  # Red
        "info": QColor(200, 200, 200),  # Light gray
        "system": QColor(150, 150, 255),  # Light purple
        "default": QColor(255, 255, 255),  # White
    }
    
    # Maximum number of lines to keep in log (prevent memory issues)
    MAX_LOG_LINES = 10000
    
    # Batch update settings for better performance
    BATCH_UPDATE_INTERVAL_MS = 50  # Update UI every 50ms max

    def __init__(self, parent=None):
        """Initialize the log viewer."""
        super().__init__(parent)

        self._setup_ui()
        self._auto_scroll = True
        self._current_thinking_active = False  # Track if we're in a thinking stream
        self._line_count = 0  # Track number of lines
        
        # Batch update buffer for better performance
        self._pending_logs = []  # List of (text, log_type) tuples
        self._batch_timer = None
        self._setup_batch_timer()

    def _setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Log text area
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.document().setMaximumBlockCount(self.MAX_LOG_LINES)
        font = QFont("Consolas", 9)
        self.text_edit.setFont(font)
        # Wrap text within the log area to avoid horizontal overflow
        self.text_edit.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.text_edit.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.text_edit)

        # Control buttons
        control_layout = QHBoxLayout()
        self.clear_btn = QPushButton("清空日志")
        self.clear_btn.clicked.connect(self.clear)
        self.auto_scroll_btn = QPushButton("自动滚动: 开")
        self.auto_scroll_btn.clicked.connect(self._toggle_auto_scroll)
        control_layout.addWidget(self.clear_btn)
        control_layout.addStretch()
        control_layout.addWidget(self.auto_scroll_btn)
        layout.addLayout(control_layout)
    
    def _setup_batch_timer(self):
        """Set up timer for batch UI updates."""
        from PyQt5.QtCore import QTimer
        self._batch_timer = QTimer(self)
        self._batch_timer.timeout.connect(self._flush_pending_logs)
        self._batch_timer.start(self.BATCH_UPDATE_INTERVAL_MS)
    
    def _queue_log(self, text: str, log_type: str):
        """Queue a log entry for batch update."""
        self._pending_logs.append((text, log_type))
    
    def _flush_pending_logs(self):
        """Flush all pending logs to the UI."""
        if not self._pending_logs:
            return
        
        # Process all pending logs at once
        logs_to_process = self._pending_logs
        self._pending_logs = []
        
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # Batch insert all logs
        for text, log_type in logs_to_process:
            # Update line count
            self._line_count += text.count('\n')
            
            # Set color format
            format = QTextCharFormat()
            color = self.COLORS.get(log_type, self.COLORS["default"])
            format.setForeground(color)
            cursor.setCharFormat(format)
            cursor.insertText(text)
        
        # Check if we need to trim
        if self._line_count > self.MAX_LOG_LINES:
            self._trim_old_logs()
        
        # Auto-scroll if enabled (only once after all logs)
        if self._auto_scroll:
            self.text_edit.ensureCursorVisible()

    def _toggle_auto_scroll(self):
        """Toggle auto-scroll mode."""
        self._auto_scroll = not self._auto_scroll
        self.auto_scroll_btn.setText(
            f"自动滚动: {'开' if self._auto_scroll else '关'}"
        )

    def _append_text(self, text: str, log_type: str = "default"):
        """Append text with specified log type color.
        
        Uses batch update for better performance - logs are queued and
        flushed to UI periodically instead of immediately.
        """
        # Queue for batch update (non-blocking)
        self._queue_log(text, log_type)
    
    def _trim_old_logs(self):
        """Trim old logs to prevent memory issues."""
        try:
            # Remove first 20% of logs when limit is reached
            lines_to_remove = self.MAX_LOG_LINES // 5
            
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QTextCursor.Start)
            
            # Move to the line we want to keep
            for _ in range(lines_to_remove):
                cursor.movePosition(QTextCursor.Down)
            
            # Select and delete old content
            cursor.movePosition(QTextCursor.Start, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            
            # Update line count
            self._line_count = self.text_edit.document().lineCount()
            
            # Add a marker that logs were trimmed
            self.log_system("--- 旧日志已清理以节省内存 ---")
        except Exception:
            # If trimming fails, just reset line count
            self._line_count = self.text_edit.document().lineCount()

    def log_thinking(self, message: str, is_incremental: bool = False):
        """
        Log thinking process with support for incremental updates.
        
        Args:
            message: Thinking content to log
            is_incremental: If True, append to current thinking without timestamp/prefix.
                          If False, start a new thinking entry with timestamp.
        """
        if is_incremental and self._current_thinking_active:
            # Append to current thinking without timestamp/prefix
            self._append_text(message, "thinking")
        else:
            # Start new thinking entry
            if self._current_thinking_active:
                # End previous thinking if still active
                self._append_text("\n", "thinking")
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            self._append_text(f"[{timestamp}] 💭 ", "thinking")
            self._append_text(message, "thinking")
            self._current_thinking_active = True

    def log_action(self, message: str):
        """Log action execution."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] 🎯 {message}\n", "action")

    def log_success(self, message: str):
        """Log success message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ✅ {message}\n", "success")

    def log_error(self, message: str):
        """Log error message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ❌ {message}\n", "error")

    def log_info(self, message: str):
        """Log info message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ℹ️ {message}\n", "info")

    def log_system(self, message: str):
        """Log system message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] 🔧 {message}\n", "system")

    def log_raw(self, message: str, log_type: str = "default"):
        """Log raw message with custom type."""
        self._append_text(f"{message}\n", log_type)

    def clear(self):
        """Clear all logs."""
        self._pending_logs.clear()
        self.text_edit.clear()
        self._current_thinking_active = False
        self._line_count = 0

    def get_text(self) -> str:
        """Get all log text."""
        return self.text_edit.toPlainText()


    def log_warning(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_text(f"[{timestamp}] ⚠️ {message}\n", "info")
