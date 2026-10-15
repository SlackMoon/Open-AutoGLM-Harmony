"""
Unified device manager for Android (ADB) and HarmonyOS (HDC) devices.

This module provides a unified interface for device operations,
automatically selecting the appropriate backend based on device mode.
"""

import base64
import os
import shlex
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from typing import Optional, Callable

from PIL import Image

from phone_agent.tool_paths import get_adb_path, get_hdc_path


class DeviceMode(Enum):
    """Device connection mode."""
    ANDROID = "android"  # Use ADB
    HARMONYOS = "harmonyos"  # Use HDC


@dataclass
class Screenshot:
    """Represents a captured screenshot."""
    base64_data: str
    width: int
    height: int
    is_sensitive: bool = False


class DeviceManager:
    """
    Unified device manager supporting both Android (ADB) and HarmonyOS (HDC).
    
    Example:
        >>> manager = DeviceManager(mode=DeviceMode.HARMONYOS, device_id="192.168.1.100:5555")
        >>> screenshot = manager.get_screenshot()
        >>> manager.tap(500, 1000)
    """
    
    def __init__(
        self,
        mode: DeviceMode = DeviceMode.ANDROID,
        device_id: Optional[str] = None,
        adb_path: Optional[str] = None,
        hdc_path: Optional[str] = None,
    ):
        """
        Initialize device manager.
        
        Args:
            mode: Device mode (ANDROID or HARMONYOS)
            device_id: Device ID for multi-device setups
            adb_path: Custom ADB path (auto-detected if not provided)
            hdc_path: Custom HDC path (auto-detected if not provided)
        """
        self.mode = mode
        self.device_id = device_id
        self._adb_path = adb_path
        self._hdc_path = hdc_path
        self.last_launch_candidates = []
    
    @property
    def adb_path(self) -> str:
        """Get ADB executable path."""
        if self._adb_path:
            return self._adb_path
        self._adb_path = get_adb_path()
        return self._adb_path
    
    @property
    def hdc_path(self) -> Optional[str]:
        """Get HDC executable path."""
        if self._hdc_path:
            return self._hdc_path
        self._hdc_path = get_hdc_path()
        return self._hdc_path
    
    def _get_cmd_prefix(self) -> list:
        """Get command prefix based on mode."""
        if self.mode == DeviceMode.HARMONYOS:
            if not self.hdc_path:
                raise RuntimeError("HDC 未安装或未找到")
            if self.device_id:
                return [self.hdc_path, "-t", self.device_id]
            return [self.hdc_path]
        else:
            adb = self.adb_path
            if self.device_id:
                return [adb, "-s", self.device_id]
            return [adb]
    
    def get_screenshot(self, timeout: int = 10) -> Screenshot:
        """
        Capture a screenshot from the device.
        
        Args:
            timeout: Timeout in seconds
        
        Returns:
            Screenshot object
        """
        if self.mode == DeviceMode.HARMONYOS:
            return self._get_screenshot_hdc(timeout)
        else:
            return self._get_screenshot_adb(timeout)
    
    def _get_screenshot_adb(self, timeout: int) -> Screenshot:
        """Capture screenshot using ADB."""
        temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{uuid.uuid4()}.png")
        cmd_prefix = self._get_cmd_prefix()
        
        try:
            result = subprocess.run(
                cmd_prefix + ["shell", "screencap", "-p", "/sdcard/tmp.png"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            output = result.stdout + result.stderr
            if "Status: -1" in output or "Failed" in output:
                return self._create_fallback_screenshot(is_sensitive=True)
            
            subprocess.run(
                cmd_prefix + ["pull", "/sdcard/tmp.png", temp_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            if not os.path.exists(temp_path):
                return self._create_fallback_screenshot(is_sensitive=False)
            
            return self._load_screenshot(temp_path)
        
        except Exception as e:
            print(f"Screenshot error (ADB): {e}")
            return self._create_fallback_screenshot(is_sensitive=False)
    
    def _get_screenshot_hdc(self, timeout: int) -> Screenshot:
        """Capture screenshot using HDC for HarmonyOS."""
        temp_path = os.path.join(tempfile.gettempdir(), f"screenshot_{uuid.uuid4()}.jpeg")
        cmd_prefix = self._get_cmd_prefix()
        remote_path = "/data/local/tmp/screenshot.jpeg"
        
        try:
            # HarmonyOS 截图命令: hdc shell snapshot_display -f <path>
            subprocess.run(
                cmd_prefix + ["shell", "snapshot_display", "-f", remote_path],
                capture_output=True,
                timeout=timeout,
            )
            
            # HDC 文件传输命令: hdc file recv <remote> <local>
            subprocess.run(
                cmd_prefix + ["file", "recv", remote_path, temp_path],
                capture_output=True,
                timeout=10,
            )
            
            # 清理远程文件
            subprocess.run(
                cmd_prefix + ["shell", "rm", "-f", remote_path],
                capture_output=True,
            )
            
            if not os.path.exists(temp_path):
                return self._create_fallback_screenshot(is_sensitive=False)
            
            return self._load_screenshot(temp_path)
        
        except Exception as e:
            print(f"Screenshot error (HDC): {e}")
            return self._create_fallback_screenshot(is_sensitive=False)
    
    def _load_screenshot(self, path: str) -> Screenshot:
        """Load screenshot from file."""
        try:
            img = Image.open(path)
            width, height = img.size
            
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
            
            os.remove(path)
            
            return Screenshot(
                base64_data=base64_data,
                width=width,
                height=height,
                is_sensitive=False,
            )
        except Exception as e:
            print(f"Failed to load screenshot: {e}")
            return self._create_fallback_screenshot(is_sensitive=False)
    
    def _create_fallback_screenshot(self, is_sensitive: bool) -> Screenshot:
        """Create fallback black screenshot."""
        default_width, default_height = 1080, 2400
        
        black_img = Image.new("RGB", (default_width, default_height), color="black")
        buffered = BytesIO()
        black_img.save(buffered, format="PNG")
        base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        return Screenshot(
            base64_data=base64_data,
            width=default_width,
            height=default_height,
            is_sensitive=is_sensitive,
        )
    
    def tap(self, x: int, y: int, delay: float = 1.0) -> None:
        """Tap at coordinates."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 点击命令: hdc shell uitest uiInput click <x> <y>
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "click", str(x), str(y)],
                capture_output=True,
            )
        else:
            # Android 点击命令: adb shell input tap <x> <y>
            subprocess.run(
                cmd_prefix + ["shell", "input", "tap", str(x), str(y)],
                capture_output=True,
            )
        time.sleep(delay)
    
    def double_tap(self, x: int, y: int, delay: float = 1.0) -> None:
        """Double tap at coordinates."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 双击命令: hdc shell uitest uiInput doubleClick <x> <y>
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "doubleClick", str(x), str(y)],
                capture_output=True,
            )
        else:
            # Android 双击: 两次快速点击
            subprocess.run(
                cmd_prefix + ["shell", "input", "tap", str(x), str(y)],
                capture_output=True,
            )
            time.sleep(0.1)
            subprocess.run(
                cmd_prefix + ["shell", "input", "tap", str(x), str(y)],
                capture_output=True,
            )
        time.sleep(delay)
    
    def long_press(self, x: int, y: int, duration_ms: int = 3000, delay: float = 1.0) -> None:
        """Long press at coordinates."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 长按命令: hdc shell uitest uiInput longClick <x> <y>
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "longClick", str(x), str(y)],
                capture_output=True,
            )
        else:
            # Android 长按: 使用 swipe 模拟
            subprocess.run(
                cmd_prefix + ["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)],
                capture_output=True,
            )
        time.sleep(delay)
    
    def swipe(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration_ms: Optional[int] = None,
        delay: float = 1.0,
    ) -> None:
        """Swipe from start to end coordinates."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if duration_ms is None:
            dist_sq = (start_x - end_x) ** 2 + (start_y - end_y) ** 2
            duration_ms = int(dist_sq / 1000)
            duration_ms = max(500, min(duration_ms, 2000))
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 滑动命令: hdc shell uitest uiInput swipe <startX> <startY> <endX> <endY> [speed]
            # speed 是滑动速度，单位是像素/秒，默认600
            speed = max(200, min(2000, int(((end_x - start_x) ** 2 + (end_y - start_y) ** 2) ** 0.5 / (duration_ms / 1000))))
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "swipe",
                             str(start_x), str(start_y), str(end_x), str(end_y), str(speed)],
                capture_output=True,
            )
        else:
            # Android 滑动命令: adb shell input swipe <x1> <y1> <x2> <y2> [duration]
            subprocess.run(
                cmd_prefix + ["shell", "input", "swipe",
                             str(start_x), str(start_y), str(end_x), str(end_y), str(duration_ms)],
                capture_output=True,
            )
        time.sleep(delay)
    
    def back(self, delay: float = 1.0) -> None:
        """Press back button."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 返回键: hdc shell uitest uiInput keyEvent Back
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "keyEvent", "Back"],
                capture_output=True,
            )
        else:
            # Android 返回键: adb shell input keyevent 4
            subprocess.run(
                cmd_prefix + ["shell", "input", "keyevent", "4"],
                capture_output=True,
            )
        time.sleep(delay)
    
    def home(self, delay: float = 1.0) -> None:
        """Press home button."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 主页键: hdc shell uitest uiInput keyEvent Home
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "keyEvent", "Home"],
                capture_output=True,
            )
        else:
            # Android 主页键: adb shell input keyevent KEYCODE_HOME
            subprocess.run(
                cmd_prefix + ["shell", "input", "keyevent", "KEYCODE_HOME"],
                capture_output=True,
            )
        time.sleep(delay)
    
    def input_text(self, text: str, delay: float = 0.5) -> None:
        """Input text."""
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # inputText requires x/y; text targets the already focused field.
            command = shlex.join(["uitest", "uiInput", "text", text])
            result = subprocess.run(cmd_prefix + ["shell", command], capture_output=True, timeout=10)
            output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
            if result.returncode or any(marker in output for marker in (
                    "[Fail]", "ErrorMessage:", "Missing parameter", "USAGE", "error:", "Error:")):
                raise RuntimeError(f"鸿蒙文字输入失败：{output.strip()[:300]}")
        else:
            # Android 使用 ADB Keyboard 输入
            subprocess.run(
                cmd_prefix + ["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT",
                             "--es", "msg", text],
                capture_output=True,
            )
        time.sleep(delay)
    
    def get_current_app(self) -> str:
        """Get currently focused app name."""
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS 获取当前应用: hdc shell aa dump -a
            try:
                result = subprocess.run(
                    cmd_prefix + ["shell", "aa", "dump", "-a"],
                    capture_output=True,
                    text=False,
                    timeout=5,
                )
                output = (result.stdout or b"").decode(errors="ignore")
                # 解析 bundle name
                for line in output.split("\n"):
                    if "bundle name" in line.lower() or "bundleName" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return parts[1].strip()
                    # 也尝试匹配 abilityName
                    if "ability name" in line.lower() or "abilityName" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return parts[1].strip()
            except Exception:
                pass
            return "System Home"
        else:
            # Android 获取当前应用: adb shell dumpsys window
            from phone_agent.config.apps import APP_PACKAGES
            try:
                result = subprocess.run(
                    cmd_prefix + ["shell", "dumpsys", "window"],
                    capture_output=True,
                    text=False,
                    timeout=5,
                )
                output = (result.stdout or b"").decode(errors="ignore")
                
                for line in output.split("\n"):
                    if "mCurrentFocus" in line or "mFocusedApp" in line:
                        for app_name, package in APP_PACKAGES.items():
                            if package in line:
                                return app_name
            except Exception:
                pass
            return "System Home"
    
    def fling(self, direction: str = "down", delay: float = 1.0) -> None:
        """
        Fling (快速滑动) in a direction. HarmonyOS specific.
        
        Args:
            direction: "up", "down", "left", "right"
            delay: Delay after fling
        """
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS fling 命令: hdc shell uitest uiInput fling <startX> <startY> <endX> <endY> <stepLen> <speed>
            # 根据方向设置坐标
            screen_w, screen_h = 1080, 2400  # 默认屏幕尺寸
            center_x, center_y = screen_w // 2, screen_h // 2
            
            if direction == "down":
                start_x, start_y = center_x, center_y - 400
                end_x, end_y = center_x, center_y + 400
            elif direction == "up":
                start_x, start_y = center_x, center_y + 400
                end_x, end_y = center_x, center_y - 400
            elif direction == "left":
                start_x, start_y = center_x + 300, center_y
                end_x, end_y = center_x - 300, center_y
            elif direction == "right":
                start_x, start_y = center_x - 300, center_y
                end_x, end_y = center_x + 300, center_y
            else:
                return
            
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "fling",
                             str(start_x), str(start_y), str(end_x), str(end_y), "50", "1500"],
                capture_output=True,
            )
        else:
            # Android 使用 swipe 模拟 fling
            self.swipe(540, 1200, 540, 600, duration_ms=200)
        
        time.sleep(delay)
    
    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        speed: int = 600,
        delay: float = 1.0,
    ) -> None:
        """
        Drag from start to end coordinates. HarmonyOS specific.
        
        Args:
            start_x, start_y: Start coordinates
            end_x, end_y: End coordinates
            speed: Drag speed (pixels per second)
            delay: Delay after drag
        """
        import time
        cmd_prefix = self._get_cmd_prefix()
        
        if self.mode == DeviceMode.HARMONYOS:
            # HarmonyOS drag 命令: hdc shell uitest uiInput drag <startX> <startY> <endX> <endY> <speed>
            subprocess.run(
                cmd_prefix + ["shell", "uitest", "uiInput", "drag",
                             str(start_x), str(start_y), str(end_x), str(end_y), str(speed)],
                capture_output=True,
            )
        else:
            # Android 使用 swipe 模拟 drag
            self.swipe(start_x, start_y, end_x, end_y, duration_ms=1000)
        
        time.sleep(delay)
    
    def launch_app(self, app_name: str, delay: float = 2.0) -> bool:
        """
        Launch an app by name.
        
        Args:
            app_name: The app name (e.g., "浏览器", "微信")
            delay: Delay after launching
            
        Returns:
            True if app was launched successfully
        """
        import time
        
        if self.mode == DeviceMode.HARMONYOS:
            return self._launch_app_harmonyos(app_name, delay)
        else:
            return self._launch_app_android(app_name, delay)
    
    def _launch_app_android(self, app_name: str, delay: float) -> bool:
        """Launch app on Android using ADB."""
        import time
        from phone_agent.config.apps import APP_PACKAGES
        
        if app_name not in APP_PACKAGES:
            return False
        
        cmd_prefix = self._get_cmd_prefix()
        package = APP_PACKAGES[app_name]
        
        subprocess.run(
            cmd_prefix + ["shell", "monkey", "-p", package, "-c",
                         "android.intent.category.LAUNCHER", "1"],
            capture_output=True,
        )
        time.sleep(delay)
        return True
    
    def _launch_app_harmonyos(self, app_name: str, delay: float) -> bool:
        """Launch app on HarmonyOS using HDC.
        
        HarmonyOS uses 'aa start' command to launch apps.
        Format: hdc shell aa start -a <ability> -b <bundle>
        """
        import time

        app_name = app_name.strip().strip('"\'“”‘’').strip()
        if not app_name:
            return False
        store_aliases = {
            "应用商店", "应用市场", "华为应用商店", "华为应用市场", "appgallery",
        }
        if app_name.casefold() in store_aliases:
            app_name = "应用市场"
        
        # HarmonyOS app bundle name mapping
        # Format: {app_name: (bundle_name, ability_name)}
        HARMONYOS_APPS = {
            # 系统应用
            "浏览器": ("com.huawei.hmos.browser", "MainAbility"),
            "设置": ("com.huawei.hmos.settings", "com.huawei.hmos.settings.MainAbility"),
            "相机": ("com.huawei.hmos.camera", "com.huawei.hmos.camera.MainAbility"),
            "图库": ("com.huawei.hmos.photos", "com.huawei.hmos.photos.MainAbility"),
            "文件管理": ("com.huawei.hmos.filemanager", "MainAbility"),
            "日历": ("com.huawei.hmos.calendar", "MainAbility"),
            "时钟": ("com.huawei.hmos.clock", "MainAbility"),
            "计算器": ("com.huawei.hmos.calculator", "MainAbility"),
            "备忘录": ("com.huawei.hmos.notepad", "MainAbility"),
            "录音机": ("com.huawei.hmos.soundrecorder", "MainAbility"),
            "天气": ("com.huawei.hmos.weather", "MainAbility"),
            "应用市场": ("com.huawei.hmsapp.appgallery", "MainAbility"),
            # 第三方应用 (需要根据实际安装情况调整)
            "微信": ("com.tencent.mm", "com.tencent.mm.ui.LauncherUI"),
            "QQ": ("com.tencent.mobileqq", "com.tencent.mobileqq.activity.SplashActivity"),
            "淘宝": ("com.taobao.taobao", "com.taobao.tao.homepage.MainActivity"),
            "支付宝": ("com.eg.android.AlipayGphone", "com.eg.android.AlipayGphone.AlipayLogin"),
            "抖音": ("com.ss.android.ugc.aweme", "com.ss.android.ugc.aweme.splash.SplashActivity"),
            "bilibili": ("tv.danmaku.bili", "tv.danmaku.bili.MainActivityV2"),
            "高德地图": ("com.autonavi.minimap", "com.autonavi.map.activity.SplashActivity"),
            "百度地图": ("com.baidu.BaiduMap", "com.baidu.baidumaps.WelcomeScreen"),
            "美团": ("com.sankuai.meituan", "com.sankuai.meituan.activity.Welcome"),
            "京东": ("com.jingdong.app.mall", "com.jingdong.app.mall.main.MainActivity"),
            "拼多多": ("com.xunmeng.pinduoduo", "com.xunmeng.pinduoduo.ui.activity.MainFrameActivity"),
            "小红书": ("com.xingin.xhs", "com.xingin.xhs.activity.SplashActivity"),
            "网易云音乐": ("com.netease.cloudmusic", "com.netease.cloudmusic.activity.LoadingActivity"),
            "QQ音乐": ("com.tencent.qqmusic", "com.tencent.qqmusic.activity.AppStarterActivity"),
        }
        
        # Try to find the app
        app_info = HARMONYOS_APPS.get(app_name)
        
        cmd_prefix = self._get_cmd_prefix()
        self.last_launch_candidates = []
        candidates = [app_info] if app_info else []
        if app_name == "应用市场":
            candidates.append(("com.huawei.appmarket", "MainAbility"))
        for bundle_name, ability_name in candidates:
            try:
                result = subprocess.run(
                    cmd_prefix + ["shell", "aa", "start", "-a", ability_name, "-b", bundle_name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"Failed to launch {app_name} ({bundle_name}): {type(exc).__name__}")
                continue
            output = (result.stdout + result.stderr).lower()
            # hdc may return 0 even when aa reports an application/ability error.
            if result.returncode == 0 and "start ability successfully" in output:
                time.sleep(delay)
                return True
            print(f"Failed to launch {app_name} ({bundle_name}): {output.strip()[:200]}")
        # A missing/stale shortcut mapping is not evidence that an app is absent.
        from phone_agent.hdc.app_discovery import discover_apps
        discovered = discover_apps(cmd_prefix, app_name, [bundle for bundle, ability in candidates])
        self.last_launch_candidates = [app.bundle for app in discovered]
        if len(discovered) == 1:
            app = discovered[0]
            command = ["aa", "start", "-a", app.ability, "-b", app.bundle]
            if app.module:
                command.extend(["-m", app.module])
            try:
                result = subprocess.run(cmd_prefix + ["shell"] + command,
                                        capture_output=True, text=True, timeout=10)
                output = (result.stdout + result.stderr).lower()
                if result.returncode == 0 and "start ability successfully" in output:
                    time.sleep(delay)
                    return True
            except (OSError, subprocess.SubprocessError):
                pass
        return False


# Global device manager instance (can be set by GUI)
_device_manager: Optional[DeviceManager] = None


def get_device_manager() -> Optional[DeviceManager]:
    """Get the global device manager instance."""
    return _device_manager


def set_device_manager(manager: DeviceManager) -> None:
    """Set the global device manager instance."""
    global _device_manager
    _device_manager = manager
