"""Device control utilities for HarmonyOS automation using HDC.

HarmonyOS HDC 命令参考:
- 点击: hdc shell uitest uiInput click <x> <y>
- 双击: hdc shell uitest uiInput doubleClick <x> <y>
- 长按: hdc shell uitest uiInput longClick <x> <y>
- 滑动: hdc shell uitest uiInput swipe <startX> <startY> <endX> <endY> [speed]
- 快滑: hdc shell uitest uiInput fling <startX> <startY> <endX> <endY> <stepLen> <speed>
- 拖拽: hdc shell uitest uiInput drag <startX> <startY> <endX> <endY> <speed>
- 按键: hdc shell uitest uiInput keyEvent <keyCode>
- 输入: hdc shell uitest uiInput inputText <text>
- 截图: hdc shell snapshot_display -f <path>
- 文件传输: hdc file recv <remote> <local>
"""

import subprocess
import time
from typing import Optional

from phone_agent.hdc.connection import get_hdc_path


def _run_hdc(command, **kwargs):
    """Bound device calls so shutdown cannot wait forever on a stuck HDC."""
    kwargs.setdefault("timeout", 30)
    return subprocess.run(command, **kwargs)


def _get_hdc_prefix(device_id: Optional[str] = None) -> list:
    """Get HDC command prefix with optional device specifier."""
    hdc_path = get_hdc_path()
    if not hdc_path:
        raise RuntimeError("HDC 未安装或未找到")
    
    if device_id:
        return [hdc_path, "-t", device_id]
    return [hdc_path]


def tap(x: int, y: int, device_id: Optional[str] = None, delay: float = 1.0) -> None:
    """
    Tap at the specified coordinates on HarmonyOS device.
    
    命令: hdc shell uitest uiInput click <x> <y>
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "click", str(x), str(y)],
        capture_output=True,
    )
    time.sleep(delay)


def double_tap(x: int, y: int, device_id: Optional[str] = None, delay: float = 1.0) -> None:
    """
    Double tap at the specified coordinates on HarmonyOS device.
    
    命令: hdc shell uitest uiInput doubleClick <x> <y>
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "doubleClick", str(x), str(y)],
        capture_output=True,
    )
    time.sleep(delay)


def long_press(
    x: int,
    y: int,
    duration_ms: int = 3000,
    device_id: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Long press at the specified coordinates on HarmonyOS device.
    
    命令: hdc shell uitest uiInput longClick <x> <y>
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "longClick", str(x), str(y)],
        capture_output=True,
    )
    time.sleep(delay)


def swipe(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    speed: int = 600,
    device_id: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Swipe from start to end coordinates on HarmonyOS device.
    
    命令: hdc shell uitest uiInput swipe <startX> <startY> <endX> <endY> [speed]
    
    Args:
        start_x, start_y: 起始坐标
        end_x, end_y: 结束坐标
        speed: 滑动速度，单位像素/秒，默认600
        device_id: 设备ID
        delay: 操作后延迟
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "swipe",
                     str(start_x), str(start_y), str(end_x), str(end_y), str(speed)],
        capture_output=True,
    )
    time.sleep(delay)


def fling(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    step_len: int = 50,
    speed: int = 1500,
    device_id: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Fling (快速滑动) on HarmonyOS device.
    
    命令: hdc shell uitest uiInput fling <startX> <startY> <endX> <endY> <stepLen> <speed>
    
    Args:
        start_x, start_y: 起始坐标
        end_x, end_y: 结束坐标
        step_len: 步长，默认50
        speed: 滑动速度，默认1500
        device_id: 设备ID
        delay: 操作后延迟
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "fling",
                     str(start_x), str(start_y), str(end_x), str(end_y),
                     str(step_len), str(speed)],
        capture_output=True,
    )
    time.sleep(delay)


def drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    speed: int = 600,
    device_id: Optional[str] = None,
    delay: float = 1.0,
) -> None:
    """
    Drag from start to end coordinates on HarmonyOS device.
    
    命令: hdc shell uitest uiInput drag <startX> <startY> <endX> <endY> <speed>
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "drag",
                     str(start_x), str(start_y), str(end_x), str(end_y), str(speed)],
        capture_output=True,
    )
    time.sleep(delay)


def back(device_id: Optional[str] = None, delay: float = 1.0) -> None:
    """
    Press the back button on HarmonyOS device.
    
    命令: hdc shell uitest uiInput keyEvent Back
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "keyEvent", "Back"],
        capture_output=True,
    )
    time.sleep(delay)


def home(device_id: Optional[str] = None, delay: float = 1.0) -> None:
    """
    Press the home button on HarmonyOS device.
    
    命令: hdc shell uitest uiInput keyEvent Home
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "keyEvent", "Home"],
        capture_output=True,
    )
    time.sleep(delay)


def input_text(text: str, device_id: Optional[str] = None, delay: float = 0.5) -> None:
    """
    Input text on HarmonyOS device.
    
    命令: hdc shell uitest uiInput inputText <text>
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    _run_hdc(
        hdc_prefix + ["shell", "uitest", "uiInput", "inputText", text],
        capture_output=True,
    )
    time.sleep(delay)


def take_screenshot(output_path: str, device_id: Optional[str] = None) -> bool:
    """
    Take a screenshot on HarmonyOS device.
    
    命令: 
    - hdc shell snapshot_display -f <remote_path>
    - hdc file recv <remote_path> <local_path>
    
    Args:
        output_path: 本地保存路径
        device_id: 设备ID
    
    Returns:
        True if successful, False otherwise.
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    remote_path = "/data/local/tmp/screenshot.jpeg"
    
    try:
        # 在设备上截图
        _run_hdc(
            hdc_prefix + ["shell", "snapshot_display", "-f", remote_path],
            capture_output=True,
            timeout=10,
        )
        
        # 传输到本地
        result = _run_hdc(
            hdc_prefix + ["file", "recv", remote_path, output_path],
            capture_output=True,
            timeout=10,
        )
        
        # 清理远程文件
        _run_hdc(
            hdc_prefix + ["shell", "rm", "-f", remote_path],
            capture_output=True,
        )
        
        return result.returncode == 0
    except Exception:
        return False


def get_screen_size(device_id: Optional[str] = None) -> tuple[int, int]:
    """
    Get screen size of HarmonyOS device.
    
    Returns:
        Tuple of (width, height). Returns (1080, 2400) as default if failed.
    """
    hdc_prefix = _get_hdc_prefix(device_id)
    
    try:
        result = _run_hdc(
            hdc_prefix + ["shell", "hidumper", "-s", "RenderService", "-a", "screen"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        output = result.stdout
        import re
        match = re.search(r'(\d+)\s*[xX×]\s*(\d+)', output)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:
        pass
    
    return 1080, 2400
