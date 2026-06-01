"""
法务审查 Agent - 应用入口

职责：
1. 初始化日志和各业务模块（依赖注入）
2. 创建 Gradio 界面
3. 启动 Web 服务
"""

# 初始化日志（必须在其他模块导入之前）
from src.logger import logger_manager

logger_manager.initialize(log_dir="logs", enable_json_log=True)

import atexit
import os
import socket
import threading

from src.agent_loop import AgentLoop
from src.chat_memory import ChatMemory
from src.config import get_llm_config, get_paths_config, get_settings
from src.legal_matcher import LegalMatcher
from src.llm_client import LLMClient
from src.parser import DocumentParser
from src.playbook_manager import PlaybookManager
from src.redliner import Redliner
from src.report import ReportGenerator
from src.risk_engine import RiskEngine
from src.security import SecurityPreprocessor
from src.ui.layout import create_ui
from src.vector_store import VectorStore


def create_app():
    """
    工厂函数：初始化所有模块并返回 Gradio 应用

    将初始化逻辑封装为函数，便于测试和多入口复用。
    """
    # 初始化反馈存储目录
    try:
        from src.feedback_store import get_feedback_store

        get_feedback_store()
    except Exception as e:
        logger_manager.warning(f"反馈存储初始化失败: {e}")

    # ============================================
    # 配置
    # ============================================

    settings = get_settings()
    _ = get_llm_config()
    paths_config = get_paths_config()

    max_file_size_mb = settings.max_file_size_mb

    rules_path = str(paths_config["rules_path"])
    kb_path = str(paths_config["kb_path"])
    playbooks_dir = str(paths_config["playbooks_dir"])

    # ============================================
    # 模块初始化（依赖注入）
    # ============================================

    parser = DocumentParser()
    security = SecurityPreprocessor()
    vector_store = VectorStore()

    try:
        vector_store.initialize()
        print(f"✅ 向量库初始化完成，当前条目数: {vector_store.get_entry_count()}")
    except Exception as e:
        print(f"⚠️ 向量库初始化失败: {e}，将在首次检索时重试")

    risk_engine = RiskEngine(rules_path=rules_path, playbooks_dir=playbooks_dir, vector_store=vector_store)
    legal_matcher = LegalMatcher(kb_path=kb_path, vector_store=vector_store)
    report_gen = ReportGenerator()
    redliner = Redliner()
    playbook_manager = PlaybookManager(playbooks_dir)
    chat_memory = ChatMemory()

    # LLM 客户端单例（线程安全）
    _cached_llm_client = None
    _llm_lock = threading.Lock()

    def llm_client_factory():
        nonlocal _cached_llm_client
        if _cached_llm_client is None:
            with _llm_lock:
                if _cached_llm_client is None:
                    cfg = get_llm_config()
                    _cached_llm_client = LLMClient(api_key=cfg["api_key"], api_base=cfg["api_base"], model=cfg["model"])
        return _cached_llm_client

    def _cleanup_llm_client():
        if _cached_llm_client is not None:
            _cached_llm_client.close()

    atexit.register(_cleanup_llm_client)

    agent_loop = AgentLoop(
        chat_memory=chat_memory,
        parser=parser,
        security=security,
        risk_engine=risk_engine,
        legal_matcher=legal_matcher,
        report_gen=report_gen,
        redliner=redliner,
        llm_client_factory=llm_client_factory,
    )

    # ============================================
    # 创建界面
    # ============================================

    app = create_ui(
        agent_loop=agent_loop,
        playbook_manager=playbook_manager,
        legal_matcher=legal_matcher,
        llm_client_factory=llm_client_factory,
        max_file_size_mb=max_file_size_mb,
    )

    return app


if __name__ == "__main__":

    def _find_free_port(start: int, end: int) -> int:
        for port in range(start, end + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("", port))
                    return port
                except OSError:
                    continue
        raise RuntimeError(f"无法在 {start}-{end} 范围内找到可用端口")

    is_hf_space = os.environ.get("SPACE_ID") is not None
    server_name = "0.0.0.0" if is_hf_space else "127.0.0.1"
    port = 7860 if is_hf_space else _find_free_port(7860, 7865)
    print(f"[启动] 请访问: http://localhost:{port}")

    app = create_app()
    app.launch(server_name=server_name, server_port=port, share=False)
