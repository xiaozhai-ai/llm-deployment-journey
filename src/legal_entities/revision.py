"""
修订追踪提取

从合同文档中提取修订和批注信息：
- Word 文档：Track Changes（插入/删除）+ 批注
- PDF 文档：注释/批注（高亮、下划线、删除线、文本批注）
- 文本内联标记：删除线文字（~~删除~~）、[删除]、[新增]
"""

from __future__ import annotations

import re
from pathlib import Path

from src.data_models import Revision
from src.logger import logger_manager

# Word 扩展名
_WORD_EXTENSIONS = {".docx", ".doc"}

# PDF 扩展名
_PDF_EXTENSIONS = {".pdf"}

# 内联修订标记模式
_INLINE_DELETE_PATTERNS = [
    re.compile(r"~~(.+?)~~"),  # Markdown 风格删除线
    re.compile(r"\[删除[：:]?\s*(.+?)\]"),  # [删除：XXX]
    re.compile(r"\[(?:删|删除)\](.+?)\[(?:/删|/删除)\]"),  # [删]XXX[/删]
]

_INLINE_INSERT_PATTERNS = [
    re.compile(r"\[新增[：:]?\s*(.+?)\]"),  # [新增：XXX]
    re.compile(r"\[(?:增|新增)\](.+?)\[(?:/增|/新增)\]"),  # [增]XXX[/增]
    re.compile(r"\[(?:改|修改)[：:]?\s*(.+?)\]"),  # [修改：XXX]
]


def extract_revisions(
    text: str,
    file_path: str | None = None,
    file_bytes: bytes | None = None,
    file_type: str | None = None,
) -> list[Revision]:
    """
    提取修订和批注信息

    Args:
        text: 文档全文（用于内联标记检测）
        file_path: 文件路径（用于 Word/PDF 专用提取）
        file_bytes: 文件字节（用于 Word/PDF 专用提取）
        file_type: 文件类型 ("word"/"pdf")

    Returns:
        list[Revision]: 修订列表
    """
    revisions: list[Revision] = []

    # 1. 文本内联修订标记（通用）
    inline_revs = _extract_inline_revisions(text)
    revisions.extend(inline_revs)

    # 2. Word Track Changes
    if file_type == "word" or (file_path and Path(file_path).suffix.lower() in _WORD_EXTENSIONS):
        word_revs = _extract_word_revisions(file_path=file_path, file_bytes=file_bytes)
        revisions.extend(word_revs)

    # 3. PDF 注释
    if file_type == "pdf" or (file_path and Path(file_path).suffix.lower() in _PDF_EXTENSIONS):
        pdf_revs = _extract_pdf_annotations(file_path=file_path, file_bytes=file_bytes)
        revisions.extend(pdf_revs)

    return revisions


def _extract_inline_revisions(text: str) -> list[Revision]:
    """提取文本中的内联修订标记"""
    revisions: list[Revision] = []

    # 删除标记
    for pattern in _INLINE_DELETE_PATTERNS:
        for m in pattern.finditer(text):
            revisions.append(
                Revision(
                    revision_type="delete",
                    text=m.group(1),
                )
            )

    # 插入/修改标记
    for pattern in _INLINE_INSERT_PATTERNS:
        for m in pattern.finditer(text):
            revisions.append(
                Revision(
                    revision_type="insert",
                    text=m.group(1),
                )
            )

    return revisions


