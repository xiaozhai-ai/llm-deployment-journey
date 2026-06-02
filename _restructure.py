"""临时脚本：批量更新 import 路径"""
import re
import os
import sys

root_dir = os.path.dirname(os.path.abspath(__file__))

moves = {
    'src.config': 'src.core.config',
    'src.data_models': 'src.core.data_models',
    'src.exceptions': 'src.core.exceptions',
    'src.parser': 'src.parsing.parser',
    'src.scan_detector': 'src.parsing.scan_detector',
    'src.risk_engine': 'src.analysis.risk_engine',
    'src.legal_matcher': 'src.analysis.legal_matcher',
    'src.playbook_manager': 'src.analysis.playbook_manager',
    'src.legal_terms': 'src.analysis.legal_terms',
    'src.knowledge_freshness': 'src.analysis.knowledge_freshness',
    'src.llm_client': 'src.llm.llm_client',
    'src.vector_store': 'src.llm.vector_store',
    'src.tool_agent': 'src.llm.tool_agent',
    'src.report': 'src.output.report',
    'src.redliner': 'src.output.redliner',
    'src.html_renderers': 'src.output.html_renderers',
    'src.security': 'src.output.security',
    'src.logger': 'src.infra.logger',
    'src.metrics': 'src.infra.metrics',
    'src.session_store': 'src.infra.session_store',
    'src.chat_memory': 'src.infra.chat_memory',
    'src.feedback_store': 'src.infra.feedback_store',
    'src.utils': 'src.infra.utils',
    # 子包映射（长路径优先，防止部分匹配）
    'src.legal_entities': 'src.parsing.legal_entities',
    'src.structure': 'src.parsing.structure',
    'src.layout': 'src.parsing.layout',
    'src.tools': 'src.llm.tools',
}

# 收集所有 .py 文件
files_to_check = []
for root, dirs, files in os.walk(root_dir):
    dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', '.pytest_cache', '.ruff_cache', 'chroma_db', 'logs', '.mypy_cache', 'node_modules', '.qwen')]
    for f in files:
        if f.endswith('.py') and f != '_restructure.py':
            files_to_check.append(os.path.join(root, f))

# 排序映射，长路径优先（防止 src.tools.xxx 被 src.tools 部分匹配）
sorted_moves = sorted(moves.items(), key=lambda x: len(x[0]), reverse=True)

total_changes = 0
changed_files = []

for fpath in files_to_check:
    try:
        with open(fpath, encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        try:
            with open(fpath, encoding='utf-8-sig') as f:
                content = f.read()
        except:
            continue
    
    original = content
    file_changes = 0
    
    for old_prefix, new_prefix in sorted_moves:
        # 匹配 from src.xxx 或 import src.xxx
        # 需要处理: from src.config import ..., from src.tools.web_search import ...
        pattern = rf'(from\s+)({re.escape(old_prefix)})(\b)'
        new_content = re.sub(pattern, lambda m: f'{m.group(1)}{new_prefix}{m.group(3)}', content)
        
        pattern2 = rf'(import\s+)({re.escape(old_prefix)})(\b)'
        new_content = re.sub(pattern2, lambda m: f'{m.group(1)}{new_prefix}{m.group(3)}', new_content)
        
        if new_content != content:
            changes = len(re.findall(pattern, original)) + len(re.findall(pattern2, original))
            file_changes += 1
            content = new_content
    
    if content != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        rel = os.path.relpath(fpath, root_dir)
        changed_files.append(rel)
        total_changes += file_changes

print(f"Updated {len(changed_files)} files, {total_changes} import changes total")
for f in sorted(changed_files):
    print(f"  {f}")
