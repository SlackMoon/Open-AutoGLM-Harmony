"""Step buffer for reliable step data persistence.

Each step is written to database immediately when added.
This ensures data is not lost if the application crashes.
"""

import logging
import threading
from typing import List, Optional, Callable

from .data_models import StepData

logger = logging.getLogger(__name__)


class StepBuffer:
    """Buffers step data and ensures reliable persistence.
    
    Each step is written to database immediately when added.
    """
    
    def __init__(self, session_id: str, step_repository, backup_manager, 
                 max_size: int = 100, async_mode: bool = True):
        """Initialize step buffer.
        
        Args:
            session_id: Session identifier
            step_repository: StepRepository instance for database operations
            backup_manager: BackupManager instance for backup operations
            max_size: Maximum buffer size (for logging purposes)
            async_mode: Ignored - kept for API compatibility
        """
        self.session_id = session_id
        self.step_repo = step_repository
        self.backup_manager = backup_manager
        self.max_size = max_size
        self.buffer: List[StepData] = []
        self.lock = threading.Lock()
        
        # Callback for UI updates
        self._on_step_written: Optional[Callable[[int], None]] = None
        
        logger.info(f"StepBuffer initialized for session {session_id}")
    
    def set_on_step_written(self, callback: Callable[[int], None]):
        """Set callback for when a step is written to database.
        
        Args:
            callback: Function that takes step_num as argument
        """
        self._on_step_written = callback
    
    def add_step(self, step_data: StepData):
        """Add step to buffer and write to database immediately.
        
        Each step is written to database right away to prevent data loss
        if the application crashes.
        
        Args:
            step_data: Step data to add
        """
        with self.lock:
            # Add to buffer for tracking
            self.buffer.append(step_data)
            
            # Write to database immediately
            try:
                self.step_repo.insert_step(step_data)
                logger.debug(f"Wrote step {step_data.step_num} to database")
                
                # Notify callback
                if self._on_step_written:
                    try:
                        self._on_step_written(step_data.step_num)
                    except Exception as e:
                        logger.error(f"Error in step written callback: {e}")
                        
            except Exception as e:
                logger.error(f"Failed to write step {step_data.step_num}: {e}")
                # Save to backup
                try:
                    self.backup_manager.save_step_backup(
                        self.session_id,
                        step_data.to_dict()
                    )
                    logger.info(f"Saved step {step_data.step_num} to backup")
                except Exception as backup_error:
                    logger.error(f"Failed to save backup: {backup_error}")
    
    def flush(self):
        """Flush buffer - verify all steps are in database.
        
        Since steps are written immediately, this just verifies
        and retries any failed writes.
        """
        with self.lock:
            if not self.buffer:
                logger.debug(f"Buffer empty for session {self.session_id}")
                return
            
            # Verify all steps exist in database
            missing_steps = []
            for step in self.buffer:
                if not self.step_repo.step_exists(self.session_id, step.step_num):
                    missing_steps.append(step)
            
            # Retry writing missing steps
            if missing_steps:
                logger.warning(f"Found {len(missing_steps)} missing steps, retrying")
                for step in missing_steps:
                    try:
                        self.step_repo.insert_step(step)
                        logger.debug(f"Wrote missing step {step.step_num}")
                    except Exception as e:
                        logger.error(f"Failed to write missing step {step.step_num}: {e}")
            
            # Clear buffer
            self.buffer.clear()
            logger.debug(f"Buffer flushed for session {self.session_id}")
    
    def close(self):
        """Close the buffer."""
        logger.debug(f"StepBuffer closed for session {self.session_id}")
    

    
    def get_buffer_size(self) -> int:
        """Get current buffer size.
        
        Returns:
            Number of steps in buffer
        """
        with self.lock:
            return len(self.buffer)
    
    def get_buffered_steps(self) -> List[StepData]:
        """Get copy of buffered steps.
        
        Returns:
            List of step data
        """
        with self.lock:
            return self.buffer.copy()