def _extract_word_revisions(
    file_path: str | None = None,
    file_bytes: bytes | None = None,
) -> list[Revision]:
    """
    从 Word 文档提取 Track Changes 和批注

    需要 python-docx 库。
    """
    try:
        from docx import Document
    except ImportError:
        logger_manager.debug("python-docx 未安装，跳过 Word 修订提取")
        return []

    revisions: list[Revision] = []

    try:
        if file_bytes:
            import io
            doc = Document(io.BytesIO(file_bytes))
        elif file_path:
            doc = Document(file_path)
        else:
            return []

        # 提取批注
        try:
            from docx.opc.constants import RELATIONSHIP_TYPE as RT

            # 尝试通过 XML 提取批注
            import xml.etree.ElementTree as ET

            # 批注在 word/comments.xml 中
            for rel in doc.part.rels.values():
                if "comments" in rel.reltype:
                    comments_part = rel.target_part
                    root = ET.fromstring(comments_part.blob)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

                    for comment in root.findall(".//w:comment", ns):
                        author = comment.get(f"{{{ns['w']}}}author", "未知")
                        date = comment.get(f"{{{ns['w']}}}date", "")
                        texts = []
                        for para in comment.findall(".//w:t", ns):
                            if para.text:
                                texts.append(para.text)
                        comment_text = "".join(texts)

                        if comment_text:
                            revisions.append(
                                Revision(
                                    revision_type="comment",
                                    text=comment_text,
                                    author=author,
                                    date=date[:10] if date else None,
                                )
                            )
        except Exception:
            pass

        # 提取 Track Changes（插入/删除）
        try:
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            body = doc.element.body

            # 插入的文本
            for insert_elem in body.iter(f"{{{ns['w']}}}ins"):
                author = insert_elem.get(f"{{{ns['w']}}}author", "未知")
                date = insert_elem.get(f"{{{ns['w']}}}date", "")
                texts = []
                for t in insert_elem.findall(f".//{{{ns['w']}}}t"):
                    if t.text:
                        texts.append(t.text)
                if texts:
                    revisions.append(
                        Revision(
                            revision_type="insert",
                            text="".join(texts),
                            author=author,
                            date=date[:10] if date else None,
                        )
                    )

            # 删除的文本
            for del_elem in body.iter(f"{{{ns['w']}}}del"):
                author = del_elem.get(f"{{{ns['w']}}}author", "未知")
                date = del_elem.get(f"{{{ns['w']}}}date", "")
                texts = []
                for t in del_elem.findall(f".//{{{ns['w']}}}t"):
                    if t.text:
                        texts.append(t.text)
                if texts:
                    revisions.append(
                        Revision(
                            revision_type="delete",
                            text="".join(texts),
                            author=author,
                            date=date[:10] if date else None,
                        )
                    )
        except Exception:
            pass

    except Exception as e:
        logger_manager.warning(f"Word 修订提取失败: {e}")

    return revisions


def _extract_pdf_annotations(
    file_path: str | None = None,
    file_bytes: bytes | None = None,
) -> list[Revision]:
    """
    从 PDF 提取注释/批注

    使用 pdfplumber 提取 PDF annotations。
    """
    try:
        import pdfplumber
    except ImportError:
        logger_manager.debug("pdfplumber 未安装，跳过 PDF 注释提取")
        return []

    revisions: list[Revision] = []

    try:
        if file_bytes:
            import io
            pdf = pdfplumber.open(io.BytesIO(file_bytes))
        elif file_path:
            pdf = pdfplumber.open(file_path)
        else:
            return []

        with pdf:
            for page_idx, page in enumerate(pdf.pages):
                # pdfplumber 的 page.annots 是底层 PDF 注释
                if not hasattr(page, "annots") or not page.annots:
                    continue

                for annot in page.annots:
                    annot_type = annot.get("subtype", "")
                    content = annot.get("contents", "")
                    author = annot.get("T", "")
                    date = annot.get("M", "")

                    if not content and annot_type not in ("/Highlight", "/Underline", "/StrikeOut"):
                        continue

                    # 映射注释类型
                    revision_type = _map_pdf_annot_type(annot_type)

                    revisions.append(
                        Revision(
                            revision_type=revision_type,
                            text=content or "",
                            author=author if isinstance(author, str) else str(author),
                            date=str(date)[:10] if date else None,
                            page_index=page_idx,
                        )
                    )

    except Exception as e:
        logger_manager.warning(f"PDF 注释提取失败: {e}")

    return revisions


def _map_pdf_annot_type(annot_type: str) -> str:
    """映射 PDF 注释类型到修订类型"""
    mapping = {
        "/Text": "comment",
        "/FreeText": "comment",
        "/Highlight": "highlight",
        "/Underline": "underline",
        "/StrikeOut": "delete",
        "/Squiggly": "comment",
        "/Stamp": "comment",
        "/Ink": "ink",
        "/Popup": "comment",
    }
    return mapping.get(annot_type, "comment")
