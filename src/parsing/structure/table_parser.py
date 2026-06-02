"""
复杂表格解析模块

处理无边框表格、合并单元格、嵌套表格，
将各种来源的表格数据统一为 [行][列] TableCell 矩阵。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from src.core.data_models import BBox, TableCell, TableBlock
from src.infra.logger import logger_manager


class HTMLTableParser(HTMLParser):
    """HTML 表格 → TableCell 矩阵解析器（支持合并单元格）"""

    def __init__(self):
        super().__init__()
        self.rows: list[list[TableCell]] = []
        self._current_row: list[TableCell] = []
        self._current_cell: list[str] = []
        self._in_cell = False
        self._is_header = False
        self._row_span = 1
        self._col_span = 1
        self._nesting = 0  # 嵌套表格层级

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attrs_dict = dict(attrs)
        if tag == "table":
            self._nesting += 1
            if self._nesting > 1:
                # 嵌套表格：将内容追加到当前单元格
                self._current_cell.append(f"[嵌套表格]")
            return

        if self._nesting > 1:
            return  # 忽略嵌套表格内部标签

        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._is_header = tag == "th"
            self._row_span = max(1, int(attrs_dict.get("rowspan", 1)))
            self._col_span = max(1, int(attrs_dict.get("colspan", 1)))
            self._current_cell = []
        elif tag == "br" and self._in_cell:
            self._current_cell.append("\n")

    def handle_endtag(self, tag: str):
        if tag == "table":
            self._nesting = max(0, self._nesting - 1)
            return

        if self._nesting > 1:
            return

        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            content = "".join(self._current_cell).strip()
            self._current_row.append(
                TableCell(
                    content=content,
                    row_span=self._row_span,
                    col_span=self._col_span,
                    is_header=self._is_header,
                )
            )
        elif tag == "tr" and self._current_row:
            self.rows.append(self._current_row)
            self._current_row = []

    def handle_data(self, data: str):
        if self._in_cell and self._nesting <= 1:
            self._current_cell.append(data)


def parse_html_table(html: str) -> list[list[TableCell]]:
    """
    将 HTML 表格解析为 [行][列] TableCell 矩阵

    支持 rowspan/colspan 合并单元格和嵌套表格标记。

    Args:
        html: HTML 表格字符串

    Returns:
        list[list[TableCell]]: 行列矩阵
    """
    if not html or "<table" not in html.lower():
        return []

    try:
        parser = HTMLTableParser()
        parser.feed(html)
        return parser.rows
    except Exception as e:
        logger_manager.warning(f"HTML 表格解析失败: {e}")
        return []


def parse_pdfplumber_table(raw_table: list[list[str | None]]) -> list[list[TableCell]]:
    """
    将 pdfplumber 的原始表格数据转为 TableCell 矩阵

    pdfplumber.extract_tables() 返回 list[list[str | None]]，
    每行是等长的单元格列表。

    Args:
        raw_table: pdfplumber 原始表格数据

    Returns:
        list[list[TableCell]]: 标准化矩阵
    """
    if not raw_table:
        return []

    rows: list[list[TableCell]] = []
    for row_idx, row in enumerate(raw_table):
        is_header = row_idx == 0
        cells = [
            TableCell(content=str(c).strip() if c else "", is_header=is_header)
            for c in row
        ]
        rows.append(cells)
    return rows


def detect_borderless_table(
    text_blocks: list[dict],
    page_width: float,
    page_height: float,
) -> list[list[TableCell]]:
    """
    检测无边框表格：基于文本块的空间对齐分析

    由 PaddleEngine._detect_borderless_tables 调用，用于 OCR 路径中
    检测 PaddleOCR 未识别的无边框表格。

    策略：
    1. 收集所有文本行的 bbox
    2. 按 y 坐标聚类为行（允许小误差）
    3. 按 x 坐标聚类为列（检测对齐模式）
    4. 如果行数 ≥ 2 且列数 ≥ 2，判定为表格

    Args:
        text_blocks: 文本块列表，每项需有 bbox (x1,y1,x2,y2) 和 content
        page_width: 页面宽度
        page_height: 页面高度

    Returns:
        list[list[TableCell]]: 检测到的表格矩阵，空列表表示未检测到
    """
    if len(text_blocks) < 4:
        return []

    # 提取文本行位置
    lines: list[dict] = []
    for block in text_blocks:
        bbox = block.get("bbox")
        content = block.get("content", "").strip()
        if not bbox or not content:
            continue
        lines.append(
            {
                "x1": bbox[0],
                "y1": bbox[1],
                "x2": bbox[2],
                "y2": bbox[3],
                "text": content,
            }
        )

    if len(lines) < 3:
        return []

    # 按 y 坐标聚类（行分组）
    lines.sort(key=lambda l: l["y1"])
    row_groups: list[list[dict]] = []
    current_group: list[dict] = [lines[0]]

    y_threshold = page_height * 0.008  # 行高误差阈值

    for line in lines[1:]:
        if abs(line["y1"] - current_group[0]["y1"]) < y_threshold:
            current_group.append(line)
        else:
            row_groups.append(current_group)
            current_group = [line]
    row_groups.append(current_group)

    if len(row_groups) < 2:
        return []

    # 按 x 坐标聚类（列分组）
    all_x_positions = sorted(set(l["x1"] for group in row_groups for l in group))
    if len(all_x_positions) < 2:
        return []

    x_threshold = page_width * 0.02  # 列对齐误差阈值
    column_starts: list[float] = [all_x_positions[0]]
    for x in all_x_positions[1:]:
        if x - column_starts[-1] > x_threshold:
            column_starts.append(x)

    if len(column_starts) < 2:
        return []

    # 构建表格矩阵
    rows: list[list[TableCell]] = []
    for group in row_groups:
        row_cells: list[str] = [""] * len(column_starts)
        for line in group:
            # 找到最近的列
            best_col = 0
            best_dist = float("inf")
            for col_idx, col_x in enumerate(column_starts):
                dist = abs(line["x1"] - col_x)
                if dist < best_dist:
                    best_dist = dist
                    best_col = col_idx
            # 追加内容（同列多行用换行连接）
            if row_cells[best_col]:
                row_cells[best_col] += "\n" + line["text"]
            else:
                row_cells[best_col] = line["text"]

        rows.append(
            [TableCell(content=text, is_header=(len(rows) == 0)) for text in row_cells]
        )

    return rows


def table_to_plain_text(rows: list[list[TableCell]]) -> str:
    """
    将 TableCell 矩阵转为纯文本（用于全文拼接）

    Args:
        rows: 行列矩阵

    Returns:
        str: 纯文本，行间换行，列间 " | " 分隔
    """
    lines: list[str] = []
    for row in rows:
        cells = [cell.content.strip() for cell in row if cell.content.strip()]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def merge_table_results(
    paddle_tables: list[TableBlock],
    pdfplumber_tables: list[list[list[str | None]]],
    page_index: int,
) -> list[TableBlock]:
    """
    合并 PaddleOCR 和 pdfplumber 的表格检测结果

    注意：当前未在主解析流程中使用，作为预留能力导出。
    当需要同时利用两种引擎的表格检测结果时调用。

    策略：PaddleOCR 优先，pdfplumber 补充未重叠区域的表格。

    Args:
        paddle_tables: PaddleOCR 检测到的表格
        pdfplumber_tables: pdfplumber 检测到的原始表格
        page_index: 页码

    Returns:
        list[TableBlock]: 合并后的表格列表
    """
    result = list(paddle_tables)

    if not pdfplumber_tables:
        return result

    # 如果 PaddleOCR 已检测到表格，检查是否有 pdfplumber 漏掉的
    paddle_table_count = len(paddle_tables)
    for idx, raw_table in enumerate(pdfplumber_tables):
        if idx < paddle_table_count:
            continue  # 已被 PaddleOCR 覆盖

        rows = parse_pdfplumber_table(raw_table)
        if not rows:
            continue

        result.append(
            TableBlock(
                block_id=f"p{page_index}_tbl_pp{idx}",
                bbox=BBox(0, 0, 0, 0),  # pdfplumber 不提供精确 bbox
                page_index=page_index,
                rows=rows,
                has_border=True,
                header_rows=1,
                html="",
                confidence=0.5,
            )
        )

    return result
