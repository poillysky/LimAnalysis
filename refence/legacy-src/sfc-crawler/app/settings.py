"""
SFC 爬虫服务配置
"""
import os
import secrets

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """系统配置"""
    
    # 应用信息
    app_name: str = "SFC-Crawler"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # 时区配置
    tz: str = "Asia/Shanghai"
    
    # SQLite 配置数据库路径
    cfg_db_path: str = "data/sfc_crawler_config.sqlite"
    
    # JWT 配置
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 小时
    
    # 加密密钥（用于加密密码）
    encryption_key: str = os.getenv("ENCRYPTION_KEY", "v8qOOLsF_1k0FHA6bJSfR-bUnOj9FOkN-Mj_AuaBs6Q=")
    
    # 日志配置
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量


settings = Settings()
