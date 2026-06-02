"""
签章识别

检测合同中的签名、盖章信息：
- 签名区域检测（基于关键词 + 布局位置）
- 公章/骑缝章检测
- 当事人签章映射
"""

from __future__ import annotations

import re

from src.data_models import BBox, PageLayout, SignatureInfo
from src.logger import logger_manager

# 签章关键词
_SIGNATURE_KEYWORDS = [
    "签字", "签名", "签署", "签章", "签字盖章",
    "盖章", "公章", "合同专用章", "法人章",
    "甲方（签章）", "乙方（签章）",
    "甲方（盖章）", "乙方（盖章）",
]

# 当事人签章行模式
_PARTY_SEAL_PATTERN = re.compile(
    r"(甲|乙|丙|丁|出租|承租|买|卖|委托|受托|发包|承包)(?:方|人)"
    r"(?:\s*[（(][^）)]*[）)])?"
    r"(?:\s*[:：]?\s*)"
    r"(?:签[字章]|盖章)?"
)

# 签章区域关键词（用于定位页面底部签章区）
_SEAL_ZONE_KEYWORDS = [
    "签章", "签字盖章", "签字", "盖章", "签名",
    "甲方", "乙方", "签章日期", "签订日期",
]


def detect_signatures(
    text: str,
    clauses: list | None = None,
    pages: list[PageLayout] | None = None,
) -> list[SignatureInfo]:
    """
    检测合同中的签章信息

    Args:
        text: 合同全文
        clauses: 条款列表（可选，用于定位签章条款）
        pages: 页面布局列表（可选，用于定位签章区域）

    Returns:
        list[SignatureInfo]: 签章信息列表
    """
    signatures: list[SignatureInfo] = []

    # 方法 1：基于文本关键词检测
    text_sigs = _detect_from_text(text)
    signatures.extend(text_sigs)

    # 方法 2：基于布局检测签章区域（如果有页面布局）
    if pages:
        layout_sigs = _detect_from_layout(pages)
        # 合并（避免重复）
        existing_roles = {s.party_role for s in signatures}
        for sig in layout_sigs:
            if sig.party_role not in existing_roles:
                signatures.append(sig)

    # 去重
    signatures = _deduplicate(signatures)

    return signatures


def _detect_from_text(text: str) -> list[SignatureInfo]:
    """基于文本关键词检测签章"""
    signatures: list[SignatureInfo] = []
    seen_roles: set[str] = set()

    # 查找签章相关段落
    lines = text.split("\n")
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # 检测当事人签章行
        m = _PARTY_SEAL_PATTERN.search(line_stripped)
        if m:
            role = m.group(1)
            if len(role) == 1:
                role = role + "方"

            if role in seen_roles:
                continue
            seen_roles.add(role)

            # 检查上下文是否有签章关键词
            context = "\n".join(lines[max(0, i - 2):min(len(lines), i + 3)])
            has_sig = any(kw in context for kw in ["签字", "签名", "签署", "签章"])
            has_seal = any(kw in context for kw in ["盖章", "公章", "合同专用章", "法人章"])

            signatures.append(
                SignatureInfo(
                    party_role=role,
                    has_signature=has_sig,
                    has_seal=has_seal,
                )
            )

    # 如果没有找到明确的当事人签章，检查是否有通用签章标记
    if not signatures:
        has_any_sig = any(kw in text for kw in _SIGNATURE_KEYWORDS)
        if has_any_sig:
            signatures.append(
                SignatureInfo(
                    party_role="未知",
                    has_signature=True,
                    has_seal=False,
                )
            )

    return signatures


def _detect_from_layout(pages: list[PageLayout]) -> list[SignatureInfo]:
    """
    基于页面布局检测签章区域

    策略：查找页面底部区域包含签章关键词的文本块，
    以及可能的印章图片（红色区域检测）。
    """
    signatures: list[SignatureInfo] = []

    for page in pages:
        page_height = page.page_height
        if page_height <= 0:
            continue

        # 只检查页面底部 30% 区域
        bottom_threshold = page_height * 0.7

        seal_blocks = []
        for block in page.blocks:
            if block.bbox.y1 >= bottom_threshold:
                block_text = block.text.lower()
                if any(kw in block_text for kw in _SEAL_ZONE_KEYWORDS):
                    seal_blocks.append(block)

        if not seal_blocks:
            continue

        # 从签章块中提取当事人信息
        for block in seal_blocks:
            m = _PARTY_SEAL_PATTERN.search(block.text)
            if m:
                role = m.group(1)
                if len(role) == 1:
                    role = role + "方"

                signatures.append(
                    SignatureInfo(
                        party_role=role,
                        has_signature=any(kw in block.text for kw in ["签字", "签名"]),
                        has_seal=any(kw in block.text for kw in ["盖章", "公章"]),
                        seal_bbox=block.bbox,
                        page_index=page.page_index,
                    )
                )

    # 检测骑缝章（每页边缘有红色区域）
    # TODO: 需要图像分析支持，当前仅做文本标记

    return signatures


def _deduplicate(signatures: list[SignatureInfo]) -> list[SignatureInfo]:
    """去重：同一当事人只保留信息最丰富的记录"""
    by_role: dict[str, SignatureInfo] = {}

    for sig in signatures:
        role = sig.party_role
        if role not in by_role:
            by_role[role] = sig
        else:
            existing = by_role[role]
            # 合并：如果新记录有更多信息则替换
            new_score = (
                int(sig.has_signature) + int(sig.has_seal) + int(sig.has_riding_seal)
            )
            old_score = (
                int(existing.has_signature) + int(existing.has_seal) + int(existing.has_riding_seal)
            )
            if new_score > old_score:
                by_role[role] = sig

    return list(by_role.values())
