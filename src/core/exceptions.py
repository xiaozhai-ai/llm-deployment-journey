"""
自定义异常类体系

定义项目专用的异常类型，便于精确错误处理和日志记录
"""


class LegalReviewError(Exception):
    """法律审查基础异常类"""

    def __init__(self, message: str, error_code: str = "UNKNOWN", context: dict = None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}


# ============================================
# LLM 相关异常
# ============================================


class LLMError(LegalReviewError):
    """LLM 调用失败异常"""

    pass


class LLMAPIKeyError(LLMError):
    """API 密钥无效"""

    def __init__(self, message: str = "LLM API 密钥无效或已过期"):
        super().__init__(message, error_code="LLM_API_KEY_INVALID")


class LLMTimeoutError(LLMError):
    """LLM 请求超时"""

    def __init__(self, message: str = "LLM 请求超时，请稍后重试", timeout_seconds: int = 60):
        super().__init__(message, error_code="LLM_TIMEOUT", context={"timeout": timeout_seconds})


class LLMRateLimitError(LLMError):
    """API 配额限制"""

    def __init__(self, message: str = "LLM API 调用频率超限，请稍后重试"):
        super().__init__(message, error_code="LLM_RATE_LIMIT")


class LLMNetworkError(LLMError):
    """网络连接错误"""

    def __init__(self, message: str = "网络连接失败，请检查网络或 API 地址"):
        super().__init__(message, error_code="LLM_NETWORK")


class LLMResponseParseError(LLMError):
    """LLM 响应解析失败"""

    def __init__(self, message: str = "LLM 返回格式异常，无法解析", raw_response: str = ""):
        super().__init__(message, error_code="LLM_PARSE_ERROR", context={"raw_response": raw_response[:200]})


# ============================================
# 文件解析异常
# ============================================


class ParsingError(LegalReviewError):
    """文件解析失败异常"""

    pass


class UnsupportedFormatError(ParsingError):
    """不支持的文件格式"""

    def __init__(self, extension: str, supported: list = None):
        supported = supported or [".pdf", ".docx", ".doc", ".txt"]
        message = f"不支持的文件格式: {extension}，支持的格式: {', '.join(supported)}"
        super().__init__(
            message, error_code="UNSUPPORTED_FORMAT", context={"extension": extension, "supported": supported}
        )


class FileCorruptedError(ParsingError):
    """文件已损坏"""

    def __init__(self, message: str = "文件已损坏或格式不正确"):
        super().__init__(message, error_code="FILE_CORRUPTED")


class FileTooLargeError(ParsingError):
    """文件过大"""

    def __init__(self, size_mb: float, limit_mb: float = 10):
        message = f"文件大小超过限制 ({size_mb:.1f}MB > {limit_mb}MB)"
        super().__init__(message, error_code="FILE_TOO_LARGE", context={"size_mb": size_mb, "limit_mb": limit_mb})


# ============================================
# 向量存储异常
# ============================================


class VectorStoreError(LegalReviewError):
    """向量数据库操作失败"""

    pass


class VectorStoreInitError(VectorStoreError):
    """向量库初始化失败"""

    def __init__(self, message: str = "向量库初始化失败，将使用关键词匹配模式"):
        super().__init__(message, error_code="VECTOR_STORE_INIT_ERROR")


class VectorSearchError(VectorStoreError):
    """向量检索失败"""

    def __init__(self, message: str = "向量检索失败，已回退到关键词匹配"):
        super().__init__(message, error_code="VECTOR_SEARCH_ERROR")


# ============================================
# 风险分析异常
# ============================================


class RiskAnalysisError(LegalReviewError):
    """风险分析失败"""

    pass


class PlaybookLoadError(RiskAnalysisError):
    """审查策略加载失败"""

    def __init__(self, playbook_id: str, message: str):
        super().__init__(message, error_code="PLAYBOOK_LOAD_ERROR", context={"playbook_id": playbook_id})


class RuleLoadError(RiskAnalysisError):
    """规则加载失败"""

    def __init__(self, rules_path: str, message: str):
        super().__init__(message, error_code="RULE_LOAD_ERROR", context={"rules_path": rules_path})


# ============================================
# 修订生成异常
# ============================================


class RevisionError(LegalReviewError):
    """修订生成失败"""

    pass


class DOCXGenerationError(RevisionError):
    """DOCX 生成失败"""

    def __init__(self, message: str = "DOCX 文件生成失败"):
        super().__init__(message, error_code="DOCX_GENERATION_ERROR")


# ============================================
# 工具调用异常
# ============================================


class ToolExecutionError(LegalReviewError):
    """工具执行失败"""

    def __init__(self, tool_name: str, message: str):
        super().__init__(message, error_code="TOOL_EXECUTION_ERROR", context={"tool_name": tool_name})


# ============================================
# 用户友好错误消息映射
# ============================================

USER_FRIENDLY_MESSAGES = {
    "LLM_API_KEY_INVALID": "🔑 API 密钥无效，请检查 LLM_API_KEY 配置",
    "LLM_TIMEOUT": "⏱️ AI 分析超时，已使用规则分析结果。可尝试减少文件大小或稍后重试",
    "LLM_RATE_LIMIT": "🚫 AI 服务调用频率超限，已使用规则分析结果",
    "LLM_NETWORK": "🌐 网络连接失败，无法访问 AI 服务。已使用规则分析结果",
    "LLM_PARSE_ERROR": "📝 AI 返回格式异常，已尝试重新解析",
    "UNSUPPORTED_FORMAT": "📄 不支持的文件格式，请上传 PDF/Word/TXT 文件",
    "FILE_CORRUPTED": "⚠️ 文件已损坏或无法读取，请重新上传",
    "FILE_TOO_LARGE": "📏 文件过大，请上传小于 10MB 的文件",
    "VECTOR_STORE_INIT_ERROR": "💾 向量库初始化失败，将使用关键词匹配模式",
    "VECTOR_SEARCH_ERROR": "🔍 向量检索失败，已回退到关键词匹配",
    "PLAYBOOK_LOAD_ERROR": "📋 审查策略加载失败，已使用默认策略",
    "RULE_LOAD_ERROR": "📜 规则文件加载失败，部分风险可能无法检测",
    "DOCX_GENERATION_ERROR": "📥 DOCX 修订文件生成失败，但 HTML 对比仍可用",
    "TOOL_EXECUTION_ERROR": "🔧 AI 工具调用失败，已跳过该步骤",
}


def get_user_friendly_message(error_code: str) -> str:
    """
    获取用户友好的错误消息

    Args:
        error_code: 错误代码

    Returns:
        用户友好的错误消息
    """
    return USER_FRIENDLY_MESSAGES.get(error_code, f"❌ 发生错误: {error_code}")


def classify_error(exception: Exception) -> str:
    """
    根据异常类型分类错误代码

    Args:
        exception: 异常对象

    Returns:
        错误代码
    """
    if isinstance(exception, LegalReviewError):
        return exception.error_code

    # 标准异常映射
    message = str(exception).lower()

    if "timeout" in message or "timed out" in message:
        return "LLM_TIMEOUT"
    if "api key" in message or "unauthorized" in message or "401" in message:
        return "LLM_API_KEY_INVALID"
    if "rate limit" in message or "429" in message:
        return "LLM_RATE_LIMIT"
    if "connection" in message or "network" in message:
        return "LLM_NETWORK"
    if "json" in message or "parse" in message:
        return "LLM_PARSE_ERROR"

    return "UNKNOWN"
