"""
通用工具函数
"""

import math
from collections import Counter


def text_similarity(text1: str, text2: str, max_chars: int = 500) -> float:
    """
    计算两段文本的相似度

    优先使用 Levenshtein（精确），fallback 到 TF-IDF 余弦相似度（语义），
    最终 fallback 到字符二元组 Jaccard。

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

    # 纯重复文本直接返回 1.0
    if t1 == t2:
        return 1.0

    try:
        import Levenshtein

        return Levenshtein.ratio(t1, t2)
    except ImportError:
        pass

    # TF-IDF 余弦相似度（字符级 unigram + bigram）
    def _char_ngrams(text: str) -> Counter:
        ngrams = Counter()
        for ch in text:
            ngrams[ch] += 1
        for i in range(len(text) - 1):
            ngrams[text[i : i + 2]] += 1
        return ngrams

    vec1 = _char_ngrams(t1)
    vec2 = _char_ngrams(t2)

    common_keys = set(vec1.keys()) & set(vec2.keys())
    if not common_keys:
        return 0.0

    dot_product = sum(vec1[k] * vec2[k] for k in common_keys)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)
