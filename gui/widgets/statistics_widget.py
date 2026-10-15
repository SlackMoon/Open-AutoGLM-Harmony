"""
Statistics Widget - 统计仪表板

显示任务执行统计、黄金路径使用情况和错误模式分析。
"""

import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QTableWidget, QTableWidgetItem, QGroupBox,
    QHeaderView, QPushButton, QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor
from typing import Optional


class StatisticsWidget(QWidget):
    """统计仪表板 Widget"""
    
    # 信号
    refresh_requested = pyqtSignal()
    
    def __init__(self, task_logger=None, parent=None):
        """
        初始化统计 Widget
        
        Args:
            task_logger: TaskLogger 实例
            parent: 父 Widget
        """
        super().__init__(parent)
        self.task_logger = task_logger
        self._init_ui()
        
        # 初始加载数据
        if self.task_logger:
            self.refresh_statistics()
    
    def _init_ui(self):
        """初始化 UI"""
        layout = QVBoxLayout(self)
        
        # 标题和刷新按钮
        header_layout = QHBoxLayout()
        title_label = QLabel("📊 统计仪表板")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        self.refresh_btn = QPushButton("🔄 刷新")
        self.refresh_btn.clicked.connect(self.refresh_statistics)
        header_layout.addWidget(self.refresh_btn)
        
        layout.addLayout(header_layout)
        
        # 创建分割器
        splitter = QSplitter(Qt.Vertical)
        
        # 上半部分：总体统计
        overview_group = self._create_overview_section()
        splitter.addWidget(overview_group)
        
        # 中间部分：黄金路径统计
        golden_path_group = self._create_golden_path_section()
        splitter.addWidget(golden_path_group)
        
        # 下半部分：错误模式统计
        error_pattern_group = self._create_error_pattern_section()
        splitter.addWidget(error_pattern_group)
        
        # 设置分割器比例
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 2)
        
        layout.addWidget(splitter)
    
    def _create_overview_section(self) -> QGroupBox:
        """创建总体统计区域"""
        group = QGroupBox("总体统计")
        layout = QHBoxLayout(group)
        
        # 创建统计卡片
        self.total_tasks_label = self._create_stat_card("总任务数", "0", "📋")
        self.success_rate_label = self._create_stat_card("成功率", "0%", "✅")
        self.avg_steps_label = self._create_stat_card("平均步骤数", "0", "👣")
        self.golden_paths_label = self._create_stat_card("黄金路径数", "0", "⭐")
        
        layout.addWidget(self.total_tasks_label)
        layout.addWidget(self.success_rate_label)
        layout.addWidget(self.avg_steps_label)
        layout.addWidget(self.golden_paths_label)
        
        return group
    
    def _create_stat_card(self, title: str, value: str, icon: str) -> QWidget:
        """创建统计卡片"""
        card = QWidget()
        card.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        
        layout = QVBoxLayout(card)
        
        # 图标和标题
        header_layout = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size: 24px;")
        header_layout.addWidget(icon_label)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #666; font-size: 12px;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        layout.addLayout(header_layout)
        
        # 数值
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #333;")
        value_label.setObjectName("value_label")
        layout.addWidget(value_label)
        
        return card
    
    def _create_golden_path_section(self) -> QGroupBox:
        """创建黄金路径统计区域"""
        group = QGroupBox("黄金路径管理")
        layout = QVBoxLayout(group)
        
        # 按钮栏
        btn_layout = QHBoxLayout()
        
        self.view_path_btn = QPushButton("👁️ 查看详情")
        self.view_path_btn.clicked.connect(self._view_golden_path_details)
        btn_layout.addWidget(self.view_path_btn)
        
        self.shortcut_btn = QPushButton("⚡ 设置快捷命令")
        self.shortcut_btn.setStyleSheet("background-color: #FF9800; color: white;")
        self.shortcut_btn.clicked.connect(self._set_shortcut_command)
        btn_layout.addWidget(self.shortcut_btn)
        
        self.test_prompt_btn = QPushButton("🧪 测试提示词")
        self.test_prompt_btn.setStyleSheet("background-color: #2196F3; color: white;")
        self.test_prompt_btn.clicked.connect(self._test_golden_path_prompt)
        btn_layout.addWidget(self.test_prompt_btn)
        
        self.delete_path_btn = QPushButton("🗑️ 删除选中")
        self.delete_path_btn.setStyleSheet("background-color: #f44336; color: white;")
        self.delete_path_btn.clicked.connect(self._delete_selected_golden_path)
        btn_layout.addWidget(self.delete_path_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 创建表格
        self.golden_path_table = QTableWidget()
        self.golden_path_table.setColumnCount(7)
        self.golden_path_table.setHorizontalHeaderLabels([
            "ID", "任务模式", "快捷命令", "难度", "成功率", "使用次数", "最后更新"
        ])
        
        # 设置表格属性
        self.golden_path_table.horizontalHeader().setStretchLastSection(True)
        self.golden_path_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.golden_path_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.golden_path_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.golden_path_table.setAlternatingRowColors(True)
        self.golden_path_table.setColumnWidth(0, 50)  # ID 列窄一点
        self.golden_path_table.setColumnWidth(2, 120)  # 快捷命令列
        
        # 右键菜单
        self.golden_path_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.golden_path_table.customContextMenuRequested.connect(self._show_golden_path_context_menu)
        
        layout.addWidget(self.golden_path_table)
        
        return group
    
    def _show_golden_path_context_menu(self, position):
        """显示黄金路径右键菜单"""
        from PyQt5.QtWidgets import QMenu, QAction
        
        menu = QMenu()
        
        view_action = QAction("👁️ 查看详情", self)
        view_action.triggered.connect(self._view_golden_path_details)
        menu.addAction(view_action)
        
        shortcut_action = QAction("⚡ 设置快捷命令", self)
        shortcut_action.triggered.connect(self._set_shortcut_command)
        menu.addAction(shortcut_action)
        
        test_action = QAction("🧪 测试提示词", self)
        test_action.triggered.connect(self._test_golden_path_prompt)
        menu.addAction(test_action)
        
        menu.addSeparator()
        
        delete_action = QAction("🗑️ 删除", self)
        delete_action.triggered.connect(self._delete_selected_golden_path)
        menu.addAction(delete_action)
        
        menu.exec_(self.golden_path_table.viewport().mapToGlobal(position))
    
    def _get_selected_golden_path_id(self) -> Optional[int]:
        """获取选中的黄金路径 ID"""
        selected_row = self.golden_path_table.currentRow()
        if selected_row < 0:
            return None
        id_item = self.golden_path_table.item(selected_row, 0)
        if id_item:
            return int(id_item.text())
        return None
    
    def _set_shortcut_command(self):
        """设置快捷命令"""
        from PyQt5.QtWidgets import QMessageBox, QInputDialog
        
        path_id = self._get_selected_golden_path_id()
        if path_id is None:
            QMessageBox.information(self, "提示", "请先选择一条黄金路径")
            return
        
        try:
            from pathlib import Path
            from gui.utils.golden_path_repository import GoldenPathRepository
            
            db_path = str(Path(self.task_logger.log_dir) / "tasks.db")
            repo = GoldenPathRepository(db_path)
            path_data = repo.find_by_id(path_id)
            
            if not path_data:
                QMessageBox.warning(self, "错误", "未找到该黄金路径")
                return
            
            # 获取当前快捷命令
            current_shortcut = path_data.get('shortcut_command', '')
            task_pattern = path_data.get('task_pattern', '')
            
            # 弹出输入对话框
            shortcut, ok = QInputDialog.getText(
                self,
                "设置快捷命令",
                f"为黄金路径设置一个简短的快捷命令：\n\n"
                f"原任务: {task_pattern[:50]}...\n\n"
                f"快捷命令（用户输入此命令时将直接匹配此黄金路径）：",
                text=current_shortcut
            )
            
            if ok:
                shortcut = shortcut.strip()
                
                # 检查是否与其他路径的快捷命令冲突
                if shortcut:
                    existing = repo.find_by_shortcut(shortcut)
                    if existing and existing.get('id') != path_id:
                        QMessageBox.warning(
                            self, 
                            "冲突", 
                            f"快捷命令「{shortcut}」已被其他黄金路径使用！\n"
                            f"冲突路径: {existing.get('task_pattern', '')[:50]}..."
                        )
                        return
                
                # 更新快捷命令
                if repo.update_shortcut_command(path_id, shortcut):
                    if shortcut:
                        QMessageBox.information(
                            self, 
                            "成功", 
                            f"已设置快捷命令：{shortcut}\n\n"
                            f"现在用户输入「{shortcut}」时将直接匹配此黄金路径。"
                        )
                    else:
                        QMessageBox.information(self, "成功", "已清除快捷命令")
                    self.refresh_statistics()
                else:
                    QMessageBox.warning(self, "失败", "更新快捷命令失败")
                    
        except Exception as e:
            QMessageBox.critical(self, "错误", f"设置快捷命令失败: {e}")
    
    def _view_golden_path_details(self):
        """查看并编辑黄金路径详情"""
        from PyQt5.QtWidgets import QMessageBox, QDialog, QTextEdit, QDialogButtonBox, QPushButton, QHBoxLayout
        import json
        
        path_id = self._get_selected_golden_path_id()
        if path_id is None:
            QMessageBox.information(self, "提示", "请先选择一条黄金路径")
            return
        
        # 从数据库获取详情
        try:
            from pathlib import Path
            from gui.utils.golden_path_repository import GoldenPathRepository
            
            db_path = str(Path(self.task_logger.log_dir) / "tasks.db")
            repo = GoldenPathRepository(db_path)
            path_data = repo.find_by_id(path_id)
            
            if not path_data:
                QMessageBox.warning(self, "错误", "未找到该黄金路径")
                return
            
            # 创建详情对话框
            dialog = QDialog(self)
            dialog.setWindowTitle(f"黄金路径详情 - ID {path_id}")
            dialog.setMinimumSize(600, 500)
            
            layout = QVBoxLayout(dialog)
            
            # 可编辑的文本框
            text_edit = QTextEdit()
            text_edit.setReadOnly(False)  # 可编辑
            
            # 格式化显示
            details = []
            details.append(f"ID: {path_id}")
            details.append(f"任务模式: {path_data.get('task_pattern', '')}")
            details.append(f"难度: {path_data.get('difficulty', '')}")
            details.append(f"成功率: {path_data.get('success_rate', 0):.1%}")
            details.append(f"使用次数: {path_data.get('usage_count', 0)}")
            details.append(f"可重放: {'是' if path_data.get('can_replay') else '否'}")
            details.append("")
            details.append("=" * 50)
            details.append("【正确步骤】(每行一个，可编辑)")
            correct_path = path_data.get('correct_path', [])
            if isinstance(correct_path, str):
                try:
                    correct_path = json.loads(correct_path)
                except:
                    correct_path = []
            for step in correct_path:
                details.append(step)
            details.append("")
            details.append("=" * 50)
            details.append("【禁止操作】(每行一个，可编辑)")
            forbidden = path_data.get('forbidden', [])
            if isinstance(forbidden, str):
                try:
                    forbidden = json.loads(forbidden)
                except:
                    forbidden = []
            for f in forbidden:
                details.append(f)
            details.append("")
            details.append("=" * 50)
            details.append("【关键提示】(每行一个，可编辑)")
            hints = path_data.get('hints', [])
            if isinstance(hints, str):
                try:
                    hints = json.loads(hints)
                except:
                    hints = []
            for h in hints:
                details.append(h)
            details.append("")
            details.append("=" * 50)
            details.append("【完成条件】(每行一个，可编辑 - 满足任意条件时任务自动停止)")
            completion_conditions = path_data.get('completion_conditions', [])
            if isinstance(completion_conditions, str):
                try:
                    completion_conditions = json.loads(completion_conditions)
                except:
                    completion_conditions = []
            for c in completion_conditions:
                details.append(c)
            
            text_edit.setPlainText("\n".join(details))
            layout.addWidget(text_edit)
            
            # 按钮栏
            btn_layout = QHBoxLayout()
            
            save_btn = QPushButton("💾 保存")
            save_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            
            def save_changes():
                try:
                    # 解析编辑后的内容
                    content = text_edit.toPlainText()
                    lines = content.split('\n')
                    
                    new_correct_path = []
                    new_forbidden = []
                    new_hints = []
                    new_completion_conditions = []
                    
                    current_section = None
                    for line in lines:
                        line = line.strip()
                        if '【正确步骤】' in line:
                            current_section = 'correct'
                        elif '【禁止操作】' in line:
                            current_section = 'forbidden'
                        elif '【关键提示】' in line:
                            current_section = 'hints'
                        elif '【完成条件】' in line:
                            current_section = 'completion'
                        elif line.startswith('=') or line.startswith('ID:') or line.startswith('任务模式:') or line.startswith('难度:') or line.startswith('成功率:') or line.startswith('使用次数:') or line.startswith('可重放:'):
                            continue
                        elif line and current_section:
                            if current_section == 'correct':
                                new_correct_path.append(line)
                            elif current_section == 'forbidden':
                                new_forbidden.append(line)
                            elif current_section == 'hints':
                                new_hints.append(line)
                            elif current_section == 'completion':
                                new_completion_conditions.append(line)
                    
                    # 检查 correct_path 是否被修改
                    old_correct_path = path_data.get('correct_path', [])
                    if isinstance(old_correct_path, str):
                        try:
                            old_correct_path = json.loads(old_correct_path)
                        except:
                            old_correct_path = []
                    
                    correct_path_changed = (new_correct_path != old_correct_path)
                    
                    # 保存到数据库
                    update_data = {
                        'correct_path': json.dumps(new_correct_path, ensure_ascii=False),
                        'forbidden': json.dumps(new_forbidden, ensure_ascii=False),
                        'hints': json.dumps(new_hints, ensure_ascii=False),
                        'completion_conditions': json.dumps(new_completion_conditions, ensure_ascii=False),
                    }
                    
                    # 如果 correct_path 被修改，清空 action_sop
                    # 这样系统会回退到提示词约束模式，而不是使用旧的动作序列
                    if correct_path_changed:
                        update_data['action_sop'] = json.dumps([], ensure_ascii=False)
                    
                    if repo.update(path_id, update_data):
                        msg = "已保存"
                        if correct_path_changed:
                            msg += "\n\n⚠️ 检测到步骤修改，已清空动作序列。\n下次执行将使用提示词约束模式（由模型决策）。\n如需使用直接回放模式，请重新用教学模式录制。"
                        QMessageBox.information(dialog, "成功", msg)
                        self.refresh_statistics()
                    else:
                        QMessageBox.warning(dialog, "失败", "保存失败")
                except Exception as e:
                    QMessageBox.critical(dialog, "错误", f"保存失败: {e}")
            
            save_btn.clicked.connect(save_changes)
            btn_layout.addWidget(save_btn)
            
            btn_layout.addStretch()
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(close_btn)
            
            layout.addLayout(btn_layout)
            
            dialog.exec_()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"获取详情失败: {e}")
    
    def _test_golden_path_prompt(self):
        """测试黄金路径生成的提示词"""
        from PyQt5.QtWidgets import QMessageBox, QDialog, QTextEdit, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QLabel
        import json
        
        path_id = self._get_selected_golden_path_id()
        if path_id is None:
            QMessageBox.information(self, "提示", "请先选择一条黄金路径")
            return
        
        try:
            from pathlib import Path
            from gui.utils.golden_path_repository import GoldenPathRepository
            
            db_path = str(Path(self.task_logger.log_dir) / "tasks.db")
            repo = GoldenPathRepository(db_path)
            path_data = repo.find_by_id(path_id)
            
            if not path_data:
                QMessageBox.warning(self, "错误", "未找到该黄金路径")
                return
            
            # 生成提示词
            prompt = self._generate_test_prompt(path_data)
            
            # 创建测试对话框
            dialog = QDialog(self)
            dialog.setWindowTitle(f"🧪 提示词测试 - {path_data.get('task_pattern', '')[:30]}")
            dialog.setMinimumSize(700, 600)
            
            layout = QVBoxLayout(dialog)
            
            # 说明
            info_label = QLabel("以下是将注入到模型的提示词内容，用于指导模型执行任务：")
            info_label.setStyleSheet("color: #666; margin-bottom: 10px;")
            layout.addWidget(info_label)
            
            # 提示词显示区域
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(prompt)
            text_edit.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 12px;
                    background-color: #1e1e1e;
                    color: #d4d4d4;
                    padding: 10px;
                    border-radius: 5px;
                }
            """)
            layout.addWidget(text_edit)
            
            # 统计信息
            stats_layout = QHBoxLayout()
            
            forbidden_count = len(path_data.get('forbidden', []))
            correct_count = len(path_data.get('correct_path', []))
            hints_count = len(path_data.get('hints', []))
            
            stats_label = QLabel(
                f"📊 统计: 禁止操作 {forbidden_count} 条 | "
                f"正确步骤 {correct_count} 步 | "
                f"关键提示 {hints_count} 条 | "
                f"总字符数 {len(prompt)}"
            )
            stats_label.setStyleSheet("color: #888; font-size: 11px;")
            stats_layout.addWidget(stats_label)
            stats_layout.addStretch()
            
            layout.addLayout(stats_layout)
            
            # 按钮
            btn_layout = QHBoxLayout()
            
            copy_btn = QPushButton("📋 复制到剪贴板")
            copy_btn.clicked.connect(lambda: self._copy_to_clipboard(prompt))
            btn_layout.addWidget(copy_btn)
            
            btn_layout.addStretch()
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.reject)
            btn_layout.addWidget(close_btn)
            
            layout.addLayout(btn_layout)
            
            dialog.exec_()
            
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成提示词失败: {e}")
    
    def _generate_test_prompt(self, path_data: dict) -> str:
        """
        生成测试提示词 - 优化版
        
        格式：原始任务,1.第一步动作,2.第二步动作,3.第三步动作...
        如果有错误步骤，添加"不要xxx"的约束
        """
        import json
        
        task = path_data.get('task_pattern', '未知任务')
        
        # 获取步骤信息
        correct_path = path_data.get('correct_path', [])
        action_sop = path_data.get('action_sop', [])
        forbidden = path_data.get('forbidden', [])
        
        # 如果 action_sop 是字符串，解析它
        if isinstance(action_sop, str):
            try:
                action_sop = json.loads(action_sop)
            except:
                action_sop = []
        
        # 如果 correct_path 是字符串，解析它
        if isinstance(correct_path, str):
            try:
                correct_path = json.loads(correct_path)
            except:
                correct_path = []
        
        # 如果 forbidden 是字符串，解析它
        if isinstance(forbidden, str):
            try:
                forbidden = json.loads(forbidden)
            except:
                forbidden = []
        
        # 从 action_sop 重新生成详细步骤描述
        steps = self._generate_detailed_steps(action_sop, path_data)
        
        # 构建提示词
        step_parts = []
        for i, step_desc in enumerate(steps, 1):
            step_parts.append(f"{i}.{step_desc}")
        
        # 添加禁止操作
        forbidden_parts = []
        for f in forbidden:
            f = str(f).strip()
            # 如果已经以"不要"、"不"、"禁止"开头，直接使用
            if f.startswith('不要') or f.startswith('不允许') or f.startswith('禁止'):
                forbidden_parts.append(f)
            elif f.startswith('不'):
                forbidden_parts.append(f)
            # 如果是提示性信息（包含"要"、"应该"、"需要"等），跳过
            elif any(kw in f for kw in ['要返回', '要点击', '应该', '需要', '就是', '说明', '表示', '显示']):
                # 这些是提示信息，不是禁止操作，跳过
                continue
            else:
                forbidden_parts.append(f"不要{f}")
        
        # 生成最终提示词
        all_parts = step_parts + forbidden_parts
        if all_parts:
            enhanced_task = f"{task},{','.join(all_parts)}"
        else:
            enhanced_task = task
        
        # 显示格式化的预览
        preview_parts = []
        preview_parts.append("【实际注入的提示词】")
        preview_parts.append(enhanced_task)
        preview_parts.append("")
        preview_parts.append("=" * 50)
        preview_parts.append("")
        preview_parts.append("【步骤分解】")
        preview_parts.append(f"原始任务: {task}")
        preview_parts.append("")
        
        if step_parts:
            preview_parts.append("执行步骤:")
            for s in step_parts:
                preview_parts.append(f"  {s}")
            preview_parts.append("")
        
        if forbidden_parts:
            preview_parts.append("禁止操作:")
            for f in forbidden_parts:
                preview_parts.append(f"  ❌ {f}")
        
        if not step_parts and not forbidden_parts:
            preview_parts.append("（无步骤信息，请重新提取黄金路径）")
        
        return '\n'.join(preview_parts)
    
    def _generate_detailed_steps(self, action_sop: list, path_data: dict) -> list:
        """
        从 correct_path 或 action_sop 生成详细的步骤描述
        
        优先使用 correct_path（已经是详细描述）
        """
        import json
        
        # 优先使用 correct_path
        correct_path = path_data.get('correct_path', [])
        if isinstance(correct_path, str):
            try:
                correct_path = json.loads(correct_path)
            except:
                correct_path = []
        
        # 如果 correct_path 有内容，直接使用
        if correct_path:
            # 移除可能存在的序号前缀
            steps = []
            for step in correct_path:
                # 移除 "1. " 这样的前缀
                cleaned = re.sub(r'^\d+\.\s*', '', str(step))
                if cleaned:
                    steps.append(cleaned)
            return steps
        
        # 否则从 action_sop 生成
        steps = []
        for step_data in action_sop:
            label = step_data.get('label', '')
            action = step_data.get('action', {})
            
            # 跳过 skip 的步骤
            if label == 'skip':
                continue
            
            # 如果是错误步骤，跳过（会在 forbidden 中处理）
            if label == 'wrong':
                continue
            
            # 解析动作
            if isinstance(action, str):
                try:
                    action = json.loads(action)
                except:
                    action = {}
            
            # 生成步骤描述
            desc = self._action_to_step_description(action)
            if desc:
                steps.append(desc)
        
        return steps
    
    def _action_to_step_description(self, action: dict) -> str:
        """将动作转换为步骤描述"""
        if not action:
            return ""
        
        action_type = action.get('action', '')
        metadata = action.get('_metadata', '')
        
        # 处理 finish 动作
        if metadata == 'finish':
            return "完成任务"
        
        if action_type == 'Launch':
            app = action.get('app', '应用')
            return f"打开{app}"
        
        elif action_type == 'Tap':
            element = action.get('element', [])
            # 这里只能返回基本描述，详细描述需要 thinking
            return "点击目标元素"
        
        elif action_type == 'Type':
            text = action.get('text', '')
            return f"输入「{text}」"
        
        elif action_type == 'Swipe':
            start = action.get('start', [0, 0])
            end = action.get('end', [0, 0])
            if len(start) >= 2 and len(end) >= 2:
                dy = end[1] - start[1]
                if dy < 0:
                    return "向上滑动屏幕"
                else:
                    return "向下滑动屏幕"
            return "滑动屏幕"
        
        elif action_type == 'Wait':
            return "等待页面加载"
        
        elif action_type == 'Back':
            return "返回上一页"
        
        elif action_type == 'Home':
            return "返回桌面"
        
        return ""
    
    def _copy_to_clipboard(self, text: str):
        """复制文本到剪贴板"""
        from PyQt5.QtWidgets import QApplication, QMessageBox
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(self, "成功", "已复制到剪贴板")

    def _delete_selected_golden_path(self):
        """删除选中的黄金路径"""
        from PyQt5.QtWidgets import QMessageBox
        
        path_id = self._get_selected_golden_path_id()
        if path_id is None:
            QMessageBox.information(self, "提示", "请先选择一条黄金路径")
            return
        
        # 获取任务模式用于确认
        selected_row = self.golden_path_table.currentRow()
        pattern_item = self.golden_path_table.item(selected_row, 1)
        pattern = pattern_item.text() if pattern_item else "未知"
        
        # 确认删除
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除以下黄金路径吗？\n\n"
            f"ID: {path_id}\n"
            f"任务模式: {pattern}\n\n"
            "此操作不可撤销！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # 执行删除
        try:
            from pathlib import Path
            from gui.utils.golden_path_repository import GoldenPathRepository
            
            db_path = str(Path(self.task_logger.log_dir) / "tasks.db")
            repo = GoldenPathRepository(db_path)
            
            if repo.delete(path_id):
                QMessageBox.information(self, "成功", f"已删除黄金路径 ID {path_id}")
                self.refresh_statistics()
            else:
                QMessageBox.warning(self, "失败", "删除失败")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除失败: {e}")
    
    def _create_error_pattern_section(self) -> QGroupBox:
        """创建错误模式统计区域"""
        group = QGroupBox("常见错误模式")
        layout = QVBoxLayout(group)
        
        # 创建表格
        self.error_pattern_table = QTableWidget()
        self.error_pattern_table.setColumnCount(4)
        self.error_pattern_table.setHorizontalHeaderLabels([
            "任务模式", "错误描述", "纠正方法", "出现次数"
        ])
        
        # 设置表格属性
        self.error_pattern_table.horizontalHeader().setStretchLastSection(True)
        self.error_pattern_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.error_pattern_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.error_pattern_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.error_pattern_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.error_pattern_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.error_pattern_table)
        
        return group
    
    def refresh_statistics(self):
        """刷新统计数据"""
        if not self.task_logger:
            return
        
        try:
            # 更新总体统计
            self._update_overview_stats()
            
            # 更新黄金路径表格
            self._update_golden_path_table()
            
            # 更新错误模式表格
            self._update_error_pattern_table()
            
        except Exception as e:
            print(f"刷新统计数据失败: {e}")
    
    def _update_overview_stats(self):
        """更新总体统计"""
        try:
            conn = self.task_logger._get_conn()
            cur = conn.cursor()
            
            # 总任务数
            cur.execute("SELECT COUNT(*) FROM tasks")
            total_tasks = cur.fetchone()[0]
            
            # 成功率
            cur.execute("""
                SELECT COUNT(*) FROM tasks 
                WHERE final_status = 'SUCCESS'
            """)
            success_count = cur.fetchone()[0]
            success_rate = (success_count / total_tasks * 100) if total_tasks > 0 else 0
            
            # 平均步骤数
            cur.execute("SELECT AVG(total_steps) FROM tasks WHERE total_steps > 0")
            avg_steps = cur.fetchone()[0] or 0
            
            # 黄金路径数
            cur.execute("SELECT COUNT(*) FROM golden_paths")
            golden_paths_count = cur.fetchone()[0]
            
            conn.close()
            
            # 更新 UI
            self._update_stat_card(self.total_tasks_label, str(total_tasks))
            self._update_stat_card(self.success_rate_label, f"{success_rate:.1f}%")
            self._update_stat_card(self.avg_steps_label, f"{avg_steps:.1f}")
            self._update_stat_card(self.golden_paths_label, str(golden_paths_count))
            
        except Exception as e:
            print(f"更新总体统计失败: {e}")
    
    def _update_stat_card(self, card: QWidget, value: str):
        """更新统计卡片的值"""
        value_label = card.findChild(QLabel, "value_label")
        if value_label:
            value_label.setText(value)
    
    def _update_golden_path_table(self):
        """更新黄金路径表格"""
        try:
            conn = self.task_logger._get_conn()
            cur = conn.cursor()
            
            # 检查 shortcut_command 列是否存在
            try:
                cur.execute("""
                    SELECT id, task_pattern, shortcut_command, difficulty, success_rate, 
                           usage_count, updated_at
                    FROM golden_paths
                    ORDER BY usage_count DESC, success_rate DESC
                    LIMIT 50
                """)
            except:
                # 如果列不存在，使用旧查询
                cur.execute("""
                    SELECT id, task_pattern, NULL as shortcut_command, difficulty, success_rate, 
                           usage_count, updated_at
                    FROM golden_paths
                    ORDER BY usage_count DESC, success_rate DESC
                    LIMIT 50
                """)
            
            rows = cur.fetchall()
            conn.close()
            
            # 清空表格
            self.golden_path_table.setRowCount(0)
            
            # 填充数据
            for row_data in rows:
                row_position = self.golden_path_table.rowCount()
                self.golden_path_table.insertRow(row_position)
                
                # ID
                self.golden_path_table.setItem(
                    row_position, 0, 
                    QTableWidgetItem(str(row_data[0]))
                )
                
                # 任务模式
                task_pattern = row_data[1] or ""
                if len(task_pattern) > 30:
                    task_pattern = task_pattern[:30] + "..."
                self.golden_path_table.setItem(
                    row_position, 1, 
                    QTableWidgetItem(task_pattern)
                )
                
                # 快捷命令
                shortcut = row_data[2] or ""
                shortcut_item = QTableWidgetItem(shortcut)
                if shortcut:
                    shortcut_item.setForeground(QColor("#FF9800"))  # 橙色高亮
                self.golden_path_table.setItem(row_position, 2, shortcut_item)
                
                # 难度
                difficulty = row_data[3] or "medium"
                difficulty_item = QTableWidgetItem(
                    {"simple": "简单", "medium": "中等", "complex": "复杂"}.get(difficulty, difficulty)
                )
                if difficulty == "simple":
                    difficulty_item.setForeground(QColor("#4CAF50"))
                elif difficulty == "complex":
                    difficulty_item.setForeground(QColor("#F44336"))
                self.golden_path_table.setItem(row_position, 3, difficulty_item)
                
                # 成功率
                success_rate = row_data[4] or 0.0
                success_item = QTableWidgetItem(f"{success_rate * 100:.1f}%")
                if success_rate >= 0.8:
                    success_item.setForeground(QColor("#4CAF50"))
                elif success_rate < 0.5:
                    success_item.setForeground(QColor("#F44336"))
                self.golden_path_table.setItem(row_position, 4, success_item)
                
                # 使用次数
                usage_count = row_data[5] or 0
                self.golden_path_table.setItem(
                    row_position, 5,
                    QTableWidgetItem(str(usage_count))
                )
                
                # 最后更新
                updated_at = row_data[6] or ""
                if updated_at:
                    # 只显示日期部分
                    updated_at = updated_at.split()[0] if ' ' in updated_at else updated_at
                self.golden_path_table.setItem(
                    row_position, 6,
                    QTableWidgetItem(updated_at)
                )
            
        except Exception as e:
            print(f"更新黄金路径表格失败: {e}")
    
    def _update_error_pattern_table(self):
        """更新错误模式表格"""
        try:
            conn = self.task_logger._get_conn()
            cur = conn.cursor()
            
            cur.execute("""
                SELECT task_pattern, error_description, correction, frequency
                FROM error_patterns
                ORDER BY frequency DESC
                LIMIT 50
            """)
            
            rows = cur.fetchall()
            conn.close()
            
            # 清空表格
            self.error_pattern_table.setRowCount(0)
            
            # 填充数据
            for row_data in rows:
                row_position = self.error_pattern_table.rowCount()
                self.error_pattern_table.insertRow(row_position)
                
                # 任务模式
                self.error_pattern_table.setItem(
                    row_position, 0,
                    QTableWidgetItem(row_data[0] or "")
                )
                
                # 错误描述（截取前50字符）
                error_desc = row_data[1] or ""
                if len(error_desc) > 50:
                    error_desc = error_desc[:50] + "..."
                self.error_pattern_table.setItem(
                    row_position, 1,
                    QTableWidgetItem(error_desc)
                )
                
                # 纠正方法
                correction = row_data[2] or ""
                self.error_pattern_table.setItem(
                    row_position, 2,
                    QTableWidgetItem(correction)
                )
                
                # 出现次数
                frequency = row_data[3] or 0
                frequency_item = QTableWidgetItem(str(frequency))
                if frequency >= 5:
                    frequency_item.setForeground(QColor("#F44336"))
                self.error_pattern_table.setItem(
                    row_position, 3,
                    frequency_item
                )
            
        except Exception as e:
            print(f"更新错误模式表格失败: {e}")
