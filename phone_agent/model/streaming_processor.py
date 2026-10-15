"""Streaming response processor for asynchronous chunk processing."""

from typing import Any, Callable, Iterator, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class StreamingResponseProcessor(QObject):
    """
    Asynchronously processes streaming response chunks using QTimer.
    
    This allows the UI to remain responsive while processing stream chunks,
    ensuring thinking updates are displayed in real-time.
    """
    
    # Signals
    chunk_received = pyqtSignal(str)  # Emitted when a thinking chunk is received
    processing_complete = pyqtSignal(object)  # Emitted when processing is complete (ModelResponse)
    processing_error = pyqtSignal(str)  # Emitted when an error occurs
    
    def __init__(
        self,
        stream: Iterator,
        thinking_callback: Optional[Callable[[str], None]] = None,
        parent=None,
    ):
        """
        Initialize the streaming processor.
        
        Args:
            stream: The streaming response iterator from OpenAI
            thinking_callback: Optional callback for real-time thinking updates
            parent: Parent QObject
        """
        super().__init__(parent)
        self.stream = stream
        self.thinking_callback = thinking_callback
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._process_next_chunk)
        self.timer.setInterval(10)  # Process chunks every 10ms for responsiveness
        
        self.raw_content = ""
        self.action_started = False
        self.last_raw_content = ""
        self.accumulated_thinking = ""
        self.thinking_buffer = ""
        self.chunk_count = 0
        self.is_processing = False
        self.stream_exhausted = False
        
        # Import here to avoid circular dependency
        from phone_agent.model.client import ModelClient
        self._model_client_instance = None  # Will be set by caller if needed for _clean_thinking
        
    def set_model_client(self, model_client):
        """Set the model client instance for accessing _clean_thinking method."""
        self._model_client_instance = model_client
    
    def start(self):
        """Start processing the stream."""
        if self.is_processing:
            return
        
        self.is_processing = True
        self.stream_exhausted = False
        self.timer.start()
    
    def stop(self):
        """Stop processing the stream."""
        self.timer.stop()
        self.is_processing = False
    
    def _clean_thinking(self, text: str) -> str:
        """Clean thinking text by removing code-like patterns."""
        if self._model_client_instance:
            return self._model_client_instance._clean_thinking(text)
        # Fallback: simple cleaning
        if not text:
            return text
        cleaned = text
        if "do(action" in cleaned.lower():
            pos = cleaned.lower().find("do(action")
            cleaned = cleaned[:pos].rstrip()
        if "finish(message" in cleaned.lower():
            pos = cleaned.lower().find("finish(message")
            cleaned = cleaned[:pos].rstrip()
        return cleaned
    
    def _process_next_chunk(self):
        """Process the next chunk from the stream."""
        if not self.is_processing or self.stream_exhausted:
            return
        
        try:
            # Get next chunk (this may block, but QTimer will allow event processing between calls)
            chunk = next(self.stream)
            
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    self.chunk_count += 1
                    content_chunk = delta.content
                    self.raw_content += content_chunk
                    
                    # Check if we've reached the action part
                    if not self.action_started:
                        # Check for action markers
                        marker_found = None
                        marker_pos = -1
                        
                        if "finish(message=" in self.raw_content and "finish(message=" not in self.last_raw_content:
                            marker_found = "finish(message="
                            marker_pos = self.raw_content.find("finish(message=")
                        elif "do(action=" in self.raw_content and "do(action=" not in self.last_raw_content:
                            marker_found = "do(action="
                            marker_pos = self.raw_content.find("do(action=")
                        
                        if marker_found:
                            # Extract thinking part before the marker
                            thinking_part = self.raw_content[:marker_pos].strip()
                            if len(thinking_part) > len(self.accumulated_thinking):
                                new_thinking = thinking_part[len(self.accumulated_thinking):]
                                if self.thinking_buffer:
                                    cleaned_buffer = self._clean_thinking(self.thinking_buffer)
                                    if cleaned_buffer:
                                        new_thinking = cleaned_buffer + new_thinking
                                    self.thinking_buffer = ""
                                new_thinking = self._clean_thinking(new_thinking)
                                if "do(action" in new_thinking.lower() or "finish(message" in new_thinking.lower():
                                    if "do(action" in new_thinking.lower():
                                        pos = new_thinking.lower().find("do(action")
                                        new_thinking = new_thinking[:pos].rstrip()
                                    if "finish(message" in new_thinking.lower():
                                        pos = new_thinking.lower().find("finish(message")
                                        new_thinking = new_thinking[:pos].rstrip()
                                if new_thinking and new_thinking.strip():
                                    if self.thinking_callback:
                                        self.thinking_callback(new_thinking)
                                    self.chunk_received.emit(new_thinking)
                                self.accumulated_thinking = thinking_part
                            self.action_started = True
                        else:
                            # Still in thinking part
                            self.accumulated_thinking += content_chunk
                            self.thinking_buffer += content_chunk
                            
                            # Send thinking chunks immediately
                            should_send = (
                                len(self.thinking_buffer) >= 3 or
                                '\n' in self.thinking_buffer or
                                any(c in self.thinking_buffer for c in ['。', '，', '！', '？', '.', ',', '!', '?', '：', ':', '；', ';', ' '])
                            )
                            
                            if should_send:
                                cleaned_chunk = self._clean_thinking(self.thinking_buffer)
                                if cleaned_chunk and self.thinking_callback:
                                    self.thinking_callback(cleaned_chunk)
                                if cleaned_chunk:
                                    self.chunk_received.emit(cleaned_chunk)
                                self.thinking_buffer = ""
                        
                        self.last_raw_content = self.raw_content
                        
        except StopIteration:
            # Stream exhausted
            self.stream_exhausted = True
            self.timer.stop()
            self._finalize_processing()
        except Exception as e:
            # Check if it's a StopIteration wrapped in another exception
            if "StopIteration" in str(type(e)) or isinstance(e, StopIteration):
                self.stream_exhausted = True
                self.timer.stop()
                self._finalize_processing()
                return
            # Error occurred
            self.timer.stop()
            self.is_processing = False
            self.processing_error.emit(str(e))
    
    def _finalize_processing(self):
        """Finalize processing after stream is exhausted."""
        try:
            # Send any remaining buffered thinking
            if self.thinking_buffer and not self.action_started and self.thinking_callback:
                cleaned_chunk = self._clean_thinking(self.thinking_buffer)
                if cleaned_chunk:
                    self.thinking_callback(cleaned_chunk)
                    self.chunk_received.emit(cleaned_chunk)
            
            # Parse final response
            from phone_agent.model.client import ModelClient, ModelResponse
            if self._model_client_instance:
                thinking, action = self._model_client_instance._parse_response(self.raw_content)
            else:
                # Fallback parsing
                if "finish(message=" in self.raw_content:
                    parts = self.raw_content.split("finish(message=", 1)
                    thinking = parts[0].strip()
                    action = "finish(message=" + parts[1]
                elif "do(action=" in self.raw_content:
                    parts = self.raw_content.split("do(action=", 1)
                    thinking = parts[0].strip()
                    action = "do(action=" + parts[1]
                else:
                    thinking = ""
                    action = self.raw_content
            
            response = ModelResponse(
                thinking=thinking,
                action=action,
                raw_content=self.raw_content
            )
            
            self._final_response = response
            self.is_processing = False
            self.processing_complete.emit(response)
            
        except Exception as e:
            self.is_processing = False
            self.processing_error.emit(f"Finalization error: {str(e)}")

