"""Bounded video and input workers for HDC/ADB; no widgets run here."""

from collections import deque
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import shlex
import subprocess
import tempfile
import threading
import time
import uuid

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage
from phone_agent.tool_paths import get_adb_path, get_hdc_path


class LatestFrame:
    def __init__(self):
        self._lock = threading.Lock()
        self._frame = None
        self._sequence = 0

    def publish(self, image, source_size):
        with self._lock:
            self._sequence += 1
            self._frame = (self._sequence, image, source_size, time.monotonic())

    def read(self):
        with self._lock:
            return self._frame


@dataclass
class ControlContext:
    mode: str
    device_id: str
    touch_channel: object = None


def _shell(context, arguments, timeout=8):
    if context.mode == "harmonyos":
        executable = get_hdc_path()
        prefix = [executable, "-t", context.device_id, "shell", shlex.join([str(a) for a in arguments])]
    else:
        executable = get_adb_path()
        prefix = [executable, "-s", context.device_id, "shell"] + [str(a) for a in arguments]
    if not executable:
        raise RuntimeError("未找到设备调试工具")
    result = subprocess.run(prefix, capture_output=True, timeout=timeout)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if result.returncode or any(marker in output for marker in (
            "[Fail]", "ErrorMessage:", "Missing parameter", "USAGE", "error:", "Error:")):
        raise RuntimeError(output.strip()[:250] or f"设备命令失败 ({result.returncode})")
    return output


def _harmony_snapshot(context):
    # Keep fallback independent of PyAV/gRPC and of the AI capture's temp file.
    remote = f"/data/local/tmp/autoglm-preview-{uuid.uuid4().hex}.jpeg"
    try:
        with tempfile.TemporaryDirectory(prefix="autoglm-preview-") as directory:
            local = Path(directory) / "frame.jpeg"
            for arguments in (["snapshot_display", "-f", remote],
                              ["screenshot", "-f", remote],
                              ["uitest", "screenshot", "-f", remote]):
                try:
                    output = _shell(context, arguments, timeout=7)
                    if any(marker in output.lower() for marker in ("not found", "error", "fail")):
                        continue
                    subprocess.run([get_hdc_path(), "-t", context.device_id, "file", "recv", remote, str(local)],
                                   capture_output=True, timeout=8, check=True)
                    return local.read_bytes()
                except (RuntimeError, OSError, subprocess.SubprocessError):
                    continue
            raise RuntimeError("鸿蒙截图失败，请检查设备连接及解锁状态")
    finally:
        try:
            _shell(context, ["rm", "-f", remote], timeout=3)
        except Exception:
            logging.debug("Preview temp-file cleanup failed", exc_info=True)


