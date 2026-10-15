"""
Experience Injector - 经验注入器

将历史错误经验（截图+纠正）注入到模型对话上下文中，
让模型"看到"之前的错误场景，形成视觉关联。

核心思路：
1. 匹配相似任务的黄金路径
2. 获取错误步骤的截图和纠正信息
3. 构建"错误示范"消息，包含截图
4. 注入到对话历史中，让模型学习
"""

import base64
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any


def _get_project_root() -> Path:
    """Get the project root directory (Open-AutoGLM-main/)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent.parent
    else:
        return Path(__file__).parent.parent.parent


@dataclass
class ErrorExample:
    """错误示例"""
    screenshot_path: str  # 错误发生时的截图路径
    screenshot_base64: Optional[str]  # 截图的 base64 编码
    wrong_action: Dict[str, Any]  # 错误的动作
    wrong_thinking: str  # 错误的思考过程
    correction: str  # 用户的纠正说明
    step_num: int  # 步骤编号


@dataclass
class GoldenPathExperience:
    """黄金路径经验"""
    task_pattern: str
    correct_steps: List[str]  # 正确步骤描述
    forbidden: List[str]  # 禁止操作
    hints: List[str]  # 关键提示
    error_examples: List[ErrorExample]  # 错误示例（带截图）


class ExperienceInjector:
    """经验注入器 - 将历史错误经验注入到模型上下文"""
    
    def __init__(self, db_path: str):
        """
        初始化
        
        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_error_examples(self, golden_path_id: int, max_examples: int = 3) -> List[ErrorExample]:
        """
        获取黄金路径关联的错误示例
        
        Args:
            golden_path_id: 黄金路径 ID
            max_examples: 最大示例数量
            
        Returns:
            错误示例列表
        """
        conn = self._get_conn()
        cur = conn.cursor()
        
        try:
            # 获取黄金路径的 source_sessions
            cur.execute("""
                SELECT source_sessions FROM golden_paths WHERE id = ?
            """, (golden_path_id,))
            row = cur.fetchone()
            
            if not row or not row['source_sessions']:
                return []
            
            source_sessions = json.loads(row['source_sessions'])
            if not source_sessions:
                return []
            
            # 从这些 session 中获取标注为 wrong 的步骤
            placeholders = ','.join(['?' for _ in source_sessions])
            cur.execute(f"""
                SELECT 
                    s.screenshot_path,
                    s.action,
                    s.thinking,
                    s.user_correction,
                    s.step_num,
                    s.session_id
                FROM steps s
                WHERE s.session_id IN ({placeholders})
                AND s.user_label = 'wrong'
                AND s.user_correction IS NOT NULL
                AND s.user_correction != ''
                ORDER BY s.id DESC
                LIMIT ?
            """, (*source_sessions, max_examples))
            
            rows = cur.fetchall()
            examples = []
            
            for row in rows:
                screenshot_base64 = None
                screenshot_path = row['screenshot_path']
                
                # 尝试读取截图文件 (转换相对路径为绝对路径)
                if screenshot_path:
                    abs_path = Path(screenshot_path)
                    if not abs_path.is_absolute():
                        abs_path = _get_project_root() / screenshot_path
                    
                    if abs_path.exists():
                        try:
                            with open(abs_path, 'rb') as f:
                                screenshot_base64 = base64.b64encode(f.read()).decode('utf-8')
                        except Exception as e:
                            print(f"读取截图失败: {e}")
                
                # 解析 action
                action = {}
                if row['action']:
                    try:
                        action = json.loads(row['action'])
                    except:
                        pass
                
                examples.append(ErrorExample(
                    screenshot_path=screenshot_path or "",
                    screenshot_base64=screenshot_base64,
                    wrong_action=action,
                    wrong_thinking=row['thinking'] or "",
                    correction=row['user_correction'] or "",
                    step_num=row['step_num']
                ))
            
            return examples
            
        finally:
            conn.close()
    
    def build_experience_messages(
        self, 
        golden_path: Dict[str, Any],
        include_screenshots: bool = True
    ) -> List[Dict[str, Any]]:
        """
        构建经验消息列表，用于注入到模型对话上下文
        
        Args:
            golden_path: 黄金路径数据
            include_screenshots: 是否包含截图
            
        Returns:
            消息列表，格式为 OpenAI 消息格式
        """
        messages = []
        
        # 获取错误示例
        path_id = golden_path.get('id')
        error_examples = self.get_error_examples(path_id) if path_id else []
        
        # 获取约束信息
        forbidden = golden_path.get('forbidden', [])
        hints = golden_path.get('hints', [])
        correct_path = golden_path.get('correct_path', [])
        
        # 如果有错误示例，构建"错误示范"消息
        if error_examples:
            for example in error_examples:
                # 构建用户消息（模拟之前的错误场景）
                user_content = []
                
                # 添加截图（如果有）
                if include_screenshots and example.screenshot_base64:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{example.screenshot_base64}"
                        }
                    })
                
                # 添加场景描述
                user_content.append({
                    "type": "text",
                    "text": f"[历史错误记录] 在执行类似任务时，你在这个界面做了错误的操作。"
                })
                
                messages.append({
                    "role": "user",
                    "content": user_content
                })
                
                # 构建助手消息（错误的响应）
                wrong_action_str = json.dumps(example.wrong_action, ensure_ascii=False)
                messages.append({
                    "role": "assistant",
                    "content": f"<think>{example.wrong_thinking[:200]}...</think><answer>{wrong_action_str}</answer>"
                })
                
                # 构建用户纠正消息
                messages.append({
                    "role": "user",
                    "content": f"❌ 错了！{example.correction}"
                })
                
                # 构建助手认错消息
                messages.append({
                    "role": "assistant",
                    "content": f"明白了，我记住了：{example.correction}。下次遇到类似界面时，我不会再犯同样的错误。"
                })
        
        # 如果没有错误示例但有约束信息，构建简化的经验消息
        elif forbidden or hints:
            experience_text = "📚 历史经验提醒：\n"
            
            if forbidden:
                experience_text += "\n⛔ 绝对禁止的操作：\n"
                for i, f in enumerate(forbidden, 1):
                    experience_text += f"  {i}. {f}\n"
            
            if hints:
                experience_text += "\n💡 关键提示：\n"
                for h in hints:
                    experience_text += f"  - {h}\n"
            
            if correct_path:
                experience_text += "\n✅ 正确步骤参考：\n"
                for step in correct_path[:5]:  # 最多显示5步
                    experience_text += f"  {step}\n"
            
            messages.append({
                "role": "user",
                "content": experience_text
            })
            
            messages.append({
                "role": "assistant",
                "content": "我已经仔细阅读了历史经验，会严格遵守这些约束，避免重复之前的错误。"
            })
        
        return messages
    
    def build_enhanced_task_prompt(
        self,
        task: str,
        golden_path: Dict[str, Any]
    ) -> str:
        """
        构建增强的任务提示词
        
        这是一个简化版本，直接把约束融入任务描述。
        用于不支持多轮对话注入的场景。
        
        Args:
            task: 原始任务描述
            golden_path: 黄金路径数据
            
        Returns:
            增强后的任务描述
        """
        forbidden = golden_path.get('forbidden', [])
        hints = golden_path.get('hints', [])
        common_errors = golden_path.get('common_errors', [])
        
        if not forbidden and not hints and not common_errors:
            return task
        
        # 构建约束列表
        constraints = []
        num = 1
        
        # 禁止操作
        if forbidden:
            for f in forbidden:
                constraints.append(f"{num}.禁止:{f}")
                num += 1
        elif common_errors:
            for error in common_errors[:3]:
                correction = error.get('correction', '')
                if correction:
                    constraints.append(f"{num}.禁止:{correction}")
                    num += 1
        
        # 提示信息
        if hints:
            for h in hints:
                h_clean = h.replace("位置提示: ", "").replace("判断条件: ", "")
                constraints.append(f"{num}.注意:{h_clean}")
                num += 1
        
        if constraints:
            return f"{task}。重要约束:{','.join(constraints)}"
        
        return task


