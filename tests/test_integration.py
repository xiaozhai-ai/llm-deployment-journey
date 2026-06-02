"""
端到端集成测试

覆盖：
- LLM 降级策略
- 文件解析错误处理
- 用户友好错误消息
"""

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.core.exceptions import FileCorruptedError, LLMTimeoutError, UnsupportedFormatError, get_user_friendly_message
from src.llm.llm_client import LLMClient
from src.parsing.parser import DocumentParser


# ============================================
# Fixtures
# ============================================


@pytest.fixture
def test_contract_bytes():
    return """
    合同

    第一条 违约责任
    如乙方违约，应承担违约责任。

    第二条 争议解决
    双方应友好协商解决争议。
    """.encode()


@pytest.fixture
def agent_loop():
    """创建 AgentLoop，需要 mock Settings 因为缺少 env 变量"""
    from src.agent_loop import AgentLoop
    from src.infra.chat_memory import ChatMemory
    from src.analysis.legal_matcher import LegalMatcher
    from src.parsing.parser import DocumentParser
    from src.output.redliner import Redliner
    from src.output.report import ReportGenerator
    from src.analysis.risk_engine import RiskEngine
    from src.output.security import SecurityPreprocessor

    # Mock Settings 以避免 pydantic 验证错误
    with patch.dict(os.environ, {"LLM_API_KEY": "test-key"}):
        chat_memory = ChatMemory()
        parser = DocumentParser()
        security = SecurityPreprocessor()

        config_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
        rules_path = os.path.join(config_dir, "legal_rules.yaml")
        playbooks_dir = os.path.join(config_dir, "playbooks")

        risk_engine = RiskEngine(rules_path=rules_path, playbooks_dir=playbooks_dir)
        legal_matcher = LegalMatcher(vector_store=risk_engine.vector_store)
        report_gen = ReportGenerator()
        redliner = Redliner()

    def failing_llm_factory():
        client = Mock(spec=LLMClient)
        client.chat_completion = AsyncMock(side_effect=LLMTimeoutError())
        client.model = "test-model"
        return client

    return AgentLoop(
        chat_memory=chat_memory,
        parser=parser,
        security=security,
        risk_engine=risk_engine,
        legal_matcher=legal_matcher,
        report_gen=report_gen,
        redliner=redliner,
        llm_client_factory=failing_llm_factory,
    )


# ============================================
# LLM 降级测试
# ============================================


class TestLLMDegradation:
    @pytest.mark.asyncio
    async def test_review_completes_with_failing_llm(self, agent_loop, test_contract_bytes):
        """LLM 失败时应降级到规则分析并完成审查"""
        result = await agent_loop.start_review(
            file_bytes=test_contract_bytes,
            filename="test_contract.txt",
            document_type="contract",
            playbook_id="neutral",
            use_llm=True,
        )

        assert isinstance(result, dict)
        assert isinstance(result.get("risks", []), list)
        assert "risk_summary" in result

    @pytest.mark.asyncio
    async def test_degradation_warning_present(self, agent_loop, test_contract_bytes):
        """LLM 降级时应包含警告信息"""
        result = await agent_loop.start_review(
            file_bytes=test_contract_bytes,
            filename="test_contract.txt",
            document_type="contract",
            playbook_id="neutral",
            use_llm=True,
        )

        warnings = result.get("warnings", [])
        assert any("降级" in w or "LLM" in w or "超时" in w for w in warnings)


# ============================================
# 文件解析错误处理
# ============================================


class TestFileParsingErrors:
    def test_unsupported_format_raises_error(self):
        """不支持的文件格式应抛出 UnsupportedFormatError"""
        parser = DocumentParser()
        with pytest.raises(UnsupportedFormatError):
            parser.parse_bytes(b"test", "test.xlsx")

    def test_corrupted_pdf_raises_error(self):
        """损坏的 PDF 应抛出 FileCorruptedError"""
        parser = DocumentParser()
        with pytest.raises(FileCorruptedError):
            parser.parse_bytes(b"not a real pdf", "test.pdf")

    def test_empty_file_returns_empty_content(self):
        """空文件应返回空内容（txt 格式允许空内容）"""
        parser = DocumentParser()
        result = parser.parse_bytes(b"", "test.txt")
        assert result is not None


# ============================================
# 用户友好错误消息
# ============================================


class TestUserFriendlyErrors:
    def test_llm_timeout_message(self):
        message = get_user_friendly_message("LLM_TIMEOUT")
        assert "超时" in message or "timeout" in message.lower()

    def test_api_key_invalid_message(self):
        message = get_user_friendly_message("LLM_API_KEY_INVALID")
        assert "密钥" in message or "API" in message

    def test_unsupported_format_message(self):
        message = get_user_friendly_message("UNSUPPORTED_FORMAT")
        assert "格式" in message

    def test_file_corrupted_message(self):
        message = get_user_friendly_message("FILE_CORRUPTED")
        assert "损坏" in message or "文件" in message

    def test_unknown_error_returns_generic_message(self):
        message = get_user_friendly_message("UNKNOWN_ERROR_CODE")
        assert isinstance(message, str)
        assert len(message) > 0
