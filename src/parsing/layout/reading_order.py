"""
多列阅读顺序恢复

检测页面是否为多栏布局，并重新排列版面块的阅读顺序，
确保合同等法律文档的逻辑阅读顺序正确。

策略：
1. 检测列布局（基于文本块 x 坐标聚类）
2. 单栏：按 y 坐标从上到下排列
3. 多栏：先左栏从上到下，再右栏从上到下
4. 页眉/页脚始终排在首尾
"""

from __future__ import annotations

from src.core.data_models import BBox, LayoutBlock
from src.infra.logger import logger_manager


def detect_column_layout(
    blocks: list[LayoutBlock],
    page_width: float,
    page_height: float,
) -> int:
    """
    检测页面的栏数

    基于文本块的 x 坐标中位数聚类来判断栏数。

    Args:
        blocks: 版面块列表
        page_width: 页面宽度（像素）
        page_height: 页面高度（像素）

    Returns:
        int: 检测到的栏数（1 或 2）
    """
    # 只看 text/title 类型的块，忽略 header/footer/table/image
    content_blocks = [
        b for b in blocks
        if b.block_type in ("text", "title") and b.bbox.area > 0
    ]

    if len(content_blocks) < 4:
        return 1

    # 收集所有块的 x 中位数
    x_centers = sorted(b.bbox.center_x for b in content_blocks)

    # 用页面中心线判断是否为双栏
    mid_x = page_width / 2
    left_count = sum(1 for x in x_centers if x < mid_x)
    right_count = sum(1 for x in x_centers if x >= mid_x)

    # 双栏条件：左右两侧各有足够多的块
    total = len(x_centers)
    if left_count >= total * 0.3 and right_count >= total * 0.3:
        # 进一步验证：左右两侧的 x 中位数是否有明显间距
        left_median = x_centers[left_count // 2] if left_count > 0 else 0
        right_median = x_centers[left_count + right_count // 2] if right_count > 0 else 0
        gap = right_median - left_median

        # 栏间距应大于页面宽度的 10%
        if gap > page_width * 0.10:
            return 2

    return 1


def restore_reading_order(
    blocks: list[LayoutBlock],
    page_width: float,
    page_height: float,
) -> list[LayoutBlock]:
    """
    恢复版面块的正确阅读顺序

    处理单栏和多栏布局，确保输出的 reading_order 字段正确。

    Args:
        blocks: 版面块列表（原始顺序可能不正确）
        page_width: 页面宽度
        page_height: 页面高度

    Returns:
        list[LayoutBlock]: reading_order 已更新的版面块列表
    """
    if not blocks:
        return blocks

    columns = detect_column_layout(blocks, page_width, page_height)

    if columns <= 1:
        return _sort_single_column(blocks)
    else:
        return _sort_multi_column(blocks, page_width)


def _sort_single_column(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """单栏排序：y 坐标从上到下，同行按 x 从左到右"""
    # 分离页眉/页脚和正文
    headers_footers = [b for b in blocks if b.block_type in ("header", "footer")]
    content = [b for b in blocks if b.block_type not in ("header", "footer")]

    # 正文按 y 排序
    content.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))

    # 页眉排最前，页脚排最后
    headers = [b for b in headers_footers if b.block_type == "header"]
    footers = [b for b in headers_footers if b.block_type == "footer"]

    ordered = headers + content + footers

    # 更新 reading_order
    for idx, block in enumerate(ordered):
        block.reading_order = idx

    return ordered


def _sort_multi_column(
    blocks: list[LayoutBlock],
    page_width: float,
) -> list[LayoutBlock]:
    """
    多栏排序：先左栏从上到下，再右栏从上到下

    页眉/页脚保持在首尾位置。
    """
    mid_x = page_width / 2

    headers = []
    footers = []
    left_blocks = []
    right_blocks = []

    for b in blocks:
        if b.block_type == "header":
            headers.append(b)
        elif b.block_type == "footer":
            footers.append(b)
        elif b.bbox.center_x < mid_x:
            left_blocks.append(b)
        else:
            right_blocks.append(b)

    # 各栏内部按 y 排序
    left_blocks.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))
    right_blocks.sort(key=lambda b: (b.bbox.y1, b.bbox.x1))

    # 合并：页眉 → 左栏 → 右栏 → 页脚
    ordered = headers + left_blocks + right_blocks + footers

    # 更新 reading_order
    for idx, block in enumerate(ordered):
        block.reading_order = idx

    return ordered


def restore_cross_page_order(
    pages: list[list[LayoutBlock]],
    page_width: float,
    page_height: float,
) -> list[list[LayoutBlock]]:
    """
    对多页文档逐页恢复阅读顺序

    Args:
        pages: 每页的版面块列表
        page_width: 页面宽度
        page_height: 页面高度

    Returns:
        list[list[LayoutBlock]]: 每页 reading_order 已更新的版面块
    """
    results: list[list[LayoutBlock]] = []
    for page_blocks in pages:
        results.append(restore_reading_order(page_blocks, page_width, page_height))
    return results
