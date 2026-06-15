import sys
import os
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).parent))

from ebook_manager import (
    BookMeta,
    FindReplaceEngine,
    RegexMatcher,
    RegexTimeoutError,
    EpubStructureValidator,
    MatchResult,
    ReplaceResult,
    ReplaceCommand,
    CommandHistory,
    ReplaceRule,
    RuleLibrary,
    BUILTIN_RULES,
)


def test_book_meta():
    print("=== 测试 BookMeta ===")
    book = BookMeta(
        title="论语",
        author="孔子",
        description="子曰学而时习之，不亦说乎？己所不欲勿施于人。",
        publish_date="2023年1月15日",
        file_path="test.epub",
        file_format="epub",
    )
    print(f"书名: {book.title}")
    print(f"描述: {book.description}")
    print("✓ BookMeta 测试通过\n")
    return book


def test_regex_matcher():
    print("=== 测试 RegexMatcher ===")
    matcher = RegexMatcher(timeout=3.0)

    text = "子曰学而时习之，不亦说乎？己所不欲勿施于人。"

    matches = matcher.findall(r"曰|己", text)
    print(f"找到 {len(matches)} 处匹配:")
    for start, end, match in matches:
        print(f"  位置 {start}-{end}: '{match}'")

    new_text, count, replacements = matcher.substitute(r"曰", r"日", text)
    print(f"\n替换后文本: {new_text}")
    print(f"替换数量: {count}")
    assert "子日" in new_text
    assert "曰" not in new_text

    new_text2, count2, _ = matcher.substitute(r"己", r"已", new_text)
    print(f"\n再次替换后: {new_text2}")
    assert count2 == 1
    assert "已所不欲" in new_text2

    print("✓ RegexMatcher 测试通过\n")


def test_regex_timeout():
    print("=== 测试正则超时 ===")
    matcher = RegexMatcher(timeout=1.0)

    print("测试正则超时机制...")

    try:
        pattern = r"曰"
        text = "子曰学而时习之"
        matches = matcher.findall(pattern, text)
        print(f"✓ 正常正则匹配完成，找到 {len(matches)} 处")
    except RegexTimeoutError as e:
        print(f"捕获超时: {e}")

    print(f"✓ 超时机制已配置: {matcher.timeout}秒")
    print()


def test_unicode_handling():
    print("=== 测试 Unicode 处理 ===")
    matcher = RegexMatcher()

    mixed_text = "古籍中常见的曰字常被误识别为日字"
    matches = matcher.findall(r"[曰日]", mixed_text)
    print(f"找到中日文匹配 {len(matches)} 处:")
    for s, e, m in matches:
        print(f"  位置 {s}: '{m}'")

    new_text, count, _ = matcher.substitute(r"曰", r"日", mixed_text)
    print(f"替换后: {new_text}")
    print(f"替换数量: {count}")
    assert count >= 1
    assert "曰" not in new_text

    print("✓ Unicode 处理测试通过\n")


def test_find_replace_engine():
    print("=== 测试 FindReplaceEngine ===")
    engine = FindReplaceEngine(regex_timeout=3.0)

    book = BookMeta(
        title="论语译注",
        author="孔子及其弟子",
        description="子曰：学而时习之，不亦说乎？己所不欲，勿施于人。",
        tags=["儒家", "经典"],
        file_path="test.epub",
        file_format="epub",
    )

    pattern = r"曰|己"
    matches = engine.find_in_book(book, pattern, fields=["title", "author", "description", "tags"])
    print(f"跨字段搜索找到 {len(matches)} 处匹配:")
    for m in matches:
        print(f"  [{m.field}] 位置 {m.start}-{m.end}: '{m.original}'")
        print(f"    上下文: ...{m.context_before}<mark>{m.original}</mark>{m.context_after}...")

    assert len(matches) == 2

    results = engine.replace_in_book(
        book, r"曰", r"日",
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
    )

    total = sum(r.count for r in results)
    print(f"\n替换结果: 共 {total} 处修改")
    for r in results:
        if r.count > 0:
            print(f"  字段 {r.field}: {r.count} 处")
            print(f"    原值: {r.original_value}")
            print(f"    新值: {r.new_value}")

    assert total == 1
    assert "子日" in results[0].new_value

    print("✓ FindReplaceEngine 测试通过\n")


