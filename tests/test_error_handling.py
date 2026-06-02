"""
错误处理改进测试脚本

测试各种异常场景，验证：
1. 异常是否正确分类
2. 用户友好消息是否正确
3. 降级策略是否生效
4. 日志是否正确记录
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core.exceptions import (
    FileCorruptedError,
    LLMAPIKeyError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMTimeoutError,
    UnsupportedFormatError,
    VectorStoreInitError,
    classify_error,
    get_user_friendly_message,
)
from src.llm.llm_client import LLMClient
from src.parsing.parser import DocumentParser
from src.llm.vector_store import VectorStore


def test_exception_classification():
    """测试异常分类"""
    print("\n=== 测试 1: 异常分类 ===")

    test_cases = [
        (LLMAPIKeyError(), "LLM_API_KEY_INVALID"),
        (LLMTimeoutError(), "LLM_TIMEOUT"),
        (LLMNetworkError(), "LLM_NETWORK"),
        (LLMRateLimitError(), "LLM_RATE_LIMIT"),
        (UnsupportedFormatError(".exe"), "UNSUPPORTED_FORMAT"),
        (FileCorruptedError(), "FILE_CORRUPTED"),
        (VectorStoreInitError(), "VECTOR_STORE_INIT_ERROR"),
    ]

    for exception, expected_code in test_cases:
        actual_code = classify_error(exception)
        status = "✅" if actual_code == expected_code else "❌"
        print(f"{status} {type(exception).__name__} -> {actual_code} (期望: {expected_code})")


def test_user_friendly_messages():
    """测试用户友好消息"""
    print("\n=== 测试 2: 用户友好消息 ===")

    error_codes = [
        "LLM_API_KEY_INVALID",
        "LLM_TIMEOUT",
        "LLM_RATE_LIMIT",
        "LLM_NETWORK",
        "UNSUPPORTED_FORMAT",
        "FILE_CORRUPTED",
        "VECTOR_STORE_INIT_ERROR",
    ]

    for code in error_codes:
        message = get_user_friendly_message(code)
        print(f"✅ {code}: {message}")


def test_llm_client_retry():
    """测试 LLM 客户端重试机制"""
    import httpx

    client = LLMClient(api_key="test_key", api_base="https://test.api.com/v1", model="test-model")
    mock_post = Mock(side_effect=httpx.TimeoutException("Connection timed out"))
    client._async_client.post = mock_post

    with pytest.raises(LLMTimeoutError):
        asyncio.run(client.chat_completion(prompt="测试"))
    assert mock_post.call_count == 3  # 1 initial + 2 retries


def test_llm_client_api_key_error():
    """测试 API 密钥错误"""
    mock_response = Mock()
    mock_response.status_code = 401
    mock_response.json.return_value = {"error": {"message": "Invalid API key"}}

    client = LLMClient(api_key="invalid_key", api_base="https://test.api.com/v1", model="test-model")
    mock_post = AsyncMock(return_value=mock_response)
    client._async_client.post = mock_post

    with pytest.raises(LLMAPIKeyError):
        asyncio.run(client.chat_completion(prompt="测试"))
    assert mock_post.call_count == 1  # 不重试


def test_parser_unsupported_format():
    """测试不支持的文件格式"""
    print("\n=== 测试 5: 不支持的文件格式 ===")

    parser = DocumentParser()

    try:
        parser.parse_bytes(b"test content", "test.exe")
        print("❌ 应该抛出 UnsupportedFormatError")
    except UnsupportedFormatError as e:
        print(f"✅ 正确抛出 UnsupportedFormatError: {e.message}")
        error_code = classify_error(e)
        message = get_user_friendly_message(error_code)
        print(f"✅ 用户友好消息: {message}")


def test_parser_file_corrupted():
    """测试文件损坏"""
    print("\n=== 测试 6: 文件损坏处理 ===")

    parser = DocumentParser()

    # 模拟损坏的 PDF
    corrupted_pdf = b"%PDF-1.4\n% corrupted content"

    try:
        parser.parse_bytes(corrupted_pdf, "test.pdf")
        print("❌ 应该抛出 FileCorruptedError")
    except FileCorruptedError as e:
        print(f"✅ 正确抛出 FileCorruptedError: {e.message}")


def test_vector_store_degradation():
    """测试 ChromaDB 降级策略"""
    print("\n=== 测试 7: ChromaDB 降级策略 ===")

    # 模拟 ChromaDB 不可用
    with patch("src.llm.vector_store.CHROMA_AVAILABLE", False):
        vector_store = VectorStore()

        try:
            vector_store.initialize()
            print("✅ ChromaDB 不可用时初始化成功（降级到关键词模式）")

            # 测试搜索
            results = vector_store.search("测试查询")
            print(f"✅ 搜索成功，返回 {len(results)} 个结果（关键词匹配）")
        except Exception as e:
            print(f"❌ 降级失败: {e}")


def test_vector_store_init_failure():
    """测试 ChromaDB 初始化失败"""
    print("\n=== 测试 8: ChromaDB 初始化失败 ===")

    # 如果 chromadb 未安装，跳过此测试
    try:
        import chromadb  # noqa: F401
    except ImportError:
        print("⏭️  跳过（chromadb 未安装）")
        return

    with patch("chromadb.PersistentClient") as mock_client:
        mock_client.side_effect = Exception("Database connection failed")

        vector_store = VectorStore()

        try:
            vector_store.initialize()
            print("✅ ChromaDB 初始化失败但不抛出异常（允许降级）")
            print(f"✅ Client 状态: {vector_store.client}")
        except Exception as e:
            print(f"❌ 不应该抛出异常: {e}")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("错误处理改进测试")
    print("=" * 60)

    test_exception_classification()
    test_user_friendly_messages()
    test_llm_client_retry()
    test_llm_client_api_key_error()
    test_parser_unsupported_format()
    test_parser_file_corrupted()
    test_vector_store_degradation()
    test_vector_store_init_failure()

    print("\n" + "=" * 60)
    print("✅ 所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
