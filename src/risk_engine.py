"""
风险识别引擎（增强版 v2.2）
- 接入 Playbook 策略，根据甲方/乙方调整风险权重
- 接入 ChromaDB 向量库进行法条检索
- 集成 Tool-Calling Agent 进行条款级深度审查（流式）
- 自我反思：结论输出前验证法条/判例引用准确性
- 支持策略权重调整
- 增强版：统一异常处理 + 日志记录
"""

import os
import re
import json
import yaml
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

from src.playbook_manager import PlaybookManager, Playbook
from src.vector_store import VectorStore
from src.tools.base import ToolRegistry
from src.tools.legal_search import LegalSearchTool
from src.tools.case_search import CaseSearchTool
from src.tools.ambiguity_check import AmbiguityCheckTool
from src.tool_agent import ToolCallingAgent, AgentOutput
from src.exceptions import (
    LLMError, LLMTimeoutError, LLMNetworkError,
    RiskAnalysisError, RuleLoadError
)
from src.logger import logger_manager
from src.config import get_paths_config


@dataclass
class RiskItem:
    """风险项"""
    id: str
    rule_id: str
    name: str
    category: str
    risk_level: str
    description: str
    clause_position: Optional[str] = None  # 条款标题（兼容旧版）
    clause_content_preview: Optional[str] = None
    legal_basis: Optional[str] = None
    suggestion: Optional[str] = None
    confidence: float = 0.0
    playbook_adjusted: bool = False
    tool_agent_output: Optional[AgentOutput] = None
    tool_agent_conclusion: Optional[str] = None

    # ===== 溯源字段（v2.5 新增） =====
    clause_id: int = 0  # 对应 Clause.id，用于溯源定位
    clause_title: str = ""  # 条款标题
    clause_line_range: str = ""  # 行号范围 "第3-5行"
    cited_provisions: List[str] = field(default_factory=list)  # 引用的法条列表
    user_feedback: Optional[str] = None  # 用户反馈（误报/同意等）


@dataclass
class RiskAnalysisResult:
    """风险分析结果"""
    risks: List[RiskItem] = field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    summary: Optional[str] = None


