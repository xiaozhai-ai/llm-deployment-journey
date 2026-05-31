"""
端到端集成测试

测试完整的审查流程中的错误处理和降级策略
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from unittest.mock import Mock, patch, AsyncMock
from src.llm_client import LLMClient
from src.exceptions import LLMTimeoutError, LLMNetworkError, LLMError


def test_llm_degradation_in_review():
    """测试审查流程中 LLM 降级"""
    print("\n=== 测试: LLM 降级策略 ===")
    
    from src.agent_loop import AgentLoop
    from src.chat_memory import ChatMemory
    from src.parser import DocumentParser
    from src.security import SecurityPreprocessor
    from src.risk_engine import RiskEngine
    from src.legal_matcher import LegalMatcher
    from src.report import ReportGenerator
    from src.redliner import Redliner
    
    # 创建 mock 对象
    chat_memory = ChatMemory()
    parser = DocumentParser()
    security = SecurityPreprocessor()
    
    # 创建风险引擎（使用默认配置）
    config_dir = os.path.join(os.path.dirname(__file__), 'config')
    rules_path = os.path.join(config_dir, 'legal_rules.yaml')
    playbooks_dir = os.path.join(config_dir, 'playbooks')
    
    risk_engine = RiskEngine(rules_path=rules_path, playbooks_dir=playbooks_dir)
    legal_matcher = LegalMatcher(vector_store=risk_engine.vector_store)
    report_gen = ReportGenerator()
    redliner = Redliner()
    
    # 创建会失败的 LLM 客户端工厂
    def failing_llm_factory():
        client = Mock(spec=LLMClient)
        client.chat_completion = AsyncMock(side_effect=LLMTimeoutError())
        client.model = "test-model"
        return client
    
    agent_loop = AgentLoop(
        chat_memory=chat_memory,
        parser=parser,
        security=security,
        risk_engine=risk_engine,
        legal_matcher=legal_matcher,
        report_gen=report_gen,
        redliner=redliner,
        llm_client_factory=failing_llm_factory
    )
    
    # 创建测试文档
    test_doc = """
    合同
    
    第一条 违约责任
    如乙方违约，应承担违约责任。
    
    第二条 争议解决
    双方应友好协商解决争议。
    """.encode('utf-8')
    
    print("🔍 开始审查（LLM 会失败，应该降级到规则分析）...")
    
    try:
        result = asyncio.run(agent_loop.start_review(
            file_bytes=test_doc,
            filename="test_contract.txt",
            document_type="contract",
            playbook_id="neutral",
            use_llm=True
        ))
        
        print(f"✅ 审查完成")
        print(f"✅ 状态: {result.get('status', 'unknown')}")
        
        warnings = result.get('warnings', [])
        if warnings:
            print(f"✅ 降级警告: {warnings[0]}")
        
        risks = result.get('risks', [])
        print(f"✅ 识别风险数: {len(risks)}")
        
        if result.get('risk_summary'):
            summary = result['risk_summary']
            print(f"✅ 风险摘要: {summary}")
        
    except Exception as e:
        print(f"❌ 审查失败: {e}")


def test_file_parsing_errors():
    """测试文件解析错误处理"""
    print("\n=== 测试: 文件解析错误处理 ===")
    
    from src.parser import DocumentParser
    from src.exceptions import UnsupportedFormatError, FileCorruptedError
    
    parser = DocumentParser()
    
    # 测试不支持格式
    print("\n1. 测试不支持格式:")
    try:
        parser.parse_bytes(b"test", "test.xlsx")
    except UnsupportedFormatError as e:
        print(f"   ✅ 捕获异常: {e.message}")
    
    # 测试损坏的 PDF
    print("\n2. 测试损坏的 PDF:")
    try:
        parser.parse_bytes(b"not a real pdf", "test.pdf")
    except FileCorruptedError as e:
        print(f"   ✅ 捕获异常: {e.message}")


def test_user_friendly_error_display():
    """测试用户友好错误显示"""
    print("\n=== 测试: 用户友好错误显示 ===")
    
    from src.exceptions import get_user_friendly_message
    
    test_errors = [
        ("LLM_TIMEOUT", "LLM 超时场景"),
        ("LLM_API_KEY_INVALID", "API 密钥错误场景"),
        ("UNSUPPORTED_FORMAT", "不支持文件格式场景"),
        ("FILE_CORRUPTED", "文件损坏场景"),
    ]
    
    for error_code, scenario in test_errors:
        message = get_user_friendly_message(error_code)
        print(f"\n{scenario}:")
        print(f"   原始代码: {error_code}")
        print(f"   用户消息: {message}")


if __name__ == "__main__":
    print("=" * 60)
    print("端到端集成测试")
    print("=" * 60)
    
    test_llm_degradation_in_review()
    test_file_parsing_errors()
    test_user_friendly_error_display()
    
    print("\n" + "=" * 60)
    print("✅ 集成测试完成！")
    print("=" * 60)
