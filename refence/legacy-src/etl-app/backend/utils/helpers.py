"""
辅助工具函数
"""
import json
import re
from typing import Any, Dict, List, Optional
from datetime import datetime


def format_sql(sql: str) -> str:
    """
    格式化 SQL 语句
    
    Args:
        sql: 原始 SQL 语句
        
    Returns:
        格式化后的 SQL
    """
    # 移除多余的空白字符
    sql = re.sub(r'\s+', ' ', sql.strip())
    
    # 在关键词前后添加换行
    keywords = ['SELECT', 'FROM', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY', 'LIMIT']
    
    for keyword in keywords:
        sql = re.sub(f'\\b{keyword}\\b', f'\n{keyword}', sql, flags=re.IGNORECASE)
    
    # 清理多余的换行
    sql = re.sub(r'\n+', '\n', sql)
    
    return sql.strip()


def parse_json_field(json_str: Optional[str]) -> List[Any]:
    """
    解析 JSON 字段
    
    Args:
        json_str: JSON 字符串
        
    Returns:
        解析后的列表，解析失败返回空列表
    """
    if not json_str:
        return []
    
    try:
        result = json.loads(json_str)
        return result if isinstance(result, list) else [result]
    except (json.JSONDecodeError, TypeError):
        return []


def serialize_json_field(data: List[Any]) -> str:
    """
    序列化为 JSON 字段
    
    Args:
        data: 要序列化的数据
        
    Returns:
        JSON 字符串
    """
    try:
        return json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError):
        return "[]"


def generate_unique_name(base_name: str, existing_names: List[str]) -> str:
    """
    生成唯一名称
    
    Args:
        base_name: 基础名称
        existing_names: 已存在的名称列表
        
    Returns:
        唯一名称
    """
    if base_name not in existing_names:
        return base_name
    
    counter = 1
    while f"{base_name}_{counter}" in existing_names:
        counter += 1
    
    return f"{base_name}_{counter}"


def convert_field_type(mysql_type: str) -> str:
    """
    转换 MySQL 字段类型为标准类型
    
    Args:
        mysql_type: MySQL 字段类型
        
    Returns:
        标准字段类型
    """
    mysql_type = mysql_type.lower()
    
    if mysql_type in ['varchar', 'char', 'text', 'longtext', 'mediumtext', 'tinytext']:
        return 'string'
    elif mysql_type in ['int', 'bigint', 'smallint', 'tinyint', 'mediumint']:
        return 'integer'
    elif mysql_type in ['float', 'double', 'decimal', 'numeric']:
        return 'float'
    elif mysql_type in ['datetime', 'timestamp', 'date', 'time']:
        return 'datetime'
    elif mysql_type in ['boolean', 'bool']:
        return 'boolean'
    else:
        return 'string'


def clean_sql_comments(sql: str) -> str:
    """
    清理 SQL 注释
    
    Args:
        sql: 包含注释的 SQL
        
    Returns:
        清理后的 SQL
    """
    # 移除单行注释 --
    sql = re.sub(r'--.*$', '', sql, flags=re.MULTILINE)
    
    # 移除多行注释 /* */
    sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
    
    # 清理多余的空白
    sql = re.sub(r'\s+', ' ', sql.strip())
    
    return sql


def validate_cron_expression(cron_expr: str) -> bool:
    """
    验证 cron 表达式格式
    
    Args:
        cron_expr: cron 表达式
        
    Returns:
        是否有效
    """
    # 简单的 cron 表达式验证（分 时 日 月 周）
    parts = cron_expr.split()
    
    if len(parts) != 5:
        return False
    
    # 每个部分的有效范围
    ranges = [
        (0, 59),   # 分钟
        (0, 23),   # 小时
        (1, 31),   # 日
        (1, 12),   # 月
        (0, 7)     # 周（0和7都表示周日）
    ]
    
    for i, part in enumerate(parts):
        if part == '*':
            continue
        
        # 检查数字范围
        if part.isdigit():
            num = int(part)
            min_val, max_val = ranges[i]
            if not (min_val <= num <= max_val):
                return False
        
        # 检查步长表达式 */n
        elif part.startswith('*/'):
            try:
                step = int(part[2:])
                if step <= 0:
                    return False
            except ValueError:
                return False
        
        # 检查范围表达式 n-m
        elif '-' in part:
            try:
                start, end = map(int, part.split('-'))
                min_val, max_val = ranges[i]
                if not (min_val <= start <= end <= max_val):
                    return False
            except ValueError:
                return False
        
        # 检查列表表达式 n,m,k
        elif ',' in part:
            try:
                nums = list(map(int, part.split(',')))
                min_val, max_val = ranges[i]
                for num in nums:
                    if not (min_val <= num <= max_val):
                        return False
            except ValueError:
                return False
        
        else:
            return False
    
    return True


def format_duration(seconds: float) -> str:
    """
    格式化执行时长
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化的时长字符串
    """
    if seconds < 1:
        return f"{seconds*1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m{secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h{minutes}m"


def get_current_timestamp() -> str:
    """
    获取当前时间戳字符串（东八区）
    
    Returns:
        格式化的时间戳
    """
    from backend.core.logger import CHINA_TZ
    return datetime.now(CHINA_TZ).strftime("%Y-%m-%d %H:%M:%S")