class RiskEngine:
    """风险识别引擎（增强版 v2.2）"""

    RISK_LEVEL_MAP = {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1
    }

    RISK_LEVEL_CN = {
        "critical": "严重",
        "high": "高",
        "medium": "中",
        "low": "低"
    }

    def __init__(
        self,
        rules_path: Optional[str] = None,
        playbooks_dir: Optional[str] = None,
        vector_store: Optional[VectorStore] = None
    ):
        self.rules = []
        self.document_types = {}
        self.playbook_manager = PlaybookManager(playbooks_dir)
        self.vector_store = vector_store or VectorStore()
        self.tool_registry = ToolRegistry()

        self._register_tools()

        if rules_path:
            self._load_rules(rules_path)
        else:
            # 从配置模块获取路径
            paths_config = get_paths_config()
            default_path = paths_config["rules_path"]
            if default_path.exists():
                self._load_rules(str(default_path))

    def _register_tools(self):
        """注册所有可用工具"""
        legal_search = LegalSearchTool()
        legal_search.set_vector_store(self.vector_store)
        self.tool_registry.register(legal_search)

        case_search = CaseSearchTool()
        case_search.set_vector_store(self.vector_store)
        self.tool_registry.register(case_search)

        ambiguity_check = AmbiguityCheckTool()
        self.tool_registry.register(ambiguity_check)

    def _load_rules(self, path: str):
        """加载风险规则"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            self.rules = config.get('risk_rules', [])
            self.document_types = config.get('document_types', {})
            logger_manager.info(f"成功加载 {len(self.rules)} 条风险规则")
        except FileNotFoundError:
            logger_manager.error(f"规则文件不存在: {path}")
            raise RuleLoadError(path, f"规则文件不存在: {path}")
        except yaml.YAMLError as e:
            logger_manager.error(f"规则文件 YAML 解析失败: {path}: {e}")
            raise RuleLoadError(path, f"规则文件格式错误: {e}")
        except Exception as e:
            logger_manager.error(f"加载规则失败: {path}: {e}")
            raise RuleLoadError(path, f"加载规则失败: {e}")

    def analyze_by_rules(
        self,
        text: str,
        document_type: str = "contract",
        playbook: Optional[Playbook] = None
    ) -> RiskAnalysisResult:
        """基于规则引擎进行风险分析"""
        risks = []

        applicable_rules = [
            rule for rule in self.rules
            if document_type in rule.get('applicable_types', [])
        ]

        for rule in applicable_rules:
            if playbook and not playbook.should_check_rule(rule['id']):
                continue

            detection_type = rule.get('detection', {}).get('type', '')

            if detection_type == 'missing_clause' or rule['id'].startswith('MISSING_'):
                is_missing, confidence = self._check_missing_clause(text, rule)
                if is_missing:
                    risk = self._create_risk_from_rule(rule, confidence)
                    if playbook:
                        adjusted_level = playbook.adjust_risk_level(rule['id'], risk.risk_level)
                        if adjusted_level != risk.risk_level:
                            risk.risk_level = adjusted_level
                            risk.playbook_adjusted = True
                    risks.append(risk)
            else:
                matched, confidence = self._check_rule_match(text, rule)
                if matched:
                    risk = self._create_risk_from_rule(rule, confidence)
                    if playbook and playbook.is_focus_area(risk.category):
                        current_level = self.RISK_LEVEL_MAP.get(risk.risk_level, 2)
                        if current_level < 3:
                            risk.risk_level = "high"
                            risk.playbook_adjusted = True
                    risks.append(risk)

        return self._count_risks(risks)

    def _check_rule_match(self, text: str, rule: Dict) -> tuple:
        """检测非缺失类风险，返回 (matched: bool, confidence: float)"""
        detection = rule.get('detection', {})
        risk_keywords = detection.get('risk_keywords', [])
        safe_keywords = detection.get('safe_keywords', [])
        require_safe_absence = detection.get('require_safe_absence', False)

        # 兜底：无 detection 配置时从规则名称提取关键词
        if not risk_keywords:
            risk_keywords = self._fallback_keywords(rule)

        text_lower = text.lower()

        # 计算 risk 关键词命中数
        risk_hits = sum(1 for kw in risk_keywords if kw in text_lower)
        if risk_hits == 0:
            return False, 0.0

        # 计算 safe 关键词命中数
        safe_hits = sum(1 for kw in safe_keywords if kw in text_lower)

        # safe 命中且有 require_safe_absence 标记 → 不触发
        if require_safe_absence and safe_hits > 0:
            return False, 0.0

        # safe 命中数 >= risk 命中数 → 大概率是平衡的，降低置信度
        if safe_hits >= risk_hits and safe_hits > 0:
            return False, 0.0

        # 计算置信度
        risk_ratio = risk_hits / len(risk_keywords) if risk_keywords else 0
        safe_penalty = (safe_hits / len(safe_keywords) * 0.4) if safe_keywords else 0
        confidence = max(0.3, min(0.95, 0.5 + risk_ratio * 0.4 - safe_penalty))

        return True, confidence

    def _check_missing_clause(self, text: str, rule: Dict) -> tuple:
        """检测条款缺失，返回 (is_missing: bool, confidence: float)"""
        detection = rule.get('detection', {})
        presence_keywords = detection.get('presence_keywords', [])
        substance_patterns = detection.get('substance_patterns', [])

        if not presence_keywords:
            presence_keywords = self._fallback_keywords(rule)

        text_lower = text.lower()

        # 第一步：检查条款是否存在（关键词）
        presence_hits = sum(1 for kw in presence_keywords if kw in text_lower)

        if presence_hits == 0:
            # 完全没有相关关键词 → 条款缺失，高置信度
            return True, 0.9

        # 第二步：检查条款是否有实质内容（正则匹配）
        substance_hits = 0
        if substance_patterns:
            for pattern in substance_patterns:
                try:
                    if re.search(pattern, text_lower):
                        substance_hits += 1
                except re.error:
                    continue

            if substance_hits > 0:
                # 有实质内容 → 不缺失
                substance_ratio = substance_hits / len(substance_patterns)
                confidence = max(0.3, 0.5 + substance_ratio * 0.4)
                return False, confidence

        # 有关键词但无实质内容 → 可能只是提及而非真正约定
        # 降低缺失置信度（因为确实提到了相关概念）
        presence_ratio = presence_hits / len(presence_keywords)
        confidence = max(0.3, 0.7 - presence_ratio * 0.3)
        return True, confidence

    def _extract_keywords_from_rule(self, rule: Dict) -> List[str]:
        """从规则中提取关键词（用于法条匹配等场景）"""
        detection = rule.get('detection', {})

        # 优先从 detection 配置中提取
        if detection:
            keywords = []
            keywords.extend(detection.get('presence_keywords', []))
            keywords.extend(detection.get('risk_keywords', []))
            keywords.extend(detection.get('safe_keywords', []))
            if keywords:
                return keywords

        return self._fallback_keywords(rule)

    def _fallback_keywords(self, rule: Dict) -> List[str]:
        """从规则名称中提取关键词作为兜底"""
        name = rule.get('name', '')
        fallback = [w for w in re.split(r'[，、/\s]+', name) if len(w) >= 2]
        return fallback or ([name] if name else [])

    def _create_risk_from_rule(self, rule: Dict, confidence: float = 0.5) -> RiskItem:
        return RiskItem(
            id=rule['id'],
            rule_id=rule['id'],
            name=rule['name'],
            category=rule['category'],
            risk_level=rule['risk_level'],
            description=rule['description'],
            legal_basis=rule.get('legal_basis'),
            suggestion=rule.get('suggestion'),
            confidence=round(confidence, 2)
        )

    def _count_risks(self, risks: List[RiskItem]) -> RiskAnalysisResult:
        return RiskAnalysisResult(
            risks=risks,
            critical_count=sum(1 for r in risks if r.risk_level == 'critical'),
            high_count=sum(1 for r in risks if r.risk_level == 'high'),
            medium_count=sum(1 for r in risks if r.risk_level == 'medium'),
            low_count=sum(1 for r in risks if r.risk_level == 'low')
        )

    def _build_rule_summary(self, document_type: str) -> str:
        """构建规则清单摘要，用于注入 LLM prompt"""
        applicable_rules = [
            rule for rule in self.rules
            if document_type in rule.get('applicable_types', [])
        ]
        level_cn = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}
        lines = []
        for rule in applicable_rules:
            rid = rule['id']
            name = rule['name']
            level = level_cn.get(rule.get('risk_level', 'medium'), '中')
            desc = rule.get('description', '')
            basis = rule.get('legal_basis', '')
            lines.append(f"- [{rid}] {name}（风险等级：{level}）— {desc} 法律依据：{basis}")
        return "\n".join(lines)

    def deduplicate_risks(self, risks: List[RiskItem]) -> List[RiskItem]:
        """
        去重风险项

        去重策略：
        1. 相同 rule_id 的风险视为重复
        2. 相同风险名称 + 相似条款预览的风险视为重复
        3. 重复时保留风险等级更高的那个

        Args:
            risks: 风险项列表

        Returns:
            去重后的风险项列表
        """
        if not risks:
            return []

        seen = {}  # key -> RiskItem

        for risk in risks:
            # 生成去重 key
            rule_key = risk.rule_id if risk.rule_id else None

            # 如果 rule_id 相同，视为重复
            if rule_key and rule_key in seen:
                existing = seen[rule_key]
                # 保留风险等级更高的
                if self.RISK_LEVEL_MAP.get(risk.risk_level, 0) > self.RISK_LEVEL_MAP.get(existing.risk_level, 0):
                    seen[rule_key] = risk
                continue

            # 如果 rule_id 不存在，基于名称 + 条款预览匹配
            name_key = risk.name.lower()
            preview_key = (risk.clause_content_preview or "")[:50].lower()

            found_duplicate = False
            for key, existing in seen.items():
                existing_name = existing.name.lower()
                existing_preview = (existing.clause_content_preview or "")[:50].lower()

                # 名称相同 + 条款预览相似度高
                if name_key == existing_name and preview_key and existing_preview:
                    # 简单判断：预览有重叠
                    if preview_key in existing_preview or existing_preview in preview_key:
                        found_duplicate = True
                        # 保留风险等级更高的
                        if self.RISK_LEVEL_MAP.get(risk.risk_level, 0) > self.RISK_LEVEL_MAP.get(existing.risk_level, 0):
                            seen[key] = risk
                        break

            if not found_duplicate:
                # 使用 rule_id 或名称作为 key
                seen_key = rule_key or f"{name_key}_{preview_key}"
                seen[seen_key] = risk

        return list(seen.values())

    def link_risks_to_clauses(
        self,
        risks: List[RiskItem],
        clauses: List  # List[Clause] from parser
    ) -> List[RiskItem]:
        """
        将风险项关联回原始条款（溯源）

        Args:
            risks: 风险项列表
            clauses: 解析后的条款列表

        Returns:
            关联后的风险项列表
        """
        for risk in risks:
            matched = self._find_matching_clause(risk, clauses)
            if matched:
                risk.clause_id = matched.id
                risk.clause_title = matched.title or f"第{matched.id}条"
                risk.clause_position = matched.title or risk.clause_position
                # 估算行号范围（按段落数估算）
                line_count = matched.content.count('\n') + 1
                risk.clause_line_range = f"约 {line_count} 行"

        return risks

    def _find_matching_clause(self, risk: RiskItem, clauses: List) -> Optional[Any]:
        """
        通过内容匹配找到风险对应的原始条款

        匹配策略（优先级从高到低）：
        1. 条款标题精确匹配
        2. 内容前缀匹配
        3. 内容包含匹配
        """
        preview = risk.clause_content_preview or ""
        position = risk.clause_position or ""

        # 策略1：标题精确匹配
        if position:
            for clause in clauses:
                if clause.title and position in clause.title:
                    return clause
                if clause.title and clause.title in position:
                    return clause

        # 策略2：内容前缀匹配
        if len(preview) > 20:
            prefix = preview[:80]
            for clause in clauses:
                if clause.content.startswith(prefix[:40]):
                    return clause

        # 策略3：内容包含匹配
        if len(preview) > 20:
            search_text = preview[:100]
            for clause in clauses:
                if search_text[:50] in clause.content:
                    return clause

        # 策略4：关键词匹配（基于风险描述）
        risk_keywords = self._extract_keywords_from_rule(
            {"name": risk.name, "description": risk.description}
        )
        if risk_keywords:
            best_match = None
            best_score = 0
            for clause in clauses:
                score = sum(1 for kw in risk_keywords if kw.lower() in clause.content.lower())
                if score > best_score:
                    best_score = score
                    best_match = clause
            if best_score > 0:
                return best_match

        return None

    async def analyze_with_llm(
        self,
        text: str,
        document_type: str,
        llm_client,
        playbook: Optional[Playbook] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None
    ) -> RiskAnalysisResult:
        """
        使用 LLM 进行深入浅出分析

        如果文档超过单次分析上限，自动分段分析并合并去重。
        如果 LLM 支持工具调用，自动对每条高风险条款进行深度审查（流式）

        Args:
            text: 文档文本
            document_type: 文档类型
            llm_client: LLM 客户端
            playbook: 审查策略
            progress_callback: 进度回调，接收 dict {type, tool, content, risk_name, step}
        """
        max_segment_length = 5000
        max_segments = 3
        segments = self._split_into_segments(text, max_segment_length)

        # 超长文档：保留首段+末段+中间一段，避免 token 爆炸
        if len(segments) > max_segments:
            original_count = len(segments)
            mid = len(segments) // 2
            segments = [segments[0], segments[mid], segments[-1]]
            logger_manager.info(
                f"文档过长（{original_count}段），仅分析首/中/末 3 段以控制成本"
            )

        extra_context = ""
        role_context = ""
        if playbook and playbook.custom_prompts.get('risk_analysis'):
            extra_context = playbook.custom_prompts['risk_analysis']
            role_context = f"你代表{playbook.name}进行审查。"
        elif playbook:
            role_map = {
                "party_a": "你代表甲方立场审查合同。",
                "party_b": "你代表乙方立场审查合同。",
                "neutral": "你保持中立立场审查合同。"
            }
            extra_context = role_map.get(playbook.role, "")
            role_context = extra_context

        # 构建规则清单注入 prompt
        rule_summary = self._build_rule_summary(document_type)

        all_risks: List[RiskItem] = []

        try:
            for seg_idx, segment in enumerate(segments):
                seg_label = f"[第{seg_idx + 1}/{len(segments)}段]" if len(segments) > 1 else ""

                prompt = f"""{extra_context}