class ExperienceAwareAgent:
    """
    经验感知代理 - 包装 PhoneAgent，注入历史经验
    
    使用方法：
    1. 创建 ExperienceAwareAgent
    2. 调用 prepare_context() 获取注入经验后的上下文
    3. 将上下文传递给 PhoneAgent
    """
    
    def __init__(self, db_path: str):
        self.injector = ExperienceInjector(db_path)
    
    def prepare_context(
        self,
        task: str,
        golden_path: Optional[Dict[str, Any]],
        system_prompt: str,
        include_screenshots: bool = True
    ) -> List[Dict[str, Any]]:
        """
        准备包含历史经验的对话上下文
        
        Args:
            task: 任务描述
            golden_path: 匹配到的黄金路径（可选）
            system_prompt: 系统提示词
            include_screenshots: 是否包含错误截图
            
        Returns:
            对话上下文消息列表
        """
        context = []
        
        # 1. 系统消息
        context.append({
            "role": "system",
            "content": system_prompt
        })
        
        # 2. 如果有黄金路径，注入历史经验
        if golden_path:
            experience_messages = self.injector.build_experience_messages(
                golden_path, 
                include_screenshots=include_screenshots
            )
            context.extend(experience_messages)
        
        # 注意：不在这里添加当前任务消息，由 PhoneAgent 处理
        
        return context
