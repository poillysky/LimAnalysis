"""
SQL 公式助手 API
提供 SQL 函数模板、字段验证等功能
"""
import re
from fastapi import APIRouter, HTTPException
from backend.config import get_config_manager

router = APIRouter()


# SQL 函数模板库
SQL_TEMPLATES = {
    "string": [
        {
            "name": "字符串截取",
            "template": "SUBSTRING(`field`, start, length)",
            "description": "从字符串中提取子串",
            "example": "SUBSTRING(`SN`, 1, 3)"
        },
        {
            "name": "字符串拼接",
            "template": "CONCAT(`field1`, ' ', `field2`)",
            "description": "连接多个字符串",
            "example": "CONCAT(`first_name`, ' ', `last_name`)"
        },
        {
            "name": "字符串替换",
            "template": "REPLACE(`field`, 'old', 'new')",
            "description": "替换字符串中的内容",
            "example": "REPLACE(`text`, 'old', 'new')"
        },
        {
            "name": "转大写",
            "template": "UPPER(`field`)",
            "description": "将字符串转为大写",
            "example": "UPPER(`name`)"
        },
        {
            "name": "转小写",
            "template": "LOWER(`field`)",
            "description": "将字符串转为小写",
            "example": "LOWER(`name`)"
        },
        {
            "name": "去空格",
            "template": "TRIM(`field`)",
            "description": "去除字符串首尾空格",
            "example": "TRIM(`text`)"
        },
        {
            "name": "字符串长度",
            "template": "LENGTH(`field`)",
            "description": "获取字符串长度",
            "example": "LENGTH(`SN`)"
        }
    ],
    
    "number": [
        {
            "name": "四舍五入",
            "template": "ROUND(`field`, 2)",
            "description": "四舍五入到指定小数位",
            "example": "ROUND(`price`, 2)"
        },
        {
            "name": "向上取整",
            "template": "CEIL(`field`)",
            "description": "向上取整",
            "example": "CEIL(`value`)"
        },
        {
            "name": "向下取整",
            "template": "FLOOR(`field`)",
            "description": "向下取整",
            "example": "FLOOR(`value`)"
        },
        {
            "name": "绝对值",
            "template": "ABS(`field`)",
            "description": "获取绝对值",
            "example": "ABS(`difference`)"
        },
        {
            "name": "数学运算",
            "template": "`field1` * `field2`",
            "description": "数学计算（+、-、*、/）",
            "example": "`price` * `quantity`"
        }
    ],
    
    "datetime": [
        {
            "name": "日期格式化",
            "template": "DATE_FORMAT(`field`, '%Y-%m-%d')",
            "description": "格式化日期时间",
            "example": "DATE_FORMAT(`upload_time`, '%Y-%m-%d')"
        },
        {
            "name": "提取年份",
            "template": "YEAR(`field`)",
            "description": "提取年份",
            "example": "YEAR(`upload_time`)"
        },
        {
            "name": "提取月份",
            "template": "MONTH(`field`)",
            "description": "提取月份",
            "example": "MONTH(`upload_time`)"
        },
        {
            "name": "提取日期",
            "template": "DATE(`field`)",
            "description": "提取日期部分",
            "example": "DATE(`upload_time`)"
        },
        {
            "name": "日期差",
            "template": "DATEDIFF(`field1`, `field2`)",
            "description": "计算两个日期的天数差",
            "example": "DATEDIFF(`end_date`, `start_date`)"
        },
        {
            "name": "当前时间",
            "template": "NOW()",
            "description": "获取当前日期时间",
            "example": "NOW()"
        }
    ],
    
    "condition": [
        {
            "name": "条件判断",
            "template": "CASE WHEN `field` = 'value' THEN 'result1' ELSE 'result2' END",
            "description": "根据条件返回不同值",
            "example": "CASE WHEN `status` = 'OK' THEN 1 ELSE 0 END"
        },
        {
            "name": "空值处理",
            "template": "COALESCE(`field`, 'default')",
            "description": "如果字段为空则返回默认值",
            "example": "COALESCE(`value`, 0)"
        },
        {
            "name": "IF 判断",
            "template": "IF(`field` > 0, 'positive', 'negative')",
            "description": "简单的条件判断",
            "example": "IF(`quantity` > 0, '有货', '缺货')"
        },
        {
            "name": "空值判断",
            "template": "IFNULL(`field`, 'default')",
            "description": "如果为 NULL 则返回默认值",
            "example": "IFNULL(`comment`, '无备注')"
        }
    ]
}


