"""
日志系统模块
- 操作审计日志：记录用户操作、文件上传、审查结果摘要
- LLM 推理链路日志：记录 prompt、response、token 消耗
- 调试日志：开发调试信息
"""

import logging
import json
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional
from pathlib import Path


class LogFormatter(logging.Formatter):
    """自定义日志格式化器，支持彩色输出（仅控制台使用）"""

    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'

    def format(self, record):
        original = record.levelname
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        result = super().format(record)
        record.levelname = original
        return result


class JSONFormatter(logging.Formatter):
    """JSON 格式日志，便于后续分析"""

    def format(self, record):
        log_entry = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        if hasattr(record, 'extra_data'):
            log_entry['data'] = record.extra_data
        if record.exc_info and record.exc_info[0]:
            log_entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


class LoggerManager:
    """日志管理器"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.log_dir = None
        self._setup_loggers()

    def initialize(self, log_dir: str = "logs", enable_json_log: bool = True):
        """
        初始化日志系统

        Args:
            log_dir: 日志目录
            enable_json_log: 是否启用 JSON 格式日志文件
        """
        self.log_dir = Path(log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 文件日志（JSON 格式）
        if enable_json_log:
            self._add_file_handler(
                'audit',
                self.log_dir / 'audit.log',
                json_format=True
            )
            self._add_file_handler(
                'llm_trace',
                self.log_dir / 'llm_trace.log',
                json_format=True
            )

    def _setup_loggers(self):
        """设置各通道日志"""
        # 主日志（应用日志）
        self.app_logger = self._create_logger('app')

        # 审计日志
        self.audit_logger = self._create_logger('audit')

        # LLM 推理链路日志
        self.llm_logger = self._create_logger('llm')

        # 调试日志
        self.debug_logger = self._create_logger('debug')

    def _create_logger(self, name: str) -> logging.Logger:
        """创建日志器"""
        logger = logging.getLogger(f'legal_agent.{name}')
        logger.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = LogFormatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 防止重复添加
        logger.propagate = False
        return logger

    def _add_file_handler(self, name: str, filepath: Path, json_format: bool = False):
        """添加文件处理器（自动 rotation，单文件 10MB，保留 5 个）"""
        logger = logging.getLogger(f'legal_agent.{name}')
        handler = RotatingFileHandler(
            filepath, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
        )

        if json_format:
            handler.setFormatter(JSONFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    '%(asctime)s [%(levelname)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
            )

        handler.setLevel(logging.DEBUG)
        logger.addHandler(handler)

    # ===== 便捷方法 =====

    def info(self, msg: str, *args, **kwargs):
        """普通信息日志"""
        self.app_logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """警告日志"""
        self.app_logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, exc_info: bool = False, **kwargs):
        """错误日志"""
        self.app_logger.error(msg, *args, exc_info=exc_info, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        """调试日志"""
        self.debug_logger.debug(msg, *args, **kwargs)

    # ===== 审计日志 =====

    def audit_file_upload(
        self,
        filename: str,
        file_size: int,
        file_type: str,
        user_id: str = "anonymous"
    ):
        """记录文件上传审计"""
        self.audit_logger.info(
            f"文件上传: {filename} ({file_size} bytes, {file_type})",
            extra={
                'extra_data': {
                    'event': 'file_upload',
                    'filename': filename,
                    'file_size': file_size,
                    'file_type': file_type,
                    'user_id': user_id
                }
            }
        )

    def audit_review_start(
        self,
        filename: str,
        document_type: str,
        playbook: str,
        use_llm: bool
    ):
        """记录审查开始"""
        self.audit_logger.info(
            f"审查开始: {filename} [类型:{document_type}, 策略:{playbook}, LLM:{use_llm}]",
            extra={
                'extra_data': {
                    'event': 'review_start',
                    'filename': filename,
                    'document_type': document_type,
                    'playbook': playbook,
                    'use_llm': use_llm
                }
            }
        )

    def audit_review_complete(
        self,
        filename: str,
        risk_count: int,
        high_count: int,
        duration_seconds: float
    ):
        """记录审查完成"""
        self.audit_logger.info(
            f"审查完成: {filename} (风险:{risk_count}, 高:{high_count}, 耗时:{duration_seconds:.1f}s)",
            extra={
                'extra_data': {
                    'event': 'review_complete',
                    'filename': filename,
                    'risk_count': risk_count,
                    'high_count': high_count,
                    'duration_seconds': duration_seconds
                }
            }
        )

    # ===== LLM 推理链路日志 =====

    @staticmethod
    def _extra(event: str, **fields) -> dict:
        """构建 extra 字典，自动注入 process_id"""
        data = {'event': event, 'pid': os.getpid()}
        data.update(fields)
        return {'extra_data': data}

    def log_llm_request(
        self,
        model: str,
        prompt_length: int,
        temperature: float = 0.1,
        max_tokens: int = 4000,
        request_id: Optional[str] = None
    ):
        """记录 LLM 请求（不记录 prompt 内容，防止 PII 泄露）"""
        self.llm_logger.info(
            f"LLM 请求 [{model}]: len={prompt_length}, temp={temperature}",
            extra=self._extra(
                'llm_request',
                request_id=request_id,
                model=model,
                prompt_length=prompt_length,
                temperature=temperature,
                max_tokens=max_tokens
            )
        )

    def log_llm_response(
        self,
        model: str,
        response_length: int,
        duration_ms: float,
        request_id: Optional[str] = None,
        error: Optional[str] = None
    ):
        """记录 LLM 响应（不记录 response 内容，防止 PII 泄露）"""
        if error:
            self.llm_logger.error(
                f"LLM 响应失败 [{model}]: {error} ({duration_ms:.0f}ms)",
                extra=self._extra(
                    'llm_response_error',
                    request_id=request_id,
                    model=model,
                    duration_ms=duration_ms,
                    error=error
                )
            )
        else:
            self.llm_logger.info(
                f"LLM 响应 [{model}]: {duration_ms:.0f}ms, {response_length} chars",
                extra=self._extra(
                    'llm_response',
                    request_id=request_id,
                    model=model,
                    duration_ms=duration_ms,
                    response_length=response_length
                )
            )


# 全局单例
logger_manager = LoggerManager()


def get_logger(name: str = 'app') -> logging.Logger:
    """
    获取日志器

    Args:
        name: 日志器名称 (app/audit/llm/debug)

    Returns:
        logging.Logger 实例
    """
    return logging.getLogger(f'legal_agent.{name}')