你是法律审查助手，请严格对照以下审查规则逐条分析文档风险。
{seg_label}

【审查规则清单】
{rule_summary}

【分析要求】
1. 逐条对照上述规则，判断文档是否触发每条规则
2. 仅返回你确认触发的风险，不要猜测
3. 每项返回：name, category, risk_level(high/medium/low), description, clause_preview(≤80字), legal_basis, suggestion, confidence(0-1)
4. 返回 JSON 数组格式

【待审文档】
{segment}"""

                response = await llm_client.chat_completion(
                    prompt,
                    system_prompt="你是中国法律审查助手，精通民法典、个人信息保护法等法律法规。严格按照给定的审查规则清单逐条分析，仅返回 JSON 数组。",
                    temperature=0.1,
                    max_tokens=2000
                )
                all_risks.extend(self._parse_llm_response(response))

            # 去重合并
            all_risks = self.deduplicate_risks(all_risks)

            # 应用策略调整
            if playbook:
                for risk in all_risks:
                    adjusted_level = playbook.adjust_risk_level(risk.rule_id, risk.risk_level)
                    if adjusted_level != risk.risk_level:
                        risk.risk_level = adjusted_level
                        risk.playbook_adjusted = True
                    if playbook.is_focus_area(risk.category):
                        current = self.RISK_LEVEL_MAP.get(risk.risk_level, 2)
                        if current < 3:
                            risk.risk_level = "high"
                            risk.playbook_adjusted = True

            # 对高风险条款进行 Tool Agent 深度审查（流式）
            high_risks = [r for r in all_risks if r.risk_level in ('high', 'critical')
                         and r.clause_content_preview]

            if high_risks:
                tool_agent = self._get_tool_agent(llm_client)

                for risk in high_risks[:3]:
                    async for event in tool_agent.analyze_stream(
                        clause_text=risk.clause_content_preview,
                        context=document_type,
                        role_context=role_context
                    ):
                        # 推送进度（包括反思事件）
                        if progress_callback and event.type.value in ("tool_call", "tool_result", "interrupted", "reflection"):
                            progress_callback({
                                "type": event.type.value,
                                "tool": event.tool_name or "自我反思",
                                "content": event.content,
                                "risk_name": risk.name,
                                "step": event.step_number
                            })

                        # 收集结论
                        if event.type.value == "conclusion" and event.is_final:
                            risk.tool_agent_conclusion = event.content
                            risk.confidence = min(1.0, risk.confidence + 0.1)

            return self._count_risks(all_risks)

        except LLMTimeoutError as e:
            logger_manager.warning(f"LLM 风险分析超时: {e}")
            raise
        except LLMNetworkError as e:
            logger_manager.warning(f"LLM 风险分析网络错误: {e}")
            raise
        except LLMError as e:
            logger_manager.error(f"LLM 风险分析失败: {e}")
            raise
        except Exception as e:
            logger_manager.error(f"LLM 风险分析未知错误: {e}", exc_info=True)
            raise RiskAnalysisError(f"LLM 风险分析失败: {e}", error_code="LLM_ANALYSIS_UNKNOWN")

    def _get_tool_agent(self, llm_client) -> ToolCallingAgent:
        """创建 Tool Agent（每次新建，避免持有旧 llm_client 引用）"""
        return ToolCallingAgent(
            llm_client=llm_client,
            tool_registry=self.tool_registry,
            max_iterations=2
        )

    @staticmethod
    def _split_into_segments(text: str, max_length: int) -> List[str]:
        """
        将长文档按段落/句子边界分割为多个片段

        优先在段落（双换行）边界分割，其次在句子（句号）边界分割。
        每个片段不超过 max_length 字符。
        """
        if len(text) <= max_length:
            return [text]

        segments = []
        remaining = text

        while len(remaining) > max_length:
            # 在 max_length 范围内寻找最佳分割点
            search_range = remaining[:max_length]

            # 优先：段落边界（双换行）
            cut = search_range.rfind('\n\n')
            if cut < max_length // 3:
                # 次优：单换行
                cut = search_range.rfind('\n')
            if cut < max_length // 3:
                # 再次：句子边界
                cut = search_range.rfind('。')
            if cut < max_length // 3:
                # 兜底：直接截断
                cut = max_length

            segments.append(remaining[:cut + 1])
            remaining = remaining[cut + 1:]

        if remaining.strip():
            segments.append(remaining)

        return segments

    async def analyze_clause_deep(
        self,
        clause_text: str,
        llm_client,
        context: str = "",
        role_context: str = ""
    ) -> AgentOutput:
        """对单条条款进行深度审查（非流式，向后兼容）"""
        tool_agent = self._get_tool_agent(llm_client)
        return await tool_agent.analyze(clause_text, context, role_context)

    def _parse_llm_response(self, response: str) -> List[RiskItem]:
        """
        解析 LLM 返回的 JSON 响应

        容错处理：
        1. 去除 markdown 代码块标记（```json ... ```）
        2. 去除首尾空白字符
        3. 尝试多种 JSON 提取策略
        """
        risks = []
        try:
            # 策略1：去除 markdown 代码块
            cleaned = response.strip()

            # 去除 ```json ... ``` 或 ``` ... ```
            md_pattern = r'```(?:json)?\s*([\s\S]*?)```'
            md_match = re.search(md_pattern, cleaned)
            if md_match:
                cleaned = md_match.group(1).strip()

            # 策略2：提取 JSON 数组
            json_match = re.search(r'\[[\s\S]*\]', cleaned)
            if json_match:
                data = json.loads(json_match.group())
            else:
                # 策略3：尝试提取 JSON 对象（有时 LLM 会返回对象而非数组）
                obj_match = re.search(r'\{[\s\S]*\}', cleaned)
                if obj_match:
                    obj = json.loads(obj_match.group())
                    # 如果对象中包含 risks 数组
                    data = obj.get("risks", []) if isinstance(obj.get("risks"), list) else [obj]
                else:
                    return risks

            if not isinstance(data, list):
                return risks

            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                risk_level = item.get("risk_level", "medium")
                if risk_level not in ("critical", "high", "medium", "low"):
                    risk_level = "medium"
                confidence = item.get("confidence", 0.7)
                if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
                    confidence = 0.7
                risks.append(RiskItem(
                    id=f"LLM_RISK_{i+1:03d}",
                    rule_id="LLM_ANALYSIS",
                    name=str(item.get("name", "未知风险"))[:100],
                    category=str(item.get("category", "其他风险"))[:50],
                    risk_level=risk_level,
                    description=str(item.get("description", "")),
                    clause_content_preview=str(item.get("clause_preview", ""))[:200],
                    legal_basis=item.get("legal_basis") or None,
                    suggestion=item.get("suggestion") or None,
                    confidence=round(float(confidence), 2)
                ))
        except json.JSONDecodeError as e:
            logger_manager.error(f"LLM JSON 解析失败: {e}, 原始响应: {response[:200]}...")
        except Exception as e:
            logger_manager.error(f"LLM 响应解析异常: {e}", exc_info=True)
        return risks

    # 通用法律文件关键词（任一命中即视为法律文件）
    LEGAL_SIGNAL_KEYWORDS = [
        "合同", "协议", "甲方", "乙方", "丙方", "当事人", "签约",
        "条款", "违约", "赔偿", "仲裁", "诉讼", "管辖", "解除",
        "隐私政策", "个人信息", "用户协议", "服务条款", "保密",
        "知识产权", "许可", "授权", "法律", "法规", "法院",
        "裁定", "判决", "起诉", "应诉", "代理", "委托",
        "租赁", "借款", "担保", "抵押", "质押", "转让",
    ]

    # 代码/技术文档信号关键词 — 命中越多越不可能是法律文件
    CODE_SIGNAL_KEYWORDS = [
        "import ", "def ", "class ", "return", "self.", "__init__",
        "function", "const ", "var ", "let ", "module", "package",
        "require(", "from ", "export", "async ", "await ",
        "try:", "except:", "raise ", "print(", "logger",
        "git", "dockerfile", "makefile", "readme", ".py", ".js",
        "src/", "tests/", "config", "setup.py", "requirements",
        "github", "npm", "pip install", "todo", "fixme", "hack",
        "refactor", "commit", "merge", "branch", "deploy",
    ]

    MIN_LEGAL_SCORE = 5   # 至少命中 5 个法律关键词才视为法律文件
    MIN_TYPE_SCORE = 2    # 类型关键词至少命中 2 个才视为该类型
    MIN_LEGAL_DENSITY = 0.005  # 法律关键词至少占分词数的 0.5%
    CODE_PENALTY_THRESHOLD = 5  # 命中 5+ 个代码信号时，提高法律阈值

    def detect_document_type(self, text: str) -> str:
        text_lower = text.lower()
        type_scores = {"contract": 0, "agreement": 0, "privacy_policy": 0}

        for kw in ["合同", "甲方", "乙方", "本合同", "价款", "报酬", "履行"]:
            if kw in text_lower:
                type_scores["contract"] += 1
        for kw in ["协议", "合作", "双方", "约定"]:
            if kw in text_lower:
                type_scores["agreement"] += 1
        for kw in ["隐私政策", "个人信息", "数据收集", "cookie", "用户信息"]:
            if kw in text_lower:
                type_scores["privacy_policy"] += 1

        best_type = max(type_scores, key=type_scores.get)
        best_score = type_scores[best_type]

        # 计算法律关键词命中数和密度
        legal_hits = sum(1 for kw in self.LEGAL_SIGNAL_KEYWORDS if kw in text_lower)
        word_count = max(len(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text_lower)), 1)
        legal_density = legal_hits / word_count

        # 计算代码信号命中数
        code_hits = sum(1 for kw in self.CODE_SIGNAL_KEYWORDS if kw in text_lower)

        # 代码信号多 → 提高法律阈值
        effective_min = self.MIN_LEGAL_SCORE
        if code_hits >= self.CODE_PENALTY_THRESHOLD:
            effective_min = self.MIN_LEGAL_SCORE + code_hits  # 代码信号越多，要求越多法律关键词

        # 类型关键词命中足够多 → 直接认定为该类型（但也要过密度关）
        if best_score >= self.MIN_TYPE_SCORE and legal_density >= self.MIN_LEGAL_DENSITY:
            return best_type

        # 法律关键词足够多 且 密度达标 → 通过
        if legal_hits >= effective_min and legal_density >= self.MIN_LEGAL_DENSITY:
            return best_type if best_score > 0 else "contract"

        return "unknown"
