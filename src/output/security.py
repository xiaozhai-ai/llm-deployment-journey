"""
安全合规模块
负责敏感信息检测、脱敏处理、安全边界检查
"""

import re
from dataclasses import dataclass


@dataclass
class SensitiveInfo:
    """敏感信息"""

    type: str  # 类型：id_card, phone, email, bank_card, address
    position: tuple[int, int]  # 位置 (start, end)
    masked_value: str  # 脱敏后的值


@dataclass
class SecurityCheckResult:
    """安全检查结果"""

    sensitive_items: list[SensitiveInfo]
    out_of_scope: bool  # 是否超出能力范围
    out_of_scope_reason: str | None = None
    risk_warning: str | None = None  # 安全风险提示


class SecurityPreprocessor:
    """安全预处理器"""

    # 超出能力范围的关键字（仅在没有安全词抑制时触发）
    OUT_OF_SCOPE_KEYWORDS = [
        "刑事犯罪",
        "刑罚",
        "有期徒刑",
        "拘役",
        "管制",
        "无期徒刑",
        "死刑",
    ]

    # 安全词：出现时抑制对应范围关键词的误报
    OUT_OF_SCOPE_SAFE_KEYWORDS = [
        "保密义务",
        "刑事责任条款",
        "法律法规",
        "适用法律",
        "管辖",
        "合规",
        "刑事附带民事",
    ]

    def __init__(self):
        # 敏感信息匹配模式
        self.patterns = {
            "身份证号": re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)"),
            "手机号": re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)"),
            "邮箱": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
            "银行卡号": re.compile(r"(?<!\d)(\d{16,19})(?!\d)"),
            "统一社会信用代码": re.compile(r"[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}"),
        }

    def check_text(self, text: str) -> SecurityCheckResult:
        """
        对文本进行安全检查

        Args:
            text: 待检查文本

        Returns:
            SecurityCheckResult: 安全检查结果
        """
        sensitive_items = self._detect_sensitive_info(text)
        out_of_scope, reason = self._check_out_of_scope(text)
        risk_warning = self._generate_risk_warning(sensitive_items)

        return SecurityCheckResult(
            sensitive_items=sensitive_items,
            out_of_scope=out_of_scope,
            out_of_scope_reason=reason,
            risk_warning=risk_warning,
        )

    def mask_sensitive_info(self, text: str) -> tuple[str, list[SensitiveInfo]]:
        """
        检测并脱敏敏感信息

        Args:
            text: 原始文本

        Returns:
            Tuple[脱敏后文本, 敏感信息列表]
        """
        sensitive_items = self._detect_sensitive_info(text)
        masked_text = text

        # 按位置从后往前替换，避免位置偏移
        for item in sorted(sensitive_items, key=lambda x: x.position[0], reverse=True):
            start, end = item.position
            masked_text = masked_text[:start] + item.masked_value + masked_text[end:]

        return masked_text, sensitive_items

    def _detect_sensitive_info(self, text: str) -> list[SensitiveInfo]:
        """检测文本中的敏感信息"""
        items = []
        seen_spans: set[tuple[int, int]] = set()

        for info_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                value = match.group()
                span = (match.start(), match.end())

                # 银行卡号需要 Luhn 校验，减少误报
                if info_type == "银行卡号" and not self._luhn_check(value):
                    continue

                # 跳过已被更精确模式匹配的区间
                if span in seen_spans:
                    continue

                masked = self._mask_value(value, info_type)
                items.append(SensitiveInfo(type=info_type, position=span, masked_value=masked))
                seen_spans.add(span)

        return items

    @staticmethod
    def _luhn_check(number: str) -> bool:
        """Luhn 算法校验银行卡号有效性"""
        try:
            digits = [int(d) for d in number]
        except ValueError:
            return False

        checksum = 0
        reverse_digits = digits[::-1]
        for i, d in enumerate(reverse_digits):
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    def _mask_value(self, value: str, info_type: str) -> str:
        """对敏感信息进行脱敏处理"""
        if info_type == "身份证号":
            return value[:6] + "****" + value[-4:]
        elif info_type == "手机号":
            return value[:3] + "****" + value[-4:]
        elif info_type == "邮箱":
            parts = value.split("@")
            return parts[0][:2] + "***@" + parts[1]
        elif info_type == "银行卡号":
            return value[:4] + "****" + value[-4:]
        elif info_type == "统一社会信用代码":
            return value[:6] + "****" + value[-4:]
        return "***"

    def _check_out_of_scope(self, text: str) -> tuple[bool, str | None]:
        """
        检查文本是否超出处理能力范围

        Returns:
            Tuple[是否超出范围, 原因]
        """
        text_lower = text.lower()

        # 安全词出现时抑制范围检测（说明文档在合法引用法律条文）
        safe_hits = sum(1 for kw in self.OUT_OF_SCOPE_SAFE_KEYWORDS if kw in text_lower)
        if safe_hits >= 2:
            return False, None

        for keyword in self.OUT_OF_SCOPE_KEYWORDS:
            if keyword in text_lower:
                return True, f"检测到可能超出处理范围的内容：'{keyword}'，建议转交专业律师处理"

        return False, None

    def _generate_risk_warning(self, items: list[SensitiveInfo]) -> str | None:
        """生成安全风险提示"""
        if not items:
            return None

        types = set(item.type for item in items)
        warning_parts = []

        if "身份证号" in types:
            warning_parts.append("身份证号码")
        if "手机号" in types:
            warning_parts.append("手机号码")
        if "邮箱" in types:
            warning_parts.append("电子邮箱")
        if "银行卡号" in types:
            warning_parts.append("银行卡号")
        if "统一社会信用代码" in types:
            warning_parts.append("统一社会信用代码")

        if warning_parts:
            return f"⚠️ 检测到以下敏感信息类型：{'、'.join(warning_parts)}。建议在上传前进行脱敏处理。"
        return None
