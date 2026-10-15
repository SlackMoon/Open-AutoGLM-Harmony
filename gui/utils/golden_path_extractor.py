"""
Golden Path Extractor - 从标注数据中提取黄金路径

优化版本：提取精简的约束信息，而不是保存完整的日志。

新格式：
- correct_path: 正确的执行步骤（从 label=correct 的步骤提取）
- forbidden: 禁止的操作（从 label=wrong 的 correction 提取）
- hints: 关键提示信息（从 correction 中提取有用信息）
"""

import json
import re
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict, field
from datetime import datetime


@dataclass
class GoldenPath:
    """黄金路径数据类 - 优化版"""
    task_pattern: str
    apps: List[str]
    difficulty: str  # 'simple' | 'medium' | 'complex'
    can_replay: bool
    
    # 新格式：精简的约束信息
    correct_path: List[str]  # 正确的执行步骤
    forbidden: List[str]  # 禁止的操作
    hints: List[str]  # 关键提示
    
    # 保留旧字段以兼容
    natural_sop: str = ""  # 保留但简化
    action_sop: List[Dict] = field(default_factory=list)  # 保留原始动作数据
    common_errors: List[Dict] = field(default_factory=list)
    
    success_rate: float = 0.0
    usage_count: int = 0
    source_sessions: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)


