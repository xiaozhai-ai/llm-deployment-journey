"""
日期实体提取

从合同文本中提取日期信息，支持：
- 中文日期：2024年1月15日 / 二〇二四年一月十五日
- 数字日期：2024-01-15 / 2024/01/15 / 2024.01.15
- 相对日期：合同签订之日起30日内
- 日期角色识别：签署日期/生效日期/到期日期/交货日期/付款日期
"""

from __future__ import annotations

import re

from src.core.data_models import DateEntity
from src.infra.logger import logger_manager

# 中文数字映射
_CN_DIGITS = {
    "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12,
}

# 日期模式列表（按优先级排序）
_DATE_PATTERNS = [
    # 中文日期：2024年1月15日
    (re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), "cn_numeric"),
    # 中文日期（带中文数字）：二〇二四年一月十五日
    (
        re.compile(
            r"([〇零一二三四五六七八九]{4})年"
            r"([一二三四五六七八九十]{1,3})月"
            r"([一二三四五六七八九十]{1,4})日"
        ),
        "cn_full",
    ),
    # ISO 日期：2024-01-15
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "iso"),
    # 斜线日期：2024/01/15
    (re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"), "slash"),
    # 点号日期：2024.01.15
    (re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})"), "dot"),
]

# 日期角色关键词
_DATE_ROLES = {
    "签署日期": ["签署日期", "签字日期", "签订日期", "签约日期", "签订之日"],
    "生效日期": ["生效日期", "生效之日", "生效日", "自.*起生效"],
    "到期日期": ["到期日期", "到期日", "届满日", "终止日期", "届满之日"],
    "交货日期": ["交货日期", "交付日期", "交货日", "交付日", "交货期限"],
    "付款日期": ["付款日期", "付款日", "支付日期", "支付日", "付款期限"],
    "验收日期": ["验收日期", "验收日", "验收期限"],
    "开工日期": ["开工日期", "开工日", "开工之日"],
    "竣工日期": ["竣工日期", "竣工日", "竣工之日"],
}

# 相对日期模式
_RELATIVE_DATE_PATTERN = re.compile(
    r"(自.{2,10}(?:之日起|起))(?:\s*)(\d+)(?:\s*)(日内|日|个月|天|年)"
)


def extract_dates(text: str) -> list[DateEntity]:
    """
    从合同全文提取所有日期实体

    Args:
        text: 合同全文

    Returns:
        list[DateEntity]: 日期实体列表
    """
    if not text.strip():
        return []

    dates: list[DateEntity] = []
    seen_raw: set[str] = set()

    # 提取绝对日期
    for pattern, fmt in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0).strip()
            if raw in seen_raw:
                continue

            standardized = _standardize_date(m, fmt)
            if standardized:
                seen_raw.add(raw)
                role = _detect_date_role(text, m.start())
                dates.append(
                    DateEntity(
                        raw_text=raw,
                        date=standardized,
                        role=role,
                    )
                )

    # 提取相对日期
    for m in _RELATIVE_DATE_PATTERN.finditer(text):
        raw = m.group(0).strip()
        if raw in seen_raw:
            continue
        seen_raw.add(raw)
        dates.append(
            DateEntity(
                raw_text=raw,
                date=f"relative:{m.group(2)}{m.group(3)}",
                role=_detect_date_role(text, m.start()),
            )
        )

    return dates


def _standardize_date(m: re.Match, fmt: str) -> str | None:
    """将匹配的日期标准化为 ISO 格式 (YYYY-MM-DD)"""
    try:
        if fmt in ("cn_numeric", "iso", "slash", "dot"):
            year = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3))

            if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
                return None

            return f"{year:04d}-{month:02d}-{day:02d}"

        elif fmt == "cn_full":
            year = _parse_cn_number(m.group(1))
            month = _parse_cn_number(m.group(2))
            day = _parse_cn_number(m.group(3))

            if not (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
                return None

            return f"{year:04d}-{month:02d}-{day:02d}"

    except (ValueError, IndexError):
        pass

    return None


def _parse_cn_number(s: str) -> int:
    """解析中文数字（如 '二〇二四' → 2024, '十五' → 15）"""
    # 先尝试直接映射
    if s in _CN_DIGITS:
        return _CN_DIGITS[s]

    # 处理多位数（如 "二〇二四"）
    result = 0
    for char in s:
        if char in _CN_DIGITS:
            result = result * 10 + _CN_DIGITS[char]
        elif char.isdigit():
            result = result * 10 + int(char)

    return result


def _detect_date_role(text: str, pos: int) -> str | None:
    """
    检测日期的角色（签署日期/生效日期等）

    基于日期前后的上下文关键词判断。

    Args:
        text: 全文
        pos: 日期在文本中的位置

    Returns:
        str | None: 角色名称
    """
    # 取日期前后各 100 字符作为上下文
    start = max(0, pos - 100)
    end = min(len(text), pos + 100)
    context = text[start:end]

    for role, keywords in _DATE_ROLES.items():
        for kw in keywords:
            if ".*" in kw:
                # 正则模式
                if re.search(kw, context):
                    return role
            elif kw in context:
                return role

    return None


def extract_dates_from_clauses(clauses: list) -> list[DateEntity]:
    """
    从条款列表中提取日期，并关联 clause_id

    Args:
        clauses: Clause 对象列表（需有 id, content 属性）

    Returns:
        list[DateEntity]: 带 clause_id 的日期实体
    """
    all_dates: list[DateEntity] = []

    for clause in clauses:
        clause_dates = extract_dates(clause.content)
        for d in clause_dates:
            d.clause_id = str(clause.id)
        all_dates.extend(clause_dates)

    return all_dates
