#!/bin/bash

echo "正在打包 GUI 应用为 exe 文件..."
echo ""

# 检查 PyInstaller 是否安装
if ! python -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller 未安装，正在安装..."
    pip install pyinstaller
    if [ $? -ne 0 ]; then
        echo "安装 PyInstaller 失败！"
        exit 1
    fi
fi

echo "开始打包..."
pyinstaller build_gui.spec --clean

if [ $? -ne 0 ]; then
    echo "打包失败！"
    exit 1
fi

echo ""
echo "打包完成！"
echo "exe 文件位置: dist/GUI.exe"
echo ""

