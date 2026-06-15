from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QTextEdit, QPushButton, QGroupBox, QLabel, QListWidget, QListWidgetItem,
    QCheckBox, QComboBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QMessageBox, QInputDialog, QDialog,
    QDialogButtonBox, QColorDialog, QFrame, QMenu
)
from PyQt6.QtCore import pyqtSignal, Qt, QThread
from PyQt6.QtGui import QColor, QTextCharFormat, QBrush, QFont, QAction

from typing import List, Optional
from pathlib import Path

from ..models import BookMeta
from ..find_replace_engine import FindReplaceEngine, MatchResult, ReplaceResult
from ..commands import CommandHistory, ReplaceCommand
from ..replace_rules import RuleLibrary, ReplaceRule


FIELD_NAMES = {
    "title": "书名",
    "author": "作者",
    "publisher": "出版社",
    "publish_date": "出版日期",
    "isbn": "ISBN",
    "language": "语言",
    "description": "简介",
    "tags": "标签",
}


class PreviewWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self._highlights = []

    def set_text_with_highlights(self, text: str, matches: List[MatchResult]):
        self.clear()
        self._highlights = matches

        self.setText(text)

        fmt = QTextCharFormat()
        fmt.setBackground(QBrush(QColor(255, 235, 59)))
        fmt.setFontWeight(QFont.Weight.Bold)

        cursor = self.textCursor()
        for match in matches:
            cursor.setPosition(match.start)
            cursor.setPosition(match.end, cursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt)

    def set_text_with_replace_preview(self, text: str, matches: List[MatchResult]):
        self.clear()
        cursor = self.textCursor()

        fmt_match = QTextCharFormat()
        fmt_match.setBackground(QBrush(QColor(255, 183, 77)))
        fmt_match.setFontWeight(QFont.Weight.Bold)
        fmt_match.setForeground(QBrush(QColor(183, 28, 28)))

        fmt_replace = QTextCharFormat()
        fmt_replace.setBackground(QBrush(QColor(129, 199, 132)))
        fmt_replace.setFontWeight(QFont.Weight.Bold)
        fmt_replace.setForeground(QBrush(QColor(27, 94, 32)))

        last_end = 0
        for match in sorted(matches, key=lambda m: m.start):
            if match.start > last_end:
                cursor.insertText(text[last_end:match.start])

            cursor.insertText(match.original, fmt_match)
            cursor.insertText(" → ")

            if match.replaced:
                cursor.insertText(match.replaced, fmt_replace)
            else:
                cursor.insertText("?", fmt_replace)

            last_end = match.end

        if last_end < len(text):
            cursor.insertText(text[last_end:])


