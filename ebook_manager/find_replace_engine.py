import re
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Callable, Any
from pathlib import Path

from .models import BookMeta


@dataclass
class MatchResult:
    field: str
    start: int
    end: int
    original: str
    replaced: str = ""
    context_before: str = ""
    context_after: str = ""


@dataclass
class ReplaceResult:
    book: BookMeta
    field: str
    matches: List[MatchResult] = field(default_factory=list)
    original_value: str = ""
    new_value: str = ""
    error: str = ""
    skipped: bool = False

    @property
    def count(self) -> int:
        return len(self.matches)


class RegexTimeoutError(Exception):
    pass


class RegexMatcher:
    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout

    def _run_with_timeout(self, func: Callable, *args, **kwargs) -> Any:
        result = [None]
        exception = [None]
        done = threading.Event()

        def wrapper():
            try:
                result[0] = func(*args, **kwargs)
            except Exception as e:
                exception[0] = e
            finally:
                done.set()

        thread = threading.Thread(target=wrapper, daemon=True)
        thread.start()
        completed = done.wait(timeout=self.timeout)

        if not completed:
            import ctypes
            if hasattr(thread, 'ident'):
                try:
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_long(thread.ident),
                        ctypes.py_object(RegexTimeoutError)
                    )
                except:
                    pass
            thread.join(0.5)
            raise RegexTimeoutError(f"正则表达式执行超时 ({self.timeout}秒)")

        if exception[0] is not None:
            raise exception[0]

        return result[0]

    @staticmethod
    def _normalize_text(text: str) -> str:
        if text is None:
            return ""
        return str(text).encode("utf-8", errors="replace").decode("utf-8")

    def findall(self, pattern: str, text: str, flags: int = 0) -> List[Tuple[int, int, str]]:
        text = self._normalize_text(text)
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"正则表达式语法错误: {e}")

        def _find():
            matches = []
            for m in compiled.finditer(text):
                matches.append((m.start(), m.end(), m.group()))
            return matches

        return self._run_with_timeout(_find)

    def substitute(self, pattern: str, replacement: str, text: str, flags: int = 0) -> Tuple[str, int, List[Tuple[int, int, str, str]]]:
        text = self._normalize_text(text)
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"正则表达式语法错误: {e}")

        def _sub():
            matches = []
            count = 0
            result = []
            last_end = 0

            for m in compiled.finditer(text):
                start, end = m.span()
                original = m.group()
                try:
                    replaced = m.expand(replacement)
                except re.error as e:
                    raise ValueError(f"替换字符串语法错误: {e}")

                result.append(text[last_end:start])
                result.append(replaced)

                matches.append((start, end, original, replaced))
                count += 1
                last_end = end

            result.append(text[last_end:])
            return "".join(result), count, matches

        return self._run_with_timeout(_sub)


class EpubStructureValidator:
    @staticmethod
    def validate_epub(file_path: str) -> Tuple[bool, str]:
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                if "mimetype" not in zf.namelist():
                    return False, "缺少 mimetype 文件"

                mimetype_data = zf.read("mimetype").decode("utf-8").strip()
                if mimetype_data != "application/epub+zip":
                    return False, f"mimetype 错误: {mimetype_data}"

                if "META-INF/container.xml" not in zf.namelist():
                    return False, "缺少 META-INF/container.xml"

                container_xml = zf.read("META-INF/container.xml").decode("utf-8")
                try:
                    root = ET.fromstring(container_xml)
                    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
                    rootfile = root.find(".//c:rootfile", ns)
                    if rootfile is None:
                        return False, "container.xml 中未找到 rootfile"
                    opf_path = rootfile.get("full-path")
                    if not opf_path:
                        return False, "rootfile 缺少 full-path 属性"
                    if opf_path not in zf.namelist():
                        return False, f"OPF 文件不存在: {opf_path}"
                except ET.ParseError as e:
                    return False, f"container.xml 解析错误: {e}"

            return True, "EPUB 结构有效"
        except zipfile.BadZipFile:
            return False, "不是有效的 ZIP 文件"
        except Exception as e:
            return False, f"验证错误: {str(e)}"


