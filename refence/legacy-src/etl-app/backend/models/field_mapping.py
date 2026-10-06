"""
字段映射模型
"""
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class MappingType(str, Enum):
    """字段映射类型枚举"""
    DIRECT = "direct"           # 直接映射
    DERIVED = "derived"         # 派生字段
    CONSTANT = "constant"       # 固定值
    DIMENSION = "dimension"     # 维度字段
    AGGREGATE = "aggregate"     # 聚合字段
    TIME_DIMENSION = "time_dimension"  # 时间维度


class FieldMapping(BaseModel):
    """字段映射配置"""
    
    source_field: str = Field(..., description="源字段名")
    target_field: str = Field(..., description="目标字段名")
    field_type: str = Field(default="string", description="字段类型")
    mapping_type: MappingType = Field(default=MappingType.DIRECT, description="映射类型")
    
    # 转换配置
    formula: Optional[str] = Field(None, description="转换公式(SQL表达式)")
    constant_value: Optional[str] = Field(None, description="固定值")
    aggregate_function: Optional[str] = Field(None, description="聚合函数")
    default_value: Optional[str] = Field(None, description="默认值")
    description: Optional[str] = Field(None, description="字段描述")
    
    # 排序和状态
    sort_order: int = Field(default=0, description="排序顺序")
    is_required: bool = Field(default=False, description="是否必填")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldMapping":
        """从字典创建实例"""
        return cls(**data)
    
    def validate_mapping(self) -> bool:
        """验证映射配置是否有效"""
        if self.mapping_type == MappingType.DERIVED and not self.formula:
            return False
        
        if self.mapping_type == MappingType.CONSTANT and not self.constant_value:
            return False
        
        if self.mapping_type == MappingType.AGGREGATE and not self.aggregate_function:
            return False
        
        return True