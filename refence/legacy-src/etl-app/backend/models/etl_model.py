"""
ETL 模型定义
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class ETLModel(Base, TimestampMixin):
    """ETL 模型表"""
    
    __tablename__ = "etl_models"
    
    # 配置 Pydantic 以允许 model_ 开头的字段名
    model_config = {"protected_namespaces": ()}
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型名称")
    table_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="目标表名")
    source_table: Mapped[str] = mapped_column(String(100), nullable=True, comment="源表名")
    model_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="模型类型(link/analysis)")
    
    # 数据库配置
    source_database: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="数据来源数据库")
    target_database: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="数据输出数据库")
    
    # SQL配置
    sql_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="SQL 文件路径")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="描述")
    
    # 唯一键配置
    unique_key_type: Mapped[str] = mapped_column(String(20), nullable=True, default='none', comment="唯一键类型(none/single/composite)")
    unique_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="唯一键字段名（单字段）")
    unique_keys: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="复合唯一键字段列表（JSON数组）")
    
    # 透视维度配置（分析表模型专用）
    dimension_fields: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="维度字段列表（JSON数组）")
    time_dimensions: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="时间维度配置（JSON数组）")
    
    # 增量配置
    incremental_field: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="增量更新字段名")
    
    # 视图配置
    view_time_field: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="视图时间字段（用于生成最近数据视图）")
    
    # 分析表时间聚合配置
    time_field: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="时间字段名（用于聚合）")
    granularity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default='hour', comment="聚合细度(hour/day/week/month)")
    time_field_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default='hour', comment="生成的时间字段名")
    
    # 状态
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用")
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否草稿")


class ETLModelField(Base, TimestampMixin):
    """ETL 模型字段配置表"""
    
    __tablename__ = "etl_model_fields"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="模型ID")
    
    # 字段映射
    source_field: Mapped[str] = mapped_column(String(100), nullable=False, comment="源字段名")
    target_field: Mapped[str] = mapped_column(String(100), nullable=False, comment="目标字段名")
    field_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="字段类型(string/integer/float/datetime/boolean)")
    
    # 字段类别（分析表专用）
    field_category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="字段类别(dimension/measure/derived)")
    
    # 映射类型和派生层级
    mapping_type: Mapped[str] = mapped_column(String(20), nullable=False, default="direct", comment="映射类型(direct/derived/constant/dimension/aggregate/time_dimension)")
    derive_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="派生层级(0:直接映射/固定值/维度/时间维度, 1:普通派生, 2:高层派生1, 3:高层派生2)")
    
    # 转换配置
    formula: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="转换公式(SQL表达式)")
    constant_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="固定值")
    aggregate_function: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="聚合函数(COUNT/SUM/AVG/MAX/MIN/COUNT_DISTINCT)")
    aggregate_func: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="聚合函数简写(用于前端)")
    default_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="默认值")
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="字段描述")
    
    # 排序和状态
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序顺序")
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否必填")


class ETLSourceField(Base, TimestampMixin):
    """ETL 数据源字段表"""
    
    __tablename__ = "etl_source_fields"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="模型ID")
    
    # 字段信息
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="字段名")
    field_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="字段类型")
    field_category: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="字段分类(文本/整数/小数/时间)")
    nullable: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可空")
    default_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="默认值")
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="字段注释")
    
    # 选择状态
    is_selected: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否选中")