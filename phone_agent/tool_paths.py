"""
Unified tool path management for ADB and HDC executables.

This module provides centralized path detection for ADB and HDC tools,
prioritizing project-bundled tools over system PATH.
"""

import os
import shutil
from typing import Optional

# Cached paths
_adb_path: Optional[str] = None
_hdc_path: Optional[str] = None


def _get_project_root() -> str:
    """Get the project root directory."""
    # This file is at: Open-AutoGLM-main/phone_agent/tool_paths.py
    # Project root is: Open-AutoGLM-main/
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_adb_path() -> str:
    """
    Get the ADB executable path.
    
    Priority:
    1. Project bundled: ./platform-tools/adb.exe
    2. System PATH
    
    Returns:
        Path to ADB executable, or "adb" if not found (will use system PATH).
    """
    global _adb_path
    
    if _adb_path:
        return _adb_path
    
    project_root = _get_project_root()
    
    # Project bundled paths (highest priority)
    bundled_paths = [
        os.path.join(project_root, "platform-tools", "adb.exe"),
        os.path.join(project_root, "platform-tools", "adb"),
    ]
    
    for path in bundled_paths:
        if os.path.exists(path):
            _adb_path = path
            return _adb_path
    
    # Fall back to system PATH
    system_adb = shutil.which("adb")
    if system_adb:
        _adb_path = system_adb
        return _adb_path
    
    # Default to "adb" (will fail if not in PATH)
    return "adb"


def get_hdc_path() -> Optional[str]:
    """
    Get the HDC executable path.
    
    Priority:
    1. Project bundled: ./toolchains/hdc.exe
    2. System PATH
    3. Common installation paths
    
    Returns:
        Path to HDC executable, or None if not found.
    """
    global _hdc_path
    
    if _hdc_path:
        return _hdc_path
    
    project_root = _get_project_root()
    username = os.getenv("USERNAME", "")
    
    # All possible paths in priority order
    search_paths = [
        # Project bundled (highest priority)
        os.path.join(project_root, "toolchains", "hdc.exe"),
        os.path.join(project_root, "toolchains", "hdc"),
    ]
    
    # Check bundled paths first
    for path in search_paths:
        if os.path.exists(path):
            _hdc_path = path
            return _hdc_path
    
    # Check system PATH
    system_hdc = shutil.which("hdc")
    if system_hdc:
        _hdc_path = system_hdc
        return _hdc_path
    
    # Common installation paths (lowest priority)
    common_paths = [
        r"C:\HuaWei\Sdk\20\toolchains\hdc.exe",
        rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\ohos\base\toolchains\hdc.exe",
        rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\10\toolchains\hdc.exe",
        rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\11\toolchains\hdc.exe",
        rf"C:\Users\{username}\AppData\Local\Huawei\Sdk\openharmony\12\toolchains\hdc.exe",
        r"C:\Program Files\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
        r"C:\Program Files (x86)\Huawei\DevEco Studio\sdk\openharmony\toolchains\hdc.exe",
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            _hdc_path = path
            return _hdc_path
    
    return None


def reset_cached_paths() -> None:
    """Reset cached paths (useful for testing or after moving files)."""
    global _adb_path, _hdc_path
    _adb_path = None
    _hdc_path = None


def get_tool_status() -> dict:
    """
    Get status of both tools.
    
    Returns:
        Dict with 'adb' and 'hdc' keys containing path info.
    """
    adb = get_adb_path()
    hdc = get_hdc_path()
    
    return {
        "adb": {
            "path": adb,
            "exists": os.path.exists(adb) if adb != "adb" else shutil.which("adb") is not None,
            "is_bundled": "platform-tools" in (adb or ""),
        },
        "hdc": {
            "path": hdc,
            "exists": hdc is not None and os.path.exists(hdc),
            "is_bundled": hdc is not None and "toolchains" in hdc and _get_project_root() in hdc,
        },
    }
