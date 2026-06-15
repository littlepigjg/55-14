from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from abc import ABC, abstractmethod

from .models import BookMeta
from .find_replace_engine import ReplaceResult, FindReplaceEngine


class Command(ABC):
    @abstractmethod
    def execute(self) -> None:
        pass

    @abstractmethod
    def undo(self) -> None:
        pass

    @abstractmethod
    def redo(self) -> None:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass


@dataclass
class FieldSnapshot:
    field: str
    old_value: Any
    new_value: Any


@dataclass
class BookSnapshot:
    book: BookMeta
    fields: List[FieldSnapshot] = field(default_factory=list)

    def restore(self) -> None:
        for fs in self.fields:
            if hasattr(self.book, fs.field):
                setattr(self.book, fs.field, fs.old_value)

    def apply_new(self) -> None:
        for fs in self.fields:
            if hasattr(self.book, fs.field):
                setattr(self.book, fs.field, fs.new_value)


class ReplaceCommand(Command):
    def __init__(
        self,
        engine: FindReplaceEngine,
        books: List[BookMeta],
        pattern: str,
        replacement: str,
        results: List[ReplaceResult],
        fields: Optional[List[str]] = None,
        use_regex: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ):
        self._engine = engine
        self._books = books
        self._pattern = pattern
        self._replacement = replacement
        self._results = results
        self._fields = fields
        self._use_regex = use_regex
        self._case_sensitive = case_sensitive
        self._whole_word = whole_word
        self._snapshots: Dict[str, BookSnapshot] = {}
        self._epub_saved: Dict[str, bool] = {}
        self._executed = False
        self._create_snapshots()

    def _create_snapshots(self) -> None:
        book_results: Dict[str, List[ReplaceResult]] = {}
        for r in self._results:
            if r.count > 0 and not r.error and not r.skipped:
                key = r.book.file_path or id(r.book)
                if key not in book_results:
                    book_results[key] = []
                book_results[key].append(r)

        for key, results in book_results.items():
            book = results[0].book
            snapshot = BookSnapshot(book=book)
            for r in results:
                old_val = getattr(book, r.field, "")
                if isinstance(old_val, list):
                    old_val = list(old_val)
                snapshot.fields.append(FieldSnapshot(
                    field=r.field,
                    old_value=old_val,
                    new_value=r.new_value,
                ))
            self._snapshots[key] = snapshot

    @property
    def description(self) -> str:
        total_changes = sum(1 for r in self._results if r.count > 0 and not r.error and not r.skipped)
        return f"替换 '{self._pattern}' -> '{self._replacement}' ({total_changes}处修改)"

    @property
    def total_matches(self) -> int:
        return sum(r.count for r in self._results if not r.error and not r.skipped)

    @property
    def affected_books(self) -> List[BookMeta]:
        seen = set()
        books = []
        for r in self._results:
            if r.count > 0 and not r.error and not r.skipped:
                key = r.book.file_path or id(r.book)
                if key not in seen:
                    seen.add(key)
                    books.append(r.book)
        return books

    @property
    def results(self) -> List[ReplaceResult]:
        return self._results

    def execute(self) -> None:
        if self._executed:
            self.redo()
            return

        for snapshot in self._snapshots.values():
            snapshot.apply_new()
            if snapshot.book.file_format == "epub" and snapshot.book.file_path:
                from .metadata_editor import MetadataEditor
                editor = MetadataEditor()
                saved = editor.save_epub_metadata(snapshot.book)
                self._epub_saved[snapshot.book.file_path] = saved

        self._executed = True

    def undo(self) -> None:
        if not self._executed:
            return

        for snapshot in self._snapshots.values():
            snapshot.restore()
            if snapshot.book.file_format == "epub" and snapshot.book.file_path:
                if self._epub_saved.get(snapshot.book.file_path, False):
                    from .metadata_editor import MetadataEditor
                    editor = MetadataEditor()
                    editor.save_epub_metadata(snapshot.book)

    def redo(self) -> None:
        if not self._executed:
            return

        for snapshot in self._snapshots.values():
            snapshot.apply_new()
            if snapshot.book.file_format == "epub" and snapshot.book.file_path:
                if self._epub_saved.get(snapshot.book.file_path, False):
                    from .metadata_editor import MetadataEditor
                    editor = MetadataEditor()
                    editor.save_epub_metadata(snapshot.book)


class CommandHistory:
    def __init__(self, max_history: int = 100):
        self._max_history = max_history
        self._undo_stack: List[Command] = []
        self._redo_stack: List[Command] = []

    def push(self, command: Command) -> None:
        if len(self._undo_stack) >= self._max_history:
            self._undo_stack.pop(0)
        self._undo_stack.append(command)
        self._redo_stack.clear()

    def undo(self) -> Optional[Command]:
        if not self._undo_stack:
            return None
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        return command

    def redo(self) -> Optional[Command]:
        if not self._redo_stack:
            return None
        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        return command

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo_description(self) -> str:
        if self._undo_stack:
            return f"撤销: {self._undo_stack[-1].description}"
        return "撤销"

    def redo_description(self) -> str:
        if self._redo_stack:
            return f"重做: {self._redo_stack[-1].description}"
        return "重做"

    def undo_list(self) -> List[str]:
        return [cmd.description for cmd in reversed(self._undo_stack)]

    def redo_list(self) -> List[str]:
        return [cmd.description for cmd in reversed(self._redo_stack)]

    def batch_undo(self, count: int) -> List[Command]:
        undone = []
        for _ in range(min(count, len(self._undo_stack))):
            cmd = self.undo()
            if cmd:
                undone.append(cmd)
        return undone

    def batch_redo(self, count: int) -> List[Command]:
        redone = []
        for _ in range(min(count, len(self._redo_stack))):
            cmd = self.redo()
            if cmd:
                redone.append(cmd)
        return redone

    def clear(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    @property
    def undo_count(self) -> int:
        return len(self._undo_stack)

    @property
    def redo_count(self) -> int:
        return len(self._redo_stack)
