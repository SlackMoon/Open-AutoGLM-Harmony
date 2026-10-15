#!/usr/bin/env python3
"""
GUI application entry point for Open-AutoGLM.

免责声明：
本软件仅供学习研究和个人合法用途，禁止用于任何违法违规活动。
使用者应遵守当地法律法规，因使用本软件产生的任何后果由使用者自行承担。
作者不对因滥用本软件造成的任何损失或法律责任负责。
"""

import os
import shutil
import sys
from pathlib import Path


def setup_tool_paths():
    """
    检测并配置 ADB 和 HDC 工具路径。
    如果系统 PATH 中找不到这些工具，则自动添加本地目录到 PATH。
    """
    # 获取程序所在目录（支持打包后的 exe）
    if getattr(sys, 'frozen', False):
        # 打包后的 exe
        app_dir = Path(sys.executable).parent
    else:
        # 开发环境
        app_dir = Path(__file__).parent
    
    # 向上查找项目根目录（包含 toolchains 和 platform-tools 的目录）
    search_dirs = [
        app_dir,
        app_dir.parent,
        app_dir.parent.parent,
    ]
    
    paths_to_add = []
    
    # 检测 ADB
    adb_found = shutil.which("adb") is not None
    if not adb_found:
        for search_dir in search_dirs:
            platform_tools = search_dir / "platform-tools"
            if platform_tools.exists() and (platform_tools / "adb.exe").exists():
                paths_to_add.append(str(platform_tools))
                print(f"[PATH] 添加 ADB 路径: {platform_tools}")
                break
    else:
        print(f"[PATH] ADB 已在系统 PATH 中")
    
    # 检测 HDC
    hdc_found = shutil.which("hdc") is not None
    if not hdc_found:
        for search_dir in search_dirs:
            toolchains = search_dir / "toolchains"
            if toolchains.exists() and (toolchains / "hdc.exe").exists():
                paths_to_add.append(str(toolchains))
                print(f"[PATH] 添加 HDC 路径: {toolchains}")
                break
    else:
        print(f"[PATH] HDC 已在系统 PATH 中")
    
    # 添加到当前进程的 PATH
    if paths_to_add:
        current_path = os.environ.get("PATH", "")
        new_paths = ";".join(paths_to_add)
        os.environ["PATH"] = f"{new_paths};{current_path}"
        print(f"[PATH] 环境变量已更新")
    
    return adb_found or bool(paths_to_add), hdc_found or bool(paths_to_add)


def main():
    """Main entry point for the GUI application."""
    # Diagnostics must be installed before importing GUI modules.
    from gui.utils.runtime_diagnostics import install_diagnostics
    app_dir = Path(sys.executable).parent.parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    install_diagnostics(app_dir / "logs")
    setup_tool_paths()
    
    from PyQt5.QtWidgets import QApplication
    from gui.main_window import MainWindow
    
    from PyQt5.QtCore import Qt
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(QApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    from gui.utils.theme import apply_light_theme
    apply_light_theme(app)
    app.setApplicationName("Open-AutoGLM GUI")
    app.setOrganizationName("Open-AutoGLM GUI")

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run application
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

