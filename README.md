# Open-AutoGLM-Harmony

面向鸿蒙设备的 AI 手机自动化桌面应用，同时支持 Android。模型通过截图理解界面，程序通过 HDC 或 ADB 执行点击、输入、滑动和导航操作。

本项目基于 [Open-AutoGLM-GUI](https://github.com/pengqiyu123/Open-AutoGLM-GUI) 和 [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM)，集成 [HOScrcpy-python](https://github.com/lizongxun1995/HOScrcpy-python) 的鸿蒙视频与触控通道。

[English](README_en.md)

## 功能

- **鸿蒙设备控制**：使用 HDC 截图、点击、输入、滑动、启动应用和系统导航。
- **自动投屏**：开始任务时启动鸿蒙 H.264 实时画面；不兼容时尝试低帧率截图预览。Android 使用 ADB 截图预览。
- **任务与投屏同步**：唯一设备自动选中，多设备需要明确选择；投屏使用与任务相同的设备。
- **视觉查找应用**：快捷启动失效后查询已安装包及入口，仍无法确定时将执行反馈交给模型，由模型通过桌面图标、搜索和相近名称继续查找。
- **手动控制**：聚焦画面后可以点按、长按、拖动、滚轮滑动和输入文字；右键返回，中键回主页。AI 执行期间暂停手动输入，保留画面。
- **模型接口**：支持 AutoGLM-Phone-9B，以及使用 OpenAI 兼容图文接口并遵循动作协议的 Qwen 视觉模型。
- **任务记录**：本地保存执行步骤、截图和审核结果，支持历史记录、教学和黄金路径。
- **Windows 界面**：固定 100% 应用字号并适配系统 DPI；浅色界面明确区分普通、禁用和选中状态。

## 环境要求

推荐 Windows、Python 3.11 和 Conda。代码支持 Python 3.10+；设备工具及原生投屏扩展的支持情况取决于操作系统和设备版本。

自行安装并加入 `PATH`：

- Android：[Android SDK Platform Tools / ADB](https://developer.android.com/tools/releases/platform-tools)。
- HarmonyOS：与设备兼容的 HarmonyOS / OpenHarmony SDK 中的 HDC，可随 DevEco Studio SDK 安装。

本仓库提供源码，不包含已编译的 GUI、SDK 工具链、手机 APK 或鸿蒙原生 `.so` 库。

## 安装

```bat
git clone https://github.com/SlackMoon/Open-AutoGLM-Harmony.git
cd Open-AutoGLM-Harmony
conda create -n autoglm python=3.11 -y
conda activate autoglm
python -m pip install -r requirements.txt
```

如需鸿蒙 H.264 实时投屏，下载设备端资源：

```bat
python scripts/fetch_harmony_assets.py
```

脚本从 HOScrcpy-python 的固定提交下载上游 JAR，提取设备库并核对 SHA-256；不会运行 JAR，也不需要 Java。下载的 `.so` 文件保存在本地且被 Git 忽略。来源与校验信息见 [第三方说明](third_party/HOScrcpy/NOTICE.txt) 和 [资源清单](third_party/HOScrcpy/assets.json)。

未下载资源或设备不兼容时，程序会尝试截图预览。

## 连接设备

### 鸿蒙

在手机上启用开发者选项和 USB 调试，连接电脑并接受设备上的调试授权，然后检查：

```bat
hdc list targets
```

列表应显示设备 ID。手机需处于可操作状态；程序无法代替用户完成设备密码、验证码等验证。

### Android

开启 USB 调试并接受授权：

```bat
adb devices
```

中文输入使用 [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard)。从其上游获取 APK 后安装，并在手机设置中启用该输入法。

## 启动与配置

```bat
python gui_app.py
```

也可以在已激活环境的终端运行 `start_gui.bat`。启动脚本使用当前 Python，不依赖指定磁盘上的 Conda。

1. 选择设备模式，刷新设备列表。只有一台设备时会自动选中。
2. 填写服务商提供的 Base URL、Model 和 API Key。
3. 输入任务，点击“开始执行”；右侧自动显示设备画面。
4. 任务执行期间可查看日志和画面。任务结束后可以继续手动操作画面。

配置示例：

| 服务 | Base URL | Model |
| --- | --- | --- |
| ModelScope AutoGLM | `https://api-inference.modelscope.cn/v1` | `ZhipuAI/AutoGLM-Phone-9B` |
| IP99 Qwen 视觉 | `https://llm.ip99.com/v1` | `qwen3.8-flash-next-uncensored` |

示例地址和名称需与服务商实际提供的接口一致，账户访问权限由服务商决定。密钥在 GUI 中填写；本仓库不包含密钥。

其他视觉模型需支持图片输入，并能按照 [动作协议](phone_agent/config/qwen_prompt.py) 输出 `do(...)` / `finish(...)`。接口兼容不代表任意模型都能准确执行手机任务。

任务示例：

```text
打开浏览器访问百度，确认首页加载完成后结束。
打开应用市场，搜索指定应用。
```

## 兼容说明

- 鸿蒙原生投屏扩展依赖系统版本、`uitest` 版本和设备 ABI；失败时尝试截图模式。截图预览约每秒一帧，速度取决于设备及 HDC 传输。
- 静止画面可能不产生新的编码帧；横竖屏坐标按实际截图尺寸转换，画面黑边不接收点击。
- 网络超时、连接错误、限流和临时服务端错误会有限重试；认证、内容拦截和无效动作不会自动重复请求。
- 快捷启动失败属于可恢复状态；模型会收到失败反馈继续查找。多个候选不会被程序随意选中。
- 未提供音频、多点触控或双向剪贴板同步；Android 预览使用截图，不是 H.264 视频。
- 运行日志和任务数据库保存在本地 `logs/`，不会随源码提交。

## 项目结构

```text
gui/                     桌面界面、投屏组件、任务与本地记录
phone_agent/             模型协议、动作执行、ADB/HDC 设备支持
hos_scrcpy/              上游鸿蒙视频与触控 Python 源码
resources/               程序图标
scripts/                 固定版本原生投屏资源下载脚本
third_party/HOScrcpy/    上游许可证、来源及资源校验清单
gui_app.py               GUI 入口
main.py                  命令行入口
requirements.txt         Python 依赖
```

## 打包

在对应平台安装依赖后执行：

```bat
python scripts/fetch_harmony_assets.py
python -m PyInstaller build_gui.spec --clean
```

输出位于 `dist/`。设备 SDK 工具仍需自行配置。原生资源、构建输出、日志、数据库、验证截图和本机配置均已加入 `.gitignore`。

## 许可证

保留上游的 [Apache-2.0 许可证](LICENSE)。`hos_scrcpy/` 引入的上游代码遵循 [MIT 许可证](third_party/HOScrcpy/LICENSE)，来源见对应 NOTICE。请遵守设备、模型服务和第三方依赖各自的使用要求。
