import json
import os
from dataclasses import dataclass, asdict, field
from typing import List, Optional
from pathlib import Path


@dataclass
class ReplaceRule:
    name: str
    pattern: str
    replacement: str
    description: str = ""
    category: str = "自定义"
    use_regex: bool = True
    case_sensitive: bool = False
    whole_word: bool = False
    fields: List[str] = field(default_factory=lambda: ["title", "author", "description"])
    is_builtin: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ReplaceRule":
        return cls(
            name=d.get("name", ""),
            pattern=d.get("pattern", ""),
            replacement=d.get("replacement", ""),
            description=d.get("description", ""),
            category=d.get("category", "自定义"),
            use_regex=d.get("use_regex", True),
            case_sensitive=d.get("case_sensitive", False),
            whole_word=d.get("whole_word", False),
            fields=d.get("fields", ["title", "author", "description"]),
            is_builtin=d.get("is_builtin", False),
        )


BUILTIN_RULES = [
    ReplaceRule(
        name="修正常见OCR错误: 曰/日",
        pattern=r"曰",
        replacement=r"日",
        description="将古籍中OCR误识别的'曰'修正为'日'",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["title", "author", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见OCR错误: 己/已",
        pattern=r"己",
        replacement=r"已",
        description="将古籍中OCR误识别的'己'修正为'已'",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["title", "author", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见OCR错误: 戊/戌/戍",
        pattern=r"戊",
        replacement=r"戌",
        description="修正常见形似字错误（需根据上下文确认）",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="统一日期格式 YYYY-MM-DD",
        pattern=r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})日?",
        replacement=r"\1-\2-\3",
        description="将各种日期格式统一为 YYYY-MM-DD 格式",
        category="格式统一",
        use_regex=True,
        case_sensitive=False,
        whole_word=False,
        fields=["publish_date", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="统一日期格式 YYYY-MM",
        pattern=r"(\d{4})[年\-/](\d{1,2})月?",
        replacement=r"\1-\2",
        description="将年月格式统一为 YYYY-MM 格式",
        category="格式统一",
        use_regex=True,
        case_sensitive=False,
        whole_word=False,
        fields=["publish_date", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见错别字: 的/地/得",
        pattern=r"([\u4e00-\u9fa5])的([\u4e00-\u9fa5])",
        replacement=r"\1地\2",
        description="修正部分'的'误用为'地'的情况（需人工确认）",
        category="错别字",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见错别字: 在/再",
        pattern=r"\b在\b",
        replacement=r"再",
        description="修正部分'在'误用为'再'的情况（需人工确认）",
        category="错别字",
        use_regex=True,
        case_sensitive=True,
        whole_word=True,
        fields=["description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见错别字: 做/作",
        pattern=r"做([\u4e00-\u9fa5]{2})",
        replacement=r"作\1",
        description="修正部分'做'误用为'作'的情况（需人工确认）",
        category="错别字",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="去除多余空格",
        pattern=r"\s+",
        replacement=r" ",
        description="将连续多个空格替换为单个空格",
        category="格式清理",
        use_regex=True,
        case_sensitive=False,
        whole_word=False,
        fields=["title", "author", "publisher", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="去除首尾空白",
        pattern=r"^\s+|\s+$",
        replacement=r"",
        description="去除字段首尾的空白字符",
        category="格式清理",
        use_regex=True,
        case_sensitive=False,
        whole_word=False,
        fields=["title", "author", "publisher", "description", "isbn", "language"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="统一全角/半角标点",
        pattern=r"[，。；：！？]",
        replacement=lambda m: {"，": ",", "。": ".", "；": ";", "：": ":", "！": "!", "？": "?"}[m.group()],
        description="将全角标点转换为半角标点",
        category="格式统一",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["title", "author", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="统一ISBN格式",
        pattern=r"(\d{3})-?(\d{1,5})-?(\d{1,7})-?(\d{1,6})-?(\d{1})",
        replacement=r"\1-\2-\3-\4-\5",
        description="统一ISBN为带连字符的标准格式",
        category="格式统一",
        use_regex=True,
        case_sensitive=False,
        whole_word=False,
        fields=["isbn"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="整词匹配 曰/日 区分",
        pattern=r"\b(曰|日)\b",
        replacement=r"日",
        description="使用整词匹配区分'曰'和'日'，避免误替换",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=True,
        fields=["title", "author", "description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见OCR错误: 间/问",
        pattern=r"间",
        replacement=r"问",
        description="将OCR误识别的'间'修正为'问'（需上下文确认）",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["description"],
        is_builtin=True,
    ),
    ReplaceRule(
        name="修正常见OCR错误: 人/入",
        pattern=r"人",
        replacement=r"入",
        description="将OCR误识别的'人'修正为'入'（需上下文确认）",
        category="OCR纠错",
        use_regex=True,
        case_sensitive=True,
        whole_word=False,
        fields=["description"],
        is_builtin=True,
    ),
]


class RuleLibrary:
    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            config_dir = os.path.join(str(Path.home()), ".ebook_manager")
        self._config_dir = config_dir
        self._rules_file = os.path.join(config_dir, "replace_rules.json")
        self._rules: List[ReplaceRule] = []
        self._load_rules()

    def _load_rules(self) -> None:
        self._rules = list(BUILTIN_RULES)

        if os.path.exists(self._rules_file):
            try:
                with open(self._rules_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for rule_data in data:
                        try:
                            rule = ReplaceRule.from_dict(rule_data)
                            rule.is_builtin = False
                            self._rules.append(rule)
                        except Exception:
                            continue
            except Exception:
                pass

    def _save_rules(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        custom_rules = [r.to_dict() for r in self._rules if not r.is_builtin]
        try:
            with open(self._rules_file, "w", encoding="utf-8") as f:
                json.dump(custom_rules, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_all_rules(self) -> List[ReplaceRule]:
        return list(self._rules)

    def get_builtin_rules(self) -> List[ReplaceRule]:
        return [r for r in self._rules if r.is_builtin]

    def get_custom_rules(self) -> List[ReplaceRule]:
        return [r for r in self._rules if not r.is_builtin]

    def get_rules_by_category(self, category: str) -> List[ReplaceRule]:
        return [r for r in self._rules if r.category == category]

    def get_categories(self) -> List[str]:
        categories = sorted({r.category for r in self._rules})
        return categories

    def add_rule(self, rule: ReplaceRule) -> None:
        rule.is_builtin = False
        self._rules.append(rule)
        self._save_rules()

    def update_rule(self, index: int, rule: ReplaceRule) -> bool:
        if 0 <= index < len(self._rules):
            if self._rules[index].is_builtin:
                return False
            rule.is_builtin = False
            self._rules[index] = rule
            self._save_rules()
            return True
        return False

    def delete_rule(self, index: int) -> bool:
        if 0 <= index < len(self._rules):
            if self._rules[index].is_builtin:
                return False
            del self._rules[index]
            self._save_rules()
            return True
        return False

    def find_rule_by_name(self, name: str) -> Optional[ReplaceRule]:
        for rule in self._rules:
            if rule.name == name:
                return rule
        return None

    def search_rules(self, keyword: str) -> List[ReplaceRule]:
        keyword = keyword.lower()
        results = []
        for rule in self._rules:
            if (keyword in rule.name.lower() or
                keyword in rule.description.lower() or
                keyword in rule.category.lower() or
                keyword in rule.pattern.lower()):
                results.append(rule)
        return results
