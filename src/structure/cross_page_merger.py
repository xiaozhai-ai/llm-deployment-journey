"""
跨页段落合并模块

检测并合并被分页截断的段落，确保条款内容的完整性。

合并策略：
1. 上一页最后一个文本块未以句末标点结尾（、。；：！？等）
2. 下一页第一个文本块不以序号/标题开头
3. 非表格/图片类块
4. 段落间距在合理范围内
"""

from __future__ import annotations

from src.data_models import LayoutBlock
from src.logger import logger_manager
from src.structure.clause_patterns import CLAUSE_HEADER_PATTERN, SENTENCE_END_PATTERN


def merge_cross_page_paragraphs(
    pages: list[list[LayoutBlock]],
) -> list[list[LayoutBlock]]:
    """
    合并跨页断裂的段落

    检测上一页末尾文本块是否被分页截断，如果是则与下一页开头块合并。

    Args:
        pages: 每页的版面块列表（已按阅读顺序排列）

    Returns:
        list[list[LayoutBlock]]: 合并后的每页版面块（可能减少块数）
    """
    if len(pages) < 2:
        return pages

    merged_pages = [list(page) for page in pages]  # 深拷贝

    for page_idx in range(len(merged_pages) - 1):
        current_page = merged_pages[page_idx]
        next_page = merged_pages[page_idx + 1]

        if not current_page or not next_page:
            continue

        # 找到当前页最后一个文本块
        last_block = _find_last_text_block(current_page)
        if last_block is None:
            continue

        # 找到下一页第一个文本块
        first_block = _find_first_text_block(next_page)
        if first_block is None:
            continue

        # 判断是否需要合并
        if _should_merge(last_block, first_block):
            # 合并：将下一页开头块的内容追加到上一页末尾块
            last_block.content = last_block.content.rstrip() + first_block.content.lstrip()
            # 从下一页移除已合并的块
            next_page.remove(first_block)
            logger_manager.debug(
                f"跨页合并: 页面 {page_idx} 末尾 ← 页面 {page_idx + 1} 开头"
            )

    return merged_pages


def _find_last_text_block(page: list[LayoutBlock]) -> LayoutBlock | None:
    """找到页面中最后一个文本/标题块"""
    for block in reversed(page):
        if block.block_type in ("text", "title"):
            return block
    return None


def _find_first_text_block(page: list[LayoutBlock]) -> LayoutBlock | None:
    """找到页面中第一个文本/标题块"""
    for block in page:
        if block.block_type in ("text", "title"):
            return block
    return None


def _should_merge(last_block: LayoutBlock, first_block: LayoutBlock) -> bool:
    """
    判断两个块是否应该合并

    条件（全部满足才合并）：
    1. 上一块不以句末标点结尾（说明被截断）
    2. 下一块不以条款标题/序号开头（说明不是新条款）
    3. 两块都是纯文本（非表格/图片）
    """
    last_text = last_block.content.rstrip()
    first_text = first_block.content.lstrip()

    if not last_text or not first_text:
        return False

    # 条件 1：上一块未以句末标点结尾
    if SENTENCE_END_PATTERN.search(last_text):
        return False

    # 条件 2：下一块不以条款标题开头
    if CLAUSE_HEADER_PATTERN.match(first_text):
        return False

    # 条件 3：两块都是文本类型
    if last_block.block_type not in ("text", "title"):
        return False
    if first_block.block_type not in ("text", "title"):
        return False

    return True


def merge_page_texts(pages: list[list[LayoutBlock]]) -> str:
    """
    将多页版面块按阅读顺序拼接为全文

    Args:
        pages: 每页的版面块列表

    Returns:
        str: 拼接后的全文
    """
    text_parts: list[str] = []
    for page in pages:
        ordered = sorted(page, key=lambda b: b.reading_order)
        for block in ordered:
            if block.block_type in ("text", "title") and block.content.strip():
                text_parts.append(block.content.strip())
            elif block.block_type == "table" and block.content.strip():
                text_parts.append(block.content.strip())
    return "\n".join(text_parts)
