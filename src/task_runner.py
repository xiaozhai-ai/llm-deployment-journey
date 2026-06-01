"""
异步任务执行器 (Task Runner)
- asyncio.Task 封装
- 6 阶段进度回调
- 超时控制、取消支持
- 无需 Redis，纯异步，兼容 HF Spaces
"""

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.logger import logger_manager


class TaskStatus(Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class TaskProgress:
    """任务进度"""

    stage: str
    stage_name: str
    percentage: float
    message: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class AsyncTask:
    """异步任务"""

    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: TaskProgress | None = None
    result: Any | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    _asyncio_task: asyncio.Task | None = None


class TaskRunner:
    """
    异步任务执行器

    管理异步审查任务的生命周期，支持进度回调、超时和取消。
    完全基于 asyncio，无需 Redis 或 Celery。
    """

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 300  # 5 分钟

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, max_tasks: int = 100):
        """
        初始化任务执行器

        Args:
            timeout: 默认超时时间（秒）
            max_tasks: 最大保留任务数，超限时清理已完成任务
        """
        self.tasks: dict[str, AsyncTask] = {}
        self.timeout = timeout
        self._max_tasks = max_tasks
        self.logger = logger_manager

    async def submit(
        self,
        coro_func: Callable,
        *args,
        progress_callback: Callable | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> str:
        """
        提交异步任务

        Args:
            coro_func: 异步函数（返回 coroutine 的函数）
            *args: 位置参数
            progress_callback: 进度回调函数
            timeout: 超时时间（秒），None 则使用默认值
            **kwargs: 关键字参数

        Returns:
            task_id: 任务 ID
        """
        task_id = str(uuid.uuid4())[:12]
        task = AsyncTask(task_id=task_id)

        # 超限时清理已完成任务
        if len(self.tasks) >= self._max_tasks:
            done_statuses = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMED_OUT}
            done_ids = [tid for tid, t in self.tasks.items() if t.status in done_statuses]
            done_ids.sort(key=lambda tid: self.tasks[tid].completed_at or 0)
            for tid in done_ids[: len(done_ids) // 2]:
                del self.tasks[tid]

        self.tasks[task_id] = task

        # 包装进度回调
        def wrapped_progress(progress: TaskProgress):
            task.progress = progress
            if progress_callback:
                if asyncio.iscoroutinefunction(progress_callback):
                    asyncio.create_task(progress_callback(progress))
                else:
                    progress_callback(progress)

        # 创建异步任务
        async def run_task():
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            try:
                # 创建进度感知的 coroutine
                coro = coro_func(*args, progress_callback=wrapped_progress, **kwargs)

                # 执行并应用超时
                effective_timeout = timeout or self.timeout
                result = await asyncio.wait_for(coro, timeout=effective_timeout)

                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = time.time()

                duration = task.completed_at - task.started_at
                self.logger.info(f"任务完成 [{task_id}]，耗时 {duration:.1f}s")

                return result

            except TimeoutError:
                task.status = TaskStatus.TIMED_OUT
                task.error = f"任务超时（{effective_timeout}s）"
                task.completed_at = time.time()
                self.logger.warning(f"任务超时 [{task_id}]")
                raise

            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.completed_at = time.time()
                self.logger.info(f"任务取消 [{task_id}]")
                raise

            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = time.time()
                self.logger.error(f"任务失败 [{task_id}]: {e}", exc_info=True)
                raise

        # 启动 asyncio.Task
        asyncio_task = asyncio.create_task(run_task())
        task._asyncio_task = asyncio_task

        return task_id

    async def submit_and_wait(
        self,
        coro_func: Callable,
        *args,
        progress_callback: Callable | None = None,
        timeout: int | None = None,
        **kwargs,
    ) -> Any:
        """
        提交任务并等待结果

        Args:
            coro_func: 异步函数
            *args: 位置参数
            progress_callback: 进度回调
            timeout: 超时时间
            **kwargs: 关键字参数

        Returns:
            任务结果
        """
        task_id = await self.submit(coro_func, *args, progress_callback=progress_callback, timeout=timeout, **kwargs)

        task = self.tasks.get(task_id)
        if not task or not task._asyncio_task:
            raise RuntimeError("任务创建失败")

        # 等待完成
        try:
            await task._asyncio_task
        except (TimeoutError, asyncio.CancelledError):
            pass  # 已在内部处理状态
        except Exception:
            self.logger.warning(f"任务 [{task_id}] 等待期间捕获异常: {task.error}")

        if task.status == TaskStatus.FAILED:
            raise RuntimeError(task.error or "任务执行失败")

        if task.status == TaskStatus.TIMED_OUT:
            raise TimeoutError(task.error or "任务超时")

        return task.result

    def get_task(self, task_id: str) -> AsyncTask | None:
        """获取任务状态"""
        return self.tasks.get(task_id)

    def get_task_status(self, task_id: str) -> dict:
        """获取任务状态摘要"""
        task = self.tasks.get(task_id)
        if not task:
            return {"error": "任务不存在"}

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "progress": {
                "stage": task.progress.stage if task.progress else None,
                "stage_name": task.progress.stage_name if task.progress else None,
                "percentage": task.progress.percentage if task.progress else 0,
                "message": task.progress.message if task.progress else "等待中",
            },
            "error": task.error,
            "created_at": task.created_at,
            "duration": (task.completed_at or time.time()) - task.started_at if task.started_at else 0,
        }

    async def cancel(self, task_id: str) -> bool:
        """
        取消任务

        Args:
            task_id: 任务 ID

        Returns:
            是否成功取消
        """
        task = self.tasks.get(task_id)
        if not task:
            return False

        if task.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
            return False

        if task._asyncio_task and not task._asyncio_task.done():
            task._asyncio_task.cancel()
            return True

        return False

    def list_tasks(self, limit: int = 20, status_filter: TaskStatus | None = None) -> list[dict]:
        """
        列出任务

        Args:
            limit: 最大数量
            status_filter: 状态过滤

        Returns:
            任务列表
        """
        tasks = list(self.tasks.values())

        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]

        # 按创建时间倒序
        tasks.sort(key=lambda t: t.created_at, reverse=True)

        return [
            {
                "task_id": t.task_id,
                "status": t.status.value,
                "progress": t.progress.percentage if t.progress else 0,
                "message": t.progress.message if t.progress else "",
                "created_at": t.created_at,
                "duration": (t.completed_at or time.time()) - (t.started_at or t.created_at),
            }
            for t in tasks[:limit]
        ]

    def cleanup(self, max_age_seconds: int = 3600):
        """清理过期任务"""
        now = time.time()
        expired = [
            tid for tid, task in self.tasks.items() if task.completed_at and (now - task.completed_at) > max_age_seconds
        ]
        for tid in expired:
            del self.tasks[tid]

        return len(expired)

    @property
    def active_count(self) -> int:
        """活跃任务数"""
        return sum(1 for t in self.tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING))
