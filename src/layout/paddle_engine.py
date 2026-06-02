"""
PaddleOCR PP-StructureV3 版面分析引擎

基于 PaddleOCR 的 PP-StructureV3 管线，提供：
- 文档版面分析（文本/标题/表格/图片/页眉/页脚）
- OCR 文字识别（中文优先）
- 表格结构化识别（HTML 输出）
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from src.data_models import BBox, LayoutBlock, PageLayout, TableCell, TableBlock
from src.layout.engine import LayoutEngine
from src.logger import logger_manager

# PaddleOCR 版面类型 → 我们的 block_type 映射
_LAYOUT_TYPE_MAP = {
    "text": "text",
    "title": "title",
    "figure": "image",
    "figure_caption": "text",
    "table": "table",
    "header": "header",
    "footer": "footer",
    "reference": "text",
    "equation": "text",
    "doc_title": "title",
}


class PaddleLayoutEngine(LayoutEngine):
    """PaddleOCR PP-StructureV3 版面分析引擎"""

    def __init__(self, lang: str = "ch", device: str = "cpu", model_config: str = "lightweight"):
        """
        Args:
            lang: OCR 语言（ch=中文, en=英文）
            device: 推理设备（cpu / gpu）
            model_config: 模型配置（lightweight=轻量级, standard=标准）
        """
        self._lang = lang
        self._device = device
        self._model_config = model_config
        self._engine: Any = None  # PPStructure 实例
        self._available: bool | None = None  # 缓存可用性

    @property
    def engine_name(self) -> str:
        return "paddleocr-ppstructurev3"

    @property
    def device(self) -> str:
        return self._device

    def is_available(self) -> bool:
        """检查 PaddleOCR 是否已安装且可初始化"""
        if self._available is not None:
            return self._available

        try:
            import paddleocr  # noqa: F401

            self._available = True
        except ImportError:
            logger_manager.info("PaddleOCR 未安装，OCR 功能不可用")
            self._available = False

        return self._available

    def _get_engine(self) -> Any:
        """懒加载 PPStructure 实例"""
        if self._engine is not None:
            return self._engine

        from paddleocr import PPStructure

        kwargs: dict[str, Any] = {
            "layout": True,
            "ocr": True,
            "table": True,
            "lang": self._lang,
            "device": self._device,
            "show_log": False,
        }

        if self._model_config == "lightweight":
            # 轻量级配置：使用较小模型，适合 CPU / 低资源环境
            kwargs["table_model_dir"] = None  # 使用默认轻量模型
            kwargs["layout_model_dir"] = None

        self._engine = PPStructure(**kwargs)
        logger_manager.info(f"PaddleOCR PP-Structure 初始化完成 (device={self._device}, lang={self._lang})")
        return self._engine

    def analyze_image(self, image_bytes: bytes, page_index: int = 0) -> PageLayout:
        """
        分析单张图片的版面

        Args:
            image_bytes: 图片字节流（PNG/JPEG）
            page_index: 页码索引

        Returns:
            PageLayout: 页面版面信息
        """
        import numpy as np
        from PIL import Image

        engine = self._get_engine()

        # bytes → numpy array
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_array = np.array(img)
        width, height = img.size

        # 调用 PP-Structure
        results = engine(img_array)

        # 解析结果
        blocks: list[LayoutBlock] = []
        tables: list[TableBlock] = []
        reading_order = 0

        for item in results:
            bbox_coords = item.get("bbox", [0, 0, 0, 0])
            region_type = item.get("type", "text")
            block_type = _LAYOUT_TYPE_MAP.get(region_type, "text")

            # PaddleOCR bbox 格式: [x1, y1, x2, y2]
            bbox = BBox(
                x1=float(bbox_coords[0]),
                y1=float(bbox_coords[1]),
                x2=float(bbox_coords[2]),
                y2=float(bbox_coords[3]),
            )

            block_id = f"p{page_index}_b{reading_order}"

            if block_type == "table":
                # 表格特殊处理：提取 HTML 和结构化数据
                table_block = self._parse_table_result(
                    item, block_id, bbox, page_index, reading_order
                )
                tables.append(table_block)
                # 同时生成一个 LayoutBlock 用于全文拼接
                content = self._table_html_to_text(item.get("res", {}).get("html", ""))
            else:
                content = self._extract_text_content(item)

            blocks.append(
                LayoutBlock(
                    block_id=block_id,
                    block_type=block_type,
                    bbox=bbox,
                    page_index=page_index,
                    reading_order=reading_order,
                    content=content,
                    confidence=self._extract_confidence(item),
                )
            )
            reading_order += 1

        # 恢复正确的阅读顺序（多栏布局支持）
        from src.layout.reading_order import restore_reading_order

        blocks = restore_reading_order(blocks, float(width), float(height))

        # 检测无边框表格：对未被 PaddleOCR 识别为表格的文本块做对齐分析
        blocks, extra_tables = self._detect_borderless_tables(
            blocks, page_index, len(tables), float(width), float(height)
        )
        tables.extend(extra_tables)

        return PageLayout(
            page_index=page_index,
            width=float(width),
            height=float(height),
            blocks=blocks,
            tables=tables,
        )

    def analyze_pdf(self, pdf_bytes: bytes) -> list[PageLayout]:
        """
        分析 PDF 所有页面的版面

        将每页渲染为图片后逐页分析。

        Args:
            pdf_bytes: PDF 字节流

        Returns:
            list[PageLayout]: 逐页版面信息
        """
        pages = self._render_pdf_pages(pdf_bytes)
        if not pages:
            logger_manager.warning("PDF 页面渲染失败或文档为空")
            return []

        results: list[PageLayout] = []
        for page_index, page_image_bytes in enumerate(pages):
            try:
                page_layout = self.analyze_image(page_image_bytes, page_index=page_index)
                results.append(page_layout)
                logger_manager.debug(
                    f"页面 {page_index} 分析完成: {len(page_layout.blocks)} 个版面块, "
                    f"{len(page_layout.tables)} 个表格"
                )
            except Exception as e:
                logger_manager.warning(f"页面 {page_index} 分析失败: {e}")
                # 生成空页面占位，保证页码对齐
                results.append(
                    PageLayout(page_index=page_index, width=0, height=0, blocks=[], tables=[])
                )

        # 跨页段落合并
        if len(results) > 1:
            from src.structure.cross_page_merger import merge_cross_page_paragraphs

            all_blocks = [page.blocks for page in results]
            merged_blocks = merge_cross_page_paragraphs(all_blocks)
            for page, merged in zip(results, merged_blocks):
                page.blocks = merged

        return results

    # ----------------------------------------------------------------
    # 内部辅助方法
    # ----------------------------------------------------------------

    @staticmethod
    def _render_pdf_pages(pdf_bytes: bytes, dpi: int = 200) -> list[bytes]:
        """将 PDF 每页渲染为 PNG 图片字节流"""
        try:
            import pdfplumber

            images: list[bytes] = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    # pdfplumber 渲染为 PIL Image
                    img = page.to_image(resolution=dpi).original
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    images.append(buf.getvalue())
            return images
        except Exception as e:
            logger_manager.error(f"PDF 页面渲染失败: {e}")
            return []

    @staticmethod
    def _extract_text_content(item: dict) -> str:
        """从 PaddleOCR 结果中提取纯文本"""
        res = item.get("res", [])
        if isinstance(res, str):
            return res
        if isinstance(res, list):
            lines = []
            for line_info in res:
                if isinstance(line_info, dict):
                    text = line_info.get("text", "")
                elif isinstance(line_info, (list, tuple)) and len(line_info) >= 2:
                    # (bbox, (text, confidence)) 格式
                    text = line_info[1][0] if isinstance(line_info[1], (list, tuple)) else str(line_info[1])
                else:
                    text = str(line_info)
                if text.strip():
                    lines.append(text.strip())
            return "\n".join(lines)
        return str(res) if res else ""

    @staticmethod
    def _extract_confidence(item: dict) -> float:
        """从 PaddleOCR 结果中提取平均置信度"""
        res = item.get("res", [])
        if not isinstance(res, list) or not res:
            return 0.0

        confidences: list[float] = []
        for line_info in res:
            if isinstance(line_info, dict):
                conf = line_info.get("confidence", 0.0)
            elif isinstance(line_info, (list, tuple)) and len(line_info) >= 2:
                inner = line_info[1]
                if isinstance(inner, (list, tuple)) and len(inner) >= 2:
                    conf = float(inner[1])
                else:
                    conf = 0.0
            else:
                conf = 0.0
            confidences.append(conf)

        return sum(confidences) / len(confidences) if confidences else 0.0

    @staticmethod
    def _parse_table_result(
        item: dict, block_id: str, bbox: BBox, page_index: int, reading_order: int
    ) -> TableBlock:
        """将 PaddleOCR 表格结果解析为 TableBlock"""
        res = item.get("res", {})
        html = res.get("html", "") if isinstance(res, dict) else ""

        # 尝试从 HTML 解析出结构化表格
        from src.structure.table_parser import parse_html_table

        rows = parse_html_table(html)

        return TableBlock(
            block_id=block_id,
            bbox=bbox,
            page_index=page_index,
            rows=rows,
            has_border=True,  # PaddleOCR 默认检测有边框表格
            header_rows=1 if rows else 0,
            html=html,
            confidence=0.0,
        )

    @staticmethod
    def _table_html_to_text(html: str) -> str:
        """将表格 HTML 转换为纯文本（用于全文拼接）"""
        from src.structure.table_parser import parse_html_table, table_to_plain_text

        rows = parse_html_table(html)
        return table_to_plain_text(rows)

    @staticmethod
    def _detect_borderless_tables(
        blocks: list[LayoutBlock],
        page_index: int,
        existing_table_count: int,
        page_width: float,
        page_height: float,
    ) -> tuple[list[LayoutBlock], list[TableBlock]]:
        """对文本块做无边框表格对齐检测，返回 (剩余blocks, 新检测到的表格)"""
        from src.structure.table_parser import detect_borderless_table, table_to_plain_text

        text_blocks = [
            b for b in blocks
            if b.block_type in ("text", "title") and b.content and b.content.strip()
        ]
        if len(text_blocks) < 4:
            return blocks, []

        text_block_dicts = [
            {"bbox": (b.bbox.x1, b.bbox.y1, b.bbox.x2, b.bbox.y2), "content": b.content}
            for b in text_blocks
        ]

        table_rows = detect_borderless_table(text_block_dicts, page_width, page_height)
        if not table_rows:
            return blocks, []

        # 计算被表格消费的文本块（bbox 完全落入表格区域）
        table_y1 = min(b.bbox.y1 for b in text_blocks if any(
            b.content.strip() == cell.content.strip()
            for row in table_rows for cell in row if cell.content.strip()
        ))
        table_y2 = max(b.bbox.y2 for b in text_blocks if any(
            b.content.strip() == cell.content.strip()
            for row in table_rows for cell in row if cell.content.strip()
        ))

        consumed_ids: set[str] = set()
        for b in text_blocks:
            if b.bbox.y1 >= table_y1 - 5 and b.bbox.y2 <= table_y2 + 5:
                consumed_ids.add(b.block_id)

        # 需要至少 60% 的文本块被消费才认为是有效表格
        if len(consumed_ids) < len(text_blocks) * 0.6:
            return blocks, []

        table_bbox = BBox(
            x1=min(b.bbox.x1 for b in text_blocks if b.block_id in consumed_ids),
            y1=table_y1,
            x2=max(b.bbox.x2 for b in text_blocks if b.block_id in consumed_ids),
            y2=table_y2,
        )

        table_block = TableBlock(
            block_id=f"p{page_index}_bt{existing_table_count}",
            bbox=table_bbox,
            page_index=page_index,
            rows=table_rows,
            has_border=False,
            header_rows=1 if table_rows else 0,
            html="",
            confidence=0.0,
        )

        remaining = [b for b in blocks if b.block_id not in consumed_ids]
        remaining.append(
            LayoutBlock(
                block_id=table_block.block_id,
                block_type="table",
                bbox=table_bbox,
                page_index=page_index,
                reading_order=0,
                content=table_to_plain_text(table_rows),
                confidence=0.0,
            )
        )

        logger_manager.info(
            f"检测到无边框表格 (page={page_index}, "
            f"rows={len(table_rows)}, consumed_blocks={len(consumed_ids)})"
        )

        return remaining, [table_block]
