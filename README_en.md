# Open-AutoGLM-Harmony

A desktop phone automation app with HarmonyOS HDC control and Android ADB support. A vision model reads screenshots and produces structured actions for the device.

Based on [Open-AutoGLM-GUI](https://github.com/pengqiyu123/Open-AutoGLM-GUI), [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM), and the HarmonyOS transport from [HOScrcpy-python](https://github.com/lizongxun1995/HOScrcpy-python).

[中文说明](README.md)

## Features

- HarmonyOS screenshot, touch, text input, navigation and app launching over HDC.
- Automatic H.264 preview when a task starts, with screenshot fallback. Android uses screenshot preview.
- Automatic selection when exactly one device is connected.
- Installed bundle/entry discovery and visual launcher/search recovery when a launch shortcut fails.
- Mouse and keyboard control on the preview; manual input pauses while AI is acting.
- AutoGLM and compatible Qwen vision endpoints, task history, review and golden paths.
- A fixed 100% application font size with system DPI support and explicit light-theme colors.

## Setup

Windows with Python 3.11 is recommended. Install the appropriate HDC or ADB SDK tools separately and add them to `PATH`.

```bash
git clone https://github.com/SlackMoon/Open-AutoGLM-Harmony.git
cd Open-AutoGLM-Harmony
conda create -n autoglm python=3.11 -y
conda activate autoglm
python -m pip install -r requirements.txt
python scripts/fetch_harmony_assets.py
python gui_app.py
```

This is a source repository. It does not bundle compiled apps, SDK tools, APKs or native `.so` libraries. The resource fetcher downloads a pinned upstream JAR, verifies library SHA-256 values, and installs device resources locally. It never executes the JAR and does not require Java. See the [upstream notice](third_party/HOScrcpy/NOTICE.txt).

If native resources are missing or incompatible, the app attempts low-rate screenshot preview instead.

## Usage

1. Enable device debugging, connect the device and accept its authorization prompt.
2. Check `hdc list targets` or `adb devices`.
3. Select the device mode and refresh. A single device is selected automatically.
4. Enter your provider's Base URL, model name and API key.
5. Start a task; the preview opens automatically.

Example configurations:

| Provider | Base URL | Model |
| --- | --- | --- |
| ModelScope | `https://api-inference.modelscope.cn/v1` | `ZhipuAI/AutoGLM-Phone-9B` |
| IP99 Qwen | `https://llm.ip99.com/v1` | `qwen3.8-flash-next-uncensored` |

Use model identifiers and account access supplied by your provider. Other vision models must support images and the [action protocol](phone_agent/config/qwen_prompt.py); compatibility does not guarantee reliable automation.

Android text input requires [ADBKeyboard](https://github.com/senzhk/ADBKeyBoard), installed and enabled separately.

On the preview, use left click/drag, the mouse wheel, right click for Back, and middle click for Home. Focus the preview for keyboard input. During an AI task the picture remains visible, while manual input is paused.

## Limitations

Native mirroring depends on HarmonyOS, `uitest` and device ABI versions. Static screens may produce no new encoded frames. Screenshot preview is approximately one frame per second, depending on the device and transfer time. Audio, multi-touch and bidirectional clipboard synchronization are not included.

Transient model network failures use bounded retries. Launch failures are passed back to the model so it can inspect the launcher, search synonyms and continue. Ambiguous app matches are not launched arbitrarily.

Logs and task databases are local under `logs/` and are ignored by Git.

## Build

```bash
python scripts/fetch_harmony_assets.py
python -m PyInstaller build_gui.spec --clean
```

Build output goes to `dist/`. Configure SDK tools separately.

## License

The repository retains the upstream [Apache-2.0 license](LICENSE). Vendored `hos_scrcpy` code retains its upstream [MIT license](third_party/HOScrcpy/LICENSE).
