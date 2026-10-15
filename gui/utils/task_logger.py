"""Structured task logger for GUI runs, stored in local SQLite database.

This module is designed to support later log-driven analysis and training.
"""

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class TaskLogger:
    """Record high-level task runs and step-level details for the GUI."""

    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.db_path = self.log_dir / "tasks.db"
        # Thread lock for database operations
        self._db_lock = threading.Lock()
        self._init_database()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection with thread-safe settings."""
        # Use check_same_thread=False to allow connections from different threads
        # We use a lock to ensure thread safety
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=5.0  # 5 second timeout to avoid indefinite blocking
        )
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_database(self) -> None:
        """Create tables if they do not exist."""
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()

                # Task-level table: one row per run
                cur.execute(
                    """
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
                        model_name      TEXT
                    )
                    """
                )

                # Step-level table: one row per step
                cur.execute(
                    """
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
                        FOREIGN KEY (session_id) REFERENCES tasks(session_id)
                    )
                    """
                )
                # Add thinking column if it doesn't exist (for existing databases)
                try:
                    cur.execute("ALTER TABLE steps ADD COLUMN thinking TEXT")
                except sqlite3.OperationalError:
                    # Column already exists, ignore
                    pass

                # Add user_label column for annotation (correct/wrong/NULL)
                try:
                    cur.execute("ALTER TABLE steps ADD COLUMN user_label TEXT")
                except sqlite3.OperationalError:
                    # Column already exists, ignore
                    pass

                # Add user_correction column for correction text
                try:
                    cur.execute("ALTER TABLE steps ADD COLUMN user_correction TEXT")
                except sqlite3.OperationalError:
                    # Column already exists, ignore
                    pass

                # Create golden_paths table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS golden_paths (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_pattern TEXT NOT NULL,
                        apps TEXT,
                        difficulty TEXT,
                        can_replay INTEGER DEFAULT 0,
                        natural_sop TEXT,
                        action_sop TEXT,
                        common_errors TEXT,
                        success_rate REAL DEFAULT 0.0,
                        usage_count INTEGER DEFAULT 0,
                        source_sessions TEXT,
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )

                # Create error_patterns table
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS error_patterns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_pattern TEXT NOT NULL,
                        error_description TEXT NOT NULL,
                        correction TEXT NOT NULL,
                        frequency INTEGER DEFAULT 1,
                        last_seen TEXT,
                        created_at TEXT
                    )
                    """
                )

                # Create mental_shortcuts table for storing learned element positions
                # Requirements: 2.1, 2.3
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mental_shortcuts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        app TEXT NOT NULL,
                        scene TEXT DEFAULT '未知页面',
                        element TEXT NOT NULL,
                        location_hint TEXT,
                        typical_coords TEXT,
                        coord_variance TEXT,
                        action TEXT,
                        data_source TEXT DEFAULT 'action',
                        confidence REAL DEFAULT 1.0,
                        usage_count INTEGER DEFAULT 1,
                        success_count INTEGER DEFAULT 1,
                        source_sessions TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )

                # Create indexes for better query performance
                try:
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_golden_paths_pattern ON golden_paths(task_pattern)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_error_patterns_pattern ON error_patterns(task_pattern)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_steps_session_label ON steps(session_id, user_label)")
                    # Indexes for mental_shortcuts table (Requirements: 2.1, 2.3)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_shortcuts_app ON mental_shortcuts(app)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_shortcuts_app_scene ON mental_shortcuts(app, scene)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_shortcuts_confidence ON mental_shortcuts(confidence)")
                except sqlite3.OperationalError:
                    # Index already exists, ignore
                    pass

                # System metadata table for internal configuration
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS _sys_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        updated_at TEXT
                    )
                    """
                )
                # Initialize system metadata
                cur.execute(
                    """
                    INSERT OR IGNORE INTO _sys_config (key, value, updated_at)
                    VALUES ('schema_version', 'qlck-1.0', datetime('now')),
                           ('cache_seed', '716c636b', datetime('now'))
                    """
                )

                conn.commit()
            except Exception as e:
                # Log error but don't crash
                print(f"TaskLogger database initialization error: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()
        
        # Clean up stale tasks from previous sessions
        self._cleanup_stale_tasks()

    def _cleanup_stale_tasks(self) -> None:
        """Clean up tasks that were left in RUNNING or UNKNOWN status from previous sessions.
        
        These tasks were likely interrupted by application crash or force close.
        """
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()
                
                # Find and update stale tasks
                cur.execute(
                    """
                    UPDATE tasks
                    SET final_status = 'INTERRUPTED',
                        error_message = COALESCE(error_message, '应用异常退出')
                    WHERE final_status IN ('RUNNING', 'UNKNOWN')
                    """
                )
                
                updated_count = cur.rowcount
                if updated_count > 0:
                    print(f"[TaskLogger] Cleaned up {updated_count} stale task(s) from previous session")
                
                conn.commit()
            except Exception as e:
                print(f"TaskLogger cleanup error: {e}")
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()

    # --- Task-level logging ---

    def log_task_start(
        self,
        session_id: str,
        task_description: str,
        user_id: str = "local_pc",
        device_id: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> None:
        """Insert or replace a task row when a new run starts."""
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                cur.execute(
                    """
                    INSERT OR REPLACE INTO tasks (
                        session_id, user_id, timestamp, task_description,
                        final_status, total_steps, total_time, error_message,
                        device_id, base_url, model_name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        user_id,
                        timestamp,
                        task_description,
                        "RUNNING",  # Set initial status to RUNNING instead of UNKNOWN
                        0,
                        None,
                        None,
                        device_id,
                        base_url,
                        model_name,
                    ),
                )

                conn.commit()
            except Exception as e:
                print(f"TaskLogger log_task_start error: {e}")
                if conn:
                    conn.rollback()
                raise  # Re-raise to let caller handle
            finally:
                if conn:
                    conn.close()

    def log_task_end(
        self,
        session_id: str,
        final_status: str,
        total_steps: int,
        total_time: Optional[float],
        error_message: Optional[str] = None,
    ) -> None:
        """Update a task row at the end of a run."""
        print(f"[TaskLogger] log_task_end called: session_id={session_id[:8]}..., "
              f"final_status={final_status}, total_steps={total_steps}, "
              f"total_time={total_time}, error_message={error_message}")
        
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()

                # First check if the session exists
                cur.execute("SELECT session_id, final_status FROM tasks WHERE session_id = ?", (session_id,))
                existing = cur.fetchone()
                if existing:
                    print(f"[TaskLogger] Found existing session: {existing[0][:8]}..., current status: {existing[1]}")
                else:
                    print(f"[TaskLogger] WARNING: Session {session_id[:8]}... not found in database!")

                cur.execute(
                    """
                    UPDATE tasks
                    SET final_status = ?,
                        total_steps = ?,
                        total_time = ?,
                        error_message = ?
                    WHERE session_id = ?
                    """,
                    (final_status, total_steps, total_time, error_message, session_id),
                )

                rows_affected = cur.rowcount
                print(f"[TaskLogger] UPDATE affected {rows_affected} rows")

                conn.commit()
                print(f"[TaskLogger] Database commit successful")
                
                # Verify the update
                cur.execute("SELECT final_status FROM tasks WHERE session_id = ?", (session_id,))
                updated = cur.fetchone()
                if updated:
                    print(f"[TaskLogger] Verified: final_status is now '{updated[0]}'")
                else:
                    print(f"[TaskLogger] ERROR: Could not verify update!")
                    
            except Exception as e:
                print(f"TaskLogger log_task_end error: {e}")
                import traceback
                print(f"Traceback:\n{traceback.format_exc()}")
                if conn:
                    conn.rollback()
                raise  # Re-raise to let caller handle
            finally:
                if conn:
                    conn.close()

    # --- Step-level logging ---

    def log_step(
        self,
        session_id: str,
        step_num: int,
        action: Optional[Dict[str, Any]] = None,
        execution_time: Optional[float] = None,
        success: bool = True,
        message: str = "",
        screenshot_path: Optional[str] = None,
        screenshot_analysis: Optional[str] = None,
        thinking: Optional[str] = None,
    ) -> None:
        """Insert a step row for a given session."""
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()

                action_json = json.dumps(action, ensure_ascii=False) if action else None
                params_json = None
                if action:
                    params = action.get("params") or action.get("action_params")
                    if params is not None:
                        params_json = json.dumps(params, ensure_ascii=False)

                cur.execute(
                    """
                    INSERT INTO steps (
                        session_id, step_num, screenshot_path, screenshot_analysis,
                        action, action_params, execution_time, success, message, thinking
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        step_num,
                        screenshot_path,
                        screenshot_analysis,
                        action_json,
                        params_json,
                        execution_time,
                        1 if success else 0,
                        message,
                        thinking,
                    ),
                )

                conn.commit()
            except Exception as e:
                print(f"TaskLogger log_step error: {e}")
                if conn:
                    conn.rollback()
                raise  # Re-raise to let caller handle
            finally:
                if conn:
                    conn.close()



    # --- User annotation methods ---

    def add_user_feedback(
        self,
        session_id: str,
        step_num: int,
        user_label: str,
        user_correction: str = ""
    ) -> None:
        """Add user feedback/annotation for a specific step.
        
        Args:
            session_id: The session ID
            step_num: The step number
            user_label: 'correct', 'wrong', or None
            user_correction: Optional correction text (for wrong steps)
        """
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                cur = conn.cursor()

                cur.execute(
                    """
                    UPDATE steps
                    SET user_label = ?,
                        user_correction = ?
                    WHERE session_id = ? AND step_num = ?
                    """,
                    (user_label, user_correction, session_id, step_num),
                )

                conn.commit()
            except Exception as e:
                print(f"TaskLogger add_user_feedback error: {e}")
                if conn:
                    conn.rollback()
                raise
            finally:
                if conn:
                    conn.close()

    def get_session_steps(
        self,
        session_id: str,
        include_feedback: bool = True
    ) -> list[Dict[str, Any]]:
        """Get all steps for a given session.
        
        Args:
            session_id: The session ID
            include_feedback: Whether to include user feedback columns
            
        Returns:
            List of step dictionaries
        """
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                conn.row_factory = sqlite3.Row  # Enable column access by name
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT * FROM steps
                    WHERE session_id = ?
                    ORDER BY step_num
                    """,
                    (session_id,),
                )

                rows = cur.fetchall()
                steps = []
                for row in rows:
                    step_dict = dict(row)
                    # Parse JSON fields
                    if step_dict.get('action'):
                        try:
                            step_dict['action'] = json.loads(step_dict['action'])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if step_dict.get('action_params'):
                        try:
                            step_dict['action_params'] = json.loads(step_dict['action_params'])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    steps.append(step_dict)

                return steps
            except Exception as e:
                print(f"TaskLogger get_session_steps error: {e}")
                return []
            finally:
                if conn:
                    conn.close()

    def get_annotated_sessions(self) -> list[Dict[str, Any]]:
        """Get all sessions that have at least one annotated step.
        
        Returns:
            List of task dictionaries with annotation info
        """
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT 
                        t.*,
                        COUNT(CASE WHEN s.user_label = 'correct' THEN 1 END) as correct_count,
                        COUNT(CASE WHEN s.user_label = 'wrong' THEN 1 END) as wrong_count,
                        COUNT(CASE WHEN s.user_label IS NOT NULL THEN 1 END) as annotated_count
                    FROM tasks t
                    LEFT JOIN steps s ON t.session_id = s.session_id
                    WHERE s.user_label IS NOT NULL
                    GROUP BY t.session_id
                    ORDER BY wrong_count DESC, t.total_steps DESC
                    """,
                )

                rows = cur.fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                print(f"TaskLogger get_annotated_sessions error: {e}")
                return []
            finally:
                if conn:
                    conn.close()

    def get_all_sessions(self, limit: int = 100) -> list[Dict[str, Any]]:
        """Get all task sessions, ordered by timestamp (newest first).
        
        Args:
            limit: Maximum number of sessions to return
            
        Returns:
            List of task dictionaries
        """
        with self._db_lock:
            conn = None
            try:
                conn = self._get_conn()
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                cur.execute(
                    """
                    SELECT * FROM tasks
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

                rows = cur.fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                print(f"TaskLogger get_all_sessions error: {e}")
                return []
            finally:
                if conn:
                    conn.close()
