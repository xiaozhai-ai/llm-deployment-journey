"""
版面分析引擎统一接口

定义 LayoutEngine 抽象基类，各引擎（PaddleOCR 等）实现此接口。
使用工厂模式按配置创建具体引擎实例。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.core.data_models import PageLayout

if TYPE_CHECKING:
    pass


class LayoutEngine(ABC):
    """版面分析引擎抽象基类"""

    @abstractmethod
    def analyze_image(self, image_bytes: bytes, page_index: int = 0) -> PageLayout:
        """
        分析单张图片的版面

        Args:
            image_bytes: 图片字节流
            page_index: 页码索引

        Returns:
            PageLayout: 页面版面信息
        """
        ...

    @abstractmethod
    def analyze_pdf(self, pdf_bytes: bytes) -> list[PageLayout]:
        """
        分析 PDF 所有页面的版面

        Args:
            pdf_bytes: PDF 字节流

        Returns:
            list[PageLayout]: 逐页版面信息
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查引擎是否可用（依赖是否已安装）"""
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """引擎名称"""
        ...

    @property
    @abstractmethod
    def device(self) -> str:
        """当前设备"""
        ...


# 全局引擎实例
_engine: LayoutEngine | None = None


def get_layout_engine(engine_name: str = "paddleocr", **kwargs) -> LayoutEngine | None:
    """
    获取版面分析引擎实例（工厂函数）

    Args:
        engine_name: 引擎名称
        **kwargs: 传递给引擎构造函数的参数

    Returns:
        LayoutEngine 实例，不可用时返回 None
    """
    global _engine

    if _engine is not None:
        return _engine

    if engine_name == "paddleocr":
        from src.parsing.layout.paddle_engine import PaddleLayoutEngine

        _engine = PaddleLayoutEngine(**kwargs)
    else:
        raise ValueError(f"不支持的版面分析引擎: {engine_name}")

    if not _engine.is_available():
        return None

    return _engine


def reset_layout_engine():
    """重置引擎实例（用于测试或配置变更）"""
    global _engine
    _engine = None


class LayoutAnalysisTimer:
    """版面分析计时器"""

    def __init__(self):
        self.elapsed_ms: float = 0
        self._start: float = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
