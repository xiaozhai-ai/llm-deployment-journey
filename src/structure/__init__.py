"""
文档结构重建模块

条款层级树构建、表格结构化、跨页段落合并。
"""

from src.structure.clause_tree import build_clause_tree, build_clause_tree_from_blocks, parse_clause_number
from src.structure.cross_page_merger import merge_cross_page_paragraphs, merge_page_texts
from src.structure.table_parser import (
    detect_borderless_table,
    merge_table_results,
    parse_html_table,
    parse_pdfplumber_table,
    table_to_plain_text,
)

__all__ = [
    "build_clause_tree",
    "build_clause_tree_from_blocks",
    "detect_borderless_table",
    "merge_cross_page_paragraphs",
    "merge_page_texts",
    "merge_table_results",
    "parse_clause_number",
    "parse_html_table",
    "parse_pdfplumber_table",
    "table_to_plain_text",
]
