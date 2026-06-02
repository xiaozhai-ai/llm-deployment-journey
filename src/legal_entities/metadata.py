"""
合同元数据提取

从合同全文中提取结构化元数据：合同名称、类型、当事人、
签署日期、争议解决方式、适用法律等。
"""

from __future__ import annotations

import re

from src.data_models import ContractParty, LegalMetadata
from src.logger import logger_manager

# 合同名称模式（通常在文档开头）
_CONTRACT_NAME_PATTERNS = [
    # "XXX合同" / "XXX协议" 作为独立行
    re.compile(r"^[\s]*(.{2,30}(?:合同|协议|契约|合约))[\s]*$", re.MULTILINE),
    # "关于XXX的合同"
    re.compile(r"(?:关于|有关).{2,20}(?:合同|协议)"),
]

# 合同类型关键词
_CONTRACT_TYPE_KEYWORDS = {
    "买卖合同": ["买卖合同", "购销合同", "采购合同", "销售合同"],
    "租赁合同": ["租赁合同", "租房合同", "房屋租赁", "场地租赁"],
    "劳动合同": ["劳动合同", "雇佣合同", "劳务合同"],
    "服务合同": ["服务合同", "服务协议", "技术服务", "咨询服务"],
    "借款合同": ["借款合同", "贷款合同", "借贷合同"],
    "建设合同": ["建设工程合同", "施工合同", "工程承包"],
    "知识产权合同": ["知识产权", "专利许可", "商标许可", "著作权许可"],
    "保密协议": ["保密协议", "保密合同", "NDA"],
    "合作协议": ["合作协议", "合作合同", "战略协议"],
    "委托合同": ["委托合同", "委托协议", "代理合同"],
    "担保合同": ["担保合同", "保证合同", "抵押合同"],
}

# 当事人模式
_PARTY_PATTERNS = [
    # 甲方：XXX公司 / 甲方：张三
    re.compile(r"(甲|乙|丙|丁|戊|己|庚|辛|壬|癸)方[：:]\s*(.{2,50}?)(?:\s|$|，|,|。)"),
    # 甲方（采购方）：XXX / 甲方（全称）：XXX
    re.compile(r"(甲|乙|丙|丁|戊|己|庚|辛|壬|癸)方[（(][^）)]*[）)][：:]\s*(.{2,50}?)(?:\s|$|，|,|。)"),
    # 出租方/承租方/买方/卖方
    re.compile(r"(出租方|承租方|买方|卖方|委托方|受托方|发包方|承包方|甲方|乙方)[：:]\s*(.{2,50}?)(?:\s|$|，|,|。)"),
]

# 法定代表人
_REP_PATTERN = re.compile(r"法定代表人[：:]\s*(.{2,20}?)(?:\s|$|，|,|。)")

# 地址
_ADDRESS_PATTERN = re.compile(r"(?:住所地|地址|住址)[：:]\s*(.{5,80}?)(?:\s*$|。)")

# 争议解决
_DISPUTE_PATTERNS = [
    re.compile(r"(?:提交|约定).{0,5}(?:仲裁|仲裁委员会)"),
    re.compile(r"(?:向|由).{0,20}(?:人民法院|法院)(?:起诉|提起诉讼|管辖)"),
    re.compile(r"争议解决[：:]?\s*(.{5,30}?(?:仲裁|诉讼|法院|管辖).{0,10})"),
]

# 适用法律
_GOVERNING_LAW_PATTERN = re.compile(r"(?:适用|依据|根据).{0,10}(中华人民共和国.{0,20}法)")


def extract_metadata(text: str) -> LegalMetadata:
    """
    从合同全文提取元数据

    Args:
        text: 合同全文

    Returns:
        LegalMetadata: 结构化元数据
    """
    if not text.strip():
        return LegalMetadata()

    meta = LegalMetadata()

    # 合同名称
    meta.contract_name = _extract_contract_name(text)

    # 合同类型
    meta.contract_type = _extract_contract_type(text)

    # 当事人
    meta.parties = _extract_parties(text)

    # 争议解决方式
    meta.dispute_resolution = _extract_dispute_resolution(text)

    # 适用法律
    meta.governing_law = _extract_governing_law(text)

    # 通知地址
    meta.notice_addresses = _extract_notice_addresses(text)

    return meta


def _extract_contract_name(text: str) -> str | None:
    """提取合同名称"""
    # 取前 500 字符（合同名称通常在开头）
    head = text[:500]
    for pattern in _CONTRACT_NAME_PATTERNS:
        m = pattern.search(head)
        if m:
            return m.group(1).strip() if m.lastindex else m.group(0).strip()
    return None


def _extract_contract_type(text: str) -> str | None:
    """识别合同类型"""
    head = text[:1000]  # 取前 1000 字符
    for contract_type, keywords in _CONTRACT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in head:
                return contract_type
    return None


def _extract_parties(text: str) -> list[ContractParty]:
    """提取合同当事人"""
    parties: list[ContractParty] = []
    seen_roles: set[str] = set()

    # 取前 2000 字符（当事人信息通常在开头）
    head = text[:2000]

    for pattern in _PARTY_PATTERNS:
        for m in pattern.finditer(head):
            role = m.group(1)
            name = m.group(2).strip()

            # 标准化角色名（"甲" → "甲方"）
            if len(role) == 1:
                role = role + "方"

            # 去重
            if role in seen_roles:
                continue
            seen_roles.add(role)

            # 清理名称（去掉后续的标点和多余内容）
            name = re.sub(r"[，,。；;].*$", "", name).strip()

            if len(name) < 2:
                continue

            # 尝试提取法定代表人
            representative = None
            rep_match = _REP_PATTERN.search(head[m.start():m.start() + 200])
            if rep_match:
                representative = rep_match.group(1).strip()

            parties.append(
                ContractParty(
                    role=role,
                    name=name,
                    representative=representative,
                )
            )

    return parties


def _extract_dispute_resolution(text: str) -> str | None:
    """提取争议解决方式"""
    for pattern in _DISPUTE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0).strip()
    return None


def _extract_governing_law(text: str) -> str | None:
    """提取适用法律"""
    m = _GOVERNING_LAW_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_notice_addresses(text: str) -> list[str]:
    """提取通知地址"""
    addresses: list[str] = []
    for m in _ADDRESS_PATTERN.finditer(text):
        addr = m.group(1).strip()
        if addr and len(addr) > 5:
            addresses.append(addr)
    return addresses[:5]  # 最多取 5 个
