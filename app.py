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
from src.config import get_settings, get_llm_config, get_paths_config
from src.parser import DocumentParser
from src.security import SecurityPreprocessor
from src.vector_store import VectorStore
from src.risk_engine import RiskEngine
from src.legal_matcher import LegalMatcher
from src.report import ReportGenerator
from src.redliner import Redliner
from src.llm_client import LLMClient
from src.playbook_manager import PlaybookManager
from src.chat_memory import ChatMemory
from src.agent_loop import AgentLoop
from src.task_runner import TaskRunner
from src.ui.layout import create_ui

# 初始化反馈存储目录
try:
    from src.feedback_store import get_feedback_store
    get_feedback_store()
except Exception as e:
    logger_manager.warning(f"反馈存储初始化失败: {e}")


# ============================================
# 配置
# ============================================

# 使用集中式配置管理
settings = get_settings()
llm_config = get_llm_config()
paths_config = get_paths_config()

LLM_API_KEY = llm_config["api_key"]
LLM_API_BASE = llm_config["api_base"]
LLM_MODEL = llm_config["model"]
MAX_FILE_SIZE_MB = settings.max_file_size_mb

# 转换为字符串路径（兼容现有模块）
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
task_runner = TaskRunner(timeout=300)


_cached_llm_client = None


def llm_client_factory():
    global _cached_llm_client
    if _cached_llm_client is None:
        _cached_llm_client = LLMClient(api_key=LLM_API_KEY, api_base=LLM_API_BASE, model=LLM_MODEL)
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
    llm_client_factory=llm_client_factory
)


# ============================================
# 创建界面 & 启动
# ============================================

app = create_ui(
    agent_loop=agent_loop,
    playbook_manager=playbook_manager,
    legal_matcher=legal_matcher,
    llm_client_factory=llm_client_factory,
    llm_api_key=LLM_API_KEY,
    max_file_size_mb=MAX_FILE_SIZE_MB,
)

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0", server_port=7860, share=False)
