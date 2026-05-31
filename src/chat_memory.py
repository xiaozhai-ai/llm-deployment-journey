"""
对话记忆管理模块 (Chat Memory)
- 多轮对话上下文存储
- 追问状态机：检测缺失信息 → 生成追问 → 接收补充 → 继续审查
- 用户偏好记忆
"""

import uuid
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class DialogState(Enum):
    """对话状态"""
    IDLE = "idle"  # 空闲
    WAITING_FOR_FILE = "waiting_for_file"  # 等待上传文件
    WAITING_FOR_CONTEXT = "waiting_for_context"  # 等待补充上下文
    ANALYZING = "analyzing"  # 分析中
    ASKING_CLARIFICATION = "asking_clarification"  # 追问中
    COMPLETE = "complete"  # 完成
    NEEDS_MANUAL_REVIEW = "needs_manual_review"  # 需要人工复核


class FollowUpType(Enum):
    """追问类型"""
    MISSING_FILE_TYPE = "missing_file_type"  # 文件类型不明确
    MISSING_PARTY_INFO = "missing_party_info"  # 缺少当事人信息
    MISSING_SPECIAL_FOCUS = "missing_special_focus"  # 缺少特殊关注点
    MISSING_INDUSTRY_CONTEXT = "missing_industry_context"  # 缺少行业背景
    AMBIGUOUS_CLAUSE = "ambiguous_clause"  # 条款含义模糊
    CONFIRM_RISK_LEVEL = "confirm_risk_level"  # 确认风险等级判断
    OTHER = "other"


@dataclass
class Message:
    """对话消息"""
    id: str
    role: str  # user / assistant / system
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


def _new_id(length: int = 16) -> str:
    return str(uuid.uuid4())[:length]


@dataclass
class FollowUpQuestion:
    """追问问题"""
    id: str
    question: str
    follow_up_type: FollowUpType
    context: str  # 为什么问这个问题
    options: List[str] = field(default_factory=list)  # 可选答案
    required: bool = True  # 是否必须回答


