#!/usr/bin/env python3
"""
配置模块测试脚本
"""

import sys
import os

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

def test_config_loading():
    """测试配置加载"""
    try:
        from src.config import get_settings, get_llm_config, get_paths_config
        
        print("✅ 配置模块导入成功")
        
        # 测试获取配置
        settings = get_settings()
        print(f"✅ 配置加载成功")
        print(f"   LLM API Base: {settings.llm_api_base}")
        print(f"   LLM Model: {settings.llm_model}")
        print(f"   Max File Size: {settings.max_file_size_mb} MB")
        print(f"   Config Dir: {settings.config_dir}")
        
        # 测试 LLM 配置
        llm_config = get_llm_config()
        print(f"✅ LLM 配置获取成功")
        print(f"   API Key: {llm_config['api_key'][:10]}...")
        print(f"   API Base: {llm_config['api_base']}")
        print(f"   Model: {llm_config['model']}")
        
        # 测试路径配置
        paths_config = get_paths_config()
        print(f"✅ 路径配置获取成功")
        print(f"   Rules Path: {paths_config['rules_path']}")
        print(f"   KB Path: {paths_config['kb_path']}")
        print(f"   Playbooks Dir: {paths_config['playbooks_dir']}")
        print(f"   Case Law Path: {paths_config['case_law_path']}")
        
        # 验证路径是否存在
        for name, path in paths_config.items():
            if path.exists():
                print(f"   ✅ {name}: 存在")
            else:
                print(f"   ❌ {name}: 不存在")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_validation():
    """测试配置验证"""
    try:
        from src.config import Settings
        
        print("\n测试配置验证...")
        
        # 测试无效的 API 密钥
        try:
            Settings(llm_api_key="", llm_api_base="https://example.com/v1")
            print("❌ 应该拒绝空 API 密钥")
            return False
        except ValueError as e:
            print(f"✅ 正确拒绝空 API 密钥: {e}")
        
        # 测试无效的 URL
        try:
            Settings(llm_api_key="test-key", llm_api_base="invalid-url")
            print("❌ 应该拒绝无效 URL")
            return False
        except ValueError as e:
            print(f"✅ 正确拒绝无效 URL: {e}")
        
        # 测试有效的配置
        try:
            settings = Settings(
                llm_api_key="test-key",
                llm_api_base="https://example.com/v1",
                llm_model="test-model",
                max_file_size_mb=5
            )
            print(f"✅ 有效配置验证通过")
            print(f"   API Base: {settings.llm_api_base}")
            print(f"   Model: {settings.llm_model}")
            print(f"   Max File Size: {settings.max_file_size_mb} MB")
        except Exception as e:
            print(f"❌ 有效配置验证失败: {e}")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ 验证测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("配置模块测试")
    print("=" * 50)
    
    success1 = test_config_loading()
    success2 = test_validation()
    
    print("\n" + "=" * 50)
    if success1 and success2:
        print("✅ 所有测试通过")
        sys.exit(0)
    else:
        print("❌ 部分测试失败")
        sys.exit(1)