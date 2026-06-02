"""
扫描件检测模块

判断 PDF 是否为扫描件/图片 PDF，决定是否需要 OCR 处理。
检测策略：文本密度 + 图片占比 + 页面尺寸分析
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from src.infra.logger import logger_manager


@dataclass
class ScanDetectionResult:
    """扫描件检测结果"""

    is_scanned: bool  # 是否为扫描件
    text_density: float  # 文本密度（字符数/页面面积）
    image_ratio: float  # 图片占比（图片面积/页面面积）
    page_count: int  # 页面数
    text_page_count: int  # 有文本的页面数
    image_page_count: int  # 有图片的页面数
    reason: str  # 判定原因


class ScanDetector:
    """扫描件/电子原生文档检测器"""

    def __init__(self, text_density_threshold: float = 0.3, image_ratio_threshold: float = 0.5):
        """
        Args:
            text_density_threshold: 文本密度阈值，低于此值可能为扫描件
            image_ratio_threshold: 图片占比阈值，高于此值可能为扫描件
        """
        self.text_density_threshold = text_density_threshold
        self.image_ratio_threshold = image_ratio_threshold

    def detect_from_path(self, file_path: str) -> ScanDetectionResult:
        """从文件路径检测"""
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                return self._analyze_pdf(pdf)
        except Exception as e:
            logger_manager.warning(f"扫描件检测失败（路径）: {e}")
            return ScanDetectionResult(
                is_scanned=False,
                text_density=0.0,
                image_ratio=0.0,
                page_count=0,
                text_page_count=0,
                image_page_count=0,
                reason=f"检测失败，默认按电子文档处理: {e}",
            )

    def detect_from_bytes(self, file_bytes: bytes) -> ScanDetectionResult:
        """从字节流检测"""
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return self._analyze_pdf(pdf)
        except Exception as e:
            logger_manager.warning(f"扫描件检测失败（字节流）: {e}")
            return ScanDetectionResult(
                is_scanned=False,
                text_density=0.0,
                image_ratio=0.0,
                page_count=0,
                text_page_count=0,
                image_page_count=0,
                reason=f"检测失败，默认按电子文档处理: {e}",
            )

    def _analyze_pdf(self, pdf) -> ScanDetectionResult:
        """分析 PDF 判断是否为扫描件"""
        page_count = len(pdf.pages)
        if page_count == 0:
            return ScanDetectionResult(
                is_scanned=False,
                text_density=0.0,
                image_ratio=0.0,
                page_count=0,
                text_page_count=0,
                image_page_count=0,
                reason="空文档",
            )

        total_text_chars = 0
        total_page_area = 0
        total_image_area = 0
        text_pages = 0
        image_pages = 0

        for page in pdf.pages:
            page_width = page.width or 612  # 默认 A4 宽度
            page_height = page.height or 792  # 默认 A4 高度
            page_area = page_width * page_height
            total_page_area += page_area

            # 统计文本
            text = page.extract_text() or ""
            char_count = len(text.strip())
            total_text_chars += char_count

            if char_count > 20:  # 至少 20 个字符才算有文本
                text_pages += 1

            # 统计图片面积
            images = page.images or []
            page_image_area = 0
            for img in images:
                img_width = abs(img.get("x1", 0) - img.get("x0", 0))
                img_height = abs(img.get("y1", 0) - img.get("y0", 0))
                page_image_area += img_width * img_height

            total_image_area += page_image_area

            # 单页图片占比超过阈值，标记为图片页
            if page_area > 0 and (page_image_area / page_area) > self.image_ratio_threshold:
                image_pages += 1

        # 计算总体指标
        text_density = total_text_chars / max(total_page_area / 10000, 1)  # 每万像素字符数
        image_ratio = total_image_area / max(total_page_area, 1)

        # 判定逻辑
        is_scanned = False
        reasons = []

        # 条件1: 文本密度极低 + 大量图片 → 扫描件
        if text_density < self.text_density_threshold and image_ratio > self.image_ratio_threshold:
            is_scanned = True
            reasons.append(f"文本密度低({text_density:.2f})且图片占比高({image_ratio:.1%})")

        # 条件2: 多数页面无文本但有图片 → 扫描件
        elif page_count > 1 and text_pages < page_count * 0.3 and image_pages > page_count * 0.5:
            is_scanned = True
            reasons.append(f"{page_count}页中仅{text_pages}页有文本，{image_pages}页有图片")

        # 条件3: 文本密度极低（几乎没有文本）→ 可能是纯图片
        elif text_density < self.text_density_threshold * 0.3 and text_pages == 0:
            is_scanned = True
            reasons.append(f"无任何可提取文本（密度={text_density:.2f}）")

        if not reasons:
            if text_density >= self.text_density_threshold:
                reasons.append(f"文本密度正常({text_density:.2f})，判定为电子文档")
            else:
                reasons.append(f"文本密度偏低({text_density:.2f})但图片不多，按电子文档处理")

        logger_manager.info(
            f"扫描件检测: {'扫描件' if is_scanned else '电子文档'}, "
            f"密度={text_density:.2f}, 图片占比={image_ratio:.1%}, "
            f"文本页={text_pages}/{page_count}, 图片页={image_pages}/{page_count}"
        )

        return ScanDetectionResult(
            is_scanned=is_scanned,
            text_density=text_density,
            image_ratio=image_ratio,
            page_count=page_count,
            text_page_count=text_pages,
            image_page_count=image_pages,
            reason="; ".join(reasons),
        )
