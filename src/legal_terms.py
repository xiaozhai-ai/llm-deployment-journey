"""
法律术语词典
- 法律术语精确匹配映射
- 同义词/近义词区分（如"定金"≠"订金"）
- 关键法律术语强制召回规则
"""


# ============================================
# 法律术语同义词/近义词词典
# ============================================
#
# 注意：法律术语的"近义词"不等于同义词。
# 例如"定金"和"订金"虽然读音相同，但法律含义完全不同。
# 此词典用于查询扩展，不混淆不同法律概念。

LEGAL_TERM_MAP: dict[str, dict] = {
    # ===== 合同法术语 =====
    "定金": {
        "exact": ["定金", "定金罚则", "定金合同"],
        "related": ["订金", "押金"],  # 法律上不同，但用户可能混淆
        "related_are_different": True,  # 标记：related 是不同法律概念
    },
    "订金": {"exact": ["订金", "预付款"], "related": ["定金"], "related_are_different": True},
    "违约金": {
        "exact": ["违约金", "违约赔偿金"],
        "related": ["赔偿金", "损害赔偿", "损失赔偿"],
        "related_are_different": False,  # 这些可以一起检索
    },
    "格式条款": {
        "exact": ["格式条款", "标准条款", "定型化条款"],
        "related": ["霸王条款"],
        "related_are_different": False,
    },
    "解除合同": {
        "exact": ["解除合同", "合同解除", "解除权"],
        "related": ["终止合同", "合同终止"],
        "related_are_different": False,
    },
    "不可抗力": {"exact": ["不可抗力", "force majeure"], "related": [], "related_are_different": False},
    "管辖": {
        "exact": ["管辖", "管辖权", "管辖法院", "管辖约定"],
        "related": ["仲裁", "诉讼"],
        "related_are_different": False,
    },
    "保密": {
        "exact": ["保密", "保密义务", "保密条款", "商业秘密"],
        "related": ["机密", "confidential"],
        "related_are_different": False,
    },
    "知识产权": {
        "exact": ["知识产权", "著作权", "版权", "专利权", "商标权"],
        "related": ["intellectual property"],
        "related_are_different": False,
    },
    "竞业限制": {
        "exact": ["竞业限制", "竞业禁止", "同业竞争"],
        "related": ["竞业补偿"],
        "related_are_different": False,
    },
    "劳动报酬": {
        "exact": ["劳动报酬", "工资", "薪酬", "薪资"],
        "related": ["福利", "奖金"],
        "related_are_different": False,
    },
    "加班": {
        "exact": ["加班", "加班费", "延长工作时间"],
        "related": ["996", "工作时间"],
        "related_are_different": False,
    },
    # ===== 个人信息保护 =====
    "个人信息": {
        "exact": ["个人信息", "个人数据", "隐私信息", "PII"],
        "related": ["数据", "隐私"],
        "related_are_different": False,
    },
    "数据出境": {
        "exact": ["数据出境", "跨境传输", "向境外提供个人信息"],
        "related": ["数据转移"],
        "related_are_different": False,
    },
    "同意": {"exact": ["同意", "用户同意", "明示同意"], "related": ["授权", "许可"], "related_are_different": False},
    # ===== 公司法 =====
    "对赌协议": {
        "exact": ["对赌协议", "估值调整机制", "VAM", "业绩补偿"],
        "related": ["股权投资", "回购"],
        "related_are_different": False,
    },
    "股权回购": {
        "exact": ["股权回购", "回购条款", "回购权"],
        "related": ["抽逃出资", "减资"],
        "related_are_different": False,
    },
    "股东": {"exact": ["股东", "出资人", "投资人"], "related": ["合伙人"], "related_are_different": True},
}


# ============================================
# 强制召回关键词
# ============================================
# 当文档中出现这些术语时，强制召回包含该术语的所有法条，
# 不管向量检索结果如何。

FORCE_RECALL_TERMS: dict[str, list[str]] = {
    "定金": ["定金", "定金罚则"],
    "违约金": ["违约金"],
    "格式条款": ["格式条款", "霸王条款"],
    "不可抗力": ["不可抗力"],
    "管辖": ["管辖", "管辖法院"],
    "竞业限制": ["竞业限制", "竞业禁止"],
    "加班": ["加班", "加班费"],
    "个人信息": ["个人信息", "个人数据"],
    "数据出境": ["数据出境", "跨境传输"],
    "对赌协议": ["对赌协议", "业绩补偿"],
    "股权回购": ["股权回购", "回购条款"],
    "劳动合同": ["劳动合同", "雇佣合同"],
    "免责条款": ["免责", "免除责任"],
    "解除": ["解除", "终止"],
    "仲裁": ["仲裁"],
    "知识产权": ["知识产权", "著作权", "专利", "商标"],
    "保密": ["保密", "商业秘密"],
}


def get_legal_terms(text: str) -> list[str]:
    """
    从文本中提取已知的法律术语

    Args:
        text: 待分析文本

    Returns:
        检测到的法律术语列表
    """
    text_lower = text.lower()
    detected = []

    for term in FORCE_RECALL_TERMS:
        for variant in FORCE_RECALL_TERMS[term]:
            if variant.lower() in text_lower:
                if term not in detected:
                    detected.append(term)
                break

    return detected


def expand_query(query: str) -> list[str]:
    """
    扩展法律术语查询

    Args:
        query: 原始查询

    Returns:
        扩展后的查询列表
    """
    expanded = [query]

    for term, info in LEGAL_TERM_MAP.items():
        if term in query or any(syn in query for syn in info["exact"]):
            # 添加精确同义词
            expanded.extend(info["exact"])
            # 添加相关词（如果法律上可一起检索）
            if not info.get("related_are_different", False):
                expanded.extend(info.get("related", []))

    return list(set(expanded))
