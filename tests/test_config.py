#!/usr/bin/env python3
"""
配置模块测试脚本
"""

import os
import sys

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_config_loading():
    """测试配置加载"""
    from src.core.config import get_llm_config, get_paths_config, get_settings

    settings = get_settings()
    assert settings.llm_api_base, "LLM API Base 不应为空"
    assert settings.llm_model, "LLM Model 不应为空"
    assert settings.max_file_size_mb > 0

    llm_config = get_llm_config()
    assert llm_config["api_key"], "API Key 不应为空"
    assert llm_config["api_base"], "API Base 不应为空"
    assert llm_config["model"], "Model 不应为空"

    paths_config = get_paths_config()
    assert "rules_path" in paths_config
    assert "kb_path" in paths_config
    assert "playbooks_dir" in paths_config


def test_validation():
    """测试配置验证"""
    from src.core.config import Settings

    try:
        Settings(llm_api_key="", llm_api_base="https://example.com/v1")
        raise AssertionError("应该拒绝空 API 密钥")
    except ValueError:
        pass

    try:
        Settings(llm_api_key="test-key", llm_api_base="invalid-url")
        raise AssertionError("应该拒绝无效 URL")
    except ValueError:
        pass

    settings = Settings(
        llm_api_key="test-key",
        llm_api_base="https://example.com/v1",
        llm_model="test-model",
        max_file_size_mb=5,
    )
    assert str(settings.llm_api_base) == "https://example.com/v1"
    assert settings.llm_model == "test-model"
    assert settings.max_file_size_mb == 5
