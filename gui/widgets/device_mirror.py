"""Qt device screen, mouse/keyboard input and explicit worker ownership."""

import time

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from gui.utils.mirror_backend import InputThread, LatestFrame, MirrorStreamThread


def image_rect(bounds, source_size):
    width, height = source_size
    if width <= 0 or height <= 0 or bounds.width() <= 0 or bounds.height() <= 0:
        return QRect()
    ratio = min(bounds.width() / width, bounds.height() / height)
    result = QRect(0, 0, max(1, int(width * ratio)), max(1, int(height * ratio)))
    result.moveCenter(bounds.center())
    return result


def map_device_point(point, target, source_size, clamp=False):
    if target.isEmpty() or (not clamp and not target.contains(point)):
        return None
    x = max(0, min(target.width() - 1, point.x() - target.x()))
    y = max(0, min(target.height() - 1, point.y() - target.y()))
    width, height = source_size
    return (min(width - 1, int(x * width / target.width())),
            min(height - 1, int(y * height / target.height())))


class ScreenCanvas(QWidget):
    command = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.source_size = (0, 0)
        self.input_enabled = False
        self._pressed = False
        self._last_move = 0.0
        self.placeholder = "开始执行任务后自动投屏"
        self.setMinimumSize(180, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setToolTip("左键点按/长按/拖动，右键返回，滚轮滑动；聚焦后可输入文字，Ctrl+V 粘贴")

    def set_frame(self, image, source_size):
        self.image = image
        self.source_size = source_size
        self.update()

    def target_rect(self):
        return image_rect(self.contentsRect().adjusted(4, 4, -4, -4), self.source_size)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111827"))
        if self.image is None:
            painter.setPen(QColor("#cbd5e1"))
            painter.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap,
                             self.placeholder)
        else:
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawImage(self.target_rect(), self.image)
        if self.hasFocus() and self.input_enabled:
            painter.setPen(QColor("#60a5fa"))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def _position(self, point, clamp=False):
        return map_device_point(point, self.target_rect(), self.source_size, clamp)

    def mousePressEvent(self, event):
        if not self.input_enabled:
            return
        point = self._position(event.pos())
        if point is None:
            return
        self.setFocus(Qt.MouseFocusReason)
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.command.emit("down", point)
        elif event.button() == Qt.RightButton:
            self.command.emit("key", ("Back",))
        elif event.button() == Qt.MiddleButton:
            self.command.emit("key", ("Home",))

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.input_enabled or not self._pressed:
            return
        now = time.monotonic()
        if now - self._last_move >= 0.04:
            point = self._position(event.pos(), clamp=True)
            if point:
                self.command.emit("move", point)
                self._last_move = now

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            point = self._position(event.pos(), clamp=True)
            if point and self.input_enabled:
                self.command.emit("up", point)

    def wheelEvent(self, event):
        if not self.input_enabled:
            return
        point = self._position(event.pos())
        if point is None or not event.angleDelta().y():
            return
        width, height = self.source_size
        distance = max(40, int(height * 0.23))
        direction = 1 if event.angleDelta().y() > 0 else -1
        x = point[0]
        sy = max(int(height * 0.15), min(int(height * 0.85), point[1]))
        ey = max(1, min(height-2, sy + direction * distance))
        self.command.emit("swipe", (x, sy, x, ey))
        event.accept()

    def keyPressEvent(self, event):
        if not self.input_enabled:
            return
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_V:
                self.command.emit("text", (QApplication.clipboard().text(),))
                event.accept()
                return
            if event.key() == Qt.Key_A:
                self.command.emit("key", ("SelectAll",))
                event.accept()
                return
        names = {Qt.Key_Return: "Enter", Qt.Key_Enter: "Enter", Qt.Key_Backspace: "Backspace",
                 Qt.Key_Tab: "Tab", Qt.Key_Escape: "Back", Qt.Key_Left: "Left", Qt.Key_Right: "Right",
                 Qt.Key_Up: "Up", Qt.Key_Down: "Down", Qt.Key_Delete: "Delete"}
        if event.key() in names:
            self.command.emit("key", (names[event.key()],))
        elif event.text() and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            self.command.emit("text", (event.text(),))
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def inputMethodEvent(self, event):
        if self.input_enabled and event.commitString():
            self.command.emit("text", (event.commitString(),))
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.ImEnabled:
            return self.input_enabled
        if query == Qt.ImCursorRectangle:
            return QRectF(8, self.height()-28, 1, 24)
        return super().inputMethodQuery(query)


