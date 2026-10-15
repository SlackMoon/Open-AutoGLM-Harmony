"""Repository for task-level database operations."""

import logging
import sqlite3
import time
from typing import Optional, List

from gui.core.data_models import TaskData
from gui.core.task_state import TaskState
from .connection_pool import ConnectionPool

logger = logging.getLogger(__name__)


class TaskRepository:
    """Manages task-level database operations."""
    
    def __init__(self, connection_pool: ConnectionPool):
        """Initialize repository.
        
        Args:
            connection_pool: Database connection pool
        """
        self.pool = connection_pool
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure tasks table exists with correct schema."""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create tasks table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    session_id      TEXT PRIMARY KEY,
                    user_id         TEXT,
                    timestamp       TEXT,
                    task_description TEXT,
                    final_status    TEXT,
                    total_steps     INTEGER,
                    total_time      REAL,
                    error_message   TEXT,
                    device_id       TEXT,
                    base_url        TEXT,
                    model_name      TEXT,
                    updated_at      TEXT
                )
            """)
            
            # Add updated_at column if it doesn't exist
            try:
                cursor.execute("ALTER TABLE tasks ADD COLUMN updated_at TEXT")
                logger.info("Added updated_at column to tasks table")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            conn.commit()
    
    def create_task(self, task_data: TaskData) -> str:
        """Create a new task record (synchronous).
        
        Args:
            task_data: Task data to insert
            
        Returns:
            Session ID of created task
            
        Raises:
            RuntimeError: If task creation fails
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self.pool.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO tasks (
                            session_id, user_id, timestamp, task_description,
                            final_status, total_steps, total_time, error_message,
                            device_id, base_url, model_name, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        task_data.session_id,
                        task_data.user_id,
                        task_data.timestamp,
                        task_data.description,
                        TaskState.CREATED.value,
                        0,
                        None,
                        None,
                        task_data.device_id,
                        task_data.base_url,
                        task_data.model_name,
                    ))
                    conn.commit()
                    
                    logger.info(f"Created task record for session {task_data.session_id}")
                    return task_data.session_id
                    
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 0.1 * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to create task after {max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to create task: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected error creating task: {e}", exc_info=True)
                raise RuntimeError(f"Failed to create task: {e}") from e
        
        # Should not reach here, but just in case
        raise RuntimeError(f"Failed to create task: {last_error}")
    
    def update_task_state(self, session_id: str, state: TaskState):
        """Update task state (synchronous with retry).
        
        Args:
            session_id: Session identifier
            state: New task state
            
        Raises:
            ValueError: If task not found
            RuntimeError: If update fails after retries
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self.pool.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE tasks 
                        SET final_status = ?, 
                            updated_at = CURRENT_TIMESTAMP
                        WHERE session_id = ?
                    """, (state.value, session_id))
                    
                    if cursor.rowcount == 0:
                        raise ValueError(f"Task {session_id} not found")
                    
                    conn.commit()
                    
                    logger.info(f"Updated task {session_id} state to {state.value}")
                    return
                    
            except ValueError:
                raise  # Don't retry if task not found
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 0.1 * (2 ** attempt)
                    logger.warning(
                        f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to update task state after {max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to update task state: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected error updating task state: {e}", exc_info=True)
                raise RuntimeError(f"Failed to update task state: {e}") from e
        
        raise RuntimeError(f"Failed to update task state: {last_error}")
    
    def finalize_task(self, session_id: str, final_state: TaskState, 
                     total_steps: int, total_time: float, error_msg: Optional[str] = None):
        """Finalize task with complete information (synchronous).
        
        Args:
            session_id: Session identifier
            final_state: Final task state
            total_steps: Total number of steps executed
            total_time: Total execution time in seconds
            error_msg: Error message if task failed
            
        Raises:
            RuntimeError: If finalization fails
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self.pool.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE tasks 
                        SET final_status = ?,
                            total_steps = ?,
                            total_time = ?,
                            error_message = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE session_id = ?
                    """, (final_state.value, total_steps, total_time, error_msg, session_id))
                    
                    if cursor.rowcount == 0:
                        logger.warning(f"Task {session_id} not found during finalization")
                    
                    conn.commit()
                    
                    time_str = f"{total_time:.2f}s" if total_time is not None else "N/A"
                    logger.info(
                        f"Finalized task {session_id}: state={final_state.value}, "
                        f"steps={total_steps}, time={time_str}"
                    )
                    return
                    
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 0.1 * (2 ** attempt)
                    logger.warning(
                        f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to finalize task after {max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to finalize task: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected error finalizing task: {e}", exc_info=True)
                raise RuntimeError(f"Failed to finalize task: {e}") from e
        
        raise RuntimeError(f"Failed to finalize task: {last_error}")
    
    def find_tasks_by_states(self, states: List[TaskState]) -> List[dict]:
        """Find all tasks with given states.
        
        Args:
            states: List of states to search for
            
        Returns:
            List of task records as dictionaries
        """
        state_values = [state.value for state in states]
        placeholders = ','.join('?' * len(state_values))
        
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT session_id, user_id, timestamp, task_description,
                       final_status, total_steps, total_time, error_message,
                       device_id, base_url, model_name, updated_at
                FROM tasks
                WHERE final_status IN ({placeholders})
            """, state_values)
            
            columns = [desc[0] for desc in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            
            return results
