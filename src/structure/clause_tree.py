"""
条款层级树构建器

将扁平的条款列表构建为层级树结构（ClauseNode），
支持中文/阿拉伯/罗马/混合编号体系，自动推断父子关系。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.data_models import BBox, ClauseNode
from src.logger import logger_manager


# ============================================================
# 编号解析
# ============================================================

# 中文数字 → 阿拉伯数字映射
_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# 层级判定规则（模式 → level）
_LEVEL_PATTERNS: list[tuple[str, str]] = [
    # 章
    (r"^第[一二三四五六七八九十百千\d]+章", "chapter"),
    # 节
    (r"^第[一二三四五六七八九十百千\d]+节", "section"),
    # 条
    (r"^第[一二三四五六七八九十百千\d]+条", "article"),
    # Article (英文)
    (r"^Article\s+", "article"),
    # Section (英文)
    (r"^Section\s+", "section"),
]

# 多级数字序号模式：1.1 / 1.1.1 / 1.1.1.1（带空格结尾）
_MULTI_LEVEL_SPACE = re.compile(r"^(\d+(?:\.\d+)+)\s+")
# 多级数字序号模式：1.1. / 1.1.1.（带分隔符结尾）
_MULTI_LEVEL_DOT = re.compile(r"^(\d+(?:\.\d+)+)[.．、]\s*")
# 单级数字序号：1. / 1、
_SINGLE_LEVEL = re.compile(r"^(\d+)[.．、]\s*")

# 中文数字序号：一、二、
_CN_SEQ_PATTERN = re.compile(r"^([一二三四五六七八九十]+)[、.．]\s*")

# 括号序号：（一）(1) （1）
_BRACKET_PATTERN = re.compile(r"^[（(]([一二三四五六七八九十\d]+)[）)]\s*")

# 罗马数字（简化匹配）
_ROMAN_PATTERN = re.compile(r"^(Article\s+[IVXLCDM]+)", re.IGNORECASE)


@dataclass
class ParsedNumber:
    """解析后的编号信息"""

    raw: str  # 原始编号文本
    level: str  # chapter | section | article | paragraph | subitem | item
    numeric_path: tuple[int, ...]  # 数值路径，用于排序和父子判定
    display: str  # 显示用编号


def parse_clause_number(title: str) -> ParsedNumber | None:
    """
    从条款标题中解析编号信息

    Args:
        title: 条款标题文本（如 "第五条 合同标的"、"5.1 付款方式"）

    Returns:
        ParsedNumber 或 None（无法解析时）
    """
    if not title:
        return None

    stripped = title.strip()

    # 策略 1：匹配 "第X章/节/条" 模式
    for pattern, level in _LEVEL_PATTERNS:
        m = re.match(pattern, stripped)
        if m:
            num = _extract_chinese_or_digit_number(m.group())
            return ParsedNumber(
                raw=m.group(),
                level=level,
                numeric_path=(num,),
                display=m.group(),
            )

    # 策略 2：匹配多级数字序号（1.1 / 1.1.1 / 1.1.1.1）
    # 优先匹配带空格的（如 "6.1 付款方式"），再匹配带分隔符的（如 "6.1."）
    for pattern in (_MULTI_LEVEL_SPACE, _MULTI_LEVEL_DOT):
        m = pattern.match(stripped)
        if m:
            parts_str = m.group(1)
            parts = tuple(int(p) for p in parts_str.split("."))
            depth = len(parts)
            level_map = {1: "article", 2: "paragraph", 3: "subitem", 4: "item"}
            level = level_map.get(depth, "item")
            return ParsedNumber(
                raw=m.group(),
                level=level,
                numeric_path=parts,
                display=parts_str,
            )

    # 策略 3：匹配单级数字序号（1. / 1、）
    m = _SINGLE_LEVEL.match(stripped)
    if m:
        num = int(m.group(1))
        return ParsedNumber(
            raw=m.group(),
            level="article",
            numeric_path=(num,),
            display=str(num),
        )

    # 策略 4：匹配中文数字序号（一、二、）
    m = _CN_SEQ_PATTERN.match(stripped)
    if m:
        cn = m.group(1)
        num = _CN_DIGITS.get(cn, 0)
        return ParsedNumber(
            raw=m.group(),
            level="article",
            numeric_path=(num,),
            display=cn,
        )

    # 策略 4：匹配括号序号（(一)、(1)）
    m = _BRACKET_PATTERN.match(stripped)
    if m:
        inner = m.group(1)
        if inner in _CN_DIGITS:
            num = _CN_DIGITS[inner]
        elif inner.isdigit():
            num = int(inner)
        else:
            num = 0
        return ParsedNumber(
            raw=m.group(),
            level="item",
            numeric_path=(num,),
            display=inner,
        )

    # 策略 5：英文 Article/Section + 罗马数字
    m = _ROMAN_PATTERN.match(stripped)
    if m:
        return ParsedNumber(
            raw=m.group(),
            level="article",
            numeric_path=(0,),  # 罗马数字暂不转数值
            display=m.group(),
        )

    return None


def _extract_chinese_or_digit_number(text: str) -> int:
    """从 '第五条'、'第3章' 中提取数值"""
    # 尝试阿拉伯数字
    m = re.search(r"(\d+)", text)
    if m:
        return int(m.group(1))
    # 尝试中文数字
    for cn, num in _CN_DIGITS.items():
        if cn in text:
            return num
    return 0


# ============================================================
# 树构建
# ============================================================

# 层级优先级（数值越小越靠上）
_LEVEL_PRIORITY = {
    "chapter": 0,
    "section": 1,
    "article": 2,
    "paragraph": 3,
    "subitem": 4,
    "item": 5,
}


def build_clause_tree(
    clauses: list,
    clause_type_fn=None,
) -> list[ClauseNode]:
    """
    将扁平条款列表构建为层级树

    Args:
        clauses: Clause 对象列表（需有 id, title, content, start_pos, end_pos 属性）
        clause_type_fn: 可选的条款类型检测函数 (clause) -> str | None

    Returns:
        list[ClauseNode]: 顶层节点列表（森林）
    """
    if not clauses:
        return []

    # 解析每个条款的编号
    parsed: list[tuple[object, ParsedNumber | None]] = []
    for clause in clauses:
        pn = parse_clause_number(clause.title or "")
        parsed.append((clause, pn))

    # 构建树：使用栈维护当前层级路径
    root_nodes: list[ClauseNode] = []
    # 栈元素：(level_priority, numeric_path, node)
    stack: list[tuple[int, tuple[int, ...], ClauseNode]] = []

    node_counter = 0

    for clause, pn in parsed:
        node_counter += 1
        clause_type = clause_type_fn(clause) if clause_type_fn else None

        node = ClauseNode(
            node_id=f"c{node_counter}",
            clause_number=pn.display if pn else None,
            title=clause.title,
            level=pn.level if pn else "article",
            content=clause.content,
            bbox=None,
            page_index=None,
            clause_type=clause_type,
        )

        if pn is None:
            # 无编号条款：附加到当前栈顶，或作为顶层节点
            if stack:
                stack[-1][2].children.append(node)
            else:
                root_nodes.append(node)
            continue

        level_pri = _LEVEL_PRIORITY.get(pn.level, 5)
        numeric_path = pn.numeric_path

        # 弹出栈中层级 ≥ 当前层级的节点（回溯到父级）
        while stack and stack[-1][0] >= level_pri:
            stack.pop()

        if stack:
            # 作为栈顶节点的子节点
            stack[-1][2].children.append(node)
        else:
            # 顶层节点
            root_nodes.append(node)

        stack.append((level_pri, numeric_path, node))

    return root_nodes


def build_clause_tree_from_blocks(
    blocks: list,
) -> list[ClauseNode]:
    """
    从 LayoutBlock 列表构建条款树（保留 bbox 和 page_index 信息）

    适用于 OCR 路径，每个 block 已有 bbox 和 page_index。

    Args:
        blocks: LayoutBlock 对象列表（需有 block_type, content, bbox, page_index, block_id）

    Returns:
        list[ClauseNode]: 顶层节点列表
    """
    # 只处理 text 和 title 类型的块
    text_blocks = [b for b in blocks if b.block_type in ("text", "title") and b.content.strip()]

    if not text_blocks:
        return []

    # 将每个 block 视为一个"条款"，尝试从内容中提取标题
    root_nodes: list[ClauseNode] = []
    stack: list[tuple[int, tuple[int, ...], ClauseNode]] = []
    node_counter = 0

    for block in text_blocks:
        content = block.content.strip()
        # 尝试从第一行提取标题
        first_line = content.split("\n", 1)[0].strip()
        pn = parse_clause_number(first_line)

        node_counter += 1
        is_title_block = block.block_type == "title" or pn is not None

        node = ClauseNode(
            node_id=f"c{node_counter}",
            clause_number=pn.display if pn else None,
            title=first_line if is_title_block else None,
            level=pn.level if pn else "article",
            content=content,
            bbox=block.bbox,
            page_index=block.page_index,
            clause_type=None,
            block_ids=[block.block_id],
        )

        if pn is None:
            if stack:
                stack[-1][2].children.append(node)
            else:
                root_nodes.append(node)
            continue

        level_pri = _LEVEL_PRIORITY.get(pn.level, 5)
        numeric_path = pn.numeric_path

        while stack and stack[-1][0] >= level_pri:
            stack.pop()

        if stack:
            stack[-1][2].children.append(node)
        else:
            root_nodes.append(node)

        stack.append((level_pri, numeric_path, node))

    return root_nodes


def tree_to_dict_list(nodes: list[ClauseNode]) -> list[dict]:
    """将树节点列表转为字典列表（用于 JSON 序列化）"""
    return [_node_to_dict_recursive(n) for n in nodes]


def _node_to_dict_recursive(node: ClauseNode) -> dict:
    d = node.to_dict()
    if node.children:
        d["children"] = [_node_to_dict_recursive(c) for c in node.children]
    else:
        d["children"] = []
    return d


def count_nodes(nodes: list[ClauseNode]) -> int:
    """统计树中所有节点数量"""
    return sum(1 + count_nodes(n.children) for n in nodes)
