"""
Session 级别审查结果存储（线程安全）

每个会话使用独立的 session_id，避免并发请求互相覆盖。
支持 LRU 淘汰，防止长时间运行后内存无限增长。
"""

import threading
import time
import uuid


class ReviewResultStore:
    """
    线程安全的审查结果存储

    每个会话使用独立的 session_id，避免并发请求互相覆盖。
    超过 max_sessions 上限时自动淘汰最旧的会话。
    """

    def __init__(self, max_sessions: int = 50, max_age_seconds: int = 7200):
        self._store = {}
        self._timestamps = {}
        self._lock = threading.Lock()
        self._latest_session_id = None
        self._max_sessions = max_sessions
        self._max_age_seconds = max_age_seconds

    def create_session(self) -> str:
        """创建新会话并返回 session_id，超限时淘汰最旧会话"""
        session_id = str(uuid.uuid4())[:12]
        with self._lock:
            self._cleanup_expired_locked()
            if len(self._store) >= self._max_sessions:
                oldest_id = min(self._timestamps, key=self._timestamps.get)
                del self._store[oldest_id]
                del self._timestamps[oldest_id]
            self._store[session_id] = {
                "clauses": [],
                "risks": [],
                "document_type": "",
                "playbook_id": "",
                "filename": "",
                "original_text": "",
            }
            self._timestamps[session_id] = time.time()
            self._latest_session_id = session_id
        return session_id

    @property
    def latest_session_id(self) -> str:
        """获取最近的 session_id（用于单用户场景）"""
        with self._lock:
            return self._latest_session_id or ""

    def update(self, session_id: str, data: dict):
        """更新会话数据"""
        with self._lock:
            if session_id in self._store:
                self._store[session_id].update(data)
                self._timestamps[session_id] = time.time()
            else:
                self._store[session_id] = data
                self._timestamps[session_id] = time.time()

    def get(self, session_id: str) -> dict:
        """获取会话数据"""
        with self._lock:
            return self._store.get(session_id, {}).copy()

    def get_risks(self, session_id: str) -> list:
        """获取风险列表（返回副本，防止外部修改内部状态）"""
        with self._lock:
            risks = self._store.get(session_id, {}).get("risks", [])
            return list(risks)

    def get_clauses(self, session_id: str) -> list:
        """获取条款列表（返回副本，防止外部修改内部状态）"""
        with self._lock:
            clauses = self._store.get(session_id, {}).get("clauses", [])
            return list(clauses)

    def _cleanup_expired_locked(self):
        """清理过期会话（调用者须持有 self._lock）"""
        now = time.time()
        expired = [sid for sid, ts in self._timestamps.items() if now - ts > self._max_age_seconds]
        for sid in expired:
            del self._store[sid]
            del self._timestamps[sid]

    def cleanup_expired(self):
        """公开接口：清理过期会话"""
        with self._lock:
            self._cleanup_expired_locked()

    def session_count(self) -> int:
        """当前会话数"""
        with self._lock:
            return len(self._store)


# 全局单例
review_store = ReviewResultStore()
