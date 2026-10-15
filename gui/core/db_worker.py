"""Database worker thread for non-blocking database operations."""

import logging
import queue
import threading
from typing import Any, Callable, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)


class DatabaseWorker(QObject):
    """Worker that processes database operations in a separate thread.
    
    This prevents database I/O from blocking the main UI thread.
    """
    
    # Signals
    operation_completed = pyqtSignal(str, bool, str)  # operation_id, success, error_msg
    
    def __init__(self):
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self):
        """Start the worker thread."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._process_queue, daemon=True)
        self._thread.start()
        logger.info("Database worker started")
    
    def stop(self):
        """Stop the worker thread."""
        self._running = False
        # Put a None to unblock the queue
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Database worker stopped")
    
    def submit(self, operation_id: str, func: Callable, *args, **kwargs):
        """Submit a database operation to be executed asynchronously.
        
        Args:
            operation_id: Unique identifier for this operation
            func: Function to execute
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func
        """
        self._queue.put((operation_id, func, args, kwargs))
    
    def _process_queue(self):
        """Process operations from the queue."""
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
                if item is None:
                    continue
                
                operation_id, func, args, kwargs = item
                
                try:
                    func(*args, **kwargs)
                    self.operation_completed.emit(operation_id, True, "")
                except Exception as e:
                    logger.error(f"Database operation {operation_id} failed: {e}")
                    self.operation_completed.emit(operation_id, False, str(e))
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in database worker: {e}")


class DatabaseWorkerThread(QThread):
    """QThread wrapper for DatabaseWorker."""
    
    operation_completed = pyqtSignal(str, bool, str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: queue.Queue = queue.Queue()
        self._running = False
    
    def run(self):
        """Thread main loop."""
        self._running = True
        logger.info("Database worker thread started")
        
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
                if item is None:
                    continue
                
                operation_id, func, args, kwargs = item
                
                try:
                    func(*args, **kwargs)
                    self.operation_completed.emit(operation_id, True, "")
                except Exception as e:
                    logger.error(f"Database operation {operation_id} failed: {e}")
                    self.operation_completed.emit(operation_id, False, str(e))
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in database worker thread: {e}")
        
        logger.info("Database worker thread stopped")
    
    def submit(self, operation_id: str, func: Callable, *args, **kwargs):
        """Submit a database operation."""
        self._queue.put((operation_id, func, args, kwargs))
    
    def stop(self):
        """Stop the worker thread."""
        self._running = False
        self._queue.put(None)