class MirrorStreamThread(QThread):
    status = pyqtSignal(str)
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, mode, device_id, mailbox, screenshot_only=False, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.device_id = device_id
        self.mailbox = mailbox
        self.screenshot_only = screenshot_only
        self.stop_event = threading.Event()
        self.bridge = None

    def request_stop(self):
        self.stop_event.set()
        self.requestInterruption()

    def run(self):
        try:
            if self.stop_event.is_set():
                return
            if self.mode == "harmonyos" and not self.screenshot_only:
                try:
                    self._stream_h264()
                    if self.stop_event.is_set():
                        return
                    raise RuntimeError("视频连接已断开")
                except Exception as exc:
                    logging.warning("HDC video falling back to snapshots: %s", exc)
                    if self.stop_event.is_set():
                        return
                    self.status.emit(f"实时流不可用，切换截图预览：{exc}")
            self._stream_snapshots()
        except Exception as exc:
            if not self.stop_event.is_set():
                logging.exception("Device preview stopped")
                self.failed.emit(str(exc))

    def _stream_h264(self):
        import av
        import hos_scrcpy.core.hdc_client as hdc_client
        from hos_scrcpy.bridge.native_stream import HosStreamBridge, read_frames
        hdc_client._HDC_PATH = get_hdc_path()
        bridge = HosStreamBridge(self.device_id)
        self.bridge = bridge
        try:
            self.status.emit("正在连接 H.264 视频及触控通道...")
            bridge.start(wait_first_chunk=True)
            if self.stop_event.is_set():
                return
            self.ready.emit(ControlContext(self.mode, self.device_id, bridge.touch))
            self.status.emit("H.264 实时投屏")
            codec = av.CodecContext.create("h264", "r")
            codec.thread_count = 2
            decoded = False
            for chunk in read_frames(bridge, stop_event=self.stop_event):
                if self.stop_event.is_set():
                    return
                try:
                    packets = codec.parse(chunk)
                    for packet in packets:
                        for frame in codec.decode(packet):
                            source_size = (frame.width, frame.height)
                            ratio = min(1.0, 1440 / max(frame.width, frame.height))
                            width = max(2, int(frame.width * ratio) // 2 * 2)
                            height = max(2, int(frame.height * ratio) // 2 * 2)
                            rgb = frame.reformat(width=width, height=height, format="rgb24")
                            plane = rgb.planes[0]
                            image = QImage(bytes(plane), width, height, plane.line_size, QImage.Format_RGB888).copy()
                            self.mailbox.publish(image, source_size)
                            decoded = True
                except av.error.InvalidDataError:
                    if decoded:
                        logging.warning("Skipped a damaged H.264 packet")
            if not decoded and not self.stop_event.is_set():
                raise RuntimeError("没有收到可解码的视频画面")
        finally:
            bridge.stop()
            self.bridge = None

    def _stream_snapshots(self):
        if self.stop_event.is_set():
            return
        self.ready.emit(ControlContext(self.mode, self.device_id))
        self.status.emit("截图预览（低帧率）")
        errors = 0
        context = ControlContext(self.mode, self.device_id)
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                if self.mode == "harmonyos":
                    data = _harmony_snapshot(context)
                else:
                    result = subprocess.run([get_adb_path(), "-s", self.device_id,
                                             "exec-out", "screencap", "-p"],
                                            capture_output=True, timeout=8, check=True)
                    data = result.stdout
                image = QImage.fromData(data or b"")
                if image.isNull():
                    raise RuntimeError("截图为空或无法解码，请检查设备连接及解锁状态")
                self.mailbox.publish(image, (image.width(), image.height()))
                errors = 0
            except Exception:
                errors += 1
                if errors >= 3:
                    raise
            self.stop_event.wait(max(0.1, 1.0 - (time.monotonic() - started)))


class InputThread(QThread):
    failed = pyqtSignal(str)
    MAX_PENDING = 128

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self._condition = threading.Condition()
        self._commands = deque()
        self._stopping = False
        self._enabled = True
        self._busy = False
        self._contact = None
        self._last_point = None

    def update_context(self, context):
        with self._condition:
            self.context = context

    def submit(self, command, *args):
        with self._condition:
            if self._stopping or not self._enabled:
                return False
            if command == "move" and self._commands and self._commands[-1][0] == "move":
                self._commands[-1] = (command, args)
            elif len(self._commands) < self.MAX_PENDING:
                self._commands.append((command, args))
            elif command == "up":
                # A release must never be lost because the queue is full.
                self._commands.clear()
                self._commands.append((command, args))
            else:
                return False
            self._condition.notify()
            return True

    def pause(self):
        with self._condition:
            self._enabled = False
            self._commands.clear()
            # The caller can start AI only when no manual operation is in flight.
            if self._busy or self._contact is not None:
                self._commands.append(("release", ()))
                self._condition.notify()
                return False
            return True

    def resume(self):
        with self._condition:
            if not self._stopping:
                self._enabled = True

    def request_stop(self):
        with self._condition:
            self._enabled = False
            self._stopping = True
            self._commands.clear()
            self._condition.notify_all()

    def run(self):
        try:
            while True:
                with self._condition:
                    while not self._commands and not self._stopping:
                        self._condition.wait(0.25)
                    if self._stopping:
                        break
                    command, args = self._commands.popleft()
                    if not self._enabled and command != "release":
                        continue
                    self._busy = True
                    context = self.context
                try:
                    self._execute(context, command, args)
                except Exception as exc:
                    logging.exception("Manual device input failed")
                    self.failed.emit(str(exc))
                    self._release(context)
                finally:
                    with self._condition:
                        self._busy = False
        finally:
            self._release(self.context)

    def _release(self, context):
        if self._contact is not None and context.touch_channel is not None and context.touch_channel.healthy:
            try:
                x, y = self._last_point or self._contact[:2]
                context.touch_channel.send_touch("touchUp", x, y)
            except Exception:
                logging.exception("Could not release manual touch")
        self._contact = None

    def _execute(self, context, command, args):
        channel = context.touch_channel
        fast = channel is not None and channel.healthy
        if command == "release":
            self._release(context)
        elif command in {"down", "move", "up"}:
            x, y = (int(args[0]), int(args[1]))
            self._last_point = (x, y)
            if command == "down":
                self._contact = (x, y, time.monotonic())
            if fast:
                channel.send_touch({"down": "touchDown", "move": "touchMove", "up": "touchUp"}[command], x, y)
            elif command == "up" and self._contact is not None:
                sx, sy, started = self._contact
                duration = min(2000, max(80, int((time.monotonic() - started) * 1000)))
                distance = math.hypot(x - sx, y - sy)
                if context.mode == "harmonyos":
                    if distance < 12:
                        kind = "longClick" if duration >= 600 else "click"
                        _shell(context, ["uitest", "uiInput", kind, x, y])
                    else:
                        speed = max(200, min(5000, int(distance / (duration / 1000))))
                        _shell(context, ["uitest", "uiInput", "swipe", sx, sy, x, y, speed])
                elif distance < 12 and duration < 600:
                    _shell(context, ["input", "tap", x, y])
                else:
                    _shell(context, ["input", "swipe", sx, sy, x, y, duration])
            if command == "up":
                self._contact = None
        elif command == "swipe":
            sx, sy, ex, ey = map(int, args)
            if fast:
                channel.send_touch("touchDown", sx, sy)
                self._contact = (sx, sy, time.monotonic())
                for i in range(1, 9):
                    x, y = sx + (ex-sx)*i//8, sy + (ey-sy)*i//8
                    channel.send_touch("touchMove", x, y)
                    self._last_point = (x, y)
                    time.sleep(0.025)
                self._release(context)
            elif context.mode == "harmonyos":
                _shell(context, ["uitest", "uiInput", "swipe", sx, sy, ex, ey, 1000])
            else:
                _shell(context, ["input", "swipe", sx, sy, ex, ey, 250])
        elif command == "text":
            if context.mode == "harmonyos":
                _shell(context, ["uitest", "uiInput", "text", str(args[0])])
            else:
                from phone_agent.adb.input import type_text
                type_text(str(args[0]), device_id=context.device_id)
        elif command == "key":
            name = args[0]
            if context.mode == "harmonyos":
                values = {"Back": "Back", "Home": "Home", "Enter": "2054", "Backspace": "2055",
                          "Tab": "2049", "Left": "2014", "Right": "2015", "Up": "2012", "Down": "2013",
                          "Escape": "2070", "Delete": "2071"}
                if name == "Recent":
                    _shell(context, ["uitest", "uiInput", "keyEvent", "10011"])
                elif name == "SelectAll":
                    _shell(context, ["uitest", "uiInput", "keyEvent", "2072", "2017"])
                else:
                    _shell(context, ["uitest", "uiInput", "keyEvent", values[name]])
            else:
                values = {"Back": 4, "Home": 3, "Recent": 187, "Enter": 66, "Backspace": 67,
                          "Tab": 61, "Left": 21, "Right": 22, "Up": 19, "Down": 20, "Escape": 111, "Delete": 112}
                if name == "SelectAll":
                    _shell(context, ["input", "keycombination", "113", "29"])
                else:
                    _shell(context, ["input", "keyevent", values[name]])