@router.get("/formula/templates")
async def get_formula_templates():
    """
    获取 SQL 函数模板库
    
    Returns:
        按类别分组的 SQL 函数模板
    """
    return {
        "code": 0,
        "message": "success",
        "data": SQL_TEMPLATES
    }


@router.post("/models/{model_id}/validate-formula")
async def validate_formula(model_id: int, formula_data: dict):
    """
    验证 SQL 公式
    
    Args:
        model_id: 模型 ID
        formula_data: {
            "formula": "SQL 表达式",
            "derive_level": 派生层级 (1 或 2)
        }
    
    Returns:
        {
            "valid": 是否有效,
            "error": 错误信息,
            "invalid_fields": 无效字段列表,
            "available_fields": 可用字段列表,
            "suggestions": 修正建议
        }
    """
    try:
        formula = formula_data.get('formula', '')
        derive_level = formula_data.get('derive_level', 1)
        
        if not formula or not formula.strip():
            return {
                "code": 1,
                "message": "公式不能为空",
                "data": {
                    "valid": False,
                    "error": "公式不能为空"
                }
            }
        
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField, ETLSourceField
            
            # 获取模型信息
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 1. 获取可用字段列表
            available_fields = set()
            
            # 1.1 源表字段
            source_fields = session.query(ETLSourceField).filter(
                ETLSourceField.model_id == model_id
            ).all()
            for sf in source_fields:
                available_fields.add(sf.field_name)
            
            # 1.2 如果是 Level 2，还可以使用 Level 1 的派生字段
            if derive_level == 2:
                level1_fields = session.query(ETLModelField).filter(
                    ETLModelField.model_id == model_id,
                    ETLModelField.derive_level == 1
                ).all()
                for f in level1_fields:
                    available_fields.add(f.target_field)
            
            # 2. 提取公式中引用的字段
            referenced_fields = extract_field_references(formula)
            
            # 3. 检查无效字段
            invalid_fields = [f for f in referenced_fields if f not in available_fields]
            
            # 4. 生成修正建议
            suggestions = []
            if invalid_fields:
                for field in invalid_fields:
                    similar = find_similar_field(field, available_fields)
                    if similar:
                        suggestions.append(f"字段 `{field}` 不存在，你是否想用 `{similar}`？")
                    else:
                        suggestions.append(f"字段 `{field}` 不存在")
            
            # 5. 基本语法检查
            syntax_error = check_basic_syntax(formula)
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "valid": len(invalid_fields) == 0 and syntax_error is None,
                    "error": syntax_error,
                    "invalid_fields": invalid_fields,
                    "available_fields": sorted(list(available_fields)),
                    "suggestions": suggestions
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        return {
            "code": 1,
            "message": f"验证失败: {str(e)}",
            "data": {
                "valid": False,
                "error": str(e)
            }
        }


def extract_field_references(formula: str) -> list:
    """
    从 SQL 公式中提取字段引用
    
    匹配模式：`field_name`
    """
    pattern = r'`([^`]+)`'
    matches = re.findall(pattern, formula)
    return list(set(matches))  # 去重


def find_similar_field(field: str, available_fields: set) -> str:
    """
    查找相似的字段名（简单的字符串相似度）
    """
    field_lower = field.lower()
    
    # 1. 精确匹配（忽略大小写）
    for af in available_fields:
        if af.lower() == field_lower:
            return af
    
    # 2. 包含匹配
    for af in available_fields:
        if field_lower in af.lower() or af.lower() in field_lower:
            return af
    
    # 3. 前缀匹配
    for af in available_fields:
        if af.lower().startswith(field_lower[:3]) or field_lower.startswith(af.lower()[:3]):
            return af
    
    return None


def check_basic_syntax(formula: str) -> str:
    """
    基本的 SQL 语法检查
    
    Returns:
        错误信息，如果没有错误则返回 None
    """
    # 1. 检查括号匹配
    if formula.count('(') != formula.count(')'):
        return "括号不匹配"
    
    # 2. 检查引号匹配
    single_quotes = formula.count("'")
    if single_quotes % 2 != 0:
        return "单引号不匹配"
    
    double_quotes = formula.count('"')
    if double_quotes % 2 != 0:
        return "双引号不匹配"
    
    # 3. 检查反引号匹配
    backticks = formula.count('`')
    if backticks % 2 != 0:
        return "反引号不匹配"
    
    # 4. 检查是否为空
    if not formula.strip():
        return "公式不能为空"
    
    return None
