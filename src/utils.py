"""
通用工具函数
"""


def text_similarity(text1: str, text2: str, max_chars: int = 500) -> float:
    """
    计算两段文本的相似度

    优先使用 Levenshtein（更准确），fallback 到字符二元组 Jaccard。

    Args:
        text1: 文本 1
        text2: 文本 2
        max_chars: 截断长度上限

    Returns:
        0.0 ~ 1.0 的相似度
    """
    if not text1 or not text2:
        return 0.0

    t1 = text1.lower()[:max_chars]
    t2 = text2.lower()[:max_chars]

    try:
        import Levenshtein

        return Levenshtein.ratio(t1, t2)
    except ImportError:
        pass

    def get_bigrams(text):
        return set(text[i : i + 2] for i in range(len(text) - 1))

    set1 = get_bigrams(t1)
    set2 = get_bigrams(t2)

    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0
