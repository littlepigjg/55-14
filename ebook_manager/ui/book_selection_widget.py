from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox, QAbstractItemView
)
from PyQt6.QtCore import Qt

from typing import List
from pathlib import Path

from ..models import BookMeta


class BookSelectionWidget(QWidget):
    def __init__(self, books: List[BookMeta], parent=None):
        super().__init__(parent)
        self._books = books
        self._checkboxes = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_row.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("全不选")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_row.addWidget(self.deselect_all_btn)

        self.invert_btn = QPushButton("反选")
        self.invert_btn.clicked.connect(self._invert_selection)
        btn_row.addWidget(self.invert_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        layout.addWidget(self.list_widget)

        for book in self._books:
            item = QListWidgetItem()
            self.list_widget.addItem(item)

            cb = QCheckBox(f"{book.title} ({Path(book.file_path).name})")
            cb.setChecked(True)
            self._checkboxes[book.file_path] = cb
            self.list_widget.setItemWidget(item, cb)

    def _select_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _deselect_all(self):
        for cb in self._checkboxes.values():
            cb.setChecked(False)

    def _invert_selection(self):
        for cb in self._checkboxes.values():
            cb.setChecked(not cb.isChecked())

    def get_selected_books(self) -> List[BookMeta]:
        return [b for b in self._books if self._checkboxes[b.file_path].isChecked()]

    def is_book_skipped(self, book: BookMeta) -> bool:
        cb = self._checkboxes.get(book.file_path)
        if cb is None:
            return True
        return not cb.isChecked()
