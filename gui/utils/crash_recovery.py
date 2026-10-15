"""Crash recovery utilities for handling system crashes."""

import logging
from typing import List, Dict, Any

from gui.core.task_state import TaskState
from gui.core.data_models import StepData
from gui.persistence import TaskRepository, StepRepository, BackupManager

logger = logging.getLogger(__name__)


def recover_crashed_tasks(task_repo: TaskRepository, step_repo: StepRepository, 
                          backup_manager: BackupManager) -> List[Dict[str, Any]]:
    """Recover tasks that were running when system crashed.
    
    This function:
    1. Finds all tasks in RUNNING or STOPPING state
    2. Marks them as CRASHED
    3. Attempts to recover missing steps from backup files
    
    Args:
        task_repo: Task repository
        step_repo: Step repository
        backup_manager: Backup manager
        
    Returns:
        List of recovered task information
    """
    logger.info("Starting crash recovery process")
    
    recovered_tasks = []
    
    try:
        # 1. Find all tasks that were running or stopping
        crashed_tasks = task_repo.find_tasks_by_states([
            TaskState.RUNNING,
            TaskState.STOPPING,
        ])
        
        if not crashed_tasks:
            logger.info("No crashed tasks found")
            return recovered_tasks
        
        logger.info(f"Found {len(crashed_tasks)} crashed tasks")
        
        # 2. Process each crashed task
        for task in crashed_tasks:
            session_id = task['session_id']
            logger.info(f"Recovering crashed task: {session_id}")
            
            try:
                # Mark task as CRASHED
                task_repo.update_task_state(session_id, TaskState.CRASHED)
                
                # Try to recover from backup
                task_data, steps_data = backup_manager.recover_from_backup(session_id)
                
                recovered_steps = 0
                if steps_data:
                    # Check which steps are missing from database
                    for step_dict in steps_data:
                        step_num = step_dict.get('step_num')
                        if step_num is None:
                            continue
                        
                        # Only insert if step doesn't exist
                        if not step_repo.step_exists(session_id, step_num):
                            try:
                                step_data = StepData.from_dict(step_dict)
                                step_repo.insert_step(step_data)
                                recovered_steps += 1
                                logger.debug(f"Recovered step {step_num} for task {session_id}")
                            except Exception as e:
                                logger.error(
                                    f"Failed to recover step {step_num} for task {session_id}: {e}"
                                )
                
                # Get final step count from database
                all_steps = step_repo.get_steps_for_session(session_id)
                total_steps = len(all_steps)
                
                # Update task with final step count
                if total_steps > 0:
                    task_repo.finalize_task(
                        session_id,
                        TaskState.CRASHED,
                        total_steps,
                        task.get('total_time', 0),
                        "System crashed during execution"
                    )
                
                # Clean up backup files
                backup_manager.cleanup_backup(session_id)
                
                recovered_tasks.append({
                    'session_id': session_id,
                    'description': task.get('task_description', ''),
                    'recovered_steps': recovered_steps,
                    'total_steps': total_steps,
                })
                
                logger.info(
                    f"Recovered task {session_id}: "
                    f"recovered {recovered_steps} steps, total {total_steps} steps"
                )
                
            except Exception as e:
                logger.error(f"Error recovering task {session_id}: {e}", exc_info=True)
                # Continue with other tasks
        
        logger.info(f"Crash recovery complete: recovered {len(recovered_tasks)} tasks")
        
    except Exception as e:
        logger.error(f"Error during crash recovery: {e}", exc_info=True)
    
    return recovered_tasks


def check_for_orphaned_backups(backup_manager: BackupManager, 
                               task_repo: TaskRepository) -> List[str]:
    """Check for backup files without corresponding database entries.
    
    This can happen if the database was corrupted or deleted.
    
    Args:
        backup_manager: Backup manager
        task_repo: Task repository
        
    Returns:
        List of orphaned session IDs
    """
    logger.info("Checking for orphaned backup files")
    
    orphaned = []
    
    try:
        # Get all sessions with backups
        backup_sessions = backup_manager.list_backup_sessions()
        
        if not backup_sessions:
            logger.info("No backup files found")
            return orphaned
        
        logger.info(f"Found {len(backup_sessions)} backup sessions")
        
        # Check each session
        for session_id in backup_sessions:
            # Try to find task in database
            tasks = task_repo.find_tasks_by_states([
                TaskState.CREATED,
                TaskState.RUNNING,
                TaskState.STOPPING,
                TaskState.STOPPED,
                TaskState.SUCCESS,
                TaskState.FAILED,
                TaskState.CRASHED,
            ])
            
            # Check if session exists in database
            session_exists = any(task['session_id'] == session_id for task in tasks)
            
            if not session_exists:
                orphaned.append(session_id)
                logger.warning(f"Found orphaned backup for session {session_id}")
        
        if orphaned:
            logger.info(f"Found {len(orphaned)} orphaned backup files")
        else:
            logger.info("No orphaned backup files found")
        
    except Exception as e:
        logger.error(f"Error checking for orphaned backups: {e}", exc_info=True)
    
    return orphaned


def restore_from_orphaned_backup(session_id: str, backup_manager: BackupManager,
                                task_repo: TaskRepository, 
                                step_repo: StepRepository) -> bool:
    """Restore a task from an orphaned backup.
    
    Args:
        session_id: Session identifier
        backup_manager: Backup manager
        task_repo: Task repository
        step_repo: Step repository
        
    Returns:
        True if restoration successful
    """
    logger.info(f"Attempting to restore task {session_id} from orphaned backup")
    
    try:
        # Recover data from backup
        task_data, steps_data = backup_manager.recover_from_backup(session_id)
        
        if not task_data:
            logger.error(f"No task data found in backup for {session_id}")
            return False
        
        # Create task record
        from gui.core.data_models import TaskData
        task = TaskData(
            session_id=task_data['session_id'],
            user_id=task_data.get('user_id', 'unknown'),
            timestamp=task_data.get('timestamp', ''),
            description=task_data.get('description', ''),
            device_id=task_data.get('device_id'),
            base_url=task_data.get('base_url'),
            model_name=task_data.get('model_name'),
        )
        
        task_repo.create_task(task)
        logger.info(f"Created task record for {session_id}")
        
        # Insert steps
        if steps_data:
            for step_dict in steps_data:
                try:
                    step_data = StepData.from_dict(step_dict)
                    step_repo.insert_step(step_data)
                except Exception as e:
                    logger.error(f"Failed to insert step: {e}")
            
            logger.info(f"Inserted {len(steps_data)} steps for {session_id}")
        
        # Mark as CRASHED
        task_repo.update_task_state(session_id, TaskState.CRASHED)
        task_repo.finalize_task(
            session_id,
            TaskState.CRASHED,
            len(steps_data),
            0,
            "Restored from orphaned backup"
        )
        
        # Clean up backup
        backup_manager.cleanup_backup(session_id)
        
        logger.info(f"Successfully restored task {session_id} from orphaned backup")
        return True
        
    except Exception as e:
        logger.error(f"Error restoring from orphaned backup: {e}", exc_info=True)
        return False
