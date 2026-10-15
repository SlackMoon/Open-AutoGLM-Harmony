"""
Error Pattern Analyzer - 错误模式分析器

识别和分析任务执行中的错误模式，帮助 AI 避免重复犯错。
"""

import sqlite3
import json
from typing import List, Dict, Optional
from datetime import datetime
from collections import defaultdict
from threading import Lock


class ErrorPatternAnalyzer:
    """错误模式分析器"""

    def __init__(self, db_path: str):
        """
        初始化分析器
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._db_lock = Lock()
        self._ensure_tables()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        """确保数据库表存在"""
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # 创建错误模式表
            cur.execute("""
                CREATE TABLE IF NOT EXISTS error_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_pattern TEXT NOT NULL,
                    error_description TEXT NOT NULL,
                    correction TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    last_seen TEXT,
                    created_at TEXT
                )
            """)
            
            # 创建索引
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_patterns_pattern
                ON error_patterns(task_pattern)
            """)
            
            conn.commit()
            conn.close()

    def analyze_errors(self, task_pattern: str = None) -> List[Dict]:
        """
        分析特定任务的错误模式
        
        Args:
            task_pattern: 任务模式（可选，如果为 None 则分析所有任务）
            
        Returns:
            错误模式列表
        """
        # 1. 从数据库收集所有标记为 wrong 的步骤
        wrong_steps = self._collect_wrong_steps(task_pattern)
        
        if not wrong_steps:
            return []
        
        # 2. 按动作类型和错误描述分组
        grouped_errors = self._group_errors(wrong_steps)
        
        # 3. 统计频率并生成错误模式
        error_patterns = []
        for key, steps in grouped_errors.items():
            pattern = self._create_error_pattern(key, steps, task_pattern)
            if pattern:
                error_patterns.append(pattern)
        
        # 4. 保存到数据库
        for pattern in error_patterns:
            self._save_or_update_pattern(pattern)
        
        return error_patterns

    def get_patterns_for_task(self, task_pattern: str) -> List[Dict]:
        """
        获取特定任务的错误模式
        
        Args:
            task_pattern: 任务模式
            
        Returns:
            错误模式列表
        """
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT * FROM error_patterns
                WHERE task_pattern LIKE ?
                ORDER BY frequency DESC, last_seen DESC
            """, (f'%{task_pattern}%',))
            
            rows = cur.fetchall()
            conn.close()
            
            return [self._row_to_dict(row) for row in rows]

    def get_all_patterns(self) -> List[Dict]:
        """
        获取所有错误模式
        
        Returns:
            错误模式列表
        """
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT * FROM error_patterns
                ORDER BY frequency DESC, last_seen DESC
            """)
            
            rows = cur.fetchall()
            conn.close()
            
            return [self._row_to_dict(row) for row in rows]

    def generate_correction_hints(self, task_pattern: str) -> str:
        """
        生成纠正提示
        
        Args:
            task_pattern: 任务模式
            
        Returns:
            纠正提示文本
        """
        patterns = self.get_patterns_for_task(task_pattern)
        
        if not patterns:
            return ""
        
        hints = ["常见错误提示:\n"]
        for i, pattern in enumerate(patterns[:5], 1):  # 只显示前5个最常见的错误
            hints.append(
                f"{i}. 错误: {pattern['error_description']}\n"
                f"   纠正: {pattern['correction']}\n"
                f"   (出现 {pattern['frequency']} 次)\n"
            )
        
        return ''.join(hints)

    def delete_pattern(self, pattern_id: int) -> bool:
        """
        删除错误模式
        
        Args:
            pattern_id: 模式 ID
            
        Returns:
            是否删除成功
        """
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                DELETE FROM error_patterns WHERE id = ?
            """, (pattern_id,))
            
            success = cur.rowcount > 0
            conn.commit()
            conn.close()
            
            return success

    def get_statistics(self) -> Dict:
        """
        获取错误模式统计信息
        
        Returns:
            统计信息字典
        """
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # 总错误模式数
            cur.execute("SELECT COUNT(*) FROM error_patterns")
            total_patterns = cur.fetchone()[0]
            
            # 总错误频率
            cur.execute("SELECT SUM(frequency) FROM error_patterns")
            total_frequency = cur.fetchone()[0] or 0
            
            # 按任务模式分组统计
            cur.execute("""
                SELECT task_pattern, COUNT(*) as count, SUM(frequency) as total_freq
                FROM error_patterns
                GROUP BY task_pattern
                ORDER BY total_freq DESC
                LIMIT 10
            """)
            top_tasks = [
                {
                    'task_pattern': row[0],
                    'pattern_count': row[1],
                    'total_frequency': row[2]
                }
                for row in cur.fetchall()
            ]
            
            conn.close()
            
            return {
                'total_patterns': total_patterns,
                'total_frequency': total_frequency,
                'top_error_tasks': top_tasks
            }

    def _collect_wrong_steps(self, task_pattern: str = None) -> List[Dict]:
        """收集所有标记为 wrong 的步骤"""
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            if task_pattern:
                # 查询特定任务的错误步骤
                cur.execute("""
                    SELECT s.*, t.task_description
                    FROM steps s
                    JOIN tasks t ON s.session_id = t.session_id
                    WHERE s.user_label = 'wrong'
                    AND t.task_description LIKE ?
                """, (f'%{task_pattern}%',))
            else:
                # 查询所有错误步骤
                cur.execute("""
                    SELECT s.*, t.task_description
                    FROM steps s
                    JOIN tasks t ON s.session_id = t.session_id
                    WHERE s.user_label = 'wrong'
                """)
            
            rows = cur.fetchall()
            conn.close()
            
            return [dict(row) for row in rows]

    def _group_errors(self, wrong_steps: List[Dict]) -> Dict[str, List[Dict]]:
        """按动作类型和错误特征分组"""
        grouped = defaultdict(list)
        
        for step in wrong_steps:
            # 提取关键特征作为分组键
            action = step.get('action', '')
            thinking = step.get('thinking', '')
            correction = step.get('user_correction', '')
            
            # 简化的分组键：动作类型 + 纠正关键词
            key = self._extract_error_key(action, thinking, correction)
            grouped[key].append(step)
        
        return grouped

    def _extract_error_key(self, action: str, thinking: str, correction: str) -> str:
        """提取错误的关键特征作为分组键"""
        # 提取动作类型
        action_lower = action.lower()
        if 'tap' in action_lower or '点击' in action_lower:
            action_type = 'tap'
        elif 'type' in action_lower or '输入' in action_lower:
            action_type = 'type'
        elif 'swipe' in action_lower or '滑动' in action_lower:
            action_type = 'swipe'
        else:
            action_type = 'other'
        
        # 提取纠正中的关键词（前3个词）
        correction_words = correction.split()[:3]
        correction_key = '_'.join(correction_words) if correction_words else 'unknown'
        
        return f"{action_type}_{correction_key}"

    def _create_error_pattern(
        self,
        key: str,
        steps: List[Dict],
        task_pattern: str = None
    ) -> Optional[Dict]:
        """创建错误模式"""
        if not steps:
            return None
        
        # 使用第一个步骤的信息作为代表
        first_step = steps[0]
        
        # 提取错误描述（从 thinking 中）
        error_description = first_step.get('thinking', '')[:200]  # 限制长度
        
        # 提取纠正说明（使用最常见的纠正）
        corrections = [s.get('user_correction', '') for s in steps if s.get('user_correction')]
        correction = corrections[0] if corrections else ''
        
        # 如果没有提供 task_pattern，从步骤中获取
        if not task_pattern:
            task_pattern = first_step.get('task_description', 'unknown')
        
        return {
            'task_pattern': task_pattern,
            'error_description': error_description,
            'correction': correction,
            'frequency': len(steps),
            'last_seen': datetime.now().isoformat(),
            'created_at': datetime.now().isoformat()
        }

    def _save_or_update_pattern(self, pattern: Dict) -> None:
        """保存或更新错误模式"""
        with self._db_lock:
            conn = self._get_conn()
            cur = conn.cursor()
            
            # 检查是否已存在相似的错误模式
            cur.execute("""
                SELECT id, frequency FROM error_patterns
                WHERE task_pattern = ?
                AND error_description = ?
            """, (pattern['task_pattern'], pattern['error_description']))
            
            existing = cur.fetchone()
            
            if existing:
                # 更新频率
                new_frequency = existing[1] + pattern['frequency']
                cur.execute("""
                    UPDATE error_patterns
                    SET frequency = ?,
                        correction = ?,
                        last_seen = ?
                    WHERE id = ?
                """, (
                    new_frequency,
                    pattern['correction'],
                    pattern['last_seen'],
                    existing[0]
                ))
            else:
                # 插入新记录
                cur.execute("""
                    INSERT INTO error_patterns (
                        task_pattern, error_description, correction,
                        frequency, last_seen, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    pattern['task_pattern'],
                    pattern['error_description'],
                    pattern['correction'],
                    pattern['frequency'],
                    pattern['last_seen'],
                    pattern['created_at']
                ))
            
            conn.commit()
            conn.close()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """将数据库行转换为字典"""
        return {
            'id': row['id'],
            'task_pattern': row['task_pattern'],
            'error_description': row['error_description'],
            'correction': row['correction'],
            'frequency': row['frequency'],
            'last_seen': row['last_seen'],
            'created_at': row['created_at']
        }
