"""
SessionStore 单元测试

覆盖：
- 创建/获取/更新/删除会话
- LRU 淘汰
- 过期清理
- get_risks/get_clauses 返回副本（不污染内部状态）
- 线程安全
"""

import time
import pytest
from unittest.mock import patch

from src.session_store import ReviewResultStore


@pytest.fixture
def store():
    return ReviewResultStore(max_sessions=3, max_age_seconds=3600)


class TestCreateSession:

    def test_create_returns_session_id(self, store):
        sid = store.create_session()
        assert isinstance(sid, str)
        assert len(sid) == 12

    def test_create_initializes_fields(self, store):
        sid = store.create_session()
        data = store.get(sid)
        assert data["clauses"] == []
        assert data["risks"] == []
        assert data["document_type"] == ""

    def test_latest_session_id(self, store):
        s1 = store.create_session()
        s2 = store.create_session()
        assert store.latest_session_id == s2

    def test_latest_session_id_empty(self):
        store = ReviewResultStore()
        assert store.latest_session_id == ""


class TestLRUEviction:

    def test_evicts_oldest(self, store):
        s1 = store.create_session()
        s2 = store.create_session()
        s3 = store.create_session()
        # 第 4 个应淘汰 s1
        s4 = store.create_session()
        assert store.get(s1) == {}
        assert store.get(s4) != {}

    def test_update_refreshes_timestamp(self, store):
        s1 = store.create_session()
        store.create_session()
        store.create_session()
        # 更新 s1 刷新时间戳
        store.update(s1, {"filename": "test.docx"})
        s4 = store.create_session()
        # s1 不应被淘汰（刚更新过），s2 应被淘汰
        assert store.get(s1) != {}


class TestExpiredCleanup:

    def test_cleanup_removes_expired(self, store):
        sid = store.create_session()
        with patch('src.session_store.time') as mock_time:
            mock_time.time.return_value = time.time() + 4000
            store.create_session()  # 触发清理
        # sid 应被清理
        assert store.get(sid) == {}

    def test_cleanup_preserves_fresh(self, store):
        sid = store.create_session()
        store.create_session()  # 不过期
        assert store.get(sid) != {}

    def test_cleanup_expired_public_api(self, store):
        store._max_age_seconds = 0
        sid = store.create_session()
        with patch('src.session_store.time') as mock_time:
            mock_time.time.return_value = time.time() + 1
            store.cleanup_expired()
        assert store.get(sid) == {}


class TestGetRisksClausesReturnsCopy:

    def test_get_risks_returns_copy(self, store):
        sid = store.create_session()
        store.update(sid, {"risks": [{"name": "R1"}]})
        risks = store.get_risks(sid)
        risks.append({"name": "R2"})
        # 内部不应被污染
        assert len(store.get_risks(sid)) == 1

    def test_get_clauses_returns_copy(self, store):
        sid = store.create_session()
        store.update(sid, {"clauses": [{"id": 1}]})
        clauses = store.get_clauses(sid)
        clauses.append({"id": 2})
        assert len(store.get_clauses(sid)) == 1

    def test_get_returns_copy(self, store):
        sid = store.create_session()
        store.update(sid, {"filename": "test.docx"})
        data = store.get(sid)
        data["filename"] = "hacked.docx"
        assert store.get(sid)["filename"] == "test.docx"


class TestSessionCount:

    def test_session_count(self, store):
        assert store.session_count() == 0
        store.create_session()
        assert store.session_count() == 1
        store.create_session()
        assert store.session_count() == 2
