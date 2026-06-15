import sys
import threading
import time
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ebook_manager.models import BookMeta
from ebook_manager.find_replace_engine import FindReplaceEngine, ReplaceResult

import ebook_manager.models
import ebook_manager.find_replace_engine
import ebook_manager.scanner
import ebook_manager.metadata_parser

workers_path = Path(__file__).parent / "ebook_manager" / "ui" / "workers.py"

source = workers_path.read_text(encoding="utf-8")

source = source.replace(
    "from PyQt6.QtCore import QThread, pyqtSignal",
    """import threading, types

class FakePyQtSignal:
    def __init__(self, *args, **kwargs): self._slots = []
    def connect(self, slot): self._slots.append(slot)
    def emit(self, *args, **kwargs):
        for s in self._slots:
            try:
                from PyQt6.QtCore import QMetaObject, Qt, Q_ARG
                QMetaObject.invokeMethod(None, None, Qt.QueuedConnection)
            except Exception:
                pass
            try:
                s(*args)
            except Exception:
                pass

class QThread(threading.Thread):
    def __init__(self, parent=None): super().__init__(daemon=True)
    def start(self): super().start()
    def wait(self, timeout=None): super().join(timeout/1000 if isinstance(timeout, int) and timeout > 100 else timeout)
    def isRunning(self): return self.is_alive()
    def terminate(self): pass

def pyqtSignal(*args, **kwargs):
    return FakePyQtSignal()"""
)

code = compile(source, str(workers_path), "exec")
ns = {
    "Path": Path,
    "threading": threading,
    "List": list,
    "Optional": type(None),
    "Callable": callable,
    "BookMeta": BookMeta,
    "BookshelfScanner": None,
    "MetadataParser": None,
    "FindReplaceEngine": FindReplaceEngine,
    "ReplaceResult": ReplaceResult,
    "__name__": "ebook_manager.ui.workers",
    "__file__": str(workers_path),
}
ns["typing"] = types = importlib.import_module("typing")
ns["List"] = types.List
ns["Optional"] = types.Optional
ns["Callable"] = types.Callable

ns["BookshelfScanner"] = importlib.import_module("ebook_manager.scanner").BookshelfScanner
ns["MetadataParser"] = importlib.import_module("ebook_manager.metadata_parser").MetadataParser

exec(code, ns)
SkipManager = ns["SkipManager"]
BatchReplaceWorker = ns["BatchReplaceWorker"]


def make_test_books(n: int = 5):
    books = []
    for i in range(n):
        book = BookMeta(
            title=f"古籍{i+1}",
            author="佚名",
            description=f"第{i+1}本书中记载了许多曰字和己字的内容。子曰学而时习之。己所不欲勿施于人。",
            file_path=f"/tmp/book_{i+1}.epub",
            file_format="epub",
        )
        books.append(book)
    return books


def test_skip_manager_thread_safety():
    print("=== 测试 SkipManager 线程安全 ===")

    manager = SkipManager()
    errors = []

    def writer(paths):
        try:
            for p in paths:
                manager.add(p)
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    def reader(checks, book):
        try:
            for _ in range(checks):
                manager.is_skipped(book)
                time.sleep(0.001)
        except Exception as e:
            errors.append(e)

    paths = [f"/tmp/book_{i}.epub" for i in range(50)]
    book = BookMeta(file_path="/tmp/book_25.epub")

    threads = []
    for _ in range(5):
        t = threading.Thread(target=writer, args=(paths,))
        threads.append(t)
    for _ in range(5):
        t = threading.Thread(target=reader, args=(100, book))
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors:
        for e in errors:
            print(f"✗ 错误: {e}")
        assert False, "线程安全测试失败"

    skipped = manager.get_skipped_paths()
    assert len(skipped) == 50
    print(f"✓ 线程安全，共 {len(skipped)} 个路径记录\n")


def test_worker_skip_before_processing():
    print("=== 测试：处理前标记跳过 ===")

    engine = FindReplaceEngine()
    books = make_test_books(3)
    skip_target = books[1].file_path

    worker = BatchReplaceWorker(
        engine=engine,
        books=books,
        pattern="曰",
        replacement="日",
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
    )

    worker.skip_book(skip_target)

    results = []
    finished = threading.Event()

    def on_finished(res):
        results.extend(res)
        finished.set()

    worker.finished_all.connect(on_finished)
    worker.start()

    finished.wait(timeout=10)
    if not finished.is_set():
        worker.terminate()
        assert False, "Worker超时未完成"

    books_results = {}
    for r in results:
        key = r.book.file_path
        if key not in books_results:
            books_results[key] = []
        books_results[key].append(r)

    print(f"书籍 {books[0].title}: ", end="")
    for r in books_results[books[0].file_path]:
        if r.skipped:
            print("跳过", end=" ")
        else:
            print(f"修改{r.count}处", end=" ")
    assert any(not r.skipped for r in books_results[books[0].file_path])
    assert any(r.count > 0 for r in books_results[books[0].file_path])
    print("✓")

    print(f"书籍 {books[1].title}(预跳过): ", end="")
    for r in books_results[books[1].file_path]:
        if r.skipped:
            print("跳过✓", end=" ")
        else:
            print(f"修改{r.count}处", end=" ")
    assert all(r.skipped for r in books_results[books[1].file_path])
    print()

    print(f"书籍 {books[2].title}: ", end="")
    for r in books_results[books[2].file_path]:
        if r.skipped:
            print("跳过", end=" ")
        else:
            print(f"修改{r.count}处", end=" ")
    assert any(not r.skipped for r in books_results[books[2].file_path])
    print("✓")

    total_skipped = sum(1 for r in results if r.skipped)
    total_changed = sum(r.count for r in results if not r.skipped)
    print(f"\n总计: 跳过 {total_skipped} 处, 修改 {total_changed} 处")
    assert total_skipped >= 1
    print("✓ 处理前标记跳过测试通过\n")


