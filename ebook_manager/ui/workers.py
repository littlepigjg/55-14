import threading
from pathlib import Path
from typing import List, Optional, Callable

from PyQt6.QtCore import QThread, pyqtSignal

from ..models import BookMeta
from ..scanner import BookshelfScanner
from ..metadata_parser import MetadataParser
from ..find_replace_engine import FindReplaceEngine, ReplaceResult


class ScanWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, directories: list, recursive: bool):
        super().__init__()
        self._directories = directories
        self._recursive = recursive

    def run(self):
        scanner = BookshelfScanner()
        scanner.set_progress_callback(
            lambda c, t, p: self.progress.emit(c, t, p)
        )
        files = scanner.scan_directories(self._directories, self._recursive)
        self.finished_signal.emit(files)


class ParseWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, files: list):
        super().__init__()
        self._files = files

    def run(self):
        parser = MetadataParser()
        books = []
        total = len(self._files)
        for i, f in enumerate(self._files):
            self.progress.emit(i + 1, total, f)
            try:
                book = parser.parse(f)
                books.append(book)
            except Exception:
                books.append(
                    BookMeta(
                        file_path=f,
                        file_format=Path(f).suffix.lstrip("."),
                        title=Path(f).stem,
                    )
                )
        self.finished_signal.emit(books)


class SkipManager:
    def __init__(self, pre_skip_callback: Optional[Callable[[BookMeta], bool]] = None):
        self._lock = threading.Lock()
        self._skipped_paths: set = set()
        self._pre_skip_callback = pre_skip_callback

    def add(self, book_path: str):
        with self._lock:
            self._skipped_paths.add(book_path)

    def is_skipped(self, book: BookMeta) -> bool:
        if self._pre_skip_callback and self._pre_skip_callback(book):
            return True
        with self._lock:
            return book.file_path in self._skipped_paths

    def get_skipped_paths(self) -> set:
        with self._lock:
            return set(self._skipped_paths)


class BatchReplaceWorker(QThread):
    progress_updated = pyqtSignal(int, int, BookMeta, list)
    book_started = pyqtSignal(int, int, BookMeta)
    book_finished = pyqtSignal(int, int, BookMeta)
    finished_all = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        engine: FindReplaceEngine,
        books: List[BookMeta],
        pattern: str,
        replacement: str,
        fields: List[str],
        use_regex: bool,
        case_sensitive: bool,
        whole_word: bool,
        skip_callback: Optional[Callable[[BookMeta], bool]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._engine = engine
        self._books = books
        self._pattern = pattern
        self._replacement = replacement
        self._fields = fields
        self._use_regex = use_regex
        self._case_sensitive = case_sensitive
        self._whole_word = whole_word
        self._skip_manager = SkipManager(pre_skip_callback=skip_callback)
        self._cancelled = False
        self._cancelled_lock = threading.Lock()

    def cancel(self):
        with self._cancelled_lock:
            self._cancelled = True

    def _is_cancelled(self) -> bool:
        with self._cancelled_lock:
            return self._cancelled

    def skip_book(self, book_path: str):
        self._skip_manager.add(book_path)

    def is_book_skipped(self, book: BookMeta) -> bool:
        return self._skip_manager.is_skipped(book)

    def run(self):
        all_results = []
        total = len(self._books)

        for i, book in enumerate(self._books):
            if self._is_cancelled():
                break

            self.book_started.emit(i + 1, total, book)

            if self._skip_manager.is_skipped(book):
                result = ReplaceResult(book=book, field="skipped", skipped=True)
                all_results.append(result)
                self.progress_updated.emit(i + 1, total, book, [result])
                self.book_finished.emit(i + 1, total, book)
                continue

            try:
                results = self._engine.replace_in_book(
                    book, self._pattern, self._replacement, self._fields,
                    self._use_regex, self._case_sensitive, self._whole_word
                )
            except Exception as e:
                result = ReplaceResult(book=book, field="error", error=str(e))
                all_results.append(result)
                self.progress_updated.emit(i + 1, total, book, [result])
                self.book_finished.emit(i + 1, total, book)
                continue

            if self._skip_manager.is_skipped(book):
                for r in results:
                    r.skipped = True
                    r.matches = []
                    r.original_value = ""
                    r.new_value = ""
                results = [ReplaceResult(book=book, field="skipped", skipped=True)]

            all_results.extend(results)
            self.progress_updated.emit(i + 1, total, book, results)
            self.book_finished.emit(i + 1, total, book)

        self.finished_all.emit(all_results)
