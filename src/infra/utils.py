"""
通用工具函数
"""

import json
import math
import re
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


def extract_char_ngrams(text: str, n: int = 2) -> set[str]:
    """
    提取字符 n-gram 集合（用于中文模糊匹配）

    移除空格和标点后，按窗口大小 n 切分。

    Args:
        text: 输入文本
        n: n-gram 大小，默认 2（字符二元组）

    Returns:
        n-gram 集合
    """
    cleaned = "".join(c for c in text if c.isalnum())
    if len(cleaned) < n:
        return {cleaned} if cleaned else set()
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def bigram_jaccard(text1: str, text2: str) -> float:
    """
    计算两段文本的字符二元组 Jaccard 相似度

    适合中文短文本的模糊匹配场景。

    Args:
        text1: 文本 1
        text2: 文本 2

    Returns:
        0.0 ~ 1.0 的 Jaccard 相似度
    """
    bg1 = extract_char_ngrams(text1.lower(), 2)
    bg2 = extract_char_ngrams(text2.lower(), 2)
    if not bg1 or not bg2:
        return 0.0
    return len(bg1 & bg2) / len(bg1 | bg2)


def extract_json(text: str) -> str | None:
    """
    从 LLM 响应中提取第一个完整 JSON 值（对象或数组）

    策略：
    1. markdown 代码块（括号计数法，正确处理嵌套）
    2. 括号计数法（在纯文本中搜索，支持 {} 和 []）

    Args:
        text: LLM 响应文本

    Returns:
        JSON 字符串，或 None（未找到有效 JSON）
    """
    # 策略1：markdown 代码块
    fence_match = re.search(r"```(?:json)?\s*\n?", text, re.IGNORECASE)
    if fence_match:
        search_start = fence_match.end()
        closing = text.find("```", search_start)
        if closing != -1:
            inner = text[search_start:closing].strip()
            open_char = None
            for ch in inner:
                if ch in ("{", "["):
                    open_char = ch
                    break
            if open_char:
                close_char = "}" if open_char == "{" else "]"
                start = inner.find(open_char)
                depth = 0
                for i in range(start, len(inner)):
                    if inner[i] == open_char:
                        depth += 1
                    elif inner[i] == close_char:
                        depth -= 1
                    if depth == 0:
                        candidate = inner[start : i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except json.JSONDecodeError:
                            break

    # 策略2：括号计数法（在纯文本中搜索第一个 { 或 [）
    first_obj = text.find("{")
    first_arr = text.find("[")
    if first_obj == -1:
        start = first_arr
    elif first_arr == -1:
        start = first_obj
    else:
        start = min(first_obj, first_arr)

    if start != -1:
        open_char = text[start]
        close_char = "}" if open_char == "{" else "]"
        depth = 0
        for i in range(start, len(text)):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    break

    return None


def extract_json_object(text: str) -> str | None:
    """从 LLM 响应中提取第一个完整 JSON 对象（兼容旧接口）"""
    result = extract_json(text)
    if result is not None and result.startswith("{"):
        return result
    return None