@dataclass
class ChatSession:
    """对话会话"""
    session_id: str
    user_id: str = "anonymous"
    state: DialogState = DialogState.IDLE
    messages: List[Message] = field(default_factory=list)
    pending_questions: List[FollowUpQuestion] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)  # 收集的上下文信息
    document_parsed: bool = False
    document_type: str = ""
    playbook_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def add_message(self, role: str, content: str, metadata: Dict = None) -> Message:
        """添加消息"""
        msg = Message(
            id=_new_id(),
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(msg)
        self.updated_at = time.time()
        return msg

    def get_context(self, key: str, default=None):
        """获取上下文信息"""
        return self.context.get(key, default)

    def set_context(self, key: str, value: Any):
        """设置上下文信息"""
        self.context[key] = value
        self.updated_at = time.time()


class ChatMemory:
    """对话记忆管理器（线程安全）"""

    def __init__(self, max_history: int = 50, max_conversations: int = 30):
        """
        初始化对话记忆

        Args:
            max_history: 每个会话最大保留消息数
            max_conversations: 最大并发会话数，超限时淘汰最旧会话
        """
        self.sessions: Dict[str, ChatSession] = {}
        self.max_history = max_history
        self._max_conversations = max_conversations
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def create_session(self, user_id: str = "anonymous") -> ChatSession:
        """
        创建新会话

        Args:
            user_id: 用户 ID

        Returns:
            ChatSession 对象
        """
        with self._lock:
            self._maybe_cleanup_expired()

            if len(self.sessions) >= self._max_conversations:
                oldest_id = min(self.sessions, key=lambda sid: self.sessions[sid].updated_at)
                del self.sessions[oldest_id]

            session_id = _new_id()
            session = ChatSession(
                session_id=session_id,
                user_id=user_id
            )
            self.sessions[session_id] = session

        # 添加系统欢迎消息（不持有锁，操作 session 内部状态）
        session.add_message(
            "system",
            "欢迎使用法务审查 Agent！请上传您需要审查的法律文件，"
            "我将为您进行自动化风险分析。"
        )

        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """获取会话"""
        with self._lock:
            return self.sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
                return True
            return False

    def add_user_message(self, session_id: str, content: str) -> Optional[Message]:
        """
        添加用户消息

        Args:
            session_id: 会话 ID
            content: 消息内容

        Returns:
            Message 对象或 None
        """
        session = self.get_session(session_id)
        if not session:
            return None
        return session.add_message("user", content)

    def add_assistant_message(self, session_id: str, content: str, metadata: Dict = None) -> Optional[Message]:
        """
        添加助手消息

        Args:
            session_id: 会话 ID
            content: 消息内容
            metadata: 附加元数据

        Returns:
            Message 对象或 None
        """
        session = self.get_session(session_id)
        if not session:
            return None
        return session.add_message("assistant", content, metadata)

    def add_follow_up_questions(
        self,
        session_id: str,
        questions: List[FollowUpQuestion]
    ) -> bool:
        """
        添加追问

        Args:
            session_id: 会话 ID
            questions: 追问列表

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if not session:
            return False

        session.pending_questions.extend(questions)
        session.state = DialogState.ASKING_CLARIFICATION

        # 生成追问消息
        question_texts = [f"{i+1}. {q.question}" for i, q in enumerate(questions)]
        session.add_message(
            "assistant",
            "为了更好地为您审查，我需要了解以下信息：\n\n" +
            "\n\n".join(question_texts)
        )

        return True

    def answer_follow_up(
        self,
        session_id: str,
        question_id: str,
        answer: str
    ) -> bool:
        """
        回答追问

        Args:
            session_id: 会话 ID
            question_id: 问题 ID
            answer: 用户回答

        Returns:
            是否成功
        """
        session = self.get_session(session_id)
        if not session:
            return False

        # 找到对应问题并记录回答
        for q in session.pending_questions:
            if q.id == question_id:
                session.set_context(f"follow_up_{question_id}", {
                    "question": q.question,
                    "answer": answer,
                    "type": q.follow_up_type.value
                })
                break

        # 检查是否所有追问都已回答
        unanswered = self._get_unanswered_questions(session)
        if not unanswered:
            session.pending_questions.clear()
            session.state = DialogState.ANALYZING

        return True

    def _get_unanswered_questions(self, session: ChatSession) -> List[FollowUpQuestion]:
        """获取未回答的追问"""
        answered_ids = {
            k.replace("follow_up_", "")
            for k in session.context.keys()
            if k.startswith("follow_up_")
        }
        return [q for q in session.pending_questions if q.id not in answered_ids]

    def generate_follow_up_questions(
        self,
        session_id: str,
        document_type: str,
        document_text: str,
        playbook_id: str = ""
    ) -> List[FollowUpQuestion]:
        """
        基于文档内容自动生成追问

        Args:
            session_id: 会话 ID
            document_type: 文档类型
            document_text: 文档文本
            playbook_id: 策略 ID

        Returns:
            追问列表
        """
        session = self.get_session(session_id)
        if not session:
            return []

        questions = []
        # 中文无需 lower()，直接使用原文匹配
        text = document_text

        # 检查是否缺少当事人信息
        if "甲方" in text or "乙方" in text:
            if not any(kw in session.context for kw in ["party_role", "user_role"]):
                questions.append(FollowUpQuestion(
                    id=_new_id(),
                    question="请问您在本合同中是甲方还是乙方？",
                    follow_up_type=FollowUpType.MISSING_PARTY_INFO,
                    context="不同立场的审查重点不同",
                    options=["甲方", "乙方", "其他/不确定"]
                ))

        # 检查是否缺少行业背景
        industry_keywords = [
            "技术开发", "软件开发", "技术服务",
            "买卖", "采购", "租赁",
            "劳动", "雇佣", "劳务",
            "投资", "融资", "股权"
        ]
        detected_industry = None
        for kw in industry_keywords:
            if kw in text:
                detected_industry = kw
                break

        if detected_industry and not session.get_context("industry"):
            questions.append(FollowUpQuestion(
                id=str(uuid.uuid4())[:16],
                question=f"检测到这可能是一份{detected_industry}相关文件，请问具体属于哪个行业领域？",
                follow_up_type=FollowUpType.MISSING_INDUSTRY_CONTEXT,
                context="不同行业的合规要求不同",
                options=["互联网/软件", "制造业", "金融", "其他"]
            ))

        # 检查文件类型是否明确
        if document_type == "unknown" or document_type == "auto_detect":
            questions.append(FollowUpQuestion(
                id=_new_id(),
                question="请问这份文件的具体类型是什么？",
                follow_up_type=FollowUpType.MISSING_FILE_TYPE,
                context="文件类型影响审查规则的选择",
                options=["合同", "协议", "隐私政策", "其他"]
            ))

        return questions

    def get_conversation_history(
        self,
        session_id: str,
        limit: int = 20
    ) -> List[Dict]:
        """
        获取对话历史（用于 LLM 上下文）

        Args:
            session_id: 会话 ID
            limit: 最大消息数

        Returns:
            消息列表，格式适合 LLM 输入
        """
        session = self.get_session(session_id)
        if not session:
            return []

        messages = session.messages[-limit:]
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    def get_context_summary(self, session_id: str) -> Dict:
        """
        获取会话上下文摘要

        Args:
            session_id: 会话 ID

        Returns:
            上下文摘要字典
        """
        session = self.get_session(session_id)
        if not session:
            return {}

        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "document_type": session.document_type,
            "playbook_id": session.playbook_id,
            "document_parsed": session.document_parsed,
            "context": session.context,
            "pending_questions": len(session.pending_questions),
            "message_count": len(session.messages)
        }

    def clear_expired_sessions(self, max_age_seconds: int = 3600):
        """清理过期会话（公开接口）"""
        with self._lock:
            self._do_cleanup(max_age_seconds)

    def _maybe_cleanup_expired(self, max_age_seconds: int = 3600):
        """惰性清理：每 60 秒最多执行一次（调用者须持有 self._lock）"""
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        self._do_cleanup(max_age_seconds)
        self._last_cleanup = now

    def _do_cleanup(self, max_age_seconds: int):
        """实际清理逻辑（调用者须持有 self._lock）"""
        now = time.time()
        expired = [
            sid for sid, session in self.sessions.items()
            if now - session.updated_at > max_age_seconds
        ]
        for sid in expired:
            del self.sessions[sid]
