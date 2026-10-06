"""
系统设置模型
"""
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SystemSettings(Base, TimestampMixin):
    """系统设置表"""
    
    __tablename__ = "system_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    param_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="参数键")
    param_value: Mapped[str] = mapped_column(Text, nullable=False, comment="参数值")
    param_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="参数名称")
    description: Mapped[str] = mapped_column(String(255), nullable=True, comment="参数描述")
    category: Mapped[str] = mapped_column(String(50), default="system", comment="参数分类")
