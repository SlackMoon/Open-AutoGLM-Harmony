"""System checker utilities for GUI application."""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
from openai import OpenAI, DefaultHttpxClient

from phone_agent.adb import list_devices
from phone_agent.tool_paths import get_adb_path, get_hdc_path


@dataclass
class CheckResult:
    """Result of a system check."""

    success: bool
    message: str
    details: Optional[str] = None
    solution: Optional[str] = None


def check_hdc_installation() -> CheckResult:
    """
    Check if HDC is installed and accessible (for HarmonyOS).

    Returns:
        CheckResult with status and message.
    """
    hdc_path = get_hdc_path()
    
    if not hdc_path:
        return CheckResult(
            success=False,
            message="HDC 未安装或未找到",
            details="HDC is not installed or not found.",
            solution="安装 HarmonyOS SDK:\n"
            "1. 将 hdc.exe 放入项目 toolchains 目录\n"
            "2. 或下载并安装 DevEco Studio\n"
            "3. 或从 https://developer.huawei.com/consumer/cn/deveco-studio/ 下载\n"
            "4. HDC 工具通常位于 SDK 的 toolchains 目录下",
        )

    try:
        result = subprocess.run(
            [hdc_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split("\n")[0] if result.stdout.strip() else "HDC 已安装"
            return CheckResult(
                success=True, message=f"HDC 已安装 ({version_line})", details=f"路径: {hdc_path}"
            )
        else:
            # Try alternative: just list targets
            result2 = subprocess.run(
                [hdc_path, "list", "targets"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result2.returncode == 0:
                return CheckResult(
                    success=True, message="HDC 已安装", details=f"路径: {hdc_path}"
                )
            return CheckResult(
                success=False,
                message="HDC 命令执行失败",
                details="HDC command failed to run.",
            )
    except FileNotFoundError:
        return CheckResult(
            success=False, message="HDC 命令未找到", details="HDC command not found."
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            success=False, message="HDC 命令超时", details="HDC command timed out."
        )
    except Exception as e:
        return CheckResult(
            success=False, message=f"HDC 检查出错: {e}", details=str(e)
        )


def check_adb_installation() -> CheckResult:
    """
    Check if ADB is installed and accessible.

    Returns:
        CheckResult with status and message.
    """
    adb_path = get_adb_path()
    
    # Check if it's the default "adb" (not found)
    if adb_path == "adb" and shutil.which("adb") is None:
        return CheckResult(
            success=False,
            message="ADB 未安装或未找到",
            details="ADB is not installed or not found.",
            solution="安装 Android SDK Platform Tools:\n"
            "1. 将 platform-tools 文件夹放入项目根目录\n"
            "2. 或从 https://developer.android.com/studio/releases/platform-tools 下载\n"
            "3. 或 macOS: brew install android-platform-tools\n"
            "4. 或 Linux: sudo apt install android-tools-adb",
        )

    try:
        result = subprocess.run(
            [adb_path, "version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split("\n")[0]
            return CheckResult(
                success=True, message=f"ADB 已安装 ({version_line})", details=f"路径: {adb_path}"
            )
        else:
            return CheckResult(
                success=False,
                message="ADB 命令执行失败",
                details="ADB command failed to run.",
            )
    except FileNotFoundError:
        return CheckResult(
            success=False, message="ADB 命令未找到", details="ADB command not found."
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            success=False, message="ADB 命令超时", details="ADB command timed out."
        )
    except Exception as e:
        return CheckResult(
            success=False, message=f"ADB 检查出错: {e}", details=str(e)
        )


def check_hdc_devices() -> CheckResult:
    """
    Check if any HarmonyOS devices are connected using HDC.

    Returns:
        CheckResult with status and device list.
    """
    hdc_path = get_hdc_path()
    
    if not hdc_path:
        return CheckResult(
            success=False,
            message="HDC 未安装",
            details="HDC is not installed.",
            solution="请先安装 HDC 工具",
        )
    
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
            if line and not line.startswith("List"):
                device_id = line.split()[0] if line.split() else line
                devices.append(device_id)
        
        if not devices:
            return CheckResult(
                success=False,
                message="未检测到设备",
                details="No devices connected.",
                solution="1. 在鸿蒙设备上启用 USB 调试和无线调试\n"
                "2. 通过 USB 连接并授权连接\n"
                "3. 或远程连接: hdc tconn <ip>:<port>",
            )
        
        device_info = "\n".join([f"  - {d}" for d in devices])
        return CheckResult(
            success=True,
            message=f"检测到 {len(devices)} 个设备",
            details=f"Connected devices:\n{device_info}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            success=False, message="设备检查超时", details="HDC command timed out."
        )
    except Exception as e:
        return CheckResult(
            success=False, message=f"设备检查出错: {e}", details=str(e)
        )


def check_devices() -> CheckResult:
    """
    Check if any devices are connected.

    Returns:
        CheckResult with status and device list.
    """
    try:
        devices = list_devices()
        connected_devices = [d for d in devices if d.status == "device"]

        if not connected_devices:
            return CheckResult(
                success=False,
                message="未检测到设备",
                details="No devices connected.",
                solution="1. 在 Android 设备上启用 USB 调试\n"
                "2. 通过 USB 连接并授权连接\n"
                "3. 或远程连接: python main.py --connect <ip>:<port>",
            )

        device_ids = [d.device_id for d in connected_devices]
        device_info = "\n".join(
            [
                f"  - {d.device_id} ({d.connection_type.value})"
                for d in connected_devices
            ]
        )
        return CheckResult(
            success=True,
            message=f"检测到 {len(connected_devices)} 个设备",
            details=f"Connected devices:\n{device_info}",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            success=False, message="设备检查超时", details="ADB command timed out."
        )
    except Exception as e:
        return CheckResult(
            success=False, message=f"设备检查出错: {e}", details=str(e)
        )


def check_adb_keyboard(device_id: Optional[str] = None) -> CheckResult:
    """
    Check if ADB Keyboard is installed on the device.
    """
    adb_path = get_adb_path()
    
    if not device_id:
        try:
            devices = list_devices()
            connected_devices = [d for d in devices if d.status == "device"]
            if not connected_devices:
                return CheckResult(
                    success=False,
                    message="未选择设备",
                    details="No device selected or connected.",
                    solution="1. 请先在设备列表中选择一个设备\n"
                    "2. 如果是无线连接，请确保设备已连接\n"
                    "3. 无线连接时建议先选择设备再检查",
                )
            device_id = connected_devices[0].device_id
        except Exception:
            return CheckResult(
                success=False,
                message="无法获取设备列表",
                details="Cannot get device list.",
                solution="1. 检查 ADB 连接\n"
                "2. 确保至少有一个设备已连接\n"
                "3. 如果是无线连接，请先连接设备",
            )

    adb_prefix = [adb_path]
    if device_id:
        adb_prefix.extend(["-s", device_id])

    try:
        result = subprocess.run(
            adb_prefix + ["shell", "ime", "list", "-s"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        
        if result.returncode != 0:
            error_output = result.stderr.strip() or result.stdout.strip()
            if "device not found" in error_output.lower() or "offline" in error_output.lower():
                return CheckResult(
                    success=False,
                    message="设备未连接或已离线",
                    details=f"Device not found or offline: {error_output}",
                    solution="1. 检查设备连接状态\n"
                    "2. 如果是无线连接，请重新连接设备\n"
                    "3. 尝试: adb devices 查看设备状态",
                )
            else:
                return CheckResult(
                    success=False,
                    message="ADB 命令执行失败",
                    details=f"ADB command failed: {error_output}",
                    solution="1. 检查设备连接\n"
                    "2. 确认设备已授权 ADB 调试\n"
                    "3. 如果是无线连接，检查网络连接",
                )
        
        ime_list = result.stdout.strip()
        
        if not ime_list:
            return CheckResult(
                success=False,
                message="无法获取输入法列表",
                details="Cannot get IME list from device.",
                solution="1. 检查设备连接是否正常\n"
                "2. 如果是无线连接，可能需要更长时间\n"
                "3. 尝试重新连接设备",
            )

        if "com.android.adbkeyboard/.AdbIME" in ime_list:
            return CheckResult(
                success=True,
                message="ADB Keyboard 已安装",
                details=f"ADB Keyboard is installed on device: {device_id}",
            )
        else:
            return CheckResult(
                success=False,
                message="ADB Keyboard 未安装",
                details=f"ADB Keyboard is not installed on device: {device_id}",
                solution="1. 下载 ADB Keyboard APK:\n"
                "   https://github.com/senzhk/ADBKeyBoard/blob/master/ADBKeyboard.apk\n"
                "2. 安装到设备:\n"
                f"   adb -s {device_id} install ADBKeyboard.apk\n"
                "3. 在设置中启用: 设置 > 系统 > 语言和输入法 > 虚拟键盘",
            )
    except subprocess.TimeoutExpired:
        return CheckResult(
            success=False,
            message="ADB Keyboard 检查超时",
            details=f"ADB command timed out after 20 seconds (device: {device_id})",
            solution="1. 如果是无线连接，网络可能较慢\n"
            "2. 检查网络连接质量\n"
            "3. 尝试重新连接设备",
        )
    except Exception as e:
        return CheckResult(
            success=False, message=f"ADB Keyboard 检查出错: {e}", details=str(e)
        )


def check_model_api(base_url: str, model_name: str, api_key: str = "EMPTY") -> CheckResult:
    """
    Check if the model API is accessible.
    """
    if not base_url or not base_url.strip():
        return CheckResult(
            success=False,
            message="Base URL 未设置",
            details="Base URL is not set.",
        )

    try:
        parsed = urlparse(base_url)
        if not parsed.scheme or not parsed.netloc:
            return CheckResult(
                success=False,
                message="Base URL 格式无效",
                details=f"Invalid URL format: {base_url}",
            )

        http_client = DefaultHttpxClient(timeout=30.0, trust_env=False)
        client = OpenAI(base_url=base_url, api_key=api_key, http_client=http_client, max_retries=0)
        
        try:
            import base64
            from io import BytesIO
            from PIL import Image, ImageDraw
            image = Image.new("RGB", (400, 400), "white")
            ImageDraw.Draw(image).rectangle((240, 80, 360, 200), fill="#00b050")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            messages = [
                {"role": "system", "content": "你是截图操作助手。只输出一条 do(action=\"Tap\", element=[x,y]) 指令，坐标归一化为0～999。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "点击截图中的绿色矩形中心。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ]},
            ]
            # Use the same SSE protocol as actual tasks, including thinking models.
            parts = []
            with client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.0,
                max_tokens=1024, stream=True,
            ) as stream:
                for chunk in stream:
                    if chunk.choices:
                        if chunk.choices[0].finish_reason == "content_filter":
                            raise ValueError("测试输出被模型服务拦截")
                        parts.append(chunk.choices[0].delta.content or "")
            content = "".join(parts)
            from phone_agent.actions.handler import parse_action
            action = parse_action(content)
            point = action.get("element", ())
            if (action.get("action") != "Tap" or len(point) != 2
                    or not (600 <= point[0] <= 900 and 200 <= point[1] <= 500)):
                raise ValueError("API 可响应，但未通过截图定位测试；请确认模型支持图片并遵守 0～999 坐标规范")
        finally:
            client.close()
        details = f"Connected to {base_url}\nModel: {model_name}\n测试响应: {content[:100]}..." if len(content) > 100 else f"Connected to {base_url}\nModel: {model_name}\n测试响应: {content}"
        
        return CheckResult(
            success=True,
            message="模型 API、图片输入及动作格式测试通过",
            details=details,
        )
    except Exception as e:
        error_msg = str(e)
        
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            return CheckResult(
                success=False,
                message="API Key 已过期或无效",
                details=f"Authentication failed: {error_msg}",
                solution="1. 检查 API Key 是否正确\n"
                "2. 确认 API Key 是否已过期\n"
                "3. 在对应平台重新申请 API Key",
            )
        elif "Connection refused" in error_msg or "connect" in error_msg.lower():
            return CheckResult(
                success=False,
                message=f"无法连接到 {base_url}",
                details=f"Cannot connect: {error_msg}",
                solution="1. 检查模型服务器是否运行\n"
                "2. 验证 Base URL 是否正确\n"
                "3. 检查网络连接",
            )
        else:
            return CheckResult(
                success=False, message=f"API 检查出错: {error_msg}", details=error_msg
            )


def run_all_checks(
    base_url: str = "",
    model_name: str = "",
    api_key: str = "EMPTY",
    device_id: Optional[str] = None,
) -> dict[str, CheckResult]:
    """Run all system checks and return results."""
    results = {}

    results["adb"] = check_adb_installation()

    if results["adb"].success:
        results["devices"] = check_devices()
        if results["devices"].success:
            results["keyboard"] = check_adb_keyboard(device_id)
    else:
        results["devices"] = CheckResult(
            success=False, message="跳过设备检查（ADB 未安装）", details="Skipped"
        )
        results["keyboard"] = CheckResult(
            success=False, message="跳过键盘检查（ADB 未安装）", details="Skipped"
        )

    if base_url and model_name:
        results["model_api"] = check_model_api(base_url, model_name, api_key)
    else:
        results["model_api"] = CheckResult(
            success=False,
            message="跳过模型 API 检查（未配置）",
            details="Skipped - Base URL or Model not set",
        )

    return results
