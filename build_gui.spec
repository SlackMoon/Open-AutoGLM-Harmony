# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

av_datas, av_binaries, av_hiddenimports = collect_all('av')
block_cipher = None

a = Analysis(
    ['gui_app.py'],
    pathex=['.'],
    binaries=av_binaries,
    datas=[
        ('使用必读.txt', '.'),
        ('resources', 'resources'),
        ('gui', 'gui'),
        ('phone_agent', 'phone_agent'),
        ('third_party/HOScrcpy', 'third_party/HOScrcpy'),
    ] + av_datas + ([('hos_scrcpy/bridge/scrcpy_server', 'hos_scrcpy/bridge/scrcpy_server')]
                      if Path('hos_scrcpy/bridge/scrcpy_server').is_dir() else []),
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'phone_agent',
        'phone_agent.agent',
        'phone_agent.model',
        'phone_agent.model.client',
        'phone_agent.adb',
        'phone_agent.actions',
        'phone_agent.config',
        'gui',
        'gui.main_window',
        'gui.utils',
        'gui.utils.agent_runner',
        'gui.utils.system_checker',
        'gui.widgets',
        'gui.widgets.log_viewer',
        'gui.widgets.device_mirror',
        'gui.utils.mirror_backend',
        'hos_scrcpy.bridge.native_stream',
        'hos_scrcpy.bridge.scrcpy_pb2',
        'hos_scrcpy.bridge.scrcpy_pb2_grpc',
        'grpc._cython.cygrpc',
    ] + av_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tensorflow',
        'torch',
        'matplotlib',
        'numpy.distutils',
        'scipy',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
        'PIL._tkinter_finder',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    collect_submodules=True,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 禁用 UPX 压缩以加快打包速度
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 显示控制台窗口以查看进度
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/LOG.ico',
)

