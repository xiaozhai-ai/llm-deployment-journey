"""
法律实体提取模块

提取合同中的法律实体信息：
- metadata: 合同元数据（名称、类型、当事人、管辖）
- amount: 金额实体（阿拉伯数字/中文大写金额/一致性校验）
- date_extractor: 日期实体（中文/数字/相对日期、角色识别）
- signature: 签章识别（签名/盖章区域检测）
- revision: 修订追踪（Word Track Changes + PDF 注释 + 内联标记）
- definition: 定义引用（"以下简称XXX" 模式检测 + 引用链接）
"""

from __future__ import annotations

from src.legal_entities.amount import check_amount_consistency, extract_amounts
from src.legal_entities.date_extractor import extract_dates
from src.legal_entities.definition import extract_definitions
from src.legal_entities.metadata import extract_metadata
from src.legal_entities.revision import extract_revisions
from src.legal_entities.signature import detect_signatures

__all__ = [
    "extract_metadata",
    "extract_amounts",
    "check_amount_consistency",
    "extract_dates",
    "detect_signatures",
    "extract_revisions",
    "extract_definitions",
]
