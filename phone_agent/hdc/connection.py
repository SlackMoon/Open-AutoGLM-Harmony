"""HDC connection management for HarmonyOS devices."""

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


# Common HDC installation paths on Windows
HDC_COMMON_PATHS = [
    # Open-AutoGLM bundled HDC (recommended)
    r".\toolchains\hdc.exe",
    r"toolchains\hdc.exe",
    # DevEco Studio default paths
    r"C:\HuaWei\Sdk\20\toolchains\hdc.exe",
    # User-specific paths
    r"C:\Users\{USERNAME}\AppData\Local\Huawei\Sdk\ohos\base\toolchains\hdc.exe",
    r"C:\Users\{USERNAME}\AppData\Local\Huawei\Sdk\openharmony\10\toolchains\hdc.exe",
    r"C:\Users\{USERNAME}\AppData\Local\Huawei\Sdk\openharmony\11\toolchains\hdc.exe",
    r"C:\Users\{USERNAME}\AppData\Local\Huawei\Sdk\openharmony\12\toolchains\hdc.exe",
    # Program Files paths
    r"C:\Program Files\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
    r"C:\Program Files (x86)\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
]


def get_hdc_path() -> Optional[str]:
    """
    Find HDC executable path.
    
    Returns:
        Path to HDC executable or None if not found.
    """
    # First try PATH
    hdc_path = shutil.which("hdc")
    if hdc_path:
        return hdc_path
    
    # Try common installation paths
    username = os.getenv("USERNAME", "")
    for path_template in HDC_COMMON_PATHS:
        path = path_template.replace("{USERNAME}", username)
        if os.path.exists(path):
            return path
    
    return None


@dataclass
class HDCDeviceInfo:
    """Information about a connected HarmonyOS device."""
    device_id: str
    status: str
    model: Optional[str] = None


class HDCConnection:
    """
    Manages HDC connections to HarmonyOS devices.
    
    Example:
        >>> conn = HDCConnection()
        >>> conn.connect("192.168.1.100:5555")
        >>> devices = conn.list_devices()
        >>> conn.disconnect("192.168.1.100:5555")
    """
    
    def __init__(self, hdc_path: Optional[str] = None):
        """
        Initialize HDC connection manager.
        
        Args:
            hdc_path: Path to HDC executable. Auto-detected if not provided.
        """
        self.hdc_path = hdc_path or get_hdc_path()
    
    def is_available(self) -> bool:
        """Check if HDC is available."""
        return self.hdc_path is not None and os.path.exists(self.hdc_path)
    
    def connect(self, address: str, timeout: int = 10) -> tuple[bool, str]:
        """
        Connect to a remote HarmonyOS device via TCP/IP.
        
        Args:
            address: Device address in format "host:port".
            timeout: Connection timeout in seconds.
        
        Returns:
            Tuple of (success, message).
        """
        if not self.is_available():
            return False, "HDC 未安装或未找到"
        
        # Validate address format
        if ":" not in address:
            address = f"{address}:5555"
        
        try:
            result = subprocess.run(
                [self.hdc_path, "tconn", address],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode == 0 or "connect ok" in output.lower() or "success" in output.lower():
                return True, f"已连接到 {address}"
            elif "already" in output.lower():
                return True, f"已连接到 {address}"
            else:
                return False, output.strip() or "连接失败"
        
        except subprocess.TimeoutExpired:
            return False, f"连接超时 ({timeout}秒)"
        except Exception as e:
            return False, f"连接错误: {e}"
    
    def disconnect(self, address: Optional[str] = None) -> tuple[bool, str]:
        """
        Disconnect from a remote device.
        
        Args:
            address: Device address to disconnect. If None, disconnects all.
        
        Returns:
            Tuple of (success, message).
        """
        if not self.is_available():
            return False, "HDC 未安装或未找到"
        
        try:
            if address:
                cmd = [self.hdc_path, "-t", address, "kill"]
            else:
                cmd = [self.hdc_path, "kill"]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return True, "已断开连接"
        
        except Exception as e:
            return False, f"断开连接错误: {e}"
    
    def list_devices(self) -> list[HDCDeviceInfo]:
        """
        List all connected HarmonyOS devices.
        
        Returns:
            List of HDCDeviceInfo objects.
        """
        if not self.is_available():
            return []
        
        try:
            result = subprocess.run(
                [self.hdc_path, "list", "targets"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            
            devices = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("List") and "[Empty]" not in line:
                    device_id = line.split()[0] if line.split() else line
                    devices.append(HDCDeviceInfo(
                        device_id=device_id,
                        status="device",
                    ))
            
            return devices
        
        except Exception:
            return []
    
    def is_connected(self, device_id: Optional[str] = None) -> bool:
        """
        Check if a device is connected.
        
        Args:
            device_id: Device ID to check. If None, checks if any device is connected.
        
        Returns:
            True if connected, False otherwise.
        """
        devices = self.list_devices()
        
        if not devices:
            return False
        
        if device_id is None:
            return len(devices) > 0
        
        return any(d.device_id == device_id for d in devices)


def list_hdc_devices() -> list[HDCDeviceInfo]:
    """
    Quick helper to list connected HarmonyOS devices.
    
    Returns:
        List of HDCDeviceInfo objects.
    """
    conn = HDCConnection()
    return conn.list_devices()


def quick_connect_hdc(address: str) -> tuple[bool, str]:
    """
    Quick helper to connect to a remote HarmonyOS device.
    
    Args:
        address: Device address (e.g., "192.168.1.100" or "192.168.1.100:5555").
    
    Returns:
        Tuple of (success, message).
    """
    conn = HDCConnection()
    return conn.connect(address)
