"""
金额实体提取

从合同文本中提取金额信息，支持：
- 阿拉伯数字：100,000.00元 / ¥100,000 / 人民币10万元
- 中文大写：壹拾万元整
- 大小写一致性校验
"""

from __future__ import annotations

import re

from src.data_models import MoneyAmount
from src.logger import logger_manager

# 中文大写数字 → 阿拉伯数字
_UPPER_DIGITS = {
    "零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
    "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
}

# 中文大写单位
_UPPER_UNITS = {"拾": 10, "佰": 100, "仟": 1000, "萬": 10000, "万": 10000, "亿": 100000000}

# 货币符号/前缀 → 标准代码
_CURRENCY_MAP = {
    "¥": "CNY", "￥": "CNY", "人民币": "CNY",
    "$": "USD", "美元": "USD", "美金": "USD",
    "€": "EUR", "欧元": "EUR",
    "£": "GBP", "英镑": "GBP",
    "HK$": "HKD", "港币": "HKD", "港元": "HKD",
    "JPY": "JPY", "日元": "JPY",
}

# 金额提取模式
_AMOUNT_PATTERNS = [
    # "人民币壹拾万元整" / "人民币100,000元"
    re.compile(
        r"(人民币|RMB|CNY)\s*"
        r"([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+元(?:整|角|分)?|\d[\d,，]*\.?\d*[万亿]?元)"
    ),
    # "¥100,000.00" / "￥10万"
    re.compile(r"[¥￥]\s*(\d[\d,，]*\.?\d*[万亿]?)"),
    # "$100,000.00"
    re.compile(r"\$\s*(\d[\d,，]*\.?\d*)"),
    # "100,000.00元" / "10万元"
    re.compile(r"(\d[\d,，]*\.?\d*(?:万|亿)?)[元圆]"),
    # "金额为100,000" / "价款100,000"
    re.compile(
        r"(?:金额|价款|价格|总价|总金额|合同金额|报酬|费用|租金|借款)"
        r"(?:为|：|:|\s)\s*"
        r"[¥￥]?\s*(\d[\d,，]*\.?\d*(?:万|亿)?)[元圆]?"
    ),
]

# 中文大写金额模式
_UPPER_AMOUNT_PATTERN = re.compile(
    r"([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+)元(?:整|角|分)?"
)

# 阿拉伯数字金额 + 中文大写 配对模式（同一句中出现）
_PAIRED_PATTERN = re.compile(
    r"[¥￥]?\s*(\d[\d,，]*\.?\d*(?:万|亿)?)[元圆]?\s*"
    r"[（(]\s*(?:大写[：:]?\s*)?([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+元(?:整|角|分)?)\s*[）)]"
    r"|"
    r"[（(]\s*(?:大写[：:]?\s*)?([零壹贰叁肆伍陆柒捌玖拾佰仟万亿]+元(?:整|角|分)?)\s*[）)]\s*"
    r"[¥￥]?\s*(\d[\d,，]*\.?\d*(?:万|亿)?)[元圆]?"
)

_pair_counter = 0


def extract_amounts(text: str) -> list[MoneyAmount]:
    """
    从合同全文提取所有金额实体

    Args:
        text: 合同全文

    Returns:
        list[MoneyAmount]: 金额实体列表
    """
    global _pair_counter
    _pair_counter = 0

    if not text.strip():
        return []

    amounts: list[MoneyAmount] = []
    seen_texts: set[str] = set()

    # 先尝试提取配对的大小写金额（一致性校验）
    for m in _PAIRED_PATTERN.finditer(text):
        amount = _parse_paired_amount(m, text)
        if amount and amount.raw_text not in seen_texts:
            seen_texts.add(amount.raw_text)
            amounts.append(amount)

    # 再提取单独的金额
    for pattern in _AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(0).strip()
            if raw in seen_texts:
                continue

            amount = _parse_single_amount(m, raw, text)
            if amount:
                seen_texts.add(raw)
                amounts.append(amount)

    # 提取单独的中文大写金额
    for m in _UPPER_AMOUNT_PATTERN.finditer(text):
        raw = m.group(0).strip()
        if raw in seen_texts:
            continue

        value = _parse_chinese_uppercase(m.group(1))
        if value > 0:
            seen_texts.add(raw)
            amounts.append(
                MoneyAmount(
                    raw_text=raw,
                    amount=float(value),
                    currency="CNY",
                    uppercase_text=raw,
                    lowercase_text=None,
                    is_consistent=None,
                )
            )

    return amounts


