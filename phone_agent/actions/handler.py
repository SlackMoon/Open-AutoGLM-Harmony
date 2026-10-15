"""Action handler for processing AI model outputs."""

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from phone_agent.adb import (
    back,
    clear_text,
    detect_and_set_adb_keyboard,
    double_tap,
    home,
    launch_app,
    long_press,
    post_notification,
    restore_keyboard,
    swipe,
    tap,
    type_text,
)


@dataclass
class ActionResult:
    """Result of an action execution."""

    success: bool
    should_finish: bool
    message: str | None = None
    requires_confirmation: bool = False
    recoverable: bool = False


class ActionHandler:
    """
    Handles execution of actions from AI model output.

    Args:
        device_id: Optional ADB device ID for multi-device setups.
        confirmation_callback: Optional callback for sensitive action confirmation.
            Should return True to proceed, False to cancel.
        takeover_callback: Optional callback for takeover requests (login, captcha).
        device_manager: Optional DeviceManager for unified device control (supports HarmonyOS).
    """

    def __init__(
        self,
        device_id: str | None = None,
        confirmation_callback: Callable[[str], bool] | None = None,
        takeover_callback: Callable[[str], None] | None = None,
        notifier: Callable[[str, str], None] | None = None,
        logger: Callable[[str], None] | None = None,
        device_manager: Optional[Any] = None,  # DeviceManager instance
    ):
        self.device_id = device_id
        self.confirmation_callback = confirmation_callback or self._default_confirmation
        self.takeover_callback = takeover_callback or self._default_takeover
        self.notifier = notifier
        self.logger = logger
        self.device_manager = device_manager  # For HarmonyOS support

    def execute(
        self, action: dict[str, Any], screen_width: int, screen_height: int
    ) -> ActionResult:
        """
        Execute an action from the AI model.

        Args:
            action: The action dictionary from the model.
            screen_width: Current screen width in pixels.
            screen_height: Current screen height in pixels.

        Returns:
            ActionResult indicating success and whether to finish.
        """
        action_type = action.get("_metadata")

        if action_type == "finish":
            return ActionResult(
                success=True, should_finish=True, message=action.get("message")
            )

        if action_type != "do":
            return ActionResult(
                success=False,
                should_finish=True,
                message=f"Unknown action type: {action_type}",
            )

        action_name = action.get("action")
        handler_method = self._get_handler(action_name)

        if handler_method is None:
            return ActionResult(
                success=False,
                should_finish=False,
                message=f"Unknown action: {action_name}",
            )

        try:
            self._notify(action_name, action)
            self._log(f"start action={action_name} payload={action}")
            return handler_method(action, screen_width, screen_height)
        except Exception as e:
            return ActionResult(
                success=False, should_finish=False, message=f"Action failed: {e}"
            )

    def _get_handler(self, action_name: str) -> Callable | None:
        """Get the handler method for an action."""
        handlers = {
            "Launch": self._handle_launch,
            "Tap": self._handle_tap,
            "Type": self._handle_type,
            "Type_Name": self._handle_type,
            "Swipe": self._handle_swipe,
            "Back": self._handle_back,
            "Home": self._handle_home,
            "Double Tap": self._handle_double_tap,
            "Long Press": self._handle_long_press,
            "Wait": self._handle_wait,
            "Take_over": self._handle_takeover,
            "Note": self._handle_note,
            "Call_API": self._handle_call_api,
            "Interact": self._handle_interact,
        }
        return handlers.get(action_name)

    def _convert_relative_to_absolute(
        self, element: list[int], screen_width: int, screen_height: int
    ) -> tuple[int, int]:
        """Convert relative coordinates (0-1000) to absolute pixels."""
        x = int(element[0] / 1000 * screen_width)
        y = int(element[1] / 1000 * screen_height)
        return x, y

    def _handle_launch(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle app launch action."""
        app_name = action.get("app")
        if not app_name:
            return ActionResult(False, False, "No app name specified")

        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            success = self.device_manager.launch_app(app_name)
            if success:
                return ActionResult(True, False)
            candidates = getattr(self.device_manager, "last_launch_candidates", [])
            detail = f"设备发现的候选应用：{', '.join(candidates[:8])}。" if candidates else ""
            return self._launch_search_result(app_name, detail)
        
        # Fallback to Android-only launch
        success = launch_app(app_name, self.device_id)
        if success:
            return ActionResult(True, False)
        return self._launch_search_result(app_name)

    @staticmethod
    def _launch_search_result(app_name, detail=""):
        return ActionResult(
            False, False,
            f"快捷启动未能打开「{app_name}」，这不代表应用未安装。{detail}"
            "请继续通过界面查找：先 Home 回桌面，查看相近名称的应用图标；"
            "必要时打开桌面/全局搜索，搜索原名或同义词，核对名称后点击目标。"
            "不要重复同一个失败的 Launch；不要随意打开不相关的候选应用。"
            "确实搜索不到时再说明原因；当前任务尚未完成。",
            recoverable=True,
        )

    def _handle_tap(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle tap action."""
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = self._convert_relative_to_absolute(element, width, height)

        # Check for sensitive operation
        if "message" in action:
            if not self.confirmation_callback(action["message"]):
                return ActionResult(
                    success=False,
                    should_finish=True,
                    message="User cancelled sensitive operation",
                )

        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.tap(x, y)
        else:
            tap(x, y, self.device_id)
        return ActionResult(True, False)

    def _handle_type(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle text input action."""
        text = action.get("text", "")

        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            # HarmonyOS uses uitest for text input directly
            from phone_agent.device_manager import DeviceMode
            if self.device_manager.mode == DeviceMode.HARMONYOS:
                self.device_manager.input_text(text)
                return ActionResult(True, False)
        
        # Android: Switch to ADB keyboard
        original_ime = detect_and_set_adb_keyboard(self.device_id)
        time.sleep(1.0)

        # Clear existing text and type new text
        clear_text(self.device_id)
        time.sleep(1.0)

        type_text(text, self.device_id)
        time.sleep(1.0)

        # Restore original keyboard
        restore_keyboard(original_ime, self.device_id)
        time.sleep(1.0)

        return ActionResult(True, False)

    def _handle_swipe(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle swipe action."""
        start = action.get("start")
        end = action.get("end")

        if not start or not end:
            return ActionResult(False, False, "Missing swipe coordinates")

        start_x, start_y = self._convert_relative_to_absolute(start, width, height)
        end_x, end_y = self._convert_relative_to_absolute(end, width, height)

        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.swipe(start_x, start_y, end_x, end_y)
        else:
            swipe(start_x, start_y, end_x, end_y, device_id=self.device_id)
        return ActionResult(True, False)

    def _handle_back(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle back button action."""
        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.back()
        else:
            back(self.device_id)
        return ActionResult(True, False)

    def _handle_home(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle home button action."""
        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.home()
        else:
            home(self.device_id)
        return ActionResult(True, False)

    def _handle_double_tap(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle double tap action."""
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = self._convert_relative_to_absolute(element, width, height)
        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.double_tap(x, y)
        else:
            double_tap(x, y, self.device_id)
        return ActionResult(True, False)

    def _handle_long_press(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle long press action."""
        element = action.get("element")
        if not element:
            return ActionResult(False, False, "No element coordinates")

        x, y = self._convert_relative_to_absolute(element, width, height)
        # Use device manager if available (supports HarmonyOS)
        if self.device_manager:
            self.device_manager.long_press(x, y)
        else:
            long_press(x, y, device_id=self.device_id)
        return ActionResult(True, False)

    def _handle_wait(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle wait action."""
        duration_str = action.get("duration", "1 seconds")
        try:
            duration = float(duration_str.replace("seconds", "").strip())
        except ValueError:
            duration = 1.0

        time.sleep(duration)
        return ActionResult(True, False)

    def _handle_takeover(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle takeover request (login, captcha, etc.)."""
        message = action.get("message", "User intervention required")
        self.takeover_callback(message)
        return ActionResult(True, False)

    def _handle_note(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle note action (placeholder for content recording)."""
        # This action is typically used for recording page content
        # Implementation depends on specific requirements
        return ActionResult(True, False)

    def _handle_call_api(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle API call action (placeholder for summarization)."""
        # This action is typically used for content summarization
        # Implementation depends on specific requirements
        return ActionResult(True, False)

    def _handle_interact(self, action: dict, width: int, height: int) -> ActionResult:
        """Handle interaction request (user choice needed)."""
        # This action signals that user input is needed
        return ActionResult(True, False, message="User interaction required")

    @staticmethod
    def _default_confirmation(message: str) -> bool:
        """Default confirmation callback using console input."""
        response = input(f"Sensitive operation: {message}\nConfirm? (Y/N): ")
        return response.upper() == "Y"

    @staticmethod
    def _default_takeover(message: str) -> None:
        """Default takeover callback using console input."""
        input(f"{message}\nPress Enter after completing manual operation...")

    def _notify(self, action_name: str, action: dict[str, Any]) -> None:
        """Send optional device notification for current action."""
        if not self.notifier:
            return
        summary = action.get("message") or action.get("text") or ""
        self.notifier(f"AutoGLM: {action_name}", summary[:60])

    def _log(self, message: str) -> None:
        if self.logger:
            self.logger(message)


def parse_action(response: str) -> dict[str, Any]:
    from phone_agent.model.action_format import parse_literal_action
    return parse_literal_action(response)


def do(**kwargs) -> dict[str, Any]:
    """Helper function for creating 'do' actions."""
    kwargs["_metadata"] = "do"
    return kwargs


def finish(**kwargs) -> dict[str, Any]:
    """Helper function for creating 'finish' actions."""
    kwargs["_metadata"] = "finish"
    return kwargs
