from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QMessageBox, QDialogButtonBox, QGroupBox,
    QTextEdit, QSplitter, QWidget
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QBrush

from typing import List, Optional
from pathlib import Path

from ..models import BookMeta
from ..find_replace_engine import FindReplaceEngine, ReplaceResult
from ..commands import ReplaceCommand
from .book_selection_widget import BookSelectionWidget
from .workers import BatchReplaceWorker


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


class BatchReplaceDialog(QDialog):
    def __init__(
        self,
        engine: FindReplaceEngine,
        books: List[BookMeta],
        pattern: str,
        replacement: str,
        fields: Optional[List[str]] = None,
        use_regex: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("批量查找替换")
        self.setMinimumSize(900, 600)

        self._engine = engine
        self._all_books = books
        self._pattern = pattern
        self._replacement = replacement
        self._fields = fields or ["title", "author", "description"]
        self._use_regex = use_regex
        self._case_sensitive = case_sensitive
        self._whole_word = whole_word

        self._results: List[ReplaceResult] = []
        self._worker: Optional[BatchReplaceWorker] = None
        self._command: Optional[ReplaceCommand] = None
        self._current_book: Optional[BookMeta] = None

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        info_group = QGroupBox("替换信息")
        info_layout = QVBoxLayout(info_group)
        info_label = QLabel(
            f"<b>查找:</b> {self._pattern}<br>"
            f"<b>替换为:</b> {self._replacement}<br>"
            f"<b>字段:</b> {', '.join(FIELD_NAMES.get(f, f) for f in self._fields)}<br>"
            f"<b>模式:</b> {'正则' if self._use_regex else '普通'} | "
            f"{'区分大小写' if self._case_sensitive else '不区分大小写'} | "
            f"{'整词匹配' if self._whole_word else '任意位置'}"
        )
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addWidget(info_label)
        layout.addWidget(info_group)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        books_group = QGroupBox(f"选择书籍（共 {len(self._all_books)} 本）")
        books_layout = QVBoxLayout(books_group)
        self.selection_widget = BookSelectionWidget(self._all_books)
        books_layout.addWidget(self.selection_widget)
        left_layout.addWidget(books_group)

        splitter.addWidget(left_panel)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        progress_group = QGroupBox("处理进度")
        progress_layout = QVBoxLayout(progress_group)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("等待开始...")
        progress_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("▶️ 开始处理")
        self.start_btn.setStyleSheet(
            "QPushButton{background:#4caf50;color:white;border:none;border-radius:4px;padding:8px 16px;font-weight:bold}"
            "QPushButton:hover{background:#388e3c}"
        )
        self.start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self.start_btn)

        self.skip_btn = QPushButton("⏭ 跳过当前")
        self.skip_btn.clicked.connect(self._on_skip_current)
        self.skip_btn.setEnabled(False)
        btn_row.addWidget(self.skip_btn)

        self.cancel_btn = QPushButton("⏹ 取消")
        self.cancel_btn.clicked.connect(self._on_cancel)
        self.cancel_btn.setEnabled(False)
        btn_row.addWidget(self.cancel_btn)
        progress_layout.addLayout(btn_row)

        right_layout.addWidget(progress_group)

        results_group = QGroupBox("处理结果")
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["书名", "字段", "修改数", "状态"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.itemClicked.connect(self._on_result_clicked)
        results_layout.addWidget(self.results_table)

        self.summary_label = QLabel("")
        results_layout.addWidget(self.summary_label)

        right_layout.addWidget(results_group)

        detail_group = QGroupBox("详细信息")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        detail_layout.addWidget(self.detail_text)
        right_layout.addWidget(detail_group)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("✅ 应用更改")
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.button_box.accepted.connect(self._on_apply)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_start(self):
        selected_books = self.selection_widget.get_selected_books()
        if not selected_books:
            QMessageBox.information(self, "提示", "请至少选择一本书")
            return

        reply = QMessageBox.question(
            self, "确认开始",
            f"将对 {len(selected_books)} 本书执行替换操作，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._results = []
        self.results_table.setRowCount(0)
        self.progress_bar.setRange(0, len(selected_books))
        self.progress_bar.setValue(0)

        self.start_btn.setEnabled(False)
        self.selection_widget.setEnabled(False)
        self.skip_btn.setEnabled(True)
        self.cancel_btn.setEnabled(True)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        self._worker = BatchReplaceWorker(
            engine=self._engine,
            books=selected_books,
            pattern=self._pattern,
            replacement=self._replacement,
            fields=self._fields,
            use_regex=self._use_regex,
            case_sensitive=self._case_sensitive,
            whole_word=self._whole_word,
            skip_callback=self.selection_widget.is_book_skipped,
        )
        self._worker.progress_updated.connect(self._on_progress)
        self._worker.book_started.connect(self._on_book_started)
        self._worker.book_finished.connect(self._on_book_finished)
        self._worker.finished_all.connect(self._on_finished)
        self._worker.start()

    def _on_book_started(self, current: int, total: int, book: BookMeta):
        self._current_book = book

    def _on_book_finished(self, current: int, total: int, book: BookMeta):
        if self._current_book is book:
            pass

    def _on_progress(self, current: int, total: int, book: BookMeta, results: List[ReplaceResult]):
        self._current_book = book
        self.progress_bar.setValue(current)

        all_skipped = all(r.skipped for r in results)
        if all_skipped:
            self.status_label.setText(f"已跳过 {current}/{total}: {book.title}")
        else:
            self.status_label.setText(f"处理完成 {current}/{total}: {book.title}")

        for result in results:
            self._add_result_row(result)

    def _add_result_row(self, result: ReplaceResult):
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        self.results_table.setItem(row, 0, QTableWidgetItem(result.book.title))

        field_name = FIELD_NAMES.get(result.field, result.field)
        if result.skipped:
            field_name = "—"
        elif result.error:
            field_name = "错误"
        self.results_table.setItem(row, 1, QTableWidgetItem(field_name))

        count_item = QTableWidgetItem(str(result.count) if not result.skipped and not result.error else "—")
        if result.count > 0:
            count_item.setForeground(QBrush(QColor(76, 175, 80)))
        self.results_table.setItem(row, 2, count_item)

        status_text = "✓ 成功"
        status_color = QColor(76, 175, 80)
        if result.skipped:
            status_text = "⏭ 已跳过"
            status_color = QColor(255, 152, 0)
        elif result.error:
            status_text = f"✗ 错误: {result.error}"
            status_color = QColor(244, 67, 54)
        elif result.count == 0:
            status_text = "— 无匹配"
            status_color = QColor(158, 158, 158)

        status_item = QTableWidgetItem(status_text)
        status_item.setForeground(QBrush(status_color))
        self.results_table.setItem(row, 3, status_item)

        self.results_table.item(row, 0).setData(Qt.ItemDataRole.UserRole, result)

        self._results.append(result)
        self._update_summary()

    def _update_summary(self):
        total_books = len(set(r.book.file_path for r in self._results))
        changed = sum(1 for r in self._results if r.count > 0 and not r.error and not r.skipped)
        total_changes = sum(r.count for r in self._results if not r.error and not r.skipped)
        errors = sum(1 for r in self._results if r.error)
        skipped = sum(1 for r in self._results if r.skipped)

        self.summary_label.setText(
            f"总计: {total_books} 本书 | "
            f"修改: {changed} 处 | "
            f"替换: {total_changes} 处 | "
            f"错误: {errors} | "
            f"跳过: {skipped}"
        )

    def _on_result_clicked(self, item: QTableWidgetItem):
        result = self.results_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        if not result:
            return

        text = f"书籍: {result.book.title}\n"
        text += f"文件: {result.book.file_path}\n"
        text += f"字段: {FIELD_NAMES.get(result.field, result.field)}\n\n"

        if result.skipped:
            text += "状态: 已跳过（用户请求跳过或未勾选）\n"
        elif result.error:
            text += f"状态: 错误\n{result.error}\n"
        elif result.count == 0:
            text += "状态: 无匹配\n"
        else:
            text += f"状态: 修改 {result.count} 处\n\n"
            text += f"原值:\n{result.original_value}\n\n"
            text += f"新值:\n{result.new_value}\n\n"
            text += "详细修改:\n"
            for i, m in enumerate(result.matches, 1):
                text += f"  {i}. 位置 {m.start}-{m.end}: '{m.original}' -> '{m.replaced}'\n"

        self.detail_text.setPlainText(text)

    def _on_skip_current(self):
        if self._worker and self._current_book:
            self._worker.skip_book(self._current_book.file_path)
            self.status_label.setText(
                f"已请求跳过: {self._current_book.title}\n"
                f"（当前处理完毕后立即生效，若已在处理中则丢弃结果）"
            )

    def _on_cancel(self):
        if self._worker:
            reply = QMessageBox.question(
                self, "确认取消",
                "确定要取消处理吗？已完成的更改将不会应用。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._worker.cancel()
                self.status_label.setText("正在取消...")

    def _on_finished(self, results: List[ReplaceResult]):
        self._worker = None
        self._all_results = results

        total_changes = sum(r.count for r in results if not r.error and not r.skipped)
        total_skipped = sum(1 for r in results if r.skipped)

        if total_skipped > 0:
            self.status_label.setText(
                f"处理完成！共修改 {total_changes} 处，跳过 {total_skipped} 处"
            )
        else:
            self.status_label.setText(f"处理完成！共修改 {total_changes} 处")

        self.start_btn.setEnabled(True)
        self.selection_widget.setEnabled(True)
        self.skip_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)

        has_changes = any(r.count > 0 and not r.error and not r.skipped for r in results)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(has_changes)

        if total_changes == 0:
            if total_skipped > 0:
                QMessageBox.information(
                    self, "完成",
                    f"没有替换内容。共跳过 {total_skipped} 项。"
                )
            else:
                QMessageBox.information(self, "完成", "没有找到可替换的内容")

    def _on_apply(self):
        skipped_keys = set()
        for r in self._all_results:
            if r.skipped:
                skipped_keys.add(r.book.file_path or id(r.book))

        changed_books = []
        seen = set()
        for r in self._all_results:
            key = r.book.file_path or id(r.book)
            if key in skipped_keys:
                continue
            if r.count > 0 and not r.error and not r.skipped:
                if key not in seen:
                    seen.add(key)
                    changed_books.append(r.book)

        if not changed_books:
            QMessageBox.information(self, "提示", "没有需要应用的更改")
            self.reject()
            return

        reply = QMessageBox.question(
            self, "确认应用",
            f"将对 {len(changed_books)} 本书应用更改，共修改 "
            f"{sum(r.count for r in self._all_results if r.count > 0)} 处。\n\n"
            "应用后可以在历史记录中撤销。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._command = ReplaceCommand(
                engine=self._engine,
                books=changed_books,
                pattern=self._pattern,
                replacement=self._replacement,
                results=self._all_results,
                fields=self._fields,
                use_regex=self._use_regex,
                case_sensitive=self._case_sensitive,
                whole_word=self._whole_word,
            )
            self._command.execute()

            epub_errors = []
            for book in changed_books:
                if book.file_format == "epub":
                    valid, msg = self._engine.validate_after_replace(book)
                    if not valid:
                        epub_errors.append(f"{book.title}: {msg}")

            if epub_errors:
                QMessageBox.warning(
                    self, "EPUB 验证警告",
                    "以下书籍的EPUB结构验证失败，建议撤销：\n\n" + "\n".join(epub_errors)
                )

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "应用失败", f"应用更改时发生错误: {e}")

    def get_command(self) -> Optional[ReplaceCommand]:
        return self._command

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        super().closeEvent(event)
