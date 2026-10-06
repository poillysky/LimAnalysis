"""
数据验证工具
"""
import re
from typing import Dict, Any, List


def validate_field_mapping(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证字段映射配置
    
    Args:
        mapping: 字段映射配置
        
    Returns:
        验证结果
    """
    errors = []
    
    # 检查必填字段
    required_fields = ["source_field", "target_field", "mapping_type"]
    for field in required_fields:
        if not mapping.get(field):
            errors.append(f"缺少必填字段: {field}")
    
    # 检查字段名格式
    if mapping.get("source_field"):
        if not is_valid_field_name(mapping["source_field"]):
            errors.append(f"源字段名格式无效: {mapping['source_field']}")
    
    if mapping.get("target_field"):
        if not is_valid_field_name(mapping["target_field"]):
            errors.append(f"目标字段名格式无效: {mapping['target_field']}")
    
    # 检查映射类型特定的配置
    mapping_type = mapping.get("mapping_type")
    
    if mapping_type == "derived":
        if not mapping.get("formula"):
            errors.append("派生字段必须提供转换公式")
        elif not is_valid_sql_expression(mapping["formula"]):
            errors.append("转换公式包含无效的 SQL 表达式")
    
    elif mapping_type == "constant":
        if not mapping.get("constant_value"):
            errors.append("固定值字段必须提供常量值")
    
    elif mapping_type == "aggregate":
        if not mapping.get("aggregate_function"):
            errors.append("聚合字段必须提供聚合函数")
        elif mapping["aggregate_function"] not in ["COUNT", "SUM", "AVG", "MAX", "MIN", "COUNT_DISTINCT"]:
            errors.append(f"不支持的聚合函数: {mapping['aggregate_function']}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def validate_model_config(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证模型配置
    
    Args:
        model: 模型配置
        
    Returns:
        验证结果
    """
    errors = []
    
    # 检查必填字段
    required_fields = ["name", "table_name", "model_type"]
    for field in required_fields:
        if not model.get(field):
            errors.append(f"缺少必填字段: {field}")
    
    # 检查模型类型
    if model.get("model_type") not in ["link", "analysis"]:
        errors.append(f"不支持的模型类型: {model.get('model_type')}")
    
    # 检查表名格式
    if model.get("table_name"):
        if not is_valid_table_name(model["table_name"]):
            errors.append(f"表名格式无效: {model['table_name']}")
    
    # 检查唯一键配置
    unique_key_type = model.get("unique_key_type", "none")
    if unique_key_type == "single":
        if not model.get("unique_key"):
            errors.append("单字段唯一键必须指定字段名")
    elif unique_key_type == "composite":
        if not model.get("unique_keys"):
            errors.append("复合唯一键必须指定字段列表")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def is_valid_field_name(field_name: str) -> bool:
    """
    检查字段名是否有效
    
    Args:
        field_name: 字段名
        
    Returns:
        是否有效
    """
    # 字段名只能包含字母、数字、下划线和中文字符
    pattern = r'^[a-zA-Z_\u4e00-\u9fa5][a-zA-Z0-9_\u4e00-\u9fa5]*$'
    return bool(re.match(pattern, field_name))


def is_valid_table_name(table_name: str) -> bool:
    """
    检查表名是否有效
    
    Args:
        table_name: 表名
        
    Returns:
        是否有效
    """
    # 表名只能包含字母、数字、下划线
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
    return bool(re.match(pattern, table_name))


def is_valid_sql_expression(expression: str) -> bool:
    """
    检查 SQL 表达式是否安全
    
    Args:
        expression: SQL 表达式
        
    Returns:
        是否安全
    """
    # 禁止的关键词（防止 SQL 注入）
    forbidden_keywords = [
        "DROP", "DELETE", "UPDATE", "INSERT", "CREATE", "ALTER", 
        "TRUNCATE", "EXEC", "EXECUTE", "UNION", "SCRIPT"
    ]
    
    expression_upper = expression.upper()
    
    for keyword in forbidden_keywords:
        if keyword in expression_upper:
            return False
    
    return True


def validate_sql_file(sql_content: str) -> Dict[str, Any]:
    """
    验证 SQL 文件内容
    
    Args:
        sql_content: SQL 文件内容
        
    Returns:
        验证结果
    """
    errors = []
    warnings = []
    
    # 检查是否包含 SELECT 语句
    if "SELECT" not in sql_content.upper():
        errors.append("SQL 文件必须包含 SELECT 语句")
    
    # 检查是否包含危险操作
    dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER"]
    for keyword in dangerous_keywords:
        if keyword in sql_content.upper():
            errors.append(f"SQL 文件不能包含危险操作: {keyword}")
    
    # 检查是否使用了参数占位符
    if ":last_update_time" not in sql_content and "增量" in sql_content:
        warnings.append("增量更新 SQL 建议使用 :last_update_time 参数")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }