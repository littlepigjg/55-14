"""
跳过功能端到端验证测试
核心验证：
 1. ReplaceCommand 严格过滤被跳过的书
 2. Worker 在处理中被标记跳过后，结果必须完全干净
 3. 预跳过的书完全不执行 replace_in_book
 4. 预跳过回调 + 运行时跳过双轨并行工作
"""
import sys
import os
import types
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_pyqt6 = types.ModuleType("PyQt6")
_pyqt6_core = types.ModuleType("PyQt6.QtCore")

class _FakeSignal:
    def __init__(self, *args, **kwargs):
        self._handlers = []
        self._emitted = []
    def connect(self, h):
        self._handlers.append(h)
    def emit(self, *args):
        self._emitted.append(args)
        for h in self._handlers:
            try:
                h(*args)
            except Exception:
                pass

class _FakeQThread:
    def __init__(self, parent=None):
        pass

_pyqt6_core.pyqtSignal = lambda *args, **kwargs: _FakeSignal()
_pyqt6_core.QThread = _FakeQThread
_pyqt6.QtCore = _pyqt6_core
sys.modules["PyQt6"] = _pyqt6
sys.modules["PyQt6.QtCore"] = _pyqt6_core

from ebook_manager.models import BookMeta
from ebook_manager.find_replace_engine import FindReplaceEngine, ReplaceResult
from ebook_manager.commands import ReplaceCommand, BookSnapshot

_ui_mod = types.ModuleType("ebook_manager.ui")
sys.modules["ebook_manager.ui"] = _ui_mod
_workers_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "ebook_manager", "ui", "workers.py")
import importlib.util
_workers_spec = importlib.util.spec_from_file_location(
    "ebook_manager.ui.workers", _workers_path
)
_workers_mod = importlib.util.module_from_spec(_workers_spec)
_workers_spec.loader.exec_module(_workers_mod)
sys.modules["ebook_manager.ui.workers"] = _workers_mod
SkipManager = _workers_mod.SkipManager
BatchReplaceWorker = _workers_mod.BatchReplaceWorker


def make_book(title, desc, path):
    b = BookMeta(file_path=path, file_format="epub")
    b.title = title
    b.description = desc
    b.publisher = "测试出版社"
    return b


def test_replace_command_filter_skipped():
    """测试1: 只要该书有任何一条 skipped 结果，ReplaceCommand 就完全排除该书"""
    print("=== 测试1: ReplaceCommand 整书级过滤 skipped ===")
    engine = FindReplaceEngine()
    book = make_book("古籍曰己录", "子曰学而时习之。己所不欲。", "/b1.epub")
    orig_title, orig_desc = book.title, book.description

    results = engine.replace_in_book(book, "曰", "日", ["title", "description"], use_regex=False)
    assert any(r.count > 0 for r in results), "预校验"

    # 只标记其中一条为 skipped，验证整本书被排除
    results[0].skipped = True

    cmd = ReplaceCommand(engine, [book], "曰", "日", results,
                         ["title", "description"], use_regex=False,
                         case_sensitive=False, whole_word=False)
    key = book.file_path or id(book)
    assert key not in cmd._snapshots, f"只要有一条skipped，整本书不该有快照"
    assert len(cmd._snapshots) == 0, f"快照数应为0，实际{len(cmd._snapshots)}"

    cmd.execute()
    assert book.title == orig_title, f"书名被改: {book.title}"
    assert book.description == orig_desc, f"简介被改: {book.description}"
    print("  ✓ 只要有一条skipped标记，整本书完全不修改")


def test_worker_mid_process_skip():
    """测试2: Worker 处理中被标记跳过 → 返回结果完全干净、对象不被修改"""
    print("\n=== 测试2: Worker 处理中跳过 → 结果干净且不影响对象 ===")
    engine = FindReplaceEngine()
    books = [
        make_book(f"古籍{i}号", f"内容曰字出现{i}次。己所不欲。", f"/tmp/book{i}.epub")
        for i in range(1, 6)
    ]
    orig_snap = [(b.title, b.description) for b in books]

    skip_target_path = books[2].file_path

    orig_replace = engine.replace_in_book
    call_count = [0]
    def slow_replace_in_book(*a, **kw):
        book = a[0]
        call_count[0] += 1
        if book.file_path == skip_target_path:
            time.sleep(0.05)
        return orig_replace(*a, **kw)
    engine.replace_in_book = slow_replace_in_book

    worker = BatchReplaceWorker(
        engine=engine, books=books, pattern="曰", replacement="日",
        fields=["title", "description"], use_regex=False,
        case_sensitive=False, whole_word=False,
    )

    skip_ready = threading.Event()
    def mid_run_skip():
        skip_ready.wait(timeout=2)
        time.sleep(0.015)
        worker.skip_book(skip_target_path)

    def on_book_started(cur, tot, bk):
        if bk.file_path == skip_target_path:
            skip_ready.set()

    worker.book_started.connect(on_book_started)

    t = threading.Thread(target=mid_run_skip, daemon=True)
    t.start()
    worker.run()
    t.join(timeout=2)

    assert not t.is_alive(), "mid_run_skip 线程未正常结束"

    final_results = []
    for args in worker.finished_all._emitted:
        final_results.extend(args[0])

    target_results = [r for r in final_results if r.book.file_path == skip_target_path]
    print(f"  被跳过的书有 {len(target_results)} 条结果")
    for r in target_results:
        print(f"    field={r.field}, count={r.count}, skipped={r.skipped}, "
              f"new_value={str(r.new_value)[:30]!r}")

    for r in target_results:
        assert r.skipped is True, f"{r.field}: skipped 必须为 True"
        assert r.count == 0, f"{r.field}: count 必须为 0（实际 {r.count}）"
        assert not r.new_value, f"{r.field}: new_value 必须清空"
    print("  ✓ Worker 返回的所有跳过结果完全干净")

    cmd = ReplaceCommand(engine, books, "曰", "日", final_results,
                         ["title", "description"], use_regex=False,
                         case_sensitive=False, whole_word=False)
    assert skip_target_path not in cmd._snapshots, "跳过的书不得出现在快照中"
    print(f"  ✓ 快照 {list(cmd._snapshots.keys())}，跳过的书不在其中")

    cmd.execute()
    for i, b in enumerate(books):
        ot, od = orig_snap[i]
        if b.file_path == skip_target_path:
            assert b.title == ot, f"跳过的书名被改（期望{ot!r}，实际{b.title!r}）"
            assert b.description == od, f"跳过的简介被改（期望{od!r}，实际{b.description!r}）"
    print("  ✓ 被跳过的书对象完全未被修改")


def test_worker_pre_skip_not_called():
    """测试3: 处理前被标记跳过 → replace_in_book 完全不调用"""
    print("\n=== 测试3: 处理前跳过 → replace_in_book 不调用 ===")
    engine = FindReplaceEngine()
    orig_replace = engine.replace_in_book
    call_log = []
    def traced(*a, **kw):
        call_log.append(a[0].file_path)
        return orig_replace(*a, **kw)
    engine.replace_in_book = traced

    books = [make_book(f"古籍{i}", f"曰字内容{i}", f"/tmp/pre{i}.epub") for i in range(4)]

    worker = BatchReplaceWorker(
        engine=engine, books=books, pattern="曰", replacement="日",
        fields=["title", "description"], use_regex=False,
        case_sensitive=False, whole_word=False,
    )
    worker.skip_book(books[1].file_path)
    worker.skip_book(books[3].file_path)
    worker.run()

    assert books[1].file_path not in call_log, f"{books[1].file_path} 不该调用"
    assert books[3].file_path not in call_log, f"{books[3].file_path} 不该调用"
    print(f"  实际调用: {call_log}")
    print("  ✓ 预跳过的书完全未执行替换逻辑")


def test_callback_and_runtime_skip_combined():
    """测试4: 预跳过回调(未勾选) + 运行时跳过(用户点跳过) 组合工作"""
    print("\n=== 测试4: 未勾选回调 + 运行时跳过双轨 ===")
    books = [make_book(f"古{i}", "曰字内容", f"/tmp/cb{i}.epub") for i in range(5)]

    unchecked = {books[0].file_path, books[3].file_path}
    mgr = SkipManager(pre_skip_callback=lambda b: b.file_path in unchecked)
    mgr.skip(books[2].file_path)

    expected = [True, False, True, True, False]
    for i, b in enumerate(books):
        assert mgr.is_skipped(b) == expected[i], \
            f"b{i}: 期望 {expected[i]} 实际 {mgr.is_skipped(b)}"
    print("  ✓ 双轨逻辑互不干扰，判断正确")


def test_dialog_apply_skip_filter():
    """测试5: _on_apply 逻辑等价的过滤函数也能正确剔除跳过的书"""
    print("\n=== 测试5: dialog 应用层过滤 ===")
    engine = FindReplaceEngine()
    books = [make_book(f"古籍曰本{i}", f"曰字内容{i}", f"/tmp/dlg{i}.epub") for i in range(3)]

    results = []
    for i, b in enumerate(books):
        rs = engine.replace_in_book(b, "曰", "日", ["title", "description"], use_regex=False)
        if i == 1:
            for r in rs:
                r.skipped = True
                r.matches = []
                r.new_value = ""
        results.extend(rs)

    skipped_keys = set()
    for r in results:
        if r.skipped:
            skipped_keys.add(r.book.file_path or id(r.book))

    changed = []
    seen = set()
    for r in results:
        key = r.book.file_path or id(r.book)
        if key in skipped_keys:
            continue
        if r.count > 0 and not r.error and not r.skipped:
            if key not in seen:
                seen.add(key)
                changed.append(r.book)

    assert len(changed) == 2, f"应有2本书被修改，实际 {len(changed)}"
    assert books[1] not in changed, "被跳过的书不应出现在 changed_books"
    print(f"  changed: {[b.file_path for b in changed]}")
    print("  ✓ dialog 层过滤正确")


if __name__ == "__main__":
    try:
        test_replace_command_filter_skipped()
        test_worker_mid_process_skip()
        test_worker_pre_skip_not_called()
        test_callback_and_runtime_skip_combined()
        test_dialog_apply_skip_filter()
        print("\n" + "=" * 60)
        print("✅ 所有跳过端到端测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