def _parse_paired_amount(m: re.Match, full_text: str) -> MoneyAmount | None:
    """解析配对的大小写金额"""
    if m.group(1):  # 阿拉伯在前，中文在后
        lower_str = m.group(1).replace(",", "").replace("，", "")
        upper_str = m.group(2)
    else:  # 中文在前，阿拉伯在后
        lower_str = m.group(4).replace(",", "").replace("，", "")
        upper_str = m.group(3)

    # 解析阿拉伯数字
    lower_value = _parse_number_with_unit(lower_str)
    upper_value = _parse_chinese_uppercase(upper_str.replace("元", "").replace("整", ""))

    # 一致性校验
    is_consistent = abs(lower_value - upper_value) < 0.01 if lower_value > 0 and upper_value > 0 else None

    # 确定货币
    currency = _detect_currency(m.group(0))

    # 生成配对 ID
    global _pair_counter
    _pair_counter += 1
    pair_id = f"pair_{_pair_counter}"

    return MoneyAmount(
        raw_text=m.group(0).strip(),
        amount=lower_value if lower_value > 0 else upper_value,
        currency=currency,
        uppercase_text=upper_str,
        lowercase_text=lower_str,
        is_consistent=is_consistent,
        pair_id=pair_id,
    )


def _parse_single_amount(m: re.Match, raw: str, full_text: str) -> MoneyAmount | None:
    """解析单个金额"""
    # 提取数值部分
    num_str = None
    for i in range(1, m.lastindex + 1 if m.lastindex else 1):
        if m.group(i) and any(c.isdigit() for c in m.group(i)):
            num_str = m.group(i)
            break

    if not num_str:
        return None

    value = _parse_number_with_unit(num_str.replace(",", "").replace("，", ""))
    if value <= 0:
        return None

    currency = _detect_currency(raw)

    return MoneyAmount(
        raw_text=raw,
        amount=value,
        currency=currency,
        uppercase_text=None,
        lowercase_text=num_str,
        is_consistent=None,
    )


def _parse_number_with_unit(s: str) -> float:
    """解析带单位的数字（如 '10万'、'100,000'、'500万元'）"""
    s = s.replace(",", "").replace("，", "").strip()

    # 去除尾部货币文字
    for suffix in ("元", "圆", "美元", "欧元", "英镑"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break

    multiplier = 1
    if s.endswith("万"):
        multiplier = 10000
        s = s[:-1]
    elif s.endswith("亿"):
        multiplier = 100000000
        s = s[:-1]

    try:
        return float(s) * multiplier
    except ValueError:
        return 0


def _parse_chinese_uppercase(s: str) -> float:
    """解析中文大写金额（壹拾贰万叁仟肆佰伍拾陆元柒角捌分）"""
    s = s.replace("整", "").strip()
    if not s:
        return 0

    result = 0
    current = 0

    for char in s:
        if char in _UPPER_DIGITS:
            current = _UPPER_DIGITS[char]
        elif char in _UPPER_UNITS:
            unit = _UPPER_UNITS[char]
            if unit >= 10000:  # 万/亿
                result = (result + current) * unit
                current = 0
            else:
                # 拾/佰/仟：累积到 current（不立即加 result，等万/亿来乘）
                current = current * unit if current > 0 else unit
        elif char in ("元", "圆"):
            result += current
            current = 0
        elif char == "角":
            result += current * 0.1
            current = 0
        elif char == "分":
            result += current * 0.01
            current = 0

    result += current
    return result


def _detect_currency(text: str) -> str:
    """从文本中检测货币类型"""
    for symbol, code in _CURRENCY_MAP.items():
        if symbol in text:
            return code
    return "CNY"  # 默认人民币


def check_amount_consistency(amounts: list[MoneyAmount]) -> list[MoneyAmount]:
    """
    检查金额列表中的大小写一致性

    Args:
        amounts: 金额实体列表

    Returns:
        list[MoneyAmount]: 更新了 is_consistent 字段的列表
    """
    for amount in amounts:
        if amount.uppercase_text and amount.lowercase_text:
            upper_val = _parse_chinese_uppercase(
                amount.uppercase_text.replace("元", "").replace("整", "")
            )
            lower_val = _parse_number_with_unit(
                amount.lowercase_text.replace(",", "").replace("，", "")
            )
            if upper_val > 0 and lower_val > 0:
                amount.is_consistent = abs(upper_val - lower_val) < 0.01

    return amounts
