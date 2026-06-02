"""
文档智能解析数据模型

定义版面分析、条款层级树、法律要素等结构化数据，
与下游模块（risk_engine、report、redliner）对接。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ============================================================
# 版面元素
# ============================================================


@dataclass
class BBox:
    """轴对齐边界框（像素坐标）"""

    x1: float  # 左上角 x
    y1: float  # 左上角 y
    x2: float  # 右下角 x
    y2: float  # 右下角 y

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def area(self) -> float:
        return max(0, self.width) * max(0, self.height)

    def to_dict(self) -> dict:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    @classmethod
    def from_list(cls, coords: list[float]) -> BBox:
        """从 [x1, y1, x2, y2] 列表构建"""
        return cls(x1=coords[0], y1=coords[1], x2=coords[2], y2=coords[3])


@dataclass
class LayoutBlock:
    """版面分析输出的单个区域"""

    block_id: str  # 全局唯一 ID，格式: "p{page}_b{block}"
    block_type: str  # text | title | table | image | header | footer | figure | stamp
    bbox: BBox  # 像素坐标
    page_index: int  # 页码 (0-based)
    reading_order: int  # 阅读顺序 (0-based)
    content: str  # 文本内容（表格则为 HTML）
    confidence: float  # 置信度 0-1
    polygon: list[tuple[float, float]] | None = None  # 四角多边形（倾斜文本）

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "block_type": self.block_type,
            "bbox": self.bbox.to_dict(),
            "page_index": self.page_index,
            "reading_order": self.reading_order,
            "content": self.content,
            "confidence": self.confidence,
        }


# ============================================================
# 表格
# ============================================================


@dataclass
class TableCell:
    """表格单元格"""

    content: str
    row_span: int = 1
    col_span: int = 1
    is_header: bool = False

    def to_dict(self) -> dict:
        d = {"content": self.content}
        if self.row_span != 1:
            d["row_span"] = self.row_span
        if self.col_span != 1:
            d["col_span"] = self.col_span
        if self.is_header:
            d["is_header"] = True
        return d


@dataclass
class TableBlock:
    """结构化表格"""

    block_id: str
    bbox: BBox
    page_index: int
    rows: list[list[TableCell]]  # [行][列] 矩阵
    has_border: bool  # 有无边框
    header_rows: int  # 表头行数
    html: str  # 原始 HTML 输出
    confidence: float

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        if not self.rows:
            return 0
        return max(len(row) for row in self.rows)

    def to_dict(self) -> dict:
        return {
            "block_id": self.block_id,
            "bbox": self.bbox.to_dict(),
            "page_index": self.page_index,
            "rows": [[cell.to_dict() for cell in row] for row in self.rows],
            "has_border": self.has_border,
            "header_rows": self.header_rows,
            "html": self.html,
            "confidence": self.confidence,
        }


# ============================================================
# 条款层级树
# ============================================================


@dataclass
class ClauseNode:
    """条款树节点（支持无限嵌套）"""

    node_id: str  # 全局唯一 ID，格式: "c{序号}"
    clause_number: str | None  # 编号: "第5条" / "5.1" / "（三）"
    title: str | None  # 标题
    level: str  # chapter | section | article | paragraph | subitem | item
    content: str  # 正文内容
    bbox: BBox | None  # 位置坐标
    page_index: int | None  # 页码
    clause_type: str | None  # 类型: 违约责任/争议解决/保密条款/...
    children: list[ClauseNode] = field(default_factory=list)  # 子节点
    block_ids: list[str] = field(default_factory=list)  # 关联的 LayoutBlock ID

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "clause_number": self.clause_number,
            "title": self.title,
            "level": self.level,
            "content": self.content[:200] + ("..." if len(self.content) > 200 else ""),
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "page_index": self.page_index,
            "clause_type": self.clause_type,
            "children_count": len(self.children),
            "block_ids": self.block_ids,
        }

    def flatten(self) -> list[ClauseNode]:
        """递归展平为列表"""
        result = [self]
        for child in self.children:
            result.extend(child.flatten())
        return result

    def find_by_number(self, number: str) -> ClauseNode | None:
        """按编号查找节点"""
        if self.clause_number == number:
            return self
        for child in self.children:
            found = child.find_by_number(number)
            if found:
                return found
        return None


# ============================================================
# 法律要素
# ============================================================


@dataclass
class ContractParty:
    """合同当事人"""

    role: str  # 甲方/乙方/丙方/担保方
    name: str
    representative: str | None = None  # 法定代表人
    address: str | None = None
    contact: str | None = None  # 联系方式

    def to_dict(self) -> dict:
        d = {"role": self.role, "name": self.name}
        if self.representative:
            d["representative"] = self.representative
        if self.address:
            d["address"] = self.address
        if self.contact:
            d["contact"] = self.contact
        return d


@dataclass
class MoneyAmount:
    """金额实体"""

    raw_text: str  # 原文
    amount: float  # 数值
    currency: str  # CNY/USD/...
    uppercase_text: str | None = None  # 大写
    lowercase_text: str | None = None  # 小写
    is_consistent: bool | None = None  # 大小写是否一致
    pair_id: str | None = None  # 大小写配对 ID
    clause_id: str | None = None  # 关联条款 ID
    bbox: BBox | None = None
    page_index: int | None = None

    def to_dict(self) -> dict:
        d = {
            "raw_text": self.raw_text,
            "amount": self.amount,
            "currency": self.currency,
        }
        if self.uppercase_text:
            d["uppercase_text"] = self.uppercase_text
        if self.lowercase_text:
            d["lowercase_text"] = self.lowercase_text
        if self.is_consistent is not None:
            d["is_consistent"] = self.is_consistent
        if self.pair_id:
            d["pair_id"] = self.pair_id
        if self.clause_id:
            d["clause_id"] = self.clause_id
        if self.bbox:
            d["bbox"] = self.bbox.to_dict()
        if self.page_index is not None:
            d["page_index"] = self.page_index
        return d


@dataclass
class DateEntity:
    """日期实体"""

    raw_text: str  # 原文
    date: str  # 标准化: "2026-01-15"
    role: str | None = None  # 关联角色: "交货日期"/"付款截止日"/"签署日期"
    clause_id: str | None = None
    bbox: BBox | None = None
    page_index: int | None = None

    def to_dict(self) -> dict:
        d = {"raw_text": self.raw_text, "date": self.date}
        if self.role:
            d["role"] = self.role
        if self.clause_id:
            d["clause_id"] = self.clause_id
        return d


@dataclass
class SignatureInfo:
    """签章信息"""

    party_role: str  # 甲方/乙方
    has_signature: bool  # 是否有签名
    has_seal: bool  # 是否有公章
    has_riding_seal: bool = False  # 是否有骑缝章
    seal_bbox: BBox | None = None  # 印章位置
    page_index: int | None = None

    def to_dict(self) -> dict:
        return {
            "party_role": self.party_role,
            "has_signature": self.has_signature,
            "has_seal": self.has_seal,
            "has_riding_seal": self.has_riding_seal,
            "page_index": self.page_index,
        }


@dataclass
class Definition:
    """定义条款"""

    term: str  # 被定义的术语: "标的物"
    definition_text: str  # 定义内容
    clause_id: str  # 定义所在条款
    references: list[str] = field(default_factory=list)  # 后续引用该术语的条款 ID

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "definition_text": self.definition_text,
            "clause_id": self.clause_id,
            "references": self.references,
        }


@dataclass
class Revision:
    """修订/批注"""

    revision_type: str  # insert | delete | comment | ink
    text: str  # 修订内容
    author: str | None = None  # 修订人
    date: str | None = None  # 修订时间
    target_text: str | None = None  # 被批注的原文
    bbox: BBox | None = None
    page_index: int | None = None

    def to_dict(self) -> dict:
        d = {"revision_type": self.revision_type, "text": self.text}
        if self.author:
            d["author"] = self.author
        if self.date:
            d["date"] = self.date
        if self.target_text:
            d["target_text"] = self.target_text
        return d


# ============================================================
# 合同元数据
# ============================================================


@dataclass
class LegalMetadata:
    """合同元数据"""

    contract_name: str | None = None  # 合同名称
    contract_type: str | None = None  # 合同类型
    parties: list[ContractParty] = field(default_factory=list)
    execution_date: str | None = None  # 签署日期
    effective_date: str | None = None  # 生效日期
    expiration_date: str | None = None  # 到期日期
    dispute_resolution: str | None = None  # 争议解决方式
    governing_law: str | None = None  # 适用法律
    notice_addresses: list[str] = field(default_factory=list)
    total_amount: MoneyAmount | None = None

    def to_dict(self) -> dict:
        d: dict = {}
        if self.contract_name:
            d["contract_name"] = self.contract_name
        if self.contract_type:
            d["contract_type"] = self.contract_type
        if self.parties:
            d["parties"] = [p.to_dict() for p in self.parties]
        if self.execution_date:
            d["execution_date"] = self.execution_date
        if self.effective_date:
            d["effective_date"] = self.effective_date
        if self.expiration_date:
            d["expiration_date"] = self.expiration_date
        if self.dispute_resolution:
            d["dispute_resolution"] = self.dispute_resolution
        if self.governing_law:
            d["governing_law"] = self.governing_law
        if self.notice_addresses:
            d["notice_addresses"] = self.notice_addresses
        if self.total_amount:
            d["total_amount"] = self.total_amount.to_dict()
        return d


# ============================================================
# 页面版面
# ============================================================


@dataclass
class PageLayout:
    """单页版面信息"""

    page_index: int
    width: float  # 页面宽度（像素）
    height: float  # 页面高度（像素）
    blocks: list[LayoutBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_index": self.page_index,
            "width": self.width,
            "height": self.height,
            "blocks_count": len(self.blocks),
            "tables_count": len(self.tables),
        }

    def get_blocks_by_type(self, block_type: str) -> list[LayoutBlock]:
        """按类型筛选版面块"""
        return [b for b in self.blocks if b.block_type == block_type]

    def get_reading_ordered_blocks(self) -> list[LayoutBlock]:
        """按阅读顺序返回版面块"""
        return sorted(self.blocks, key=lambda b: b.reading_order)
