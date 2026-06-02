"""
共享条款模式常量

集中管理条款标题匹配的正则模式和关键词列表，
供 parser._split_clauses 和 cross_page_merger 复用。

支持从 config/clause_patterns.yml 加载自定义配置，
YAML 不存在时使用内置默认值。
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "clause_patterns.yml"

# ============================================================
# 条款标题正则模式（按优先级排序）
# ============================================================

_DEFAULT_PATTERNS: list[tuple[int, re.Pattern, str]] = [
    (1, re.compile(r"^(第[一二三四五六七八九十百千\d]+[条章节])\s*"), "中文：第一条/第一章"),
    (2, re.compile(r"^([一二三四五六七八九十]+[、.．])\s*"), "中文数字序号：一、二、"),
    (3, re.compile(r"^(第\d+条)\s*"), "中文数字序号：第1条"),
    (4, re.compile(r"^(\d+[.．、])\s*([^\n]{2,30})$"), "纯数字序号：1.、2.、3."),
    (5, re.compile(r"^(Article\s+[IVXLCDM\d]+)\s*"), "英文 Article"),
    (6, re.compile(r"^(Section\s+\d+(?:\.\d+)?)\s*"), "英文 Section"),
    (7, re.compile(r"^[（(]([一二三四五六七八九十\d]+)[）)]\s*([^\n]{2,30})$"), "带括号序号"),
]

_DEFAULT_KEYWORDS: list[str] = [
    "违约责任", "争议解决", "保密条款", "知识产权", "不可抗力", "生效条款",
    "当事人信息", "合同解除", "合同终止", "付款方式", "交货期限", "质量保证",
    "售后服务", "管辖法院", "适用法律", "定义与解释", "权利义务", "合作内容",
    "合作期限", "费用与支付", "保密义务", "其他约定", "附则", "总则",
]


def _load_from_yaml() -> tuple[list[tuple[int, re.Pattern, str]], list[str]]:
    """从 YAML 配置加载条款模式和关键词，失败时返回默认值"""
    if not _CONFIG_PATH.exists():
        return _DEFAULT_PATTERNS, _DEFAULT_KEYWORDS

    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return _DEFAULT_PATTERNS, _DEFAULT_KEYWORDS

    patterns_raw = data.get("patterns")
    keywords_raw = data.get("title_keywords")

    compiled: list[tuple[int, re.Pattern, str]] = []
    if isinstance(patterns_raw, list):
        for item in patterns_raw:
            try:
                regex = re.compile(item["regex"])
                priority = int(item.get("priority", 99))
                name = item.get("name", item["regex"][:40])
                compiled.append((priority, regex, name))
            except (KeyError, re.error, TypeError):
                continue

    keywords: list[str] = []
    if isinstance(keywords_raw, list):
        keywords = [str(kw) for kw in keywords_raw if isinstance(kw, str)]

    return (compiled or _DEFAULT_PATTERNS, keywords or _DEFAULT_KEYWORDS)


CLAUSE_PATTERNS, CLAUSE_TITLE_KEYWORDS = _load_from_yaml()

# 句末标点
SENTENCE_END_PATTERN: re.Pattern = re.compile(r"[。！？；：.!?;:]\s*$")

# 条款标题/序号开头模式（用于跨页合并判断）
# 动态生成，覆盖所有已配置的模式
_pattern_prefixes = [
    r"第[一二三四五六七八九十百千零壹贰叁肆伍陆柒捌玖拾佰仟\d]+[条章节条款]",
    r"[一二三四五六七八九十百]+[、.]",
    r"\d+[.．、]",
    r"\d+(?:\.\d+)+[.、\s]",
    r"Article\s+",
    r"Section\s+",
    r"Clause\s+",
    r"Paragraph\s+",
    r"Para\.?\s+",
    r"§\s*\d+",
    r"[（(][一二三四五六七八九十百\d]+[）)]",
    r"[（(][a-z][）)]",
    r"[IVXLCDM]+[.、\s]",
    r"附录",
    r"Appendix\s+",
]
# 追加所有关键词作为标题开头匹配
_escaped_keywords = [re.escape(kw) for kw in CLAUSE_TITLE_KEYWORDS]

CLAUSE_HEADER_PATTERN: re.Pattern = re.compile(
    r"^(" + "|".join(_pattern_prefixes + _escaped_keywords) + r")"
)
