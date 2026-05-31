"""
安全合规模块
负责敏感信息检测、脱敏处理、安全边界检查
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SensitiveInfo:
    """敏感信息"""
    type: str  # 类型：id_card, phone, email, bank_card, address
    value: str  # 原始值
    position: Tuple[int, int]  # 位置 (start, end)
    masked_value: str  # 脱敏后的值


@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    sensitive_items: List[SensitiveInfo]
    out_of_scope: bool  # 是否超出能力范围
    out_of_scope_reason: Optional[str] = None
    risk_warning: Optional[str] = None  # 安全风险提示


class SecurityPreprocessor:
    """安全预处理器"""

    # 超出能力范围的关键字
    OUT_OF_SCOPE_KEYWORDS = [
        "刑事", "犯罪", "刑罚", "有期徒刑", "拘役", "管制",
        "境外法律", "外国法", "国际法", "涉外",
        "知识产权诉讼", "专利无效",
        "税务筹划", "避税",
    ]

    def __init__(self):
        # 敏感信息匹配模式
        self.patterns = {
            "身份证号": re.compile(r'(?<!\d)(\d{17}[\dXx])(?!\d)'),
            "手机号": re.compile(r'(?<!\d)(1[3-9]\d{9})(?!\d)'),
            "邮箱": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
            "银行卡号": re.compile(r'(?<!\d)(\d{16,19})(?!\d)'),
            "统一社会信用代码": re.compile(r'[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}'),
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
            risk_warning=risk_warning
        )

    def mask_sensitive_info(self, text: str) -> Tuple[str, List[SensitiveInfo]]:
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

    def _detect_sensitive_info(self, text: str) -> List[SensitiveInfo]:
        """检测文本中的敏感信息"""
        items = []

        for info_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                value = match.group()
                masked = self._mask_value(value, info_type)
                items.append(SensitiveInfo(
                    type=info_type,
                    value=value,
                    position=(match.start(), match.end()),
                    masked_value=masked
                ))

        return items

    def _mask_value(self, value: str, info_type: str) -> str:
        """对敏感信息进行脱敏处理"""
        if info_type == "身份证号":
            return value[:6] + '****' + value[-4:]
        elif info_type == "手机号":
            return value[:3] + '****' + value[-4:]
        elif info_type == "邮箱":
            parts = value.split('@')
            return parts[0][:2] + '***@' + parts[1]
        elif info_type == "银行卡号":
            return value[:4] + '****' + value[-4:]
        elif info_type == "统一社会信用代码":
            return value[:6] + '****' + value[-4:]
        return '***'

    def _check_out_of_scope(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        检查文本是否超出处理能力范围

        Returns:
            Tuple[是否超出范围, 原因]
        """
        text_lower = text.lower()

        for keyword in self.OUT_OF_SCOPE_KEYWORDS:
            if keyword in text_lower:
                return True, f"检测到可能超出处理范围的内容：'{keyword}'，建议转交专业律师处理"

        return False, None

    def _generate_risk_warning(self, items: List[SensitiveInfo]) -> Optional[str]:
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

    def check_file_type_compatibility(self, file_type: str) -> Tuple[bool, Optional[str]]:
        """
        检查文件类型是否适合处理

        Args:
            file_type: 文件类型（pdf, docx, txt）

        Returns:
            Tuple[是否兼容, 提示信息]
        """
        supported = {'pdf', 'docx', 'doc', 'txt'}
        if file_type.lower() in supported:
            return True, None
        return False, f"不支持的文件类型: {file_type}，请上传 PDF、Word 或 TXT 格式文件"
