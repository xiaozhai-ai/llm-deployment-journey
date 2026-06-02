"""
ChatMemory 单元测试

覆盖：
- 创建/获取/删除会话
- 消息添加
- 追问状态机
- 过期清理
- UUID 长度
- FollowUpType 拼写
"""

import time

import pytest

from src.infra.chat_memory import ChatMemory, DialogState, FollowUpQuestion, FollowUpType


@pytest.fixture
def memory():
    return ChatMemory(max_history=10, max_conversations=3)


class TestSessionLifecycle:
    def test_create_session(self, memory):
        session = memory.create_session("user1")
        assert session.user_id == "user1"
        assert session.state == DialogState.IDLE
        assert len(session.messages) == 1  # 系统欢迎消息
        assert session.messages[0].role == "system"

    def test_get_session(self, memory):
        session = memory.create_session()
        assert memory.get_session(session.session_id) is session

    def test_get_nonexistent_session(self, memory):
        assert memory.get_session("nonexistent") is None

    def test_delete_session(self, memory):
        session = memory.create_session()
        assert memory.delete_session(session.session_id) is True
        assert memory.get_session(session.session_id) is None

    def test_delete_nonexistent(self, memory):
        assert memory.delete_session("nonexistent") is False


class TestMessageHandling:
    def test_add_user_message(self, memory):
        session = memory.create_session()
        msg = memory.add_user_message(session.session_id, "你好")
        assert msg is not None
        assert msg.role == "user"
        assert msg.content == "你好"

    def test_add_assistant_message(self, memory):
        session = memory.create_session()
        msg = memory.add_assistant_message(session.session_id, "你好！", {"key": "val"})
        assert msg is not None
        assert msg.role == "assistant"
        assert msg.metadata == {"key": "val"}

    def test_message_to_nonexistent_session(self, memory):
        assert memory.add_user_message("nope", "hi") is None
        assert memory.add_assistant_message("nope", "hi") is None


class TestConversationHistory:
    def test_returns_llm_format(self, memory):
        session = memory.create_session()
        memory.add_user_message(session.session_id, "问题")
        memory.add_assistant_message(session.session_id, "回答")
        history = memory.get_conversation_history(session.session_id)
        assert all("role" in m and "content" in m for m in history)
        assert history[-1]["content"] == "回答"

    def test_limit(self, memory):
        session = memory.create_session()
        for i in range(20):
            memory.add_user_message(session.session_id, f"msg{i}")
        history = memory.get_conversation_history(session.session_id, limit=5)
        assert len(history) == 5


class TestFollowUpQuestions:
    def test_add_follow_up(self, memory):
        session = memory.create_session()
        q = FollowUpQuestion(
            id="q1",
            question="你是甲方还是乙方？",
            follow_up_type=FollowUpType.MISSING_PARTY_INFO,
            context="不同立场审查重点不同",
        )
        result = memory.add_follow_up_questions(session.session_id, [q])
        assert result is True
        assert session.state == DialogState.ASKING_CLARIFICATION
        assert len(session.pending_questions) == 1

    def test_answer_all_clears_pending(self, memory):
        session = memory.create_session()
        q = FollowUpQuestion(id="q1", question="问题？", follow_up_type=FollowUpType.OTHER, context="")
        memory.add_follow_up_questions(session.session_id, [q])
        memory.answer_follow_up(session.session_id, "q1", "回答")
        assert len(session.pending_questions) == 0
        assert session.state == DialogState.ANALYZING

    def test_partial_answer_keeps_asking(self, memory):
        session = memory.create_session()
        q1 = FollowUpQuestion(id="q1", question="A?", follow_up_type=FollowUpType.OTHER, context="")
        q2 = FollowUpQuestion(id="q2", question="B?", follow_up_type=FollowUpType.OTHER, context="")
        memory.add_follow_up_questions(session.session_id, [q1, q2])
        memory.answer_follow_up(session.session_id, "q1", "答A")
        assert len(session.pending_questions) == 2  # 未全部回答，不清空


class TestGenerateFollowUp:
    def test_party_question(self, memory):
        session = memory.create_session()
        questions = memory.generate_follow_up_questions(session.session_id, "contract", "甲方应向乙方支付货款")
        types = [q.follow_up_type for q in questions]
        assert FollowUpType.MISSING_PARTY_INFO in types

    def test_industry_detection(self, memory):
        session = memory.create_session()
        questions = memory.generate_follow_up_questions(session.session_id, "contract", "本技术开发合同由甲方委托乙方")
        types = [q.follow_up_type for q in questions]
        assert FollowUpType.MISSING_INDUSTRY_CONTEXT in types

    def test_unknown_file_type(self, memory):
        session = memory.create_session()
        questions = memory.generate_follow_up_questions(session.session_id, "unknown", "一些文本")
        types = [q.follow_up_type for q in questions]
        assert FollowUpType.MISSING_FILE_TYPE in types


class TestExpiredCleanup:
    def test_lazy_cleanup_on_create(self, memory):
        s1 = memory.create_session()
        # 模拟时间流逝
        s1.updated_at = time.time() - 7200
        memory._last_cleanup = 0
        memory.create_session()
        # s1 应被清理
        assert memory.get_session(s1.session_id) is None


class TestUUIDLength:
    def test_session_id_length(self, memory):
        session = memory.create_session()
        assert len(session.session_id) == 16

    def test_message_id_length(self, memory):
        session = memory.create_session()
        msg = memory.add_user_message(session.session_id, "test")
        assert len(msg.id) == 16


class TestFollowUpTypeTypo:
    def test_industry_spelling(self):
        """MISSING_INDUTRY_CONTEXT 已修正为 MISSING_INDUSTRY_CONTEXT"""
        assert hasattr(FollowUpType, "MISSING_INDUSTRY_CONTEXT")
        assert FollowUpType.MISSING_INDUSTRY_CONTEXT.value == "missing_industry_context"