class FindReplaceEngine:
    SEARCHABLE_FIELDS = ["title", "author", "publisher", "description", "tags"]

    def __init__(self, regex_timeout: float = 5.0):
        self.matcher = RegexMatcher(timeout=regex_timeout)
        self.validator = EpubStructureValidator()

    def find_in_book(
        self,
        book: BookMeta,
        pattern: str,
        fields: Optional[List[str]] = None,
        use_regex: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
        context_chars: int = 20,
    ) -> List[MatchResult]:
        fields = fields or self.SEARCHABLE_FIELDS
        flags = 0 if case_sensitive else re.IGNORECASE
        results = []

        search_pattern = pattern
        if not use_regex:
            search_pattern = re.escape(pattern)
        if whole_word:
            search_pattern = r"\b" + search_pattern + r"\b"

        for field_name in fields:
            value = getattr(book, field_name, "")
            if isinstance(value, list):
                value = ", ".join(value)
            if not value:
                continue

            try:
                matches = self.matcher.findall(search_pattern, value, flags)
            except (RegexTimeoutError, ValueError) as e:
                raise RuntimeError(f"在字段 '{field_name}' 中搜索失败: {e}")

            for start, end, original in matches:
                ctx_before = value[max(0, start - context_chars):start]
                ctx_after = value[end:end + context_chars]

                results.append(MatchResult(
                    field=field_name,
                    start=start,
                    end=end,
                    original=original,
                    context_before=ctx_before,
                    context_after=ctx_after,
                ))

        return results

    def replace_in_book(
        self,
        book: BookMeta,
        pattern: str,
        replacement: str,
        fields: Optional[List[str]] = None,
        use_regex: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
    ) -> List[ReplaceResult]:
        fields = fields or self.SEARCHABLE_FIELDS
        flags = 0 if case_sensitive else re.IGNORECASE
        results = []

        search_pattern = pattern
        if not use_regex:
            search_pattern = re.escape(pattern)
        if whole_word:
            search_pattern = r"\b" + search_pattern + r"\b"

        for field_name in fields:
            result = ReplaceResult(book=book, field=field_name)
            value = getattr(book, field_name, "")
            is_list = isinstance(value, list)
            if is_list:
                value = ", ".join(value)

            result.original_value = value
            if not value:
                result.skipped = True
                results.append(result)
                continue

            try:
                new_text, count, matches = self.matcher.substitute(
                    search_pattern, replacement, value, flags
                )
            except (RegexTimeoutError, ValueError) as e:
                result.error = str(e)
                results.append(result)
                continue

            if count == 0:
                result.skipped = True
                results.append(result)
                continue

            for start, end, original, replaced in matches:
                result.matches.append(MatchResult(
                    field=field_name,
                    start=start,
                    end=end,
                    original=original,
                    replaced=replaced,
                ))

            result.new_value = new_text
            results.append(result)

        return results

    def apply_replacements(self, book: BookMeta, results: List[ReplaceResult]) -> BookMeta:
        for result in results:
            if result.error or result.skipped or result.count == 0:
                continue
            if hasattr(book, result.field):
                current = getattr(book, result.field)
                if isinstance(current, list):
                    tags = [t.strip() for t in result.new_value.split(",") if t.strip()]
                    setattr(book, result.field, tags)
                else:
                    setattr(book, result.field, result.new_value)
        return book

    def validate_after_replace(self, book: BookMeta) -> Tuple[bool, str]:
        if book.file_format == "epub" and book.file_path:
            if Path(book.file_path).exists():
                return self.validator.validate_epub(book.file_path)
        return True, "跳过验证（非EPUB或文件不存在）"

    def batch_process(
        self,
        books: List[BookMeta],
        pattern: str,
        replacement: str,
        fields: Optional[List[str]] = None,
        use_regex: bool = True,
        case_sensitive: bool = False,
        whole_word: bool = False,
        progress_callback: Optional[Callable[[int, int, BookMeta, List[ReplaceResult]], None]] = None,
        skip_callback: Optional[Callable[[BookMeta], bool]] = None,
    ) -> List[ReplaceResult]:
        all_results = []
        total = len(books)

        for i, book in enumerate(books):
            if skip_callback and skip_callback(book):
                result = ReplaceResult(book=book, field="skipped", skipped=True)
                all_results.append(result)
                if progress_callback:
                    progress_callback(i + 1, total, book, [result])
                continue

            try:
                results = self.replace_in_book(
                    book, pattern, replacement, fields,
                    use_regex, case_sensitive, whole_word
                )
                all_results.extend(results)

                if progress_callback:
                    progress_callback(i + 1, total, book, results)
            except Exception as e:
                result = ReplaceResult(book=book, field="error", error=str(e))
                all_results.append(result)

        return all_results
