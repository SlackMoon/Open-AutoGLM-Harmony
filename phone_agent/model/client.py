"""Model client for AI inference using OpenAI-compatible API."""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI, DefaultHttpxClient, Timeout, APIConnectionError, APIStatusError


@dataclass
class ModelConfig:
    """Configuration for the AI model."""

    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    model_name: str = "autoglm-phone-9b"
    max_tokens: int = 3000
    temperature: float = 0.0
    top_p: float = 0.85
    frequency_penalty: float = 0.2
    extra_body: dict[str, Any] = field(default_factory=dict)
    # Optional HTTP proxy settings. Default None.
    proxies: dict | None = None
    max_stream_seconds: float = 120.0
    request_timeout_seconds: float = 90.0
    max_request_attempts: int = 3
    retry_delay_seconds: float = 2.0


@dataclass
class ModelResponse:
    """Response from the AI model."""

    thinking: str
    action: str
    raw_content: str


class ModelClient:
    """
    Client for interacting with OpenAI-compatible vision-language models.

    Args:
        config: Model configuration.
    """

    def __init__(self, config: ModelConfig | None = None):
        self.config = config or ModelConfig()
        timeout = Timeout(self.config.request_timeout_seconds, connect=10.0, write=30.0, pool=10.0)
        # Disable env proxies by default to avoid accidental localhost (e.g., 127.0.0.1:11434).
        if self.config.proxies is not None:
            http_client = DefaultHttpxClient(
                proxies=self.config.proxies,
                timeout=timeout,
            )
        else:
            http_client = DefaultHttpxClient(
                timeout=timeout,
                trust_env=False,
            )
        self.client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            http_client=http_client,
            max_retries=0,
            timeout=timeout,
        )

    def request(self, messages: list[dict[str, Any]]) -> ModelResponse:
        """
        Send a request to the model.

        Args:
            messages: List of message dictionaries in OpenAI format.

        Returns:
            ModelResponse containing thinking and action.

        Raises:
            Exception: If the request fails, with detailed error information.
        """
        try:
            response = self.client.chat.completions.create(
                messages=messages,
                model=self.config.model_name,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                frequency_penalty=self.config.frequency_penalty,
                extra_body=self.config.extra_body,
                stream=False,
            )

            raw_content = response.choices[0].message.content

            # Parse thinking and action from response
            thinking, action = self._parse_response(raw_content)

            return ModelResponse(thinking=thinking, action=action, raw_content=raw_content)

        except Exception as e:
            # Parse and format error information
            error_info = self._parse_error(e)
            raise Exception(error_info) from e

    def request_stream(
        self,
        messages: list[dict[str, Any]],
        thinking_callback: Callable[[str], None] | None = None,
    ):
        """
        Send a streaming request to the model and return stream iterator for async processing.

        Args:
            messages: List of message dictionaries in OpenAI format.
            thinking_callback: Optional callback (not used in async mode, kept for compatibility).

        Returns:
            Stream iterator from OpenAI API.

        Raises:
            Exception: If the request fails, with detailed error information.
        """
        try:
            stream = self.client.chat.completions.create(
                messages=messages,
                model=self.config.model_name,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                frequency_penalty=self.config.frequency_penalty,
                extra_body=self.config.extra_body,
                stream=True,
            )
            
            # Return stream iterator for async processing
            return stream
            
        except Exception as e:
            # Parse and format error information
            error_info = self._parse_error(e)
            raise Exception(error_info) from e
    
    def request_stream_sync(self, messages, thinking_callback=None, stop_requested=None):
        """Retry transient inference failures before any device action executes."""
        attempts = max(1, min(5, self.config.max_request_attempts))
        for attempt in range(1, attempts + 1):
            try:
                return self._request_stream_once(messages, thinking_callback, stop_requested)
            except Exception as exc:
                if stop_requested and stop_requested():
                    raise RuntimeError("任务已停止") from exc
                if not self._retryable(exc):
                    raise
                if attempt == attempts:
                    raise RuntimeError(f"模型服务暂时无响应，已尝试 {attempts} 次。请检查网络或稍后重试。详细信息：{exc}") from exc
                logging.warning("Transient model request failure, retry %s/%s (%s)",
                                attempt + 1, attempts, type(exc.__cause__ or exc).__name__)
                if thinking_callback:
                    thinking_callback(f"\n模型请求暂时失败，正在重试（{attempt + 1}/{attempts}）…\n")
                deadline = time.monotonic() + self.config.retry_delay_seconds * 2 ** (attempt - 1)
                while time.monotonic() < deadline:
                    if stop_requested and stop_requested():
                        raise RuntimeError("任务已停止") from exc
                    time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    @staticmethod
    def _retryable(error):
        seen = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            if isinstance(error, (APIConnectionError, TimeoutError)):
                return True
            if isinstance(error, APIStatusError) and (error.status_code in (408, 429) or error.status_code >= 500):
                return True
            error = error.__cause__
        return False

    def _request_stream_once(self, messages, thinking_callback=None, stop_requested=None):
        """Consume SSE in the existing worker thread, without Qt event loops."""
        stream = None
        raw = ""
        emitted = 0
        last_emit = time.monotonic()
        deadline = last_emit + self.config.max_stream_seconds
        try:
            if stop_requested and stop_requested():
                raise RuntimeError("任务已停止")
            stream = self.request_stream(messages)
            for chunk in stream:
                if stop_requested and stop_requested():
                    raise RuntimeError("任务已停止")
                if time.monotonic() > deadline:
                    raise TimeoutError("模型响应超过时限，请重试或检查服务状态")
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason == "content_filter":
                    raise RuntimeError("模型服务拦截了本次输出（content_filter）")
                content = choice.delta.content
                if content:
                    raw += content
                    if len(raw) > 262144:
                        raise ValueError("模型响应过长，已停止本次任务")
                    # Retain a short tail so partial XML/action markers are not shown.
                    cuts = [raw.find(m) for m in ("<answer>", "do(action=", "finish(message=") if m in raw]
                    cut = min(cuts) if cuts else max(0, len(raw) - 32)
                    visible = raw[:cut].replace("<think>", "").replace("</think>", "")
                    if thinking_callback and time.monotonic() - last_emit >= 0.1:
                        if len(visible) > emitted:
                            thinking_callback(visible[emitted:])
                            emitted = len(visible)
                        last_emit = time.monotonic()
            if stop_requested and stop_requested():
                raise RuntimeError("任务已停止")
            thinking, action = self._parse_response(raw)
            if thinking_callback and len(thinking) > emitted:
                thinking_callback(thinking[emitted:])
            return ModelResponse(thinking=thinking, action=action, raw_content=raw)
        except Exception as exc:
            raise RuntimeError(self._parse_error(exc)) from exc
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    logging.exception("Could not close response stream")

    def _parse_error(self, error: Exception) -> str:
        """
        Parse error exception and return formatted error message.

        Args:
            error: The exception that occurred.

        Returns:
            Formatted error message string.
        """
        error_type = type(error).__name__
        error_str = str(error)

        # Try to extract error details from OpenAI exceptions
        if hasattr(error, "response") and error.response is not None:
            try:
                error_body = error.response.json() if hasattr(error.response, "json") else {}
                error_code = error_body.get("error", {}).get("code", "")
                error_message = error_body.get("error", {}).get("message", error_str)
                error_type_api = error_body.get("error", {}).get("type", "")
                request_id = error_body.get("request_id", "")

                # Format error message
                parts = [f"Error code: {error.response.status_code}"]
                if error_code:
                    parts.append(f"Code: {error_code}")
                if error_type_api:
                    parts.append(f"Type: {error_type_api}")
                if error_message:
                    parts.append(f"Message: {error_message}")
                if request_id:
                    parts.append(f"Request ID: {request_id}")

                return " - ".join(parts)
            except Exception:
                pass

        # For connection errors, provide more helpful message
        if "Connection" in error_type or "connect" in error_str.lower():
            if "127.0.0.1" in error_str or "localhost" in error_str.lower():
                return (
                    f"连接错误: 无法连接到本地服务\n"
                    f"详细信息: {error_str}\n\n"
                    f"请检查:\n"
                    f"1. Base URL 是否正确（应使用 ModelScope 或智谱 BigModel 的地址）\n"
                    f"2. 如果确实需要本地服务，请确保服务正在运行"
                )
            else:
                return (
                    f"连接错误: 无法连接到模型服务\n"
                    f"详细信息: {error_str}\n\n"
                    f"请检查:\n"
                    f"1. Base URL 是否正确\n"
                    f"2. 网络连接是否正常\n"
                    f"3. 模型服务是否正在运行"
                )

        # For authentication errors
        if "401" in error_str or "unauthorized" in error_str.lower() or "authentication" in error_str.lower():
            return (
                f"认证错误: API Key 无效或已过期\n"
                f"详细信息: {error_str}\n\n"
                f"请检查:\n"
                f"1. API Key 是否正确\n"
                f"2. API Key 是否已过期\n"
                f"3. 请参考 使用必读.txt 重新获取 API Key"
            )

        # Default error format
        return f"{error_type}: {error_str}"

    def _clean_thinking(self, text: str) -> str:
        """
        Clean thinking text by removing code-like patterns.
        
        Args:
            text: Raw thinking text that may contain code fragments
            
        Returns:
            Cleaned thinking text without code patterns
        """
        if not text:
            return text
        
        # Remove action markers and any content after them
        cleaned = text
        
        # Remove action markers if they appear (case-insensitive)
        # Check for "do(action" pattern (with or without "=")
        if "do(action" in cleaned.lower():
            # Find the position (case-insensitive)
            pos = cleaned.lower().find("do(action")
            cleaned = cleaned[:pos].rstrip()
        
        # Check for "finish(message" pattern (with or without "=")
        if "finish(message" in cleaned.lower():
            # Find the position (case-insensitive)
            pos = cleaned.lower().find("finish(message")
            cleaned = cleaned[:pos].rstrip()
        
        # Remove any lines that contain code patterns
        lines = cleaned.split('\n')
        cleaned_lines = []
        for line in lines:
            # Skip lines that contain code markers
            line_lower = line.lower()
            if "do(action" in line_lower or "finish(message" in line_lower:
                # If line contains marker, only keep part before it
                if "do(action" in line_lower:
                    pos = line_lower.find("do(action")
                    line = line[:pos].rstrip()
                if "finish(message" in line_lower:
                    pos = line_lower.find("finish(message")
                    line = line[:pos].rstrip()
                # Only add if there's meaningful content
                if line.strip() and not line.strip().startswith(('{', '}', '[', ']')):
                    cleaned_lines.append(line)
            else:
                # Check if line looks like code (starts with code-like characters)
                stripped = line.strip()
                if stripped and not stripped.startswith(('{', '}', '[', ']', 'do', 'finish')):
                    cleaned_lines.append(line)
        
        cleaned = '\n'.join(cleaned_lines).rstrip()
        
        # Remove any trailing incomplete code patterns
        # Remove trailing code-like characters
        while cleaned and cleaned[-1] in ['{', '}', '[', ']', '=', '(', ')', ',', ';']:
            cleaned = cleaned[:-1].rstrip()
        
        # Remove trailing code keywords
        code_keywords = ["do(action", "finish(message", "do", "finish", "action", "message"]
        for keyword in code_keywords:
            if cleaned.lower().endswith(keyword.lower()):
                cleaned = cleaned[:-len(keyword)].rstrip()
                break
        
        # Remove any remaining code-like patterns at the end
        # Look for patterns like "do(action", "finish(message" anywhere in the text
        if "do(action" in cleaned.lower():
            pos = cleaned.lower().rfind("do(action")
            cleaned = cleaned[:pos].rstrip()
        if "finish(message" in cleaned.lower():
            pos = cleaned.lower().rfind("finish(message")
            cleaned = cleaned[:pos].rstrip()
        
        return cleaned

    def _parse_response(self, content):
        from phone_agent.model.action_format import split_response
        return split_response(content)


