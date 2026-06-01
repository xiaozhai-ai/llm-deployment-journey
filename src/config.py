"""
集中式配置管理模块
使用 Pydantic Settings 进行配置验证和管理
"""

from pathlib import Path
from typing import Optional
from pydantic import Field, AnyHttpUrl, ConfigDict, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM 配置
    llm_api_key: str = Field(..., min_length=1, description="LLM API 密钥")
    llm_api_base: AnyHttpUrl = Field(
        default="https://token-plan-cn.xiaomimimo.com/v1",
        description="LLM API 端点"
    )
    llm_model: str = Field(
        default="mimo-v2.5-pro",
        description="LLM 模型名称"
    )

    # 文件处理配置
    max_file_size_mb: int = Field(
        default=10,
        ge=1,
        le=100,
        description="最大文件大小（MB）"
    )

    # HuggingFace 配置
    hf_endpoint: Optional[str] = Field(
        default=None,
        description="HuggingFace 镜像端点（国内网络可选）"
    )

    # 路径配置
    config_dir: Path = Field(
        default=Path(__file__).parent.parent / "config",
        description="配置文件目录"
    )

    @model_validator(mode='before')
    @classmethod
    def validate_config_dir(cls, values):
        """验证配置目录是否存在"""
        config_dir = values.get('config_dir')
        if config_dir is not None:
            path = Path(config_dir).resolve()
            if not path.exists():
                raise ValueError(f"配置目录不存在: {path}")
            values['config_dir'] = path
        return values
    
    @property
    def rules_path(self) -> Path:
        """风险规则文件路径"""
        return self.config_dir / "legal_rules.yaml"

    @property
    def kb_path(self) -> Path:
        """法律知识库文件路径"""
        return self.config_dir / "legal_kb.yaml"

    @property
    def playbooks_dir(self) -> Path:
        """审查策略目录路径"""
        return self.config_dir / "playbooks"

    @property
    def case_law_path(self) -> Path:
        """司法判例库文件路径"""
        return self.config_dir / "case_law.yaml"


# 全局配置实例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置实例（单例模式）"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """重新加载配置"""
    global _settings
    _settings = None
    return get_settings()


# 便捷访问函数
def get_llm_config() -> dict:
    """获取 LLM 配置"""
    settings = get_settings()
    return {
        "api_key": settings.llm_api_key,
        "api_base": str(settings.llm_api_base),
        "model": settings.llm_model
    }


def get_file_config() -> dict:
    """获取文件处理配置"""
    settings = get_settings()
    return {
        "max_file_size_mb": settings.max_file_size_mb
    }


def get_paths_config() -> dict:
    """获取路径配置"""
    settings = get_settings()
    
    # 验证路径是否存在
    paths = {
        "config_dir": settings.config_dir,
        "rules_path": settings.rules_path,
        "kb_path": settings.kb_path,
        "playbooks_dir": settings.playbooks_dir,
        "case_law_path": settings.case_law_path
    }
    
    # 验证配置目录
    if not paths["config_dir"].exists():
        raise ValueError(f"配置目录不存在: {paths['config_dir']}")
    
    # 验证配置文件
    for name in ["rules_path", "kb_path", "case_law_path"]:
        if not paths[name].exists():
            raise ValueError(f"配置文件不存在: {paths[name]}")
    
    # 验证策略目录
    if not paths["playbooks_dir"].exists():
        raise ValueError(f"策略目录不存在: {paths['playbooks_dir']}")
    
    return paths