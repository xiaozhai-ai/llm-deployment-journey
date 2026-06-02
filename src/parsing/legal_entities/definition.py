"""
定义引用提取

检测合同中的术语定义和引用：
- "以下简称XXX" 模式检测
- "以下称XXX" / "（以下简称'XXX'）" 变体
- 定义-引用交叉链接（标记后续条款中使用该术语的位置）
"""

from __future__ import annotations

import re

from src.core.data_models import Definition
from src.infra.logger import logger_manager

# 定义模式列表（按优先级排序）
_DEFINITION_PATTERNS = [
    # "甲方（以下简称'甲方'）" — 全称在前
    re.compile(
        r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·（()）]{2,30})"
        r"(?:\s*[(（]\s*以下简称\s*['\u2018\"]?\s*(.+?)\s*['\u2019\"]?\s*[)）])"
    ),
    # "以下简称XXX" — 直接定义
    re.compile(r"以下简称\s*['\u2018\"]?\s*(.+?)\s*['\u2019\"]?(?:[，。,.\s]|$)"),
    # "以下称XXX"
    re.compile(r"以下(?:简称|称)\s*['\u2018\"]?\s*(.+?)\s*['\u2019\"]?(?:[，。,.\s]|$)"),
    # "XXX（下称'YYY'）"
    re.compile(
        r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·（()）]{2,30})"
        r"(?:\s*[(（]\s*下称\s*['\u2018\"]?\s*(.+?)\s*['\u2019\"]?\s*[)）])"
    ),
]

# 定义条款关键词（用于识别定义条款）
_DEFINITION_CLAUSE_KEYWORDS = [
    "定义", "术语定义", "名词解释", "词语定义", "词语解释",
    "本合同中", "本合同中下列词语", "下列术语", "下列用语",
]

# 定义条款内的术语定义模式（"XXX是指..." 或 "XXX：指..."）
_DEFINITION_CLAUSE_PATTERN = re.compile(
    r"['\u2018\"]?([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{1,15})['\u2019\"]?"
    r"\s*(?:是指|指|系指|是|为)\s*(.{5,100}?)(?:[。；;]|$)"
)


def extract_definitions(
    text: str,
    clauses: list | None = None,
) -> list[Definition]:
    """
    提取合同中的术语定义

    Args:
        text: 合同全文
        clauses: 条款列表（可选，用于关联 clause_id）

    Returns:
        list[Definition]: 定义列表（含引用链接）
    """
    definitions: list[Definition] = []
    seen_terms: set[str] = set()

    # 方法 1：全文搜索 "以下简称XXX" 模式
    inline_defs = _extract_inline_definitions(text, clauses)
    for d in inline_defs:
        if d.term not in seen_terms:
            seen_terms.add(d.term)
            definitions.append(d)

    # 方法 2：识别定义条款（"定义" 章节）
    clause_defs = _extract_definition_clauses(text, clauses)
    for d in clause_defs:
        if d.term not in seen_terms:
            seen_terms.add(d.term)
            definitions.append(d)

    # 方法 3：建立引用链接
    if definitions:
        _link_references(text, definitions, clauses)

    return definitions


def _extract_inline_definitions(
    text: str,
    clauses: list | None = None,
) -> list[Definition]:
    """提取内联定义（"以下简称XXX" 模式）"""
    definitions: list[Definition] = []

    for pattern in _DEFINITION_PATTERNS:
        for m in pattern.finditer(text):
            groups = m.groups()

            if len(groups) == 2 and groups[0] and groups[1]:
                # "全称（以下简称'简称'）" 格式
                full_name = groups[0].strip()
                short_name = groups[1].strip()
                definition_text = full_name
            elif len(groups) == 1:
                # "以下简称XXX" 格式（全称在前文）
                short_name = groups[0].strip()
                full_name = _find_full_name_before(text, m.start())
                definition_text = full_name or short_name
            else:
                continue

            if not short_name or len(short_name) > 20:
                continue

            # 查找所属条款
            clause_id = _find_clause_id(clauses, m.start()) if clauses else None

            definitions.append(
                Definition(
                    term=short_name,
                    definition_text=definition_text,
                    clause_id=clause_id or "",
                )
            )

    return definitions


def _extract_definition_clauses(
    text: str,
    clauses: list | None = None,
) -> list[Definition]:
    """
    提取定义条款中的术语

    识别 "XXX是指YYY" / "XXX：指YYY" 格式
    """
    definitions: list[Definition] = []

    # 查找定义条款
    lines = text.split("\n")
    in_definition_section = False

    for i, line in enumerate(lines):
        line_stripped = line.strip()

        # 检测是否进入定义条款
        if any(kw in line_stripped for kw in _DEFINITION_CLAUSE_KEYWORDS):
            in_definition_section = True

        # 在定义条款内搜索术语定义
        if in_definition_section:
            for m in _DEFINITION_CLAUSE_PATTERN.finditer(line_stripped):
                term = m.group(1).strip()
                def_text = m.group(2).strip()

                if not term or len(term) > 16:
                    continue

                # 查找所属条款
                clause_id = _find_clause_id(clauses, text.find(line_stripped)) if clauses else None

                definitions.append(
                    Definition(
                        term=term,
                        definition_text=def_text,
                        clause_id=clause_id or "",
                    )
                )

            # 遇到新的章节标题时退出定义条款
            if re.match(r"^(?:第[一二三四五六七八九十百千]+[条章节]|[\d]+[.．、])", line_stripped):
                if i > 0 and not any(kw in line_stripped for kw in _DEFINITION_CLAUSE_KEYWORDS):
                    in_definition_section = False

    return definitions


def _find_full_name_before(text: str, pos: int) -> str:
    """在定义位置之前查找全称"""
    # 取前 100 字符
    before = text[max(0, pos - 100):pos]

    # 查找最后一个合理的名词短语（2-30 字）
    m = re.search(
        r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9·（()）]{2,30})$",
        before,
    )
    if m:
        return m.group(1).strip()
    return ""


def _find_clause_id(clauses: list | None, pos: int) -> str | None:
    """根据文本位置查找所属条款 ID"""
    if not clauses:
        return None

    # 查找包含该位置的条款
    for clause in reversed(clauses):
        if hasattr(clause, "id"):
            return str(clause.id)
    return None


def _link_references(
    text: str,
    definitions: list[Definition],
    clauses: list | None = None,
) -> None:
    """
    在全文中查找对已定义术语的引用

    更新 Definition.references 字段。
    """
    if not definitions:
        return

    # 为每个定义构建匹配模式
    for defn in definitions:
        term = defn.term
        if len(term) < 2:
            continue

        # 统计该术语在全文中的出现次数
        count = text.count(term)
        if count <= 1:
            continue

        # 查找引用位置（排除定义位置本身）
        ref_positions = []
        start = 0
        while True:
            idx = text.find(term, start)
            if idx == -1:
                break
            ref_positions.append(idx)
            start = idx + len(term)

        # 关联到条款
        if clauses and ref_positions:
            ref_clause_ids: set[str] = set()
            for pos in ref_positions:
                clause_id = _find_clause_id(clauses, pos)
                if clause_id and clause_id != defn.clause_id:
                    ref_clause_ids.add(clause_id)
            defn.references = list(ref_clause_ids)