class MessageBuilder:
    """Helper class for building conversation messages."""

    @staticmethod
    def create_system_message(content: str) -> dict[str, Any]:
        """Create a system message."""
        return {"role": "system", "content": content}

    @staticmethod
    def create_user_message(
        text: str, image_base64: str | None = None
    ) -> dict[str, Any]:
        """
        Create a user message with optional image.

        Args:
            text: Text content.
            image_base64: Optional base64-encoded image.

        Returns:
            Message dictionary.
        """
        content = []

        if image_base64:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                }
            )

        content.append({"type": "text", "text": text})

        return {"role": "user", "content": content}

    @staticmethod
    def create_assistant_message(content: str) -> dict[str, Any]:
        """Create an assistant message."""
        return {"role": "assistant", "content": content}

    @staticmethod
    def remove_images_from_message(message: dict[str, Any]) -> dict[str, Any]:
        """
        Remove image content from a message to save context space.

        Args:
            message: Message dictionary.

        Returns:
            Message with images removed.
        """
        if isinstance(message.get("content"), list):
            message["content"] = [
                item for item in message["content"] if item.get("type") == "text"
            ]
        return message

    @staticmethod
    def build_screen_info(current_app: str, **extra_info) -> str:
        """
        Build screen info string for the model.

        Args:
            current_app: Current app name.
            **extra_info: Additional info to include.

        Returns:
            JSON string with screen info.
        """
        info = {"current_app": current_app, **extra_info}
        return json.dumps(info, ensure_ascii=False)