class RuleEditDialog(QDialog):
    def __init__(self, rule: Optional[ReplaceRule] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑替换规则" if rule else "新建替换规则")
        self.setMinimumWidth(500)
        self._rule = rule

        self._init_ui()
        if rule:
            self._load_rule(rule)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit()
        form.addRow("规则名称:", self.name_edit)

        self.category_edit = QLineEdit()
        self.category_edit.setPlaceholderText("如: OCR纠错、格式统一")
        form.addRow("分类:", self.category_edit)

        self.desc_edit = QLineEdit()
        form.addRow("描述:", self.desc_edit)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("如: \\b(曰|日)\\b")
        form.addRow("查找模式:", self.pattern_edit)

        self.replacement_edit = QLineEdit()
        self.replacement_edit.setPlaceholderText("如: 日 或 \\1-\\2-\\3")
        form.addRow("替换为:", self.replacement_edit)

        self.use_regex_cb = QCheckBox("使用正则表达式")
        self.use_regex_cb.setChecked(True)
        form.addRow("", self.use_regex_cb)

        self.case_sensitive_cb = QCheckBox("区分大小写")
        form.addRow("", self.case_sensitive_cb)

        self.whole_word_cb = QCheckBox("整词匹配")
        form.addRow("", self.whole_word_cb)

        fields_group = QGroupBox("应用到字段")
        fields_layout = QHBoxLayout(fields_group)
        self.field_cbs = {}
        for field, label in FIELD_NAMES.items():
            cb = QCheckBox(label)
            if field in ["title", "author", "description"]:
                cb.setChecked(True)
            self.field_cbs[field] = cb
            fields_layout.addWidget(cb)
        form.addRow(fields_group)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_rule(self, rule: ReplaceRule):
        self.name_edit.setText(rule.name)
        self.category_edit.setText(rule.category)
        self.desc_edit.setText(rule.description)
        self.pattern_edit.setText(rule.pattern)
        self.replacement_edit.setText(rule.replacement)
        self.use_regex_cb.setChecked(rule.use_regex)
        self.case_sensitive_cb.setChecked(rule.case_sensitive)
        self.whole_word_cb.setChecked(rule.whole_word)
        for field, cb in self.field_cbs.items():
            cb.setChecked(field in rule.fields)

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入规则名称")
            return
        if not self.pattern_edit.text().strip():
            QMessageBox.warning(self, "提示", "请输入查找模式")
            return
        self.accept()

    def get_rule(self) -> ReplaceRule:
        fields = [f for f, cb in self.field_cbs.items() if cb.isChecked()]
        return ReplaceRule(
            name=self.name_edit.text().strip(),
            pattern=self.pattern_edit.text().strip(),
            replacement=self.replacement_edit.text().strip(),
            description=self.desc_edit.text().strip(),
            category=self.category_edit.text().strip() or "自定义",
            use_regex=self.use_regex_cb.isChecked(),
            case_sensitive=self.case_sensitive_cb.isChecked(),
            whole_word=self.whole_word_cb.isChecked(),
            fields=fields,
            is_builtin=False,
        )


class FindReplacePanel(QWidget):
    replace_executed = pyqtSignal(object)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: List[BookMeta] = []
        self._current_matches: List[MatchResult] = []
        self._engine = FindReplaceEngine(regex_timeout=5.0)
        self._rule_library = RuleLibrary()
        self._history = CommandHistory(max_history=100)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._create_find_replace_tab(), "查找替换")
        self.tabs.addTab(self._create_rules_tab(), "规则库")
        self.tabs.addTab(self._create_history_tab(), "历史记录")

    def _create_find_replace_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        search_group = QGroupBox("查找选项")
        search_layout = QFormLayout(search_group)

        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("输入要查找的内容或正则表达式")
        self.find_edit.returnPressed.connect(self._on_find)
        search_layout.addRow("查找:", self.find_edit)

        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("输入替换后的内容（支持反向引用 \\1, \\2 等）")
        search_layout.addRow("替换为:", self.replace_edit)

        opt_row = QHBoxLayout()
        self.use_regex_cb = QCheckBox("正则表达式")
        self.use_regex_cb.setChecked(True)
        self.use_regex_cb.toggled.connect(self._on_regex_toggled)
        opt_row.addWidget(self.use_regex_cb)

        self.case_sensitive_cb = QCheckBox("区分大小写")
        opt_row.addWidget(self.case_sensitive_cb)

        self.whole_word_cb = QCheckBox("整词匹配")
        opt_row.addWidget(self.whole_word_cb)

        self.timeout_spin = QComboBox()
        self.timeout_spin.addItems(["1秒", "3秒", "5秒", "10秒", "30秒"])
        self.timeout_spin.setCurrentIndex(2)
        self.timeout_spin.currentIndexChanged.connect(self._on_timeout_changed)
        opt_row.addWidget(QLabel("超时:"))
        opt_row.addWidget(self.timeout_spin)

        opt_row.addStretch()
        search_layout.addRow("", opt_row)

        fields_group = QGroupBox("搜索字段（可多选）")
        fields_layout = QHBoxLayout(fields_group)
        self.field_cbs = {}
        for field, label in FIELD_NAMES.items():
            cb = QCheckBox(label)
            if field in ["title", "description"]:
                cb.setChecked(True)
            self.field_cbs[field] = cb
            fields_layout.addWidget(cb)
        search_layout.addRow(fields_group)

        btn_row = QHBoxLayout()
        self.find_btn = QPushButton("🔍 查找")
        self.find_btn.clicked.connect(self._on_find)
        btn_row.addWidget(self.find_btn)

        self.preview_btn = QPushButton("👁 预览替换")
        self.preview_btn.clicked.connect(self._on_preview)
        btn_row.addWidget(self.preview_btn)

        self.replace_btn = QPushButton("🔄 替换全部")
        self.replace_btn.setStyleSheet(
            "QPushButton{background:#4a9eff;color:white;border:none;border-radius:4px;padding:8px 16px;font-weight:bold}"
            "QPushButton:hover{background:#3d8be0}"
        )
        self.replace_btn.clicked.connect(self._on_replace)
        btn_row.addWidget(self.replace_btn)

        self.batch_btn = QPushButton("📚 批量应用到多本书")
        self.batch_btn.clicked.connect(self._on_batch_replace)
        btn_row.addWidget(self.batch_btn)

        btn_row.addStretch()
        search_layout.addRow("", btn_row)

        layout.addWidget(search_group)

        splitter = QSplitter(Qt.Orientation.Vertical)

        matches_group = QGroupBox("匹配结果")
        matches_layout = QVBoxLayout(matches_group)

        self.matches_table = QTableWidget(0, 4)
        self.matches_table.setHorizontalHeaderLabels(["字段", "位置", "原文", "上下文"])
        self.matches_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.matches_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.matches_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.matches_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.matches_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.matches_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.matches_table.itemClicked.connect(self._on_match_selected)
        matches_layout.addWidget(self.matches_table)

        self.matches_label = QLabel("共找到 0 处匹配")
        matches_layout.addWidget(self.matches_label)

        splitter.addWidget(matches_group)

        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_tabs = QTabWidget()
        self.preview_tabs.addTab(self._create_preview_tab("match"), "原文高亮")
        self.preview_tabs.addTab(self._create_preview_tab("replace"), "替换预览")
        preview_layout.addWidget(self.preview_tabs)

        splitter.addWidget(preview_group)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        return widget

    def _create_preview_tab(self, mode: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        preview = PreviewWidget()
        if mode == "match":
            self.match_preview = preview
        else:
            self.replace_preview = preview

        layout.addWidget(preview)
        return widget

    def _create_rules_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        tool_row = QHBoxLayout()
        self.rule_category_combo = QComboBox()
        self.rule_category_combo.addItem("全部分类")
        for cat in self._rule_library.get_categories():
            self.rule_category_combo.addItem(cat)
        self.rule_category_combo.currentIndexChanged.connect(self._refresh_rules_list)
        tool_row.addWidget(QLabel("分类:"))
        tool_row.addWidget(self.rule_category_combo)

        self.rule_search_edit = QLineEdit()
        self.rule_search_edit.setPlaceholderText("搜索规则...")
        self.rule_search_edit.textChanged.connect(self._refresh_rules_list)
        tool_row.addWidget(self.rule_search_edit)
        tool_row.addStretch()

        self.add_rule_btn = QPushButton("➕ 新建规则")
        self.add_rule_btn.clicked.connect(self._on_add_rule)
        tool_row.addWidget(self.add_rule_btn)

        self.edit_rule_btn = QPushButton("✏️ 编辑规则")
        self.edit_rule_btn.clicked.connect(self._on_edit_rule)
        tool_row.addWidget(self.edit_rule_btn)

        self.delete_rule_btn = QPushButton("🗑 删除规则")
        self.delete_rule_btn.clicked.connect(self._on_delete_rule)
        tool_row.addWidget(self.delete_rule_btn)

        layout.addLayout(tool_row)

        self.rules_list = QListWidget()
        self.rules_list.itemDoubleClicked.connect(self._on_rule_activated)
        self.rules_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rules_list.customContextMenuRequested.connect(self._on_rules_context_menu)
        layout.addWidget(self.rules_list)

        self.apply_rule_btn = QPushButton("▶️ 应用选中规则")
        self.apply_rule_btn.setStyleSheet(
            "QPushButton{background:#4caf50;color:white;border:none;border-radius:4px;padding:8px 16px;font-weight:bold}"
            "QPushButton:hover{background:#388e3c}"
        )
        self.apply_rule_btn.clicked.connect(self._on_apply_rule)
        layout.addWidget(self.apply_rule_btn)

        self._refresh_rules_list()
        return widget

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        btn_row = QHBoxLayout()
        self.undo_btn = QPushButton("↩️ 撤销")
        self.undo_btn.clicked.connect(self._on_undo)
        btn_row.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("↪️ 重做")
        self.redo_btn.clicked.connect(self._on_redo)
        btn_row.addWidget(self.redo_btn)

        self.batch_undo_btn = QPushButton("⏮ 批量撤销")
        self.batch_undo_btn.clicked.connect(self._on_batch_undo)
        btn_row.addWidget(self.batch_undo_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        history_splitter = QSplitter(Qt.Orientation.Horizontal)

        undo_group = QGroupBox("可撤销操作")
        undo_layout = QVBoxLayout(undo_group)
        self.undo_list = QListWidget()
        undo_layout.addWidget(self.undo_list)
        history_splitter.addWidget(undo_group)

        redo_group = QGroupBox("可重做操作")
        redo_layout = QVBoxLayout(redo_group)
        self.redo_list = QListWidget()
        redo_layout.addWidget(self.redo_list)
        history_splitter.addWidget(redo_group)

        layout.addWidget(history_splitter)

        self._refresh_history_buttons()
        return widget

    def set_books(self, books: List[BookMeta]):
        self._books = books
        if books and len(books) == 1:
            self.batch_btn.setText(f"📚 批量应用到多本书（当前选中 {len(books)} 本）")
        elif books:
            self.batch_btn.setText(f"📚 批量应用到 {len(books)} 本书")
        else:
            self.batch_btn.setText("📚 批量应用到多本书")

    def _get_selected_fields(self) -> List[str]:
        return [f for f, cb in self.field_cbs.items() if cb.isChecked()]

    def _on_regex_toggled(self, checked: bool):
        self.whole_word_cb.setEnabled(not checked)

    def _on_timeout_changed(self, index: int):
        timeouts = [1.0, 3.0, 5.0, 10.0, 30.0]
        self._engine = FindReplaceEngine(regex_timeout=timeouts[index])

    def _on_find(self):
        pattern = self.find_edit.text()
        if not pattern:
            QMessageBox.information(self, "提示", "请输入要查找的内容")
            return

        fields = self._get_selected_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请至少选择一个搜索字段")
            return

        if not self._books:
            QMessageBox.information(self, "提示", "请先选择书籍")
            return

        try:
            all_matches = []
            for book in self._books:
                matches = self._engine.find_in_book(
                    book, pattern, fields,
                    use_regex=self.use_regex_cb.isChecked(),
                    case_sensitive=self.case_sensitive_cb.isChecked(),
                    whole_word=self.whole_word_cb.isChecked(),
                )
                for m in matches:
                    m.book_title = book.title
                    m.book_path = book.file_path
                all_matches.extend(matches)

            self._current_matches = all_matches
            self._update_matches_table(all_matches)
            self._update_match_preview()
        except RuntimeError as e:
            QMessageBox.critical(self, "搜索错误", str(e))

    def _update_matches_table(self, matches: List[MatchResult]):
        self.matches_table.setRowCount(0)
        for i, match in enumerate(matches):
            self.matches_table.insertRow(i)

            field_item = QTableWidgetItem(FIELD_NAMES.get(match.field, match.field))
            field_item.setData(Qt.ItemDataRole.UserRole, match)
            self.matches_table.setItem(i, 0, field_item)

            self.matches_table.setItem(i, 1, QTableWidgetItem(f"{match.start}-{match.end}"))

            orig_item = QTableWidgetItem(match.original)
            orig_item.setBackground(QColor(255, 235, 59))
            self.matches_table.setItem(i, 2, orig_item)

            context = f"...{match.context_before}<mark>{match.original}</mark>{match.context_after}..."
            self.matches_table.setItem(i, 3, QTableWidgetItem(context))

        self.matches_label.setText(f"共找到 {len(matches)} 处匹配")

    def _on_match_selected(self, item: QTableWidgetItem):
        match = self.matches_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        if match and self._books:
            for book in self._books:
                value = getattr(book, match.field, "")
                if isinstance(value, list):
                    value = ", ".join(value)
                if value and match.start < len(value):
                    self.match_preview.set_text_with_highlights(value, [match])
                    break

    def _update_match_preview(self):
        if self._current_matches and self._books:
            book = self._books[0]
            matches_by_field = {}
            for m in self._current_matches:
                if m.field not in matches_by_field:
                    matches_by_field[m.field] = []
                matches_by_field[m.field].append(m)

            for field, matches in matches_by_field.items():
                value = getattr(book, field, "")
                if isinstance(value, list):
                    value = ", ".join(value)
                if value:
                    self.match_preview.set_text_with_highlights(value, matches)
                    break

    def _on_preview(self):
        pattern = self.find_edit.text()
        replacement = self.replace_edit.text()
        if not pattern:
            QMessageBox.information(self, "提示", "请输入要查找的内容")
            return

        fields = self._get_selected_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请至少选择一个搜索字段")
            return

        if not self._books:
            QMessageBox.information(self, "提示", "请先选择书籍")
            return

        try:
            book = self._books[0]
            results = self._engine.replace_in_book(
                book, pattern, replacement, fields,
                use_regex=self.use_regex_cb.isChecked(),
                case_sensitive=self.case_sensitive_cb.isChecked(),
                whole_word=self.whole_word_cb.isChecked(),
            )

            all_matches = []
            for r in results:
                if r.matches:
                    all_matches.extend(r.matches)

            self._current_matches = all_matches
            self._update_matches_table(all_matches)

            for r in results:
                if r.matches:
                    value = getattr(book, r.field, "")
                    if isinstance(value, list):
                        value = ", ".join(value)
                    if value:
                        self.replace_preview.set_text_with_replace_preview(value, r.matches)
                        break

            total = sum(r.count for r in results)
            self.matches_label.setText(f"预览: 共 {total} 处将被替换")
            self.preview_tabs.setCurrentIndex(1)
        except RuntimeError as e:
            QMessageBox.critical(self, "预览错误", str(e))

    def _on_replace(self):
        pattern = self.find_edit.text()
        replacement = self.replace_edit.text()
        if not pattern:
            QMessageBox.information(self, "提示", "请输入要查找的内容")
            return

        fields = self._get_selected_fields()
        if not fields:
            QMessageBox.information(self, "提示", "请至少选择一个搜索字段")
            return

        if not self._books:
            QMessageBox.information(self, "提示", "请先选择书籍")
            return

        reply = QMessageBox.question(
            self, "确认替换",
            f"将对 {len(self._books)} 本书执行替换操作\n"
            f"查找: {pattern}\n"
            f"替换为: {replacement}\n\n"
            "是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            all_results = []
            for book in self._books:
                results = self._engine.replace_in_book(
                    book, pattern, replacement, fields,
                    use_regex=self.use_regex_cb.isChecked(),
                    case_sensitive=self.case_sensitive_cb.isChecked(),
                    whole_word=self.whole_word_cb.isChecked(),
                )
                all_results.extend(results)

            total_matches = sum(r.count for r in all_results)
            if total_matches == 0:
                QMessageBox.information(self, "提示", "没有找到可替换的内容")
                return

            command = ReplaceCommand(
                engine=self._engine,
                books=self._books,
                pattern=pattern,
                replacement=replacement,
                results=all_results,
                fields=fields,
                use_regex=self.use_regex_cb.isChecked(),
                case_sensitive=self.case_sensitive_cb.isChecked(),
                whole_word=self.whole_word_cb.isChecked(),
            )
            command.execute()

            valid, msg = True, ""
            for book in command.affected_books:
                if book.file_format == "epub":
                    valid, msg = self._engine.validate_after_replace(book)
                    if not valid:
                        break

            if not valid:
                QMessageBox.warning(self, "EPUB 验证警告", f"替换后EPUB结构验证失败:\n{msg}\n建议撤销此操作")

            self._history.push(command)
            self._refresh_history_buttons()
            self.replace_executed.emit(command)

            QMessageBox.information(
                self, "替换完成",
                f"已完成替换:\n"
                f"- 修改书籍: {len(command.affected_books)} 本\n"
                f"- 修改位置: {total_matches} 处"
            )

            self._current_matches = []
            self._update_matches_table([])
        except RuntimeError as e:
            QMessageBox.critical(self, "替换错误", str(e))

    def _on_batch_replace(self):
        from .batch_replace_dialog import BatchReplaceDialog

        pattern = self.find_edit.text()
        replacement = self.replace_edit.text()
        if not pattern:
            QMessageBox.information(self, "提示", "请输入要查找的内容")
            return

        if not self._books:
            QMessageBox.information(self, "提示", "请先选择书籍")
            return

        dialog = BatchReplaceDialog(
            self._engine,
            self._books,
            pattern,
            replacement,
            fields=self._get_selected_fields(),
            use_regex=self.use_regex_cb.isChecked(),
            case_sensitive=self.case_sensitive_cb.isChecked(),
            whole_word=self.whole_word_cb.isChecked(),
            parent=self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            command = dialog.get_command()
            if command:
                self._history.push(command)
                self._refresh_history_buttons()
                self.replace_executed.emit(command)

    def _refresh_rules_list(self):
        self.rules_list.clear()
        category = self.rule_category_combo.currentText()
        keyword = self.rule_search_edit.text().strip()

        if keyword:
            rules = self._rule_library.search_rules(keyword)
        elif category == "全部分类":
            rules = self._rule_library.get_all_rules()
        else:
            rules = self._rule_library.get_rules_by_category(category)

        for rule in rules:
            prefix = "📦 " if rule.is_builtin else "🔧 "
            item = QListWidgetItem(f"{prefix}{rule.name}")
            item.setToolTip(f"{rule.description}\n\n模式: {rule.pattern}\n替换: {rule.replacement}")
            item.setData(Qt.ItemDataRole.UserRole, rule)
            self.rules_list.addItem(item)

    def _get_selected_rule(self) -> Optional[ReplaceRule]:
        item = self.rules_list.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None

    def _get_selected_rule_index(self) -> int:
        item = self.rules_list.currentItem()
        if not item:
            return -1

        rule = item.data(Qt.ItemDataRole.UserRole)
        if not rule:
            return -1

        all_rules = self._rule_library.get_all_rules()
        for i, r in enumerate(all_rules):
            if r.name == rule.name and r.pattern == rule.pattern:
                return i
        return -1

    def _on_add_rule(self):
        dialog = RuleEditDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rule = dialog.get_rule()
            self._rule_library.add_rule(rule)
            self._refresh_rules_list()
            self.rule_category_combo.clear()
            self.rule_category_combo.addItem("全部分类")
            for cat in self._rule_library.get_categories():
                self.rule_category_combo.addItem(cat)

    def _on_edit_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一个规则")
            return
        if rule.is_builtin:
            QMessageBox.warning(self, "提示", "内置规则不能编辑")
            return

        index = self._get_selected_rule_index()
        dialog = RuleEditDialog(rule, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_rule = dialog.get_rule()
            self._rule_library.update_rule(index, new_rule)
            self._refresh_rules_list()

    def _on_delete_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一个规则")
            return
        if rule.is_builtin:
            QMessageBox.warning(self, "提示", "内置规则不能删除")
            return

        reply = QMessageBox.question(
            self, "确认删除", f"确定要删除规则 '{rule.name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            index = self._get_selected_rule_index()
            self._rule_library.delete_rule(index)
            self._refresh_rules_list()

    def _on_rule_activated(self, item: QListWidgetItem):
        self._on_apply_rule()

    def _on_apply_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            QMessageBox.information(self, "提示", "请先选择一个规则")
            return

        self.find_edit.setText(rule.pattern)
        self.replace_edit.setText(rule.replacement)
        self.use_regex_cb.setChecked(rule.use_regex)
        self.case_sensitive_cb.setChecked(rule.case_sensitive)
        self.whole_word_cb.setChecked(rule.whole_word)

        for field, cb in self.field_cbs.items():
            cb.setChecked(field in rule.fields)

        self.tabs.setCurrentIndex(0)

    def _on_rules_context_menu(self, pos):
        rule = self._get_selected_rule()
        if not rule:
            return

        menu = QMenu(self)

        apply_action = QAction("应用规则", self)
        apply_action.triggered.connect(self._on_apply_rule)
        menu.addAction(apply_action)

        if not rule.is_builtin:
            menu.addSeparator()
            edit_action = QAction("编辑规则", self)
            edit_action.triggered.connect(self._on_edit_rule)
            menu.addAction(edit_action)

            delete_action = QAction("删除规则", self)
            delete_action.triggered.connect(self._on_delete_rule)
            menu.addAction(delete_action)

        menu.exec(self.rules_list.mapToGlobal(pos))

    def _refresh_history_buttons(self):
        self.undo_btn.setEnabled(self._history.can_undo())
        self.undo_btn.setText(self._history.undo_description())
        self.redo_btn.setEnabled(self._history.can_redo())
        self.redo_btn.setText(self._history.redo_description())

        self.undo_list.clear()
        for desc in self._history.undo_list():
            self.undo_list.addItem(desc)

        self.redo_list.clear()
        for desc in self._history.redo_list():
            self.redo_list.addItem(desc)

    def _on_undo(self):
        command = self._history.undo()
        if command:
            self.undo_requested.emit()
            self._refresh_history_buttons()
            QMessageBox.information(self, "撤销完成", command.description)

    def _on_redo(self):
        command = self._history.redo()
        if command:
            self.redo_requested.emit()
            self._refresh_history_buttons()
            QMessageBox.information(self, "重做完成", command.description)

    def _on_batch_undo(self):
        if not self._history.can_undo():
            return

        count, ok = QInputDialog.getInt(
            self, "批量撤销",
            f"请输入要撤销的操作数量 (最多 {self._history.undo_count} 步):",
            1, 1, self._history.undo_count
        )
        if ok and count > 0:
            commands = self._history.batch_undo(count)
            self.undo_requested.emit()
            self._refresh_history_buttons()
            QMessageBox.information(self, "批量撤销完成", f"已撤销 {len(commands)} 步操作")

    @property
    def history(self) -> CommandHistory:
        return self._history

    @property
    def engine(self) -> FindReplaceEngine:
        return self._engine
