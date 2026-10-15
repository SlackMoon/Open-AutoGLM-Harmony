"""
Steering File Manager - 管理 Steering 文件的生成和读取

负责将黄金路径转换为 YAML 格式的 steering 文件，并管理文件的读写操作。
"""

import os
import re
import yaml
from typing import Dict, Optional, List
from pathlib import Path


class SteeringFileManager:
    """Steering 文件管理器"""

    def __init__(self, steering_dir: str = None):
        """
        初始化管理器
        
        Args:
            steering_dir: Steering 文件目录，默认为 .kiro/steering/golden-paths/
        """
        if steering_dir is None:
            # 默认目录
            self.steering_dir = Path('.kiro/steering/golden-paths')
        else:
            self.steering_dir = Path(steering_dir)
        
        # 确保目录存在
        self.steering_dir.mkdir(parents=True, exist_ok=True)

    def save_golden_path(self, golden_path_dict: Dict) -> Optional[str]:
        """
        将黄金路径保存为 YAML 文件
        
        Args:
            golden_path_dict: 黄金路径字典
            
        Returns:
            保存的文件路径，如果失败则返回 None
        """
        try:
            # 生成文件名
            filename = self._generate_filename(golden_path_dict['task_pattern'])
            filepath = self.steering_dir / filename
            
            # 转换为 YAML 格式
            yaml_content = self._to_yaml_format(golden_path_dict)
            
            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(yaml_content)
            
            return str(filepath)
        
        except Exception as e:
            print(f"保存 steering 文件失败: {e}")
            return None

    def load_golden_path(self, filename: str) -> Optional[Dict]:
        """
        从 YAML 文件加载黄金路径
        
        Args:
            filename: 文件名（不含路径）
            
        Returns:
            黄金路径字典，如果失败则返回 None
        """
        try:
            filepath = self.steering_dir / filename
            
            if not filepath.exists():
                print(f"文件不存在: {filepath}")
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析 YAML
            data = yaml.safe_load(content)
            return data
        
        except yaml.YAMLError as e:
            print(f"YAML 解析错误: {e}")
            return None
        except Exception as e:
            print(f"加载 steering 文件失败: {e}")
            return None

    def list_all_files(self) -> List[str]:
        """
        列出所有 steering 文件
        
        Returns:
            文件名列表
        """
        try:
            if not self.steering_dir.exists():
                return []
            
            files = [f.name for f in self.steering_dir.glob('*.yaml')]
            return sorted(files)
        
        except Exception as e:
            print(f"列出文件失败: {e}")
            return []

    def delete_file(self, filename: str) -> bool:
        """
        删除 steering 文件
        
        Args:
            filename: 文件名（不含路径）
            
        Returns:
            是否删除成功
        """
        try:
            filepath = self.steering_dir / filename
            
            if filepath.exists():
                filepath.unlink()
                return True
            
            return False
        
        except Exception as e:
            print(f"删除文件失败: {e}")
            return False

    def _generate_filename(self, task_pattern: str) -> str:
        """
        根据任务模式生成文件名
        
        Args:
            task_pattern: 任务模式
            
        Returns:
            文件名（含 .yaml 扩展名）
        """
        # 清理任务模式，只保留字母、数字、中文和连字符
        sanitized = re.sub(r'[^\w\u4e00-\u9fff-]', '-', task_pattern)
        
        # 移除连续的连字符
        sanitized = re.sub(r'-+', '-', sanitized)
        
        # 移除首尾的连字符
        sanitized = sanitized.strip('-')
        
        # 限制长度
        if len(sanitized) > 50:
            sanitized = sanitized[:50]
        
        # 转换为小写（仅英文字母）
        sanitized = sanitized.lower()
        
        return f"{sanitized}.yaml"

    def _to_yaml_format(self, golden_path_dict: Dict) -> str:
        """
        将黄金路径字典转换为 YAML 格式字符串
        
        Args:
            golden_path_dict: 黄金路径字典
            
        Returns:
            YAML 格式字符串
        """
        # 构建 YAML 数据结构
        yaml_data = {
            'task_pattern': golden_path_dict['task_pattern'],
            'apps': golden_path_dict.get('apps', []),
            'difficulty': golden_path_dict.get('difficulty', 'medium'),
            'can_replay': golden_path_dict.get('can_replay', False),
            'natural_sop': golden_path_dict.get('natural_sop', ''),
            'action_sop': golden_path_dict.get('action_sop', []),
            'common_errors': golden_path_dict.get('common_errors', []),
            'success_rate': golden_path_dict.get('success_rate', 0.0),
            'last_updated': golden_path_dict.get('updated_at', ''),
            'source_sessions': golden_path_dict.get('source_sessions', [])
        }
        
        # 使用 yaml.dump 生成 YAML 字符串
        yaml_str = yaml.dump(
            yaml_data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            indent=2
        )
        
        # 添加文件头注释
        header = "# Golden Path - Auto-generated by Task Review System\n"
        header += "# This file contains a successful task execution path learned from user annotations\n"
        header += "---\n"
        
        return header + yaml_str

    def validate_yaml_file(self, filename: str) -> tuple[bool, Optional[str]]:
        """
        验证 YAML 文件的有效性
        
        Args:
            filename: 文件名（不含路径）
            
        Returns:
            (是否有效, 错误信息)
        """
        try:
            filepath = self.steering_dir / filename
            
            if not filepath.exists():
                return False, "文件不存在"
            
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 尝试解析 YAML
            data = yaml.safe_load(content)
            
            # 检查必需字段
            required_fields = ['task_pattern', 'natural_sop', 'action_sop']
            for field in required_fields:
                if field not in data:
                    return False, f"缺少必需字段: {field}"
            
            return True, None
        
        except yaml.YAMLError as e:
            return False, f"YAML 语法错误: {str(e)}"
        except Exception as e:
            return False, f"验证失败: {str(e)}"

    def get_file_path(self, filename: str) -> str:
        """
        获取文件的完整路径
        
        Args:
            filename: 文件名（不含路径）
            
        Returns:
            完整路径
        """
        return str(self.steering_dir / filename)

    def update_golden_path(self, filename: str, updates: Dict) -> bool:
        """
        更新现有的黄金路径文件
        
        Args:
            filename: 文件名（不含路径）
            updates: 要更新的字段字典
            
        Returns:
            是否更新成功
        """
        try:
            # 加载现有数据
            existing_data = self.load_golden_path(filename)
            if existing_data is None:
                return False
            
            # 更新字段
            existing_data.update(updates)
            
            # 保存回文件
            filepath = self.steering_dir / filename
            yaml_content = self._to_yaml_format(existing_data)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(yaml_content)
            
            return True
        
        except Exception as e:
            print(f"更新文件失败: {e}")
            return False