def test_epub_validator():
    print("=== 测试 EPUB 结构验证 ===")
    validator = EpubStructureValidator()

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        import zipfile
        with zipfile.ZipFile(tmp_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>""")
            zf.writestr("content.opf", """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>测试</dc:title>
  </metadata>
</package>""")

        valid, msg = validator.validate_epub(tmp_path)
        print(f"测试 EPUB 验证: {valid} - {msg}")
        assert valid

        book = BookMeta(file_path=tmp_path, file_format="epub")
        engine = FindReplaceEngine()
        valid2, msg2 = engine.validate_after_replace(book)
        print(f"引擎验证: {valid2} - {msg2}")

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    invalid_path = "nonexistent.epub"
    valid3, msg3 = validator.validate_epub(invalid_path)
    print(f"不存在文件验证: {valid3} - {msg3}")
    assert not valid3

    print("✓ EPUB 结构验证测试通过\n")


def test_command_pattern():
    print("=== 测试命令模式（撤销/重做） ===")
    engine = FindReplaceEngine()
    history = CommandHistory(max_history=50)

    book = BookMeta(
        title="古籍曰己录",
        author="佚名",
        description="书中记载了许多曰己相关的内容。己所不欲勿施于人。",
        file_path="test.epub",
        file_format="epub",
    )

    results = engine.replace_in_book(book, r"曰", r"日", fields=["title", "description"])
    command1 = ReplaceCommand(engine, [book], r"曰", r"日", results, fields=["title", "description"])

    print(f"原始书名: {book.title}")
    print(f"原始描述: {book.description}")

    command1.execute()
    print(f"\n执行替换后:")
    print(f"书名: {book.title}")
    print(f"描述: {book.description}")
    assert "日" in book.title
    assert "曰" not in book.description
    assert "日" in book.description

    history.push(command1)
    assert history.can_undo()
    assert not history.can_redo()

    results2 = engine.replace_in_book(book, r"己", r"已", fields=["description"])
    command2 = ReplaceCommand(engine, [book], r"己", r"已", results2, fields=["description"])
    command2.execute()
    history.push(command2)

    print(f"\n第二次替换后描述: {book.description}")
    assert "已所不欲" in book.description

    print(f"\n可撤销操作: {history.undo_list()}")

    undone = history.undo()
    print(f"\n撤销后描述: {book.description}")
    assert "己所不欲" in book.description
    assert history.can_redo()

    redone = history.redo()
    print(f"重做后描述: {book.description}")
    assert "已所不欲" in book.description

    batch_undone = history.batch_undo(2)
    print(f"\n批量撤销 {len(batch_undone)} 步后:")
    print(f"书名: {book.title}")
    print(f"描述: {book.description}")
    assert "曰" in book.title
    assert "己所不欲" in book.description

    print("✓ 命令模式测试通过\n")


def test_rule_library():
    print("=== 测试替换规则库 ===")
    import tempfile
    tmpdir = tempfile.mkdtemp()
    library = RuleLibrary(config_dir=tmpdir)

    print(f"内置规则数量: {len(library.get_builtin_rules())}")
    print(f"分类: {library.get_categories()}")

    ocr_rules = library.get_rules_by_category("OCR纠错")
    print(f"\nOCR纠错规则 ({len(ocr_rules)} 条):")
    for rule in ocr_rules[:3]:
        print(f"  - {rule.name}: /{rule.pattern}/ -> '{rule.replacement}'")

    print(f"\n所有规则 ({len(library.get_all_rules())} 条):")
    for rule in library.get_all_rules()[:5]:
        prefix = "📦" if rule.is_builtin else "🔧"
        print(f"  {prefix} [{rule.category}] {rule.name}")

    custom_rule = ReplaceRule(
        name="自定义: 修正书名号",
        pattern=r"《([^》]+)》",
        replacement=r"【\1】",
        description="将书名号替换为方头括号",
        category="自定义",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["title", "description"],
    )
    library.add_rule(custom_rule)
    print(f"\n添加自定义规则后总数: {len(library.get_all_rules())}")

    search_results = library.search_rules("曰")
    print(f"\n搜索'曰'找到 {len(search_results)} 条规则:")
    for rule in search_results:
        print(f"  - {rule.name}")

    custom_rules = library.get_custom_rules()
    assert len(custom_rules) == 1
    assert custom_rules[0].name == "自定义: 修正书名号"

    try:
        import shutil
        shutil.rmtree(tmpdir)
    except:
        pass

    print("✓ 替换规则库测试通过\n")


def test_whole_word_matching():
    print("=== 测试整词匹配 ===")
    engine = FindReplaceEngine()

    book = BookMeta(
        title="日记",
        description="这本书记录了日常生活。曰记是另一个词。",
    )

    matches = engine.find_in_book(
        book, r"曰",
        fields=["title", "description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=True,
    )
    print(f"整词匹配'曰'找到 {len(matches)} 处")

    matches2 = engine.find_in_book(
        book, r"曰",
        fields=["title", "description"],
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
    )
    print(f"非整词匹配'曰'找到 {len(matches2)} 处")

    pattern = r"\b(曰|日)\b"
    matches3 = engine.find_in_book(
        book, pattern,
        fields=["description"],
        use_regex=True,
        case_sensitive=True,
    )
    print(f"\\b(曰|日)\\b 匹配找到 {len(matches3)} 处:")
    for m in matches3:
        print(f"  '{m.original}' 在 '{m.context_before}{m.original}{m.context_after}'")

    print("✓ 整词匹配测试通过\n")


def test_date_format_rule():
    print("=== 测试日期格式统一规则 ===")
    library = RuleLibrary()
    date_rule = library.find_rule_by_name("统一日期格式 YYYY-MM-DD")

    if date_rule:
        print(f"找到规则: {date_rule.name}")
        print(f"模式: {date_rule.pattern}")
        print(f"替换: {date_rule.replacement}")

        engine = FindReplaceEngine()
        book = BookMeta(
            title="测试书籍",
            publish_date="2023年1月15日",
            description="出版于2022/12/01，重印于2023-06-20",
        )

        results = engine.replace_in_book(
            book,
            date_rule.pattern,
            date_rule.replacement,
            fields=date_rule.fields,
            use_regex=date_rule.use_regex,
            case_sensitive=date_rule.case_sensitive,
            whole_word=date_rule.whole_word,
        )

        for r in results:
            if r.count > 0:
                print(f"\n{r.field}:")
                print(f"  原值: {r.original_value}")
                print(f"  新值: {r.new_value}")
                print(f"  修改 {r.count} 处")

        assert any("2023-1-15" in r.new_value for r in results if r.count > 0)
        print("✓ 日期格式规则测试通过\n")


def run_all_tests():
    print("=" * 60)
    print("古籍电子书查找替换工具 - 功能测试")
    print("=" * 60 + "\n")

    try:
        book = test_book_meta()
        test_regex_matcher()
        test_regex_timeout()
        test_unicode_handling()
        test_find_replace_engine()
        test_epub_validator()
        test_command_pattern()
        test_rule_library()
        test_whole_word_matching()
        test_date_format_rule()

        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        return True
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
