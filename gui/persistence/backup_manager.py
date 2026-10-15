"""Backup manager for crash recovery and data safety."""

import json
import logging
from pathlib import Path
from typing import Tuple, List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages backup files for crash recovery."""
    
    def __init__(self, backup_dir: str = "logs/backup"):
        """Initialize backup manager.
        
        Args:
            backup_dir: Directory for backup files
        """
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"BackupManager initialized with directory: {self.backup_dir}")
    
    def save_task_backup(self, session_id: str, task_data: Dict[str, Any]):
        """Save task data to backup file.
        
        Args:
            session_id: Session identifier
            task_data: Task data dictionary
        """
        try:
            backup_file = self.backup_dir / f"{session_id}_task.json"
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Saved task backup for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to save task backup for {session_id}: {e}", exc_info=True)
    
    def save_step_backup(self, session_id: str, step_data: Dict[str, Any]):
        """Save step data to backup file (append mode).
        
        Args:
            session_id: Session identifier
            step_data: Step data dictionary
        """
        try:
            backup_file = self.backup_dir / f"{session_id}_steps.jsonl"
            with open(backup_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(step_data, ensure_ascii=False) + '\n')
            
            logger.debug(f"Saved step backup for session {session_id}, step {step_data.get('step_num')}")
        except Exception as e:
            logger.error(f"Failed to save step backup for {session_id}: {e}", exc_info=True)
    
    def recover_from_backup(self, session_id: str) -> Tuple[Optional[Dict], List[Dict]]:
        """Recover data from backup files.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Tuple of (task_data, list of step_data)
        """
        task_data = None
        steps_data = []
        
        # Recover task data
        task_file = self.backup_dir / f"{session_id}_task.json"
        if task_file.exists():
            try:
                with open(task_file, 'r', encoding='utf-8') as f:
                    task_data = json.load(f)
                logger.info(f"Recovered task data from backup for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to recover task backup for {session_id}: {e}", exc_info=True)
        
        # Recover steps data
        steps_file = self.backup_dir / f"{session_id}_steps.jsonl"
        if steps_file.exists():
            try:
                with open(steps_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            steps_data.append(json.loads(line))
                logger.info(f"Recovered {len(steps_data)} steps from backup for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to recover steps backup for {session_id}: {e}", exc_info=True)
        
        return task_data, steps_data
    
    def cleanup_backup(self, session_id: str):
        """Delete backup files for a session.
        
        Args:
            session_id: Session identifier
        """
        task_file = self.backup_dir / f"{session_id}_task.json"
        steps_file = self.backup_dir / f"{session_id}_steps.jsonl"
        
        deleted = []
        
        if task_file.exists():
            try:
                task_file.unlink()
                deleted.append("task")
            except Exception as e:
                logger.error(f"Failed to delete task backup for {session_id}: {e}")
        
        if steps_file.exists():
            try:
                steps_file.unlink()
                deleted.append("steps")
            except Exception as e:
                logger.error(f"Failed to delete steps backup for {session_id}: {e}")
        
        if deleted:
            logger.info(f"Cleaned up backup files for session {session_id}: {', '.join(deleted)}")
    
    def list_backup_sessions(self) -> List[str]:
        """List all sessions with backup files.
        
        Returns:
            List of session IDs
        """
        sessions = set()
        
        for file in self.backup_dir.glob("*_task.json"):
            session_id = file.stem.replace("_task", "")
            sessions.add(session_id)
        
        for file in self.backup_dir.glob("*_steps.jsonl"):
            session_id = file.stem.replace("_steps", "")
            sessions.add(session_id)
        
        return sorted(sessions)
    
    def has_backup(self, session_id: str) -> bool:
        """Check if backup exists for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if backup exists
        """
        task_file = self.backup_dir / f"{session_id}_task.json"
        steps_file = self.backup_dir / f"{session_id}_steps.jsonl"
        
        return task_file.exists() or steps_file.exists()
