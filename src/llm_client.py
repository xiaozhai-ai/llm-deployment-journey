"""
LLM 客户端模块
封装对第三方 LLM API 的调用
支持工具调用（Function Calling / Tool Calling）
自动追踪 Token 消耗并上报 MetricsCollector
增强版：统一异常处理 + 自动重试机制
"""

import asyncio
import json
import random
import time

import requests

from src.config import get_llm_config
from src.exceptions import (
    LLMAPIKeyError,
    LLMError,
    LLMNetworkError,
    LLMRateLimitError,
    LLMResponseParseError,
    LLMTimeoutError,
)
from src.logger import logger_manager


class LLMClient:
    """LLM API 客户端（OpenAI 兼容格式）"""

    def __init__(self, api_key: str | None = None, api_base: str | None = None, model: str | None = None):
        # 从配置模块获取默认配置
        config = get_llm_config()

        # 允许传入参数覆盖配置
        self.api_key = api_key or config["api_key"]
        self.api_base = (api_base or config["api_base"]).rstrip("/")
        self.model = model or config["model"]

        if not self.api_key:
            raise ValueError("未设置 LLM_API_KEY 环境变量")
        if not self.api_base:
            self.api_base = "https://dashscope.aliyuncs.com/compatible-mode/v1"

        self.headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        # 复用 TCP 连接，减少高频调用时的连接建立开销
        self._session = requests.Session()
        self._session.headers.update(self.headers)

    def close(self):
        """释放 TCP 连接池资源"""
        self._session.close()

    def _report_metrics(self, response_data: dict, duration_ms: float, purpose: str = ""):
        """上报 Token 消耗到 MetricsCollector"""
        try:
            usage = response_data.get("usage", {})
            if usage:
                from src.metrics import get_current_collector

                collector = get_current_collector()
                if collector:
                    collector.record_llm_call(
                        model=self.model,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                        duration_ms=duration_ms,
                        purpose=purpose,
                    )
        except Exception as e:
            logger_manager.warning(f"Metrics 上报失败: {e}")  # 不影响主流程

    async def _async_post(self, url: str, headers: dict, json_data: dict, timeout: int) -> requests.Response:
        """在线程池中执行同步 POST 请求，避免阻塞事件循环"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._session.post(url, json=json_data, timeout=timeout))

    async def _retry_post(self, payload: dict, timeout: int = 60, retries: int = 2, purpose: str = "") -> dict:
        """
        带重试、随机抖动和总耗时上限的 POST 请求，返回解析后的 JSON 响应

        Args:
            payload: 请求体
            timeout: 超时秒数
            retries: 重试次数
            purpose: 用途标识（用于日志和 metrics）

        Returns:
            API 返回的 JSON dict
        """
        url = f"{self.api_base}/chat/completions"
        last_error = None
        total_budget = timeout * 2  # 总耗时上限
        start_time = time.monotonic()

        model = payload.get("model", "unknown")
        prompt_chars = sum(len(m.get("content", "")) for m in payload.get("messages", []) if isinstance(m, dict))
        logger_manager.log_llm_request(
            model=model,
            prompt_length=prompt_chars,
            temperature=payload.get("temperature", 0.1),
            max_tokens=payload.get("max_tokens", 0),
        )

        for attempt in range(retries + 1):
            if time.monotonic() - start_time > total_budget:
                raise LLMTimeoutError(f"总耗时超过 {total_budget}s 上限")

            try:
                req_start = time.time()
                response = await self._async_post(url, self.headers, payload, timeout=timeout)
                duration_ms = (time.time() - req_start) * 1000

                if response.status_code == 401:
                    raise LLMAPIKeyError("API 密钥无效或已过期")
                elif response.status_code == 404:
                    raise LLMNetworkError(f"API 端点不存在 (404)，请检查 LLM_API_BASE 配置是否正确: {url}")
                elif response.status_code == 429:
                    # Rate Limit 可重试，不直接 raise
                    raise LLMRateLimitError("API 调用频率超限，请稍后重试")
                elif response.status_code >= 500:
                    raise LLMNetworkError(f"服务器错误 ({response.status_code})")

                response.raise_for_status()
                result = response.json()
                self._report_metrics(result, duration_ms, purpose=purpose)

                # LLM 链路日志
                resp_text = ""
                if result.get("choices"):
                    resp_text = result["choices"][0].get("message", {}).get("content", "")
                logger_manager.log_llm_response(
                    model=model,
                    response_length=len(resp_text),
                    duration_ms=duration_ms,
                )
                return result

            except LLMAPIKeyError:
                raise
            except LLMRateLimitError as e:
                last_error = e
                logger_manager.warning(f"{purpose}频率超限 (尝试 {attempt + 1}/{retries + 1}): {e}")
            except LLMError as e:
                last_error = e
                logger_manager.warning(f"{purpose}失败 (尝试 {attempt + 1}/{retries + 1}): {e}")
            except requests.exceptions.Timeout as e:
                last_error = LLMTimeoutError(timeout_seconds=timeout)
                logger_manager.warning(f"{purpose}超时 (尝试 {attempt + 1}/{retries + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                last_error = LLMNetworkError()
                logger_manager.warning(f"{purpose}网络失败 (尝试 {attempt + 1}/{retries + 1}): {e}")
            except Exception as e:
                last_error = LLMError(f"{purpose}失败: {str(e)}", error_code="LLM_UNKNOWN")
                logger_manager.error(f"{purpose}未知错误 (尝试 {attempt + 1}/{retries + 1}): {e}")

            if attempt < retries:
                # Rate Limit 使用更长退避（至少 3 秒）+ 随机抖动防惊群
                delay = 2**attempt + random.uniform(0, 1)
                if isinstance(last_error, LLMRateLimitError):
                    delay = max(delay, 3) * (attempt + 1) + random.uniform(0, 1)
                await asyncio.sleep(delay)

        elapsed = (time.monotonic() - start_time) * 1000
        logger_manager.log_llm_response(
            model=model,
            response_length=0,
            duration_ms=elapsed,
            error=str(last_error) if last_error else "未知错误",
        )
        raise last_error or LLMError(f"{purpose}失败")

    async def chat_completion(
        self,
        prompt: str = "",
        system_prompt: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 3000,
        messages: list[dict] | None = None,
        retries: int = 2,
    ) -> str:
        """
        调用聊天模型（简单模式）

        Args:
            prompt: 用户提示（与 messages 二选一）
            system_prompt: 系统提示
            temperature: 温度参数
            max_tokens: 最大 token 数
            messages: 对话消息列表（OpenAI 格式，优先级高于 prompt）
            retries: 重试次数（默认 2 次）

        Returns:
            模型回复文本
        """
        # 如果提供了 messages，直接使用；否则从 prompt 构建
        if messages:
            final_messages = messages
        else:
            final_messages = []
            if system_prompt:
                final_messages.append({"role": "system", "content": system_prompt})
            final_messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": final_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        result = await self._retry_post(payload, timeout=60, retries=retries, purpose="通用对话")

        if not result.get("choices"):
            raise LLMResponseParseError("LLM 返回空响应", raw_response=str(result)[:200])

        content = result["choices"][0]["message"]["content"]
        if not content:
            raise LLMResponseParseError("LLM 返回空文本", raw_response=str(result)[:200])

        return content

    async def chat_completion_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 3000,
        retries: int = 2,
    ) -> dict:
        """
        调用聊天模型（支持工具调用）

        Args:
            messages: 对话消息列表（可包含 system/user/tool/assistant）
            tools: 工具定义列表（OpenAI 格式）
            temperature: 温度参数
            max_tokens: 最大 token 数
            retries: 重试次数

        Returns:
            {
                "content": "文本回复",
                "tool_calls": [
                    {
                        "id": "call_xxx",
                        "name": "tool_name",
                        "arguments": {"key": "value"}
                    }
                ]
            }
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        result = await self._retry_post(payload, timeout=90, retries=retries, purpose="工具调用")

        if not result.get("choices"):
            raise LLMResponseParseError("工具调用返回空响应", raw_response=str(result)[:200])

        message = result["choices"][0]["message"]

        parsed = {}

        if message.get("tool_calls"):
            tool_calls = []
            for tc in message["tool_calls"]:
                tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "name": tc["function"]["name"],
                        "arguments": self._parse_tool_arguments(tc["function"]["arguments"]),
                    }
                )
            parsed["tool_calls"] = tool_calls

        if message.get("content"):
            parsed["content"] = message["content"]

        return parsed

    def stream_chat_completion_sync(
        self, messages: list[dict], temperature: float = 0.7, max_tokens: int = 800, timeout: int = 30
    ):
        """
        同步流式聊天（SSE），直接 yield 每个 token。

        用于 Gradio 对话助手的流式输出，避免 asyncio + 线程池的开销。

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            timeout: 超时秒数

        Yields:
            每个 token 的文本片段
        """
        url = f"{self.api_base}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            with self._session.post(url, json=payload, timeout=timeout, stream=True) as response:
                if response.status_code == 401:
                    raise LLMAPIKeyError("API 密钥无效或已过期")
                elif response.status_code == 429:
                    raise LLMRateLimitError("API 调用频率超限")
                elif response.status_code >= 400:
                    raise LLMNetworkError(f"API 错误 ({response.status_code})")

                response.encoding = "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

        except (LLMAPIKeyError, LLMRateLimitError):
            raise
        except requests.exceptions.Timeout as e:
            raise LLMTimeoutError(timeout_seconds=timeout) from e
        except requests.exceptions.ConnectionError as e:
            raise LLMNetworkError() from e

    @staticmethod
    def _parse_tool_arguments(arguments_str: str) -> dict:
        """解析工具调用参数"""
        if isinstance(arguments_str, dict):
            return arguments_str
        try:
            return json.loads(arguments_str)
        except json.JSONDecodeError:
            return {"raw": arguments_str}
