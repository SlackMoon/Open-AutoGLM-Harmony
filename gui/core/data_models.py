"""Data models for task execution."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class TaskData:
    """Task-level data."""
    
    session_id: str
    user_id: str
    timestamp: str
    description: str
    device_id: Optional[str] = None
    base_url: Optional[str] = None
    model_name: Optional[str] = None
    
    @classmethod
    def create(cls, description: str, user_id: str = "default_user", 
               device_id: Optional[str] = None, base_url: Optional[str] = None,
               model_name: Optional[str] = None) -> 'TaskData':
        """Create a new TaskData instance with generated session_id and timestamp.
        
        Args:
            description: Task description
            user_id: User identifier
            device_id: Device identifier
            base_url: API base URL
            model_name: Model name
            
        Returns:
            New TaskData instance
        """
        import uuid
        return cls(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            timestamp=datetime.now().isoformat(),
            description=description,
            device_id=device_id,
            base_url=base_url,
            model_name=model_name,
        )


@dataclass
class StepData:
    """Step-level data."""
    
    session_id: str
    step_num: int
    screenshot_path: Optional[str] = None
    screenshot_analysis: Optional[str] = None
    action: Optional[Dict[str, Any]] = None
    action_params: Optional[Dict[str, Any]] = None
    execution_time: Optional[float] = None
    success: bool = True
    message: str = ""
    thinking: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.
        
        Returns:
            Dictionary representation
        """
        import json
        return {
            'session_id': self.session_id,
            'step_num': self.step_num,
            'screenshot_path': self.screenshot_path,
            'screenshot_analysis': self.screenshot_analysis,
            'action': json.dumps(self.action) if self.action else None,
            'action_params': json.dumps(self.action_params) if self.action_params else None,
            'execution_time': self.execution_time,
            'success': 1 if self.success else 0,
            'message': self.message,
            'thinking': self.thinking,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StepData':
        """Create from dictionary.
        
        Args:
            data: Dictionary with step data
            
        Returns:
            New StepData instance
        """
        import json
        return cls(
            session_id=data['session_id'],
            step_num=data['step_num'],
            screenshot_path=data.get('screenshot_path'),
            screenshot_analysis=data.get('screenshot_analysis'),
            action=json.loads(data['action']) if data.get('action') else None,
            action_params=json.loads(data['action_params']) if data.get('action_params') else None,
            execution_time=data.get('execution_time'),
            success=bool(data.get('success', True)),
            message=data.get('message', ''),
            thinking=data.get('thinking'),
        )
