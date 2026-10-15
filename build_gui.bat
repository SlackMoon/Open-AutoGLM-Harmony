@echo off
echo 正在打包 GUI 应用为 exe 文件...
echo.

REM 使用系统默认Python，用户可根据需要修改
set PYTHON=python

REM 检查 PyInstaller 是否安装
%PYTHON% -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller 未安装，正在安装...
    %PYTHON% -m pip install pyinstaller
    if errorlevel 1 (
        echo 安装 PyInstaller 失败！
        pause
        exit /b 1
    )
)

echo 开始打包...
%PYTHON% -m PyInstaller build_gui.spec --clean

if errorlevel 1 (
    echo 打包失败！
    pause
    exit /b 1
)

echo.
echo 打包完成！
echo exe 文件位置: dist\GUI.exe
echo.
pause

