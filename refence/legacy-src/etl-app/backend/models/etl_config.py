"""
ETL 配置模型
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ETLConfig(Base, TimestampMixin):
    """ETL 全局配置表"""
    
    __tablename__ = "etl_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称")
    description: Mapped[str] = mapped_column(String(255), nullable=True, comment="描述")
    
    # MySQL 连接配置
    mysql_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="MySQL 配置 ID")
    
    # 数据库名称配置
    source_database: Mapped[str] = mapped_column(String(100), default="sfc_raw", comment="源数据库")
    target_database: Mapped[str] = mapped_column(String(100), default="link_db", comment="关联数据库")
    analytics_database: Mapped[str] = mapped_column(String(100), default="analytics_dw", comment="分析数据库")
    
    # 执行配置
    run_interval: Mapped[int] = mapped_column(Integer, default=60, comment="执行间隔（分钟）")
    backfill_hours: Mapped[int] = mapped_column(Integer, default=24, comment="回算窗口（小时）")
    timeout: Mapped[int] = mapped_column(Integer, default=300, comment="执行超时（秒）")
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    last_run_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, comment="最后运行时间")
    last_run_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="最后运行状态")


class MySQLConfig(Base, TimestampMixin):
    """MySQL 连接配置表"""
    
    __tablename__ = "mysql_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称")
    description: Mapped[str] = mapped_column(String(255), nullable=True, comment="描述")
    
    # 连接配置
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="主机地址")
    port: Mapped[int] = mapped_column(Integer, default=3306, comment="端口号")
    username: Mapped[str] = mapped_column(String(100), nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(Text, nullable=False, comment="密码（加密存储）")
    database: Mapped[str] = mapped_column(String(100), nullable=False, comment="数据库名")
    
    # 连接池配置
    min_connections: Mapped[int] = mapped_column(Integer, default=5, comment="最小连接数")
    max_connections: Mapped[int] = mapped_column(Integer, default=20, comment="最大连接数")
    connection_timeout: Mapped[int] = mapped_column(Integer, default=30, comment="连接超时（秒）")
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")