"""Main PhoneAgent class for orchestrating phone automation."""

import base64
import json
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from phone_agent.actions import ActionHandler
from phone_agent.actions.handler import do, finish, parse_action
from phone_agent.adb import get_current_app, get_screenshot
from phone_agent.adb.screenshot import Screenshot
from phone_agent.config import get_messages, get_system_prompt
from phone_agent.model import ModelClient, ModelConfig
from phone_agent.model.client import MessageBuilder
from phone_agent.device_manager import DeviceManager, DeviceMode


def _get_logs_dir() -> Path:
    """Get the logs directory path (always in Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe (dist/GUI.exe)
        # Go up from dist/ to Open-AutoGLM-main/
        return Path(sys.executable).parent.parent / "logs"
    else:
        # Running as script
        return Path("logs")


@dataclass
class AgentConfig:
    """Configuration for the PhoneAgent."""

    max_steps: int = 100
    device_id: str | None = None
    lang: str = "cn"
    system_prompt: str | None = None
    verbose: bool = True
    notify: bool = False
    log_file: str | None = None
    gui_mode: bool = False  # GUI模式，禁用终端输出
    thinking_callback: Callable[[str], None] | None = None  # 实时thinking回调
    stop_requested: Callable[[], bool] | None = None
    device_mode: str = "android"  # 设备模式: "android" (ADB) 或 "harmonyos" (HDC)

    def __post_init__(self):
        if self.system_prompt is None:
            self.system_prompt = get_system_prompt(self.lang)


@dataclass
class StepResult:
    """Result of a single agent step."""

    success: bool
    finished: bool
    action: dict[str, Any] | None
    thinking: str
    message: str | None = None
    screenshot_path: str | None = None  # Path to saved screenshot file
    recoverable: bool = False


class PhoneAgent:
    """
    AI-powered agent for automating Android phone interactions.

    The agent uses a vision-language model to understand screen content
    and decide on actions to complete user tasks.

    Args:
        model_config: Configuration for the AI model.
        agent_config: Configuration for the agent behavior.
        confirmation_callback: Optional callback for sensitive action confirmation.
        takeover_callback: Optional callback for takeover requests.

    Example:
        >>> from phone_agent import PhoneAgent
        >>> from phone_agent.model import ModelConfig
        >>>
        >>> model_config = ModelConfig(base_url="http://localhost:8000/v1")
        >>> agent = PhoneAgent(model_config)
        >>> agent.run("Open WeChat and send a message to John")
    """

    def __init__(
        self,
        model_config: ModelConfig | None = None,
        agent_config: AgentConfig | None = None,
        confirmation_callback: Callable[[str], bool] | None = None,
        takeover_callback: Callable[[str], None] | None = None,
    ):
        self.model_config = model_config or ModelConfig()
        self.agent_config = agent_config or AgentConfig()

        self.model_client = ModelClient(self.model_config)
        self._logger = self._create_logger(self.agent_config.log_file)
        
        # Initialize device manager based on device mode
        device_mode = DeviceMode.HARMONYOS if self.agent_config.device_mode == "harmonyos" else DeviceMode.ANDROID
        self.device_manager = DeviceManager(
            mode=device_mode,
            device_id=self.agent_config.device_id,
        )
        
        self.action_handler = ActionHandler(
            device_id=self.agent_config.device_id,
            confirmation_callback=confirmation_callback,
            takeover_callback=takeover_callback,
            notifier=self._create_notifier() if self.agent_config.notify else None,
            logger=self._log,
            device_manager=self.device_manager,  # Pass device manager for HarmonyOS support
        )

        self._context: list[dict[str, Any]] = []
        self._step_count = 0

    def run(self, task: str) -> str:
        """
        Run the agent to complete a task.

        Args:
            task: Natural language description of the task.

        Returns:
            Final message from the agent.
        """
        self._context = []
        self._step_count = 0

        # First step with user prompt
        result = self._execute_step(task, is_first=True)

        if result.finished:
            return result.message or "Task completed"

        # Continue until finished or max steps reached
        while self._step_count < self.agent_config.max_steps:
            result = self._execute_step(is_first=False)

            if result.finished:
                return result.message or "Task completed"

        return "Max steps reached"

    def step(self, task: str | None = None) -> StepResult:
        """
        Execute a single step of the agent.

        Useful for manual control or debugging.

        Args:
            task: Task description (only needed for first step).

        Returns:
            StepResult with step details.
        """
        is_first = len(self._context) == 0

        if is_first and not task:
            raise ValueError("Task is required for the first step")

        return self._execute_step(task, is_first)

    def reset(self) -> None:
        """Reset the agent state for a new task."""
        self._context = []
        self._step_count = 0

    def _execute_step(
        self, user_prompt: str | None = None, is_first: bool = False
    ) -> StepResult:
        """Execute a single step of the agent loop."""
        if self.agent_config.stop_requested and self.agent_config.stop_requested():
            return StepResult(False, True, None, "", "任务已停止")
        self._step_count += 1

        # Capture current screen state using device manager (supports both ADB and HDC)
        screenshot = self.device_manager.get_screenshot()
        current_app = self.device_manager.get_current_app()
        
        # Save screenshot to file for logging
        screenshot_path = self._save_screenshot(screenshot)
        
        # Handle sensitive screen (FLAG_SECURE apps like banking, payment)
        if screenshot.is_sensitive:
            return StepResult(
                success=False,
                finished=True,
                action={"action": "Take_over", "message": "检测到敏感屏幕（可能是支付、银行或密码页面），无法截图。请手动处理后重试。", "_metadata": "finish"},
                thinking="截图失败，检测到敏感屏幕。应用设置了 FLAG_SECURE 防止截图。",
                message="敏感屏幕，需要用户手动处理",
                screenshot_path=screenshot_path,
            )

        # Build messages
        if is_first:
            # 检查是否已经有系统消息（可能是预注入的经验上下文）
            has_system_message = any(
                msg.get('role') == 'system' for msg in self._context
            )
            if not has_system_message:
                self._context.append(
                    MessageBuilder.create_system_message(self.agent_config.system_prompt)
                )

            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"{user_prompt}\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )
        else:
            screen_info = MessageBuilder.build_screen_info(current_app)
            text_content = f"** Screen Info **\n\n{screen_info}"

            self._context.append(
                MessageBuilder.create_user_message(
                    text=text_content, image_base64=screenshot.base64_data
                )
            )

        # Get model response
        try:
            if self.agent_config.gui_mode:
                response = self.model_client.request_stream_sync(
                    self._context,
                    thinking_callback=self.agent_config.thinking_callback,
                    stop_requested=self.agent_config.stop_requested,
                )
            else:
                response = self.model_client.request(self._context)
        except Exception as e:
            error_msg = str(e)
            if self.agent_config.verbose and not self.agent_config.gui_mode:
                traceback.print_exc()
            # Don't add "Model error: " prefix - the error message from ModelClient already contains it
            # This allows better error parsing in the GUI
            return StepResult(
                success=False,
                finished=True,
                action=None,
                thinking="",
                message=error_msg,
                screenshot_path=screenshot_path,
            )

        if self.agent_config.stop_requested and self.agent_config.stop_requested():
            return StepResult(False, True, None, "", "任务已停止", screenshot_path)

        # Parse action from response
        try:
            action = parse_action(response.action)
        except ValueError as exc:
            return StepResult(False, True, None, response.thinking,
                              f"模型动作格式错误: {exc}", screenshot_path)

        if self.agent_config.verbose and not self.agent_config.gui_mode:
            # Print thinking process (only in CLI mode, not GUI mode)
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "=" * 50)
            print(f"💭 {msgs['thinking']}:")
            print("-" * 50)
            print(response.thinking)
            print("-" * 50)
            print(f"🎯 {msgs['action']}:")
            print(json.dumps(action, ensure_ascii=False, indent=2))
            print("=" * 50 + "\n")

        # Log step details
        self._log(
            f"step={self._step_count} action={action.get('action')} finished={action.get('_metadata')=='finish'} "
            f"thinking={response.thinking[:200]} action_raw={response.action[:200]}"
        )

        # Remove image from context to save space
        self._context[-1] = MessageBuilder.remove_images_from_message(self._context[-1])

        # Execute action
        try:
            result = self.action_handler.execute(
                action, screenshot.width, screenshot.height
            )
        except Exception as e:
            if self.agent_config.verbose and not self.agent_config.gui_mode:
                traceback.print_exc()
            return StepResult(False, True, action, response.thinking,
                              f"设备操作失败: {e}", screenshot_path)

        # Add assistant response to context
        self._context.append(
            MessageBuilder.create_assistant_message(
                f"<think>{response.thinking}</think><answer>{response.action}</answer>"
            )
        )

        recoverable = not result.success and getattr(result, "recoverable", False)
        if recoverable:
            self._context.append(MessageBuilder.create_user_message(
                text=f"【设备执行反馈】{result.message} 请根据下一张新截图选择下一步操作。"
            ))

        # Check if finished
        finished = action.get("_metadata") == "finish" or result.should_finish

        if finished and self.agent_config.verbose and not self.agent_config.gui_mode:
            # Print completion message (only in CLI mode, not GUI mode)
            msgs = get_messages(self.agent_config.lang)
            print("\n" + "🎉 " + "=" * 48)
            print(
                f"✅ {msgs['task_completed']}: {result.message or action.get('message', msgs['done'])}"
            )
            print("=" * 50 + "\n")

        return StepResult(
            success=result.success,
            finished=finished,
            action=action,
            thinking=response.thinking,
            message=result.message or action.get("message"),
            screenshot_path=screenshot_path,
            recoverable=recoverable,
        )

    def _create_notifier(self):
        """Create a simple notification sender to the device."""
        from phone_agent.adb import post_notification

        def notify(title: str, text: str) -> None:
            post_notification(title=title, text=text, device_id=self.agent_config.device_id)

        return notify

    def _create_logger(self, path: str | None):
        if not path:
            return None

        def log_fn(message: str) -> None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {message}\n")

        return log_fn

    def _log(self, message: str) -> None:
        if self._logger:
            self._logger(message)
    
    def _save_screenshot(self, screenshot: Screenshot) -> str | None:
        """
        Save screenshot to file system for logging.
        
        Args:
            screenshot: Screenshot object containing base64 data
            
        Returns:
            Path to saved screenshot file, or None if save failed
        """
        try:
            # Create screenshots directory in logs folder
            screenshots_dir = _get_logs_dir() / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with timestamp and step number
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"step_{self._step_count}_{timestamp}.png"
            filepath = screenshots_dir / filename
            
            # Decode base64 and save to file
            image_data = base64.b64decode(screenshot.base64_data)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            
            return str(filepath)
        except Exception as e:
            print(f"Failed to save screenshot: {e}")
            return None

    @property
    def context(self) -> list[dict[str, Any]]:
        """Get the current conversation context."""
        return self._context.copy()

    @property
    def step_count(self) -> int:
        """Get the current step count."""
        return self._step_count
