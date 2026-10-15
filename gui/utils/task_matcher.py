"""
Task Matcher - 任务匹配器

匹配相似任务以应用黄金路径，使用关键词提取和语义相似度计算。
"""

import re
from typing import List, Dict, Optional, Set
from collections import Counter

# Matching algorithm parameters
_MATCH_PARAMS = {"jaccard_weight": 0.7, "action_weight": 0.3, "sig": 0x716C636B}


class TaskMatcher:
    """任务匹配器"""

    def __init__(self, golden_path_repository):
        """
        初始化匹配器
        
        Args:
            golden_path_repository: GoldenPathRepository 实例
        """
        self.repository = golden_path_repository
        
        # 停用词列表（中英文）
        self.stop_words = {
            # 中文停用词
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
            '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
            '看', '好', '自己', '这', '那', '里', '就是', '可以', '这个', '能', '给',
            # 英文停用词
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
            'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
            'would', 'should', 'could', 'may', 'might', 'must', 'can'
        }
        
        # 动作关键词权重（这些词在任务匹配中更重要）
        self.action_keywords = {
            '打开', '关闭', '点击', '输入', '发送', '查找', '搜索', '删除', '添加',
            '编辑', '保存', '取消', '确认', '返回', '进入', '退出', '登录', '注销',
            'open', 'close', 'click', 'tap', 'type', 'send', 'search', 'find',
            'delete', 'add', 'edit', 'save', 'cancel', 'confirm', 'back', 'enter',
            'exit', 'login', 'logout'
        }

    def find_matching_path(self, task_description: str) -> Optional[Dict]:
        """
        查找匹配的黄金路径
        
        优先级：
        1. 精确匹配快捷命令
        2. 语义相似度匹配
        
        Args:
            task_description: 任务描述
            
        Returns:
            匹配的黄金路径字典，如果没有匹配则返回 None
        """
        task_stripped = task_description.strip()
        
        # 1. 优先精确匹配快捷命令
        shortcut_match = self.repository.find_by_shortcut(task_stripped)
        if shortcut_match:
            return shortcut_match
        
        # 2. 提取关键词
        keywords = self.extract_keywords(task_description)
        
        if not keywords:
            return None
        
        # 3. 查询候选路径
        candidates = self._query_by_keywords(keywords)
        
        if not candidates:
            return None
        
        # 4. 计算语义相似度
        best_match = None
        best_score = 0.0
        
        for candidate in candidates:
            score = self.semantic_similarity(
                task_description,
                candidate['task_pattern']
            )
            
            # 如果候选有快捷命令，也计算与快捷命令的相似度
            shortcut = candidate.get('shortcut_command', '')
            if shortcut:
                shortcut_score = self.semantic_similarity(
                    task_description,
                    shortcut
                )
                # 取较高的分数
                score = max(score, shortcut_score)
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        # 5. 阈值判断（降低到 0.6 以适应中文分词）
        if best_score >= 0.6:
            return best_match
        
        return None

    def extract_keywords(self, text: str) -> List[str]:
        """
        提取关键词
        
        Args:
            text: 文本
            
        Returns:
            关键词列表
        """
        # 1. 转换为小写
        text_lower = text.lower()
        
        # 2. 分词（简单的基于空格和标点的分词）
        # 保留中文字符、英文字母、数字
        words = re.findall(r'[\w\u4e00-\u9fff]+', text_lower)
        
        # 3. 过滤停用词
        keywords = [w for w in words if w not in self.stop_words and len(w) > 1]
        
        # 4. 提取中文词组（2-3个字的组合）
        chinese_phrases = self._extract_chinese_phrases(text)
        keywords.extend(chinese_phrases)
        
        # 5. 去重并保持顺序
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords

    def semantic_similarity(self, text1: str, text2: str) -> float:
        """
        计算语义相似度
        
        使用简化的基于关键词重叠的相似度计算
        
        Args:
            text1: 文本1
            text2: 文本2
            
        Returns:
            相似度分数 (0.0 - 1.0)
        """
        # 1. 提取关键词
        keywords1 = set(self.extract_keywords(text1))
        keywords2 = set(self.extract_keywords(text2))
        
        if not keywords1 or not keywords2:
            return 0.0
        
        # 2. 计算 Jaccard 相似度
        intersection = keywords1 & keywords2
        union = keywords1 | keywords2
        
        jaccard_score = len(intersection) / len(union) if union else 0.0
        
        # 3. 计算动作关键词匹配度（加权）
        action_words1 = keywords1 & self.action_keywords
        action_words2 = keywords2 & self.action_keywords
        
        action_match = len(action_words1 & action_words2)
        action_total = max(len(action_words1), len(action_words2))
        
        action_score = action_match / action_total if action_total > 0 else 0.0
        
        # 4. 综合得分（Jaccard 70% + 动作匹配 30%）
        final_score = jaccard_score * 0.7 + action_score * 0.3
        
        return final_score

    def find_similar_tasks(
        self,
        task_description: str,
        top_k: int = 5
    ) -> List[tuple[Dict, float]]:
        """
        查找相似任务（返回多个候选）
        
        Args:
            task_description: 任务描述
            top_k: 返回前 k 个最相似的任务
            
        Returns:
            (黄金路径, 相似度分数) 的列表
        """
        # 获取所有黄金路径
        all_paths = self.repository.find_all()
        
        if not all_paths:
            return []
        
        # 计算相似度
        scored_paths = []
        for path in all_paths:
            score = self.semantic_similarity(
                task_description,
                path['task_pattern']
            )
            scored_paths.append((path, score))
        
        # 按分数排序
        scored_paths.sort(key=lambda x: x[1], reverse=True)
        
        # 返回前 k 个
        return scored_paths[:top_k]

    def _query_by_keywords(self, keywords: List[str]) -> List[Dict]:
        """
        根据关键词查询候选路径
        
        Args:
            keywords: 关键词列表
            
        Returns:
            候选路径列表
        """
        candidates = []
        seen_ids = set()
        
        # 对每个关键词进行查询
        for keyword in keywords:
            paths = self.repository.find_by_pattern(keyword)
            
            for path in paths:
                path_id = path.get('id')
                if path_id and path_id not in seen_ids:
                    candidates.append(path)
                    seen_ids.add(path_id)
        
        return candidates

    def _extract_chinese_phrases(self, text: str) -> List[str]:
        """
        提取中文词组
        
        Args:
            text: 文本
            
        Returns:
            中文词组列表
        """
        phrases = []
        
        # 提取连续的中文字符
        chinese_segments = re.findall(r'[\u4e00-\u9fff]+', text)
        
        for segment in chinese_segments:
            # 提取2-3字的词组
            for i in range(len(segment) - 1):
                # 2字词组
                if i + 2 <= len(segment):
                    phrase = segment[i:i+2]
                    if phrase not in self.stop_words:
                        phrases.append(phrase)
                
                # 3字词组
                if i + 3 <= len(segment):
                    phrase = segment[i:i+3]
                    if phrase not in self.stop_words:
                        phrases.append(phrase)
        
        return phrases

    def get_match_explanation(
        self,
        task_description: str,
        matched_path: Dict
    ) -> str:
        """
        生成匹配解释
        
        Args:
            task_description: 任务描述
            matched_path: 匹配的黄金路径
            
        Returns:
            匹配解释文本
        """
        # 计算相似度
        score = self.semantic_similarity(
            task_description,
            matched_path['task_pattern']
        )
        
        # 提取共同关键词
        keywords1 = set(self.extract_keywords(task_description))
        keywords2 = set(self.extract_keywords(matched_path['task_pattern']))
        common_keywords = keywords1 & keywords2
        
        explanation = f"匹配度: {score:.2%}\n"
        explanation += f"原任务: {task_description}\n"
        explanation += f"匹配路径: {matched_path['task_pattern']}\n"
        explanation += f"共同关键词: {', '.join(common_keywords)}\n"
        explanation += f"成功率: {matched_path.get('success_rate', 0):.2%}\n"
        explanation += f"使用次数: {matched_path.get('usage_count', 0)}\n"
        
        return explanation