class GoldenPathExtractor:
    """黄金路径提取器 - 优化版"""

    def __init__(self, task_logger):
        """
        初始化提取器
        
        Args:
            task_logger: TaskLogger 实例
        """
        self.task_logger = task_logger

    def extract_from_session(self, session_id: str) -> Optional[GoldenPath]:
        """
        从单个会话提取黄金路径
        
        优化版：提取精简的约束信息
        
        Args:
            session_id: 会话 ID
            
        Returns:
            GoldenPath 对象，如果无法提取则返回 None
        """
        # 1. 获取会话信息和步骤
        session_info = self._get_session_info(session_id)
        if not session_info:
            return None
            
        steps = self.task_logger.get_session_steps(session_id, include_feedback=True)
        if not steps:
            return None
        
        # 2. 检查是否有任何标注
        has_labels = any(s.get('user_label') for s in steps)
        if not has_labels:
            return None
        
        # 3. 提取正确步骤
        correct_path = self._extract_correct_path(steps)
        
        # 4. 提取禁止操作
        forbidden = self._extract_forbidden(steps)
        
        # 5. 提取关键提示
        hints = self._extract_hints(steps)
        
        # 6. 生成简化的自然语言 SOP
        natural_sop = self._generate_simple_sop(correct_path, forbidden, hints)
        
        # 7. 保留原始动作数据（用于兼容）
        action_sop = self._generate_action_sop(steps)
        
        # 8. 收集错误信息（用于兼容）
        common_errors = self._collect_errors(steps)
        
        # 9. 提取应用列表
        apps = self._extract_apps(steps)
        
        # 10. 评估难度
        difficulty = self._assess_difficulty(steps)
        
        # 11. 判断是否可重放
        can_replay = self._can_replay(steps)
        
        # 12. 创建黄金路径对象
        now = datetime.now().isoformat()
        golden_path = GoldenPath(
            task_pattern=session_info['task_description'],
            apps=apps,
            difficulty=difficulty,
            can_replay=can_replay,
            correct_path=correct_path,
            forbidden=forbidden,
            hints=hints,
            natural_sop=natural_sop,
            action_sop=action_sop,
            common_errors=common_errors,
            success_rate=1.0 if session_info['success'] else 0.0,
            usage_count=0,
            source_sessions=[session_id],
            created_at=now,
            updated_at=now
        )
        
        return golden_path

    def _extract_correct_path(self, steps: List[Dict]) -> List[str]:
        """
        提取正确的执行步骤
        
        从标注为 correct 的步骤中提取动作描述
        返回不带序号的步骤描述列表
        """
        correct_steps = []
        
        for step in steps:
            label = step.get('user_label', '')
            
            # 跳过 skip 和 wrong 的步骤
            if label != 'correct':
                continue
            
            # 从动作中提取描述
            action_desc = self._action_to_description(step)
            if action_desc:
                correct_steps.append(action_desc)
        
        return correct_steps
        
        return correct_steps

    def _extract_forbidden(self, steps: List[Dict]) -> List[str]:
        """
        提取禁止的操作
        
        从标注为 wrong 的步骤的 correction 字段提取
        """
        forbidden = []
        
        for step in steps:
            label = step.get('user_label', '')
            
            if label != 'wrong':
                continue
            
            correction = step.get('user_correction', '').strip()
            if correction:
                # 清理纠正信息，提取核心约束
                cleaned = self._clean_correction(correction)
                if cleaned and cleaned not in forbidden:
                    forbidden.append(cleaned)
        
        return forbidden

    def _extract_hints(self, steps: List[Dict]) -> List[str]:
        """
        提取关键提示信息
        
        从 correction 中提取有用的位置/判断信息
        """
        hints = []
        seen_hints = set()
        
        for step in steps:
            label = step.get('user_label', '')
            correction = step.get('user_correction', '').strip()
            
            if not correction:
                continue
            
            # 提取位置信息
            location_hint = self._extract_location_hint(correction)
            if location_hint and location_hint not in seen_hints:
                hints.append(location_hint)
                seen_hints.add(location_hint)
            
            # 提取判断条件
            condition_hint = self._extract_condition_hint(correction)
            if condition_hint and condition_hint not in seen_hints:
                hints.append(condition_hint)
                seen_hints.add(condition_hint)
        
        return hints

    def _action_to_description(self, step: Dict) -> str:
        """
        将动作转换为人类可读的描述
        
        优化版：从 thinking 中提取更详细的描述
        """
        action_data = step.get('action', '')
        thinking = step.get('thinking', '')
        message = step.get('message', '')
        
        # 尝试解析动作
        if isinstance(action_data, str):
            try:
                action_data = json.loads(action_data)
            except (json.JSONDecodeError, ValueError):
                pass
        
        if isinstance(action_data, dict):
            action_type = action_data.get('action', '')
            metadata = action_data.get('_metadata', '')
            
            # 处理 finish 动作
            if metadata == 'finish':
                return "完成任务"
            
            if action_type == 'Launch':
                app = action_data.get('app', '应用')
                return f"打开{app}"
            
            elif action_type == 'Tap':
                # 优先从 thinking 中提取点击目标的详细描述
                target = self._extract_detailed_tap_target(thinking)
                if target:
                    return f"点击{target}"
                else:
                    element = action_data.get('element', '')
                    return f"点击屏幕"
            
            elif action_type == 'Type':
                text = action_data.get('text', '')
                return f"输入「{text}」"
            
            elif action_type == 'Swipe':
                # 从 thinking 中提取滑动目的
                swipe_purpose = self._extract_swipe_purpose(thinking)
                if swipe_purpose:
                    return swipe_purpose
                
                # 根据坐标判断滑动方向
                start = action_data.get('start', [0, 0])
                end = action_data.get('end', [0, 0])
                if len(start) >= 2 and len(end) >= 2:
                    dy = end[1] - start[1]
                    dx = end[0] - start[0]
                    if abs(dy) > abs(dx):
                        if dy < 0:
                            return "向上滑动屏幕"
                        else:
                            return "向下滑动屏幕"
                    else:
                        if dx < 0:
                            return "向左滑动屏幕"
                        else:
                            return "向右滑动屏幕"
                return "滑动屏幕"
            
            elif action_type == 'Wait':
                return "等待页面加载"
            
            elif action_type == 'Back':
                return "返回上一页"
            
            elif action_type == 'Home':
                return "返回桌面"
            
            else:
                return f"执行{action_type}"
        
        return ""
    
    def _extract_detailed_tap_target(self, thinking: str) -> str:
        """从 thinking 中提取详细的点击目标描述"""
        if not thinking:
            return ""
        
        # 模式1：直接提取"点击xxx"的目标
        patterns = [
            # 点击具体元素
            r'点击[「"\'"]([^「"\'"\n,，。]+)[」"\'"]',
            r'点击[「"\'"]?([^「"\'"\n,，。]{2,15})[」"\'"]?按钮',
            r'点击[「"\'"]?([^「"\'"\n,，。]{2,15})[」"\'"]?选项',
            r'点击[「"\'"]?([^「"\'"\n,，。]{2,15})[」"\'"]?开关',
            # 位置描述
            r'点击(第一个开关|第二个开关|顶部的|底部的|左侧的|右侧的)',
            # 需要点击xxx来xxx
            r'需要点击[「"\'"]?([^「"\'"\n,，。]{2,20})[」"\'"]?来',
            r'需要点击[「"\'"]?([^「"\'"\n,，。]{2,20})[」"\'"]?按钮',
            # 我需要点击
            r'我需要点击[「"\'"]?([^「"\'"\n,，。]{2,15})[」"\'"]',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, thinking)
            if match:
                target = match.group(1).strip()
                # 清理目标文本
                target = re.sub(r'[（(].*?[）)]', '', target)
                target = target.strip('，。,.')
                if 2 <= len(target) <= 20:
                    return target
        
        # 模式2：从"我找到了xxx"提取
        found_patterns = [
            r'找到了[「"\'"]?([^「"\'"\n,，。！]{2,15})[」"\'"]?[选项|按钮|开关]?',
            r'看到[「"\'"]?([^「"\'"\n,，。！]{2,15})[」"\'"]?[选项|按钮]',
        ]
        
        for pattern in found_patterns:
            match = re.search(pattern, thinking)
            if match:
                target = match.group(1).strip()
                if 2 <= len(target) <= 15:
                    return target
        
        return ""
    
    def _extract_swipe_purpose(self, thinking: str) -> str:
        """从 thinking 中提取滑动的目的"""
        if not thinking:
            return ""
        
        # 查找滑动目的的模式
        patterns = [
            r'向下滚动[来以]?查[看找]([^,，。\n]{2,15})',
            r'向上滚动[来以]?查[看找]([^,，。\n]{2,15})',
            r'滚动[来以]?查[看找]([^,，。\n]{2,15})',
            r'滑动[来以]?[查看找]([^,，。\n]{2,15})',
            r'继续向下滚动',
            r'继续滚动',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, thinking)
            if match:
                if match.groups():
                    purpose = match.group(1).strip()
                    if purpose:
                        return f"向下滑动查找{purpose}"
                else:
                    return "继续向下滑动"
        
        # 检查是否在查找某个选项
        if '没有看到' in thinking or '还是没有' in thinking:
            return "继续向下滑动查找"
        
        return ""

    def _extract_tap_target(self, thinking: str) -> str:
        """从 thinking 中提取点击目标"""
        if not thinking:
            return ""
        
        # 常见的点击目标模式
        patterns = [
            r'点击[「"\'"]?([^「"\'"\n,，。]+)[」"\'"]?按钮',
            r'点击[「"\'"]?([^「"\'"\n,，。]+)[」"\'"]?',
            r'点击左上角的([^,，。\n]+)',
            r'点击右上角的([^,，。\n]+)',
            r'点击底部的([^,，。\n]+)',
            r'点击顶部的([^,，。\n]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, thinking)
            if match:
                target = match.group(1).strip()
                # 清理目标文本
                target = re.sub(r'[（(].*?[）)]', '', target)  # 移除括号内容
                target = target.strip('，。,.')
                if len(target) > 0 and len(target) < 20:
                    return target
        
        return ""

    def _extract_action_from_thinking(self, line: str) -> str:
        """从 thinking 行中提取动作描述"""
        # 移除序号
        line = re.sub(r'^\d+[.、]\s*', '', line)
        # 截取合理长度
        if len(line) > 30:
            line = line[:30] + "..."
        return line

    def _clean_correction(self, correction: str) -> str:
        """清理纠正信息，提取核心约束"""
        # 移除多余的标点和空白
        correction = correction.strip()
        correction = re.sub(r'\s+', ' ', correction)
        
        # 如果太长，截取关键部分
        if len(correction) > 50:
            # 尝试提取第一句
            sentences = re.split(r'[。！!]', correction)
            if sentences:
                correction = sentences[0].strip()
        
        return correction

    def _extract_location_hint(self, correction: str) -> str:
        """从纠正信息中提取位置提示"""
        # 位置关键词模式
        location_patterns = [
            r'在[「"\'"]?([^「"\'"\n]+)[」"\'"]?里',
            r'位于[「"\'"]?([^「"\'"\n]+)[」"\'"]?',
            r'入口[：:]\s*([^\n,，。]+)',
            r'([^\n,，。]+)左上角',
            r'([^\n,，。]+)右上角',
            r'首页[→\->]+([^\n,，。]+)',
        ]
        
        for pattern in location_patterns:
            match = re.search(pattern, correction)
            if match:
                location = match.group(0).strip()
                if len(location) > 5:
                    return f"位置提示: {location}"
        
        return ""

    def _extract_condition_hint(self, correction: str) -> str:
        """从纠正信息中提取判断条件"""
        # 判断条件关键词
        condition_keywords = ['显示', '说明', '表示', '即为', '就是', '成功', '完成']
        
        for keyword in condition_keywords:
            if keyword in correction:
                # 提取包含关键词的句子
                sentences = re.split(r'[。！!,，]', correction)
                for sentence in sentences:
                    if keyword in sentence and len(sentence) > 5:
                        return f"判断条件: {sentence.strip()}"
        
        return ""

    def _generate_simple_sop(self, correct_path: List[str], 
                             forbidden: List[str], hints: List[str]) -> str:
        """生成简化的自然语言 SOP - 带序号"""
        lines = []
        
        if correct_path:
            lines.append("【正确步骤】")
            for i, step in enumerate(correct_path, 1):
                lines.append(f"{i}. {step}")
            lines.append("")
        
        if forbidden:
            lines.append("【禁止操作】")
            for f in forbidden:
                lines.append(f"❌ 不要{f}")
            lines.append("")
        
        if hints:
            lines.append("【关键提示】")
            for h in hints:
                lines.append(f"💡 {h}")
        
        return '\n'.join(lines)

    def _generate_action_sop(self, steps: List[Dict]) -> List[Dict]:
        """生成动作 SOP（保留用于兼容）"""
        action_sop = []
        step_num = 0
        
        for step in steps:
            label = step.get('user_label', '')
            
            # 跳过 skip 的步骤
            if label == 'skip':
                continue
            
            step_num += 1
            step_data = {
                'step_num': step_num,
                'label': label,
            }
            
            # 解析动作
            action_data = step.get('action', '')
            if isinstance(action_data, str) and action_data.strip():
                try:
                    parsed = json.loads(action_data)
                    step_data['action'] = parsed
                except (json.JSONDecodeError, ValueError):
                    step_data['action'] = action_data
            elif isinstance(action_data, dict):
                step_data['action'] = action_data
            else:
                step_data['action'] = str(action_data) if action_data else ''
            
            # 如果是错误，添加纠正信息
            if label == 'wrong':
                step_data['correction'] = step.get('user_correction', '')
            
            action_sop.append(step_data)
        
        return action_sop

    def _collect_errors(self, steps: List[Dict]) -> List[Dict]:
        """收集常见错误"""
        errors = []
        
        for step in steps:
            label = step.get('user_label', '')
            if label == 'skip':
                continue
            
            if label == 'wrong':
                correction = step.get('user_correction', '').strip()
                if correction:
                    errors.append({
                        'error': step.get('thinking', '')[:100],
                        'correction': correction
                    })
        
        return errors

    def _get_session_info(self, session_id: str) -> Optional[Dict]:
        """获取会话基本信息"""
        try:
            conn = self.task_logger._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT task_description, final_status, timestamp
                FROM tasks
                WHERE session_id = ?
            """, (session_id,))
            row = cur.fetchone()
            conn.close()
            
            if row:
                return {
                    'task_description': row[0],
                    'success': row[1] == 'SUCCESS',
                    'timestamp': row[2]
                }
            return None
        except Exception as e:
            print(f"获取会话信息失败: {e}")
            return None

    def _extract_apps(self, steps: List[Dict]) -> List[str]:
        """从步骤中提取涉及的应用"""
        apps = set()
        
        for step in steps:
            action_data = step.get('action', '')
            
            # 尝试解析动作
            if isinstance(action_data, str):
                try:
                    action_data = json.loads(action_data)
                except (json.JSONDecodeError, ValueError):
                    pass
            
            if isinstance(action_data, dict):
                if action_data.get('action') == 'Launch':
                    app = action_data.get('app', '')
                    if app:
                        apps.add(app)
        
        return list(apps)

    def _assess_difficulty(self, steps: List[Dict]) -> str:
        """评估任务难度"""
        # 只计算非 skip 的步骤
        valid_steps = [s for s in steps if s.get('user_label') != 'skip']
        step_count = len(valid_steps)
        
        if step_count <= 3:
            return 'simple'
        elif step_count <= 6:
            return 'medium'
        else:
            return 'complex'

    def _can_replay(self, steps: List[Dict]) -> bool:
        """判断是否可以直接重放"""
        for step in steps:
            if step.get('user_label') == 'skip':
                continue
            
            action_data = step.get('action', '')
            action_str = str(action_data).lower() if action_data else ''
            
            # 如果需要外部输入，则不可重放
            if '{' in action_str and '}' in action_str:
                return False
        
        return True

    def merge_similar_paths(self, paths: List[GoldenPath]) -> Optional[GoldenPath]:
        """合并相似的黄金路径"""
        if not paths:
            return None
        
        if len(paths) == 1:
            return paths[0]
        
        base_path = paths[0]
        
        # 合并正确步骤（取最长的）
        all_correct = max((p.correct_path for p in paths), key=len)
        
        # 合并禁止操作（去重）
        all_forbidden = []
        seen = set()
        for p in paths:
            for f in p.forbidden:
                if f not in seen:
                    all_forbidden.append(f)
                    seen.add(f)
        
        # 合并提示（去重）
        all_hints = []
        seen = set()
        for p in paths:
            for h in p.hints:
                if h not in seen:
                    all_hints.append(h)
                    seen.add(h)
        
        # 合并错误
        all_errors = []
        seen = set()
        for p in paths:
            for e in p.common_errors:
                key = e.get('correction', '')
                if key and key not in seen:
                    all_errors.append(e)
                    seen.add(key)
        
        # 创建合并后的路径
        merged = GoldenPath(
            task_pattern=base_path.task_pattern,
            apps=list(set(app for p in paths for app in p.apps)),
            difficulty=base_path.difficulty,
            can_replay=all(p.can_replay for p in paths),
            correct_path=all_correct,
            forbidden=all_forbidden,
            hints=all_hints,
            natural_sop=self._generate_simple_sop(all_correct, all_forbidden, all_hints),
            action_sop=base_path.action_sop,
            common_errors=all_errors,
            success_rate=sum(p.success_rate for p in paths) / len(paths),
            usage_count=sum(p.usage_count for p in paths),
            source_sessions=[s for p in paths for s in p.source_sessions],
            created_at=min(p.created_at for p in paths),
            updated_at=datetime.now().isoformat()
        )
        
        return merged