class DeviceMirrorWidget(QWidget):
    message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream_thread = None
        self.input_thread = None
        self.mailbox = LatestFrame()
        self.mode = "harmonyos"
        self.device_id = None
        self._connected = False
        self._stop_requested = False
        self._ai_running = False
        self._closing = False
        self._sequence = 0
        self._preview_requested = False
        self._start_attempts = 0
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(2000)
        self._retry_timer.timeout.connect(self._try_start_preview)
        self.status_text = "选择设备，开始执行任务后自动投屏"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = ScreenCanvas()
        self.canvas.command.connect(self._submit)
        layout.addWidget(self.canvas)
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._show_latest)
        self.timer.start()
        self._update_controls()

    def set_device(self, mode, device_id):
        if (mode, device_id) == (self.mode, self.device_id):
            return
        wanted = self._preview_requested
        self.stop_preview()
        self._preview_requested = wanted
        self._start_attempts = 0
        self.mode, self.device_id = mode, device_id
        self.canvas.image = None
        self.canvas.source_size = (0, 0)
        self.canvas.update()
        self._set_status("开始执行任务后自动投屏" if device_id else "请先选择设备")
        self._update_controls()
        if wanted:
            self._try_start_preview()

    def start_preview(self):
        if self._closing:
            return
        self._preview_requested = True
        self._start_attempts = 0
        return self._try_start_preview()

    def _try_start_preview(self):
        if not self._preview_requested or self.has_workers() or not self.device_id or self._closing:
            return False
        if self._start_attempts >= 3:
            return False
        self._retry_timer.stop()
        self._start_attempts += 1
        self.mailbox = LatestFrame()
        self._sequence = 0
        self._stop_requested = False
        self._connected = False
        self.stream_thread = MirrorStreamThread(self.mode, self.device_id, self.mailbox,
                                               False, self)
        self.stream_thread.status.connect(self._on_status, Qt.QueuedConnection)
        self.stream_thread.ready.connect(self._on_ready, Qt.QueuedConnection)
        self.stream_thread.failed.connect(self._on_failure, Qt.QueuedConnection)
        self.stream_thread.finished.connect(self._on_stream_finished, Qt.QueuedConnection)
        self._set_status("正在连接投屏...")
        self._update_controls()
        self.stream_thread.start()
        self.message.emit("正在自动启动设备投屏")
        return True

    def stop_preview(self):
        self._preview_requested = False
        self._retry_timer.stop()
        if self.has_workers():
            self._set_status("正在停止投屏...")
        self._stop_requested = True
        self._connected = False
        if self.input_thread is not None:
            self.input_thread.request_stop()
        elif self.stream_thread is not None:
            self.stream_thread.request_stop()
        self._update_controls()

    def request_shutdown(self):
        self._closing = True
        self.stop_preview()

    def has_workers(self):
        return self.stream_thread is not None or self.input_thread is not None

    def prepare_ai(self):
        if self._closing or (self._stop_requested and self.has_workers()):
            return False
        if self.input_thread is not None and not self.input_thread.pause():
            self.input_thread.resume()
            return False
        return True

    def set_ai_running(self, running):
        self._ai_running = running
        if self.input_thread is not None:
            self.input_thread.pause() if running else self.input_thread.resume()
        self._update_controls()

    def _set_status(self, text):
        self.status_text = text
        self.canvas.placeholder = text
        self.canvas.setToolTip(text)
        self.canvas.update()

    def _update_controls(self):
        self.canvas.input_enabled = (self._connected and not self._ai_running
                                     and not self._stop_requested and not self._closing)
        self.canvas.update()

    @pyqtSlot(str, object)
    def _submit(self, command, args):
        if self.canvas.input_enabled and self.input_thread is not None:
            self.input_thread.submit(command, *args)

    @pyqtSlot(object)
    def _on_ready(self, context):
        if self.sender() is not self.stream_thread or self._stop_requested:
            return
        self._connected = True
        if self.input_thread is None:
            self.input_thread = InputThread(context, self)
            self.input_thread.failed.connect(self._on_input_failure, Qt.QueuedConnection)
            self.input_thread.finished.connect(self._on_input_finished, Qt.QueuedConnection)
            if self._ai_running:
                self.input_thread.pause()
            self.input_thread.start()
        else:
            self.input_thread.update_context(context)
        self._update_controls()

    @pyqtSlot(str)
    def _on_status(self, message):
        if self.sender() is not self.stream_thread or self._stop_requested:
            return
        self._set_status(message)
        self.message.emit(message)

    @pyqtSlot(str)
    def _on_failure(self, message):
        if self.sender() is self.stream_thread:
            self._set_status(f"投屏失败：{message}")
            self.message.emit(f"投屏失败：{message}")

    @pyqtSlot(str)
    def _on_input_failure(self, message):
        if self.sender() is not self.input_thread or self._stop_requested:
            return
        self._set_status(f"控制失败：{message}")
        self.message.emit(f"控制失败：{message}")

    @pyqtSlot()
    def _on_input_finished(self):
        worker = self.sender()
        if worker is not self.input_thread:
            return
        self.input_thread = None
        worker.deleteLater()
        if self._stop_requested and self.stream_thread is not None:
            self.stream_thread.request_stop()
        self._update_controls()
        self._schedule_preview_restart()

    @pyqtSlot()
    def _on_stream_finished(self):
        worker = self.sender()
        if worker is not self.stream_thread:
            return
        self.stream_thread = None
        self._connected = False
        worker.deleteLater()
        if self.input_thread is not None:
            self.input_thread.request_stop()
        if self._stop_requested:
            self._set_status("投屏已停止")
        self._update_controls()
        self._schedule_preview_restart()

    def _schedule_preview_restart(self):
        if self._preview_requested and not self._closing and not self.has_workers() and self.device_id:
            if self._start_attempts < 3:
                self._set_status("投屏连接中断，正在重新连接...")
                self._retry_timer.start()
            else:
                self._set_status("投屏连接失败，请检查设备连接；下次开始任务时会重试。")
                self.message.emit(self.status_text)

    def _show_latest(self):
        frame = self.mailbox.read()
        if frame is None or frame[0] == self._sequence or self._stop_requested:
            return
        sequence, image, source_size, timestamp = frame
        self._sequence = sequence
        self._start_attempts = 0
        self.canvas.set_frame(image, source_size)
        self.canvas.setToolTip(f"{self.status_text} · {source_size[0]} × {source_size[1]}")
