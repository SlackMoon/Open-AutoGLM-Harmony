"""Repository for step-level database operations."""

import logging
import sqlite3
import time
from typing import List

from gui.core.data_models import StepData
from .connection_pool import ConnectionPool

logger = logging.getLogger(__name__)


class StepRepository:
    """Manages step-level database operations."""
    
    def __init__(self, connection_pool: ConnectionPool):
        """Initialize repository.
        
        Args:
            connection_pool: Database connection pool
        """
        self.pool = connection_pool
        self._ensure_schema()
    
    def _ensure_schema(self):
        """Ensure steps table exists with correct schema."""
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create steps table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS steps (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id          TEXT,
                    step_num            INTEGER,
                    screenshot_path     TEXT,
                    screenshot_analysis TEXT,
                    action              TEXT,
                    action_params       TEXT,
                    execution_time      REAL,
                    success             INTEGER,
                    message             TEXT,
                    thinking            TEXT,
                    user_label          TEXT,
                    user_correction     TEXT,
                    FOREIGN KEY (session_id) REFERENCES tasks(session_id)
                )
            """)
            
            # Add columns if they don't exist
            columns_to_add = [
                ("thinking", "TEXT"),
                ("user_label", "TEXT"),
                ("user_correction", "TEXT"),
            ]
            
            for column_name, column_type in columns_to_add:
                try:
                    cursor.execute(f"ALTER TABLE steps ADD COLUMN {column_name} {column_type}")
                    logger.info(f"Added {column_name} column to steps table")
                except sqlite3.OperationalError:
                    pass  # Column already exists
            
            # Create index for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_steps_session 
                ON steps(session_id, step_num)
            """)
            
            conn.commit()
    
    def insert_step(self, step_data: StepData):
        """Insert a step record (synchronous with retry).
        
        Args:
            step_data: Step data to insert
            
        Raises:
            RuntimeError: If insert fails after retries
        """
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self.pool.get_connection() as conn:
                    cursor = conn.cursor()
                    step_dict = step_data.to_dict()
                    
                    cursor.execute("""
                        INSERT INTO steps (
                            session_id, step_num, screenshot_path, screenshot_analysis,
                            action, action_params, execution_time, success, message, thinking
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        step_dict['session_id'],
                        step_dict['step_num'],
                        step_dict['screenshot_path'],
                        step_dict['screenshot_analysis'],
                        step_dict['action'],
                        step_dict['action_params'],
                        step_dict['execution_time'],
                        step_dict['success'],
                        step_dict['message'],
                        step_dict['thinking'],
                    ))
                    conn.commit()
                    
                    logger.debug(
                        f"Inserted step {step_data.step_num} for session {step_data.session_id}"
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
                    logger.error(f"Failed to insert step after {max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to insert step: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected error inserting step: {e}", exc_info=True)
                raise RuntimeError(f"Failed to insert step: {e}") from e
        
        raise RuntimeError(f"Failed to insert step: {last_error}")
    
    def batch_insert_steps(self, steps: List[StepData]):
        """Batch insert multiple steps (transactional).
        
        Args:
            steps: List of step data to insert
            
        Raises:
            RuntimeError: If batch insert fails
        """
        if not steps:
            return
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                with self.pool.get_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Begin transaction
                    conn.execute("BEGIN TRANSACTION")
                    
                    try:
                        for step_data in steps:
                            step_dict = step_data.to_dict()
                            cursor.execute("""
                                INSERT INTO steps (
                                    session_id, step_num, screenshot_path, screenshot_analysis,
                                    action, action_params, execution_time, success, message, thinking
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                step_dict['session_id'],
                                step_dict['step_num'],
                                step_dict['screenshot_path'],
                                step_dict['screenshot_analysis'],
                                step_dict['action'],
                                step_dict['action_params'],
                                step_dict['execution_time'],
                                step_dict['success'],
                                step_dict['message'],
                                step_dict['thinking'],
                            ))
                        
                        conn.commit()
                        logger.info(f"Batch inserted {len(steps)} steps")
                        return
                        
                    except Exception as e:
                        conn.rollback()
                        raise
                    
            except sqlite3.OperationalError as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 0.1 * (2 ** attempt)
                    logger.warning(
                        f"Database locked, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to batch insert steps after {max_retries} attempts: {e}")
                    raise RuntimeError(f"Failed to batch insert steps: {e}") from e
            except Exception as e:
                logger.error(f"Unexpected error batch inserting steps: {e}", exc_info=True)
                raise RuntimeError(f"Failed to batch insert steps: {e}") from e
        
        raise RuntimeError(f"Failed to batch insert steps: {last_error}")
    
    def step_exists(self, session_id: str, step_num: int) -> bool:
        """Check if a step exists in the database.
        
        Args:
            session_id: Session identifier
            step_num: Step number
            
        Returns:
            True if step exists
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM steps 
                WHERE session_id = ? AND step_num = ?
            """, (session_id, step_num))
            
            return cursor.fetchone() is not None
    
    def get_steps_for_session(self, session_id: str) -> List[StepData]:
        """Get all steps for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of step data
        """
        with self.pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id, step_num, screenshot_path, screenshot_analysis,
                       action, action_params, execution_time, success, message, thinking
                FROM steps
                WHERE session_id = ?
                ORDER BY step_num
            """, (session_id,))
            
            steps = []
            for row in cursor.fetchall():
                step_dict = {
                    'session_id': row[0],
                    'step_num': row[1],
                    'screenshot_path': row[2],
                    'screenshot_analysis': row[3],
                    'action': row[4],
                    'action_params': row[5],
                    'execution_time': row[6],
                    'success': row[7],
                    'message': row[8],
                    'thinking': row[9],
                }
                steps.append(StepData.from_dict(step_dict))
            
            return steps
