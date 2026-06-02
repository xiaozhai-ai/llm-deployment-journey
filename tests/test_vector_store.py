"""
VectorStore / DashScope 嵌入函数单元测试

覆盖：
- DashScopeEmbeddingFunction 单批次调用
- 多批次分片（> MAX_BATCH）
- 429 重试机制
- API 错误处理
- close 资源释放
- VectorStore 降级到关键词模式
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.llm.vector_store import _DashScopeEmbeddingFunction


class TestDashScopeEmbeddingFunction:
    """_DashScopeEmbeddingFunction 单元测试"""

    def _make_fn(self):
        return _DashScopeEmbeddingFunction(
            api_key="test-key", api_base="https://dashscope.aliyuncs.com", model="text-embedding-v3"
        )

    def test_url_construction(self):
        fn = self._make_fn()
        assert fn._api_url == "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

    def test_url_trailing_slash(self):
        fn = _DashScopeEmbeddingFunction(
            api_key="k", api_base="https://dashscope.aliyuncs.com/", model="text-embedding-v3"
        )
        assert "aliyuncs.com/api" in fn._api_url
        assert fn._api_url.count("//") == 1  # no double slashes in path

    @patch("src.llm.vector_store._DashScopeEmbeddingFunction._call_api")
    def test_single_batch(self, mock_call):
        mock_call.return_value = [[0.1, 0.2], [0.3, 0.4]]
        fn = self._make_fn()
        result = fn(["text1", "text2"])
        assert len(result) == 2
        mock_call.assert_called_once_with(["text1", "text2"])

    @patch("src.llm.vector_store._DashScopeEmbeddingFunction._call_api")
    def test_multi_batch(self, mock_call):
        # 30 items > MAX_BATCH(25), should split into 2 batches
        texts = [f"text{i}" for i in range(30)]
        mock_call.side_effect = [[[0.1] * 3] * 25, [[0.2] * 3] * 5]
        fn = self._make_fn()
        result = fn(texts)
        assert len(result) == 30
        assert mock_call.call_count == 2
        mock_call.assert_any_call(texts[:25])
        mock_call.assert_any_call(texts[25:])

    def test_api_retry_on_429(self):
        fn = self._make_fn()
        mock_client = MagicMock()
        fn._client = mock_client

        # First call: 429, second call: success
        error_response = MagicMock()
        error_response.status_code = 429
        mock_resp_fail = MagicMock()
        mock_resp_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=error_response
        )
        mock_resp_ok = MagicMock()
        mock_resp_ok.raise_for_status.return_value = None
        mock_resp_ok.json.return_value = {"output": {"embeddings": [{"embedding": [0.1, 0.2]}]}}

        mock_client.post.side_effect = [mock_resp_fail, mock_resp_ok]

        with patch("src.llm.vector_store.time.sleep"):
            result = fn._call_api(["test"])

        assert result == [[0.1, 0.2]]
        assert mock_client.post.call_count == 2

    def test_api_error_no_retry(self):
        fn = self._make_fn()
        mock_client = MagicMock()
        fn._client = mock_client

        error_response = MagicMock()
        error_response.status_code = 500
        mock_client.post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=error_response
        )

        with patch("src.llm.vector_store.time.sleep"), pytest.raises(httpx.HTTPStatusError):
            fn._call_api(["test"])

    def test_close(self):
        fn = self._make_fn()
        mock_client = MagicMock()
        fn._client = mock_client
        fn.close()
        mock_client.close.assert_called_once()
        assert fn._client is None

    def test_close_no_client(self):
        fn = self._make_fn()
        fn.close()  # should not raise


class TestVectorStoreDegradation:
    """VectorStore 降级测试"""

    def test_init_without_chromadb(self):
        """ChromaDB 不可用时降级到关键词模式"""
        with patch("src.llm.vector_store.CHROMA_AVAILABLE", False):
            from src.llm.vector_store import VectorStore

            vs = VectorStore()
            vs.initialize()
            assert vs._initialized is True
            assert vs.collection is None

    def test_add_provision_keyword_only(self):
        """无向量库时法条仍存入关键词索引"""
        with patch("src.llm.vector_store.CHROMA_AVAILABLE", False):
            from src.llm.vector_store import VectorStore

            vs = VectorStore()
            vs.initialize()
            entry_id = vs.add_provision(
                law="民法典", article="第五百七十七条", title="违约责任", content="test content", keywords=["违约"]
            )
            assert entry_id in vs._keyword_index
            assert vs.get_entry_count() == 1