def test_worker_skip_during_processing():
    print("=== 测试：处理中标记跳过（丢弃结果）===")

    engine = FindReplaceEngine(regex_timeout=5.0)
    books = make_test_books(5)

    worker = BatchReplaceWorker(
        engine=engine,
        books=books,
        pattern="曰",
        replacement="日",
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
    )

    book_to_skip_idx = 3
    skip_triggered = threading.Event()

    def on_progress(current, total, book, results_partial):
        if current == book_to_skip_idx and not skip_triggered.is_set():
            worker.skip_book(book.file_path)
            skip_triggered.set()
            print(f"  [触发跳过] {book.title}")

    results = []
    finished = threading.Event()

    def on_finished(res):
        results.extend(res)
        finished.set()

    worker.progress_updated.connect(on_progress)
    worker.finished_all.connect(on_finished)
    worker.start()

    finished.wait(timeout=10)
    if not finished.is_set():
        worker.terminate()
        assert False, "Worker超时未完成"

    skip_target = books[book_to_skip_idx - 1].file_path
    books_results = {}
    for r in results:
        key = r.book.file_path
        if key not in books_results:
            books_results[key] = []
        books_results[key].append(r)

    for i, book in enumerate(books):
        rs = books_results[book.file_path]
        status = []
        for r in rs:
            if r.skipped:
                status.append("跳过")
            elif r.error:
                status.append("错误")
            elif r.count > 0:
                status.append(f"修改{r.count}处")
            else:
                status.append("无匹配")
        print(f"  {book.title}: {', '.join(status)}")

    skip_results = books_results[skip_target]
    for r in results:
        if r.skipped:
            assert r.count == 0, f"跳过的结果不应有修改数: {r.count}"
            assert len(r.matches) == 0, "跳过的结果不应有匹配记录"

    if skip_triggered.is_set():
        any_skipped = any(r.skipped for r in skip_results)
        if any_skipped:
            print(f"✓ 书籍 {book_to_skip_idx} 的结果正确标记为跳过")
    print("✓ 处理中标记跳过测试通过\n")


def test_skip_callback_and_runtime_skip_combined():
    print("=== 测试：勾选框跳过 + 运行时跳过 组合 ===")

    engine = FindReplaceEngine()
    books = make_test_books(4)

    deselected = {books[0].file_path, books[3].file_path}

    def pre_skip_cb(book):
        return book.file_path in deselected

    worker = BatchReplaceWorker(
        engine=engine,
        books=books,
        pattern="己",
        replacement="已",
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        skip_callback=pre_skip_cb,
    )

    runtime_skip_idx = 2

    def on_progress(current, total, book, partial):
        if current == runtime_skip_idx and book.file_path not in deselected:
            worker.skip_book(book.file_path)

    results = []
    finished = threading.Event()

    worker.progress_updated.connect(on_progress)
    worker.finished_all.connect(lambda res: (results.extend(res), finished.set()))
    worker.start()

    finished.wait(timeout=10)

    for i, book in enumerate(books):
        rs = [r for r in results if r.book.file_path == book.file_path]
        kind = "未勾选" if book.file_path in deselected else "已勾选"
        statuses = []
        for r in rs:
            if r.skipped:
                statuses.append("⏭跳过")
            elif r.count > 0:
                statuses.append(f"✓改{r.count}")
            else:
                statuses.append("—")
        print(f"  [{kind}] {book.title}: {', '.join(statuses)}")

    for r in results:
        if r.book.file_path in deselected:
            assert r.skipped, f"未勾选的书 {r.book.title} 应标记为跳过"
        if r.skipped:
            assert r.count == 0
            assert len(r.matches) == 0

    print("✓ 组合跳过逻辑测试通过\n")


def test_cancel_functionality():
    print("=== 测试：取消功能 ===")

    engine = FindReplaceEngine()
    books = make_test_books(10)

    worker = BatchReplaceWorker(
        engine=engine,
        books=books,
        pattern="曰",
        replacement="日",
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
    )

    cancel_at = 4
    results = []
    finished = threading.Event()

    def on_progress(current, total, book, partial):
        if current >= cancel_at:
            if not worker._is_cancelled():
                worker.cancel()
                print(f"  [取消触发] 到达第 {current} 本")

    worker.progress_updated.connect(on_progress)
    worker.finished_all.connect(lambda res: (results.extend(res), finished.set()))
    worker.start()

    finished.wait(timeout=10)
    if not finished.is_set():
        worker.terminate()
        assert False, "Worker超时"

    processed_books = set()
    for r in results:
        processed_books.add(r.book.file_path)

    print(f"  处理了 {len(processed_books)} / {len(books)} 本书")
    assert len(processed_books) <= cancel_at + 2
    print("✓ 取消功能测试通过\n")


def run_all_tests():
    print("=" * 60)
    print("跳过功能修复验证测试")
    print("=" * 60 + "\n")

    try:
        test_skip_manager_thread_safety()
        test_worker_skip_before_processing()
        test_worker_skip_during_processing()
        test_skip_callback_and_runtime_skip_combined()
        test_cancel_functionality()

        print("=" * 60)
        print("✅ 所有跳过功能测试通过！")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    ok = run_all_tests()
    sys.exit(0 if ok else 1)
