"""
ETL 字段配置 API
"""
import os
from fastapi import APIRouter, HTTPException
from backend.config import get_config_manager

router = APIRouter()


@router.get("/models/{model_id}/source-fields")
async def get_source_fields(model_id: int):
    """获取源表字段"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLSourceField
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 从 etl_source_fields 表读取
            source_fields = session.query(ETLSourceField).filter(
                ETLSourceField.model_id == model_id
            ).all()
            
            fields = [
                {
                    "field_name": sf.field_name,
                    "field_type": sf.field_type or "文本",
                    "field_category": sf.field_category or "文本",  # ✅ 添加 field_category
                    "nullable": sf.nullable if hasattr(sf, 'nullable') else True,
                    "default_value": sf.default_value if hasattr(sf, 'default_value') else None,
                    "comment": sf.comment if hasattr(sf, 'comment') else "",
                    "is_selected": sf.is_selected if hasattr(sf, 'is_selected') else True
                }
                for sf in source_fields
            ]
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "fields": fields
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取源表字段失败: {str(e)}")


@router.get("/models/{model_id}/fields")
async def get_model_fields(model_id: int):
    """获取模型字段配置"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 从 etl_model_fields 表读取
            model_fields = session.query(ETLModelField).filter(
                ETLModelField.model_id == model_id
            ).order_by(ETLModelField.sort_order, ETLModelField.id).all()
            
            fields = []
            for mf in model_fields:
                fields.append({
                    "target_field": mf.target_field,
                    "source_field": mf.source_field or '',
                    "mapping_type": mf.mapping_type,
                    "derive_level": mf.derive_level,
                    "formula": mf.formula or '',
                    "constant_value": mf.constant_value or '',
                    "field_type": mf.field_type,
                    "field_category": mf.field_category or '',  # 新增：字段类别
                    "aggregate_func": mf.aggregate_func or ''   # 新增：聚合函数
                })
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "fields": fields
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型字段失败: {str(e)}")


@router.post("/models/{model_id}/fields")
async def save_fields(model_id: int, fields_data: dict):
    """保存字段配置"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 删除旧的字段配置
            session.query(ETLModelField).filter(ETLModelField.model_id == model_id).delete()
            
            # 保存新的字段配置
            fields = fields_data.get('fields', [])
            
            # 调试：打印接收到的数据
            print("\n" + "=" * 80)
            print(f"📥 接收到保存字段请求 - 模型 ID: {model_id}")
            print(f"📊 共 {len(fields)} 个字段")
            print("=" * 80)
            
            for idx, field in enumerate(fields):
                # 兼容 camelCase 和 snake_case
                target_field = field.get('target_field') or field.get('targetField', '')
                mapping_type = field.get('mapping_type') or field.get('mappingType', 'derived')
                derive_level = field.get('derive_level') or field.get('deriveLevel', 1)
                formula = field.get('formula', '')
                field_type = field.get('field_type') or field.get('fieldType', '文本')
                
                # 获取 source_field 和 constant_value（新格式）
                source_field = field.get('source_field') or field.get('sourceField', '')
                constant_value = field.get('constant_value') or field.get('constantValue', '')
                
                # 获取分析表字段配置
                field_category = field.get('field_category') or field.get('fieldCategory', '')
                aggregate_func = field.get('aggregate_func') or field.get('aggregateFunc', '')
                
                # 调试：打印每个字段的数据
                print(f"\n字段 {idx + 1}: {target_field}")
                print(f"  mapping_type: {mapping_type}")
                print(f"  source_field: '{source_field}'")
                print(f"  formula: '{formula}'")
                print(f"  constant_value: '{constant_value}'")
                print(f"  field_type: {field_type}")
                print(f"  derive_level: {derive_level}")
                print(f"  field_category: '{field_category}'")
                print(f"  aggregate_func: '{aggregate_func}'")
                
                model_field = ETLModelField(
                    model_id=model_id,
                    source_field=source_field,  # 使用正确的 source_field
                    target_field=target_field,
                    field_type=field_type,
                    mapping_type=mapping_type,
                    derive_level=derive_level,
                    formula=formula,
                    constant_value=constant_value,  # 保存 constant_value
                    field_category=field_category,  # 保存字段类别
                    aggregate_func=aggregate_func,  # 保存聚合函数
                    sort_order=idx
                )
                session.add(model_field)
            
            session.commit()
            
            # ========== 生成 SQL 文件 ==========
            try:
                from backend.core.sql_generator import SqlGenerator
                import json
                
                # 准备字段数据（兼容 camelCase 和 snake_case）
                fields_for_sql = []
                for field in fields:
                    target_field = field.get('target_field') or field.get('targetField', '')
                    mapping_type = field.get('mapping_type') or field.get('mappingType', 'derived')
                    derive_level = field.get('derive_level') or field.get('deriveLevel', 1)
                    formula = field.get('formula', '')
                    field_type = field.get('field_type') or field.get('fieldType', '文本')
                    source_field = field.get('source_field') or field.get('sourceField', '')
                    constant_value = field.get('constant_value') or field.get('constantValue', '')
                    field_category = field.get('field_category') or field.get('fieldCategory', '')
                    aggregate_func = field.get('aggregate_func') or field.get('aggregateFunc', '')
                    
                    fields_for_sql.append({
                        'target_field': target_field,
                        'mapping_type': mapping_type,
                        'derive_level': derive_level,
                        'formula': formula,
                        'field_type': field_type,
                        'source_field': source_field,
                        'constant_value': constant_value,
                        'field_category': field_category,
                        'aggregate_func': aggregate_func
                    })
                
                # 解析唯一键配置
                unique_keys = []
                if model.unique_keys:
                    try:
                        unique_keys = json.loads(model.unique_keys)
                    except:
                        unique_keys = []
                
                # 生成 SQL 文件
                sql_generator = SqlGenerator()
                
                if model.model_type == 'link':
                    sql_path = sql_generator.generate_link_model_sql(
                        model_name=model.name,
                        table_name=model.table_name,
                        source_table=model.source_table,
                        source_database=model.source_database,
                        target_database=model.target_database,
                        fields=fields_for_sql,
                        unique_key_type=model.unique_key_type or 'none',
                        unique_key=model.unique_key or None,
                        unique_keys=unique_keys,
                        description=model.description or '',
                        project_name='default',
                        view_time_field=model.view_time_field or None
                    )
                    
                    # 更新模型的 sql_path 和草稿状态
                    model.sql_path = sql_path
                    model.is_draft = False  # 标记为非草稿
                    session.commit()
                    
                    print(f"✅ SQL 文件已生成: {sql_path}")
                    print(f"✅ 模型已标记为非草稿状态")
                
                elif model.model_type == 'analysis':
                    # 生成分析表 SQL
                    sql_path = sql_generator.generate_analysis_model_sql(
                        model_name=model.name,
                        table_name=model.table_name,
                        source_table=model.source_table,
                        source_database=model.source_database,
                        target_database=model.target_database,
                        time_field=model.time_field or 'ServerTime',
                        granularity=model.granularity or 'hour',
                        time_field_name=model.time_field_name or 'hour',
                        fields=fields_for_sql,
                        description=model.description or '',
                        project_name='default'
                    )
                    
                    # 更新模型的 sql_path 和草稿状态
                    model.sql_path = sql_path
                    model.is_draft = False
                    session.commit()
                    
                    print(f"✅ 分析表 SQL 文件已生成: {sql_path}")
                    print(f"✅ 模型已标记为非草稿状态")
                
            except Exception as sql_error:
                print(f"⚠️  生成 SQL 文件失败: {sql_error}")
                # 不影响字段保存，只记录错误
            
            # ========== 自动创建唯一索引 ==========
            try:
                unique_key_type = model.unique_key_type or 'none'
                
                if unique_key_type != 'none':
                    print(f"🔧 检测到唯一键配置，准备创建唯一索引...")
                    
                    # 获取 MySQL 配置
                    from backend.models.etl_config import MySQLConfig
                    import pymysql
                    from cryptography.fernet import Fernet
                    
                    mysql_config = session.query(MySQLConfig).first()
                    if not mysql_config:
                        print(f"⚠️  未找到 MySQL 配置，跳过创建唯一索引")
                    else:
                        # 解密密码
                        encryption_key = os.getenv("ENCRYPTION_KEY")
                        if encryption_key and mysql_config.password:
                            try:
                                cipher = Fernet(encryption_key.encode())
                                password = cipher.decrypt(mysql_config.password.encode()).decode()
                            except:
                                password = mysql_config.password
                        else:
                            password = mysql_config.password
                        
                        # 连接到目标数据库
                        target_database = model.target_database or 'link_db'
                        connection = pymysql.connect(
                            host=mysql_config.host,
                            port=mysql_config.port,
                            user=mysql_config.username,
                            password=password,
                            database=target_database,
                            charset='utf8mb4'
                        )
                        
                        try:
                            with connection.cursor() as cursor:
                                table_name = model.table_name
                                
                                # 构建索引名称和字段列表
                                if unique_key_type == 'single':
                                    # 单字段唯一键
                                    unique_key = model.unique_key
                                    index_name = f"uk_{table_name}_{unique_key}"
                                    index_fields = f"`{unique_key}`"
                                    
                                elif unique_key_type == 'composite':
                                    # 复合唯一键
                                    unique_keys_list = []
                                    if model.unique_keys:
                                        try:
                                            unique_keys_list = json.loads(model.unique_keys)
                                        except:
                                            unique_keys_list = []
                                    
                                    if not unique_keys_list:
                                        print(f"⚠️  复合唯一键配置为空，跳过创建索引")
                                        raise Exception("复合唯一键配置为空")
                                    
                                    index_name = f"uk_{table_name}_composite"
                                    index_fields = ', '.join([f"`{key}`" for key in unique_keys_list])
                                
                                else:
                                    print(f"⚠️  未知的唯一键类型: {unique_key_type}")
                                    raise Exception(f"未知的唯一键类型: {unique_key_type}")
                                
                                # 检查索引是否已存在
                                check_sql = f"""
                                    SELECT COUNT(*) as count
                                    FROM information_schema.statistics
                                    WHERE table_schema = '{target_database}'
                                    AND table_name = '{table_name}'
                                    AND index_name = '{index_name}'
                                """
                                cursor.execute(check_sql)
                                result = cursor.fetchone()
                                
                                if result and result[0] > 0:
                                    print(f"✅ 唯一索引已存在: {index_name}")
                                else:
                                    # 创建唯一索引
                                    create_index_sql = f"""
                                        ALTER TABLE `{target_database}`.`{table_name}`
                                        ADD UNIQUE KEY `{index_name}` ({index_fields})
                                    """
                                    
                                    print(f"🔧 创建唯一索引: {index_name}")
                                    print(f"   字段: {index_fields}")
                                    
                                    cursor.execute(create_index_sql)
                                    connection.commit()
                                    
                                    print(f"✅ 唯一索引创建成功: {index_name}")
                        
                        finally:
                            connection.close()
                
            except Exception as index_error:
                print(f"⚠️  创建唯一索引失败: {index_error}")
                # 不影响字段保存，只记录错误
            
            return {
                "code": 0,
                "message": "字段配置保存成功",
                "data": None
            }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"保存字段配置失败: {str(e)}")


@router.post("/models/{model_id}/validate-formula")
async def validate_formula(model_id: int, formula_data: dict):
    """校验公式"""
    try:
        formula = formula_data.get('formula', '')
        derive_level = formula_data.get('derive_level', 1)
        
        if not formula:
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "valid": False,
                    "message": "公式不能为空"
                }
            }
        
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLSourceField, ETLModelField
            
            # 获取模型信息
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "valid": False,
                        "message": "模型不存在"
                    }
                }
            
            # 获取可用字段列表
            available_fields = set()
            
            # 1. 源表字段（层级0）
            source_fields = session.query(ETLSourceField).filter(
                ETLSourceField.model_id == model_id
            ).all()
            for sf in source_fields:
                available_fields.add(sf.field_name)
            
            # 2. 如果是层级2，还可以使用层级1的字段
            if derive_level == 2:
                level1_fields = session.query(ETLModelField).filter(
                    ETLModelField.model_id == model_id,
                    ETLModelField.derive_level == 1
                ).all()
                for f in level1_fields:
                    available_fields.add(f.target_field)
            
            # 检查公式中引用的字段是否存在
            import re
            # 匹配反引号包裹的字段名：`field_name`
            field_pattern = r'`([^`]+)`'
            referenced_fields = re.findall(field_pattern, formula)
            
            # 检查每个引用的字段是否存在
            invalid_fields = []
            for field in referenced_fields:
                if field not in available_fields:
                    invalid_fields.append(field)
            
            if invalid_fields:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "valid": False,
                        "message": f"字段不存在: {', '.join(invalid_fields)}"
                    }
                }
            
            # 基本语法检查
            formula_upper = formula.upper()
            
            # 检查括号是否匹配
            if formula.count('(') != formula.count(')'):
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "valid": False,
                        "message": "括号不匹配"
                    }
                }
            
            # 检查引号是否匹配
            single_quotes = formula.count("'")
            if single_quotes % 2 != 0:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "valid": False,
                        "message": "单引号不匹配"
                    }
                }
            
            # 通过所有检查
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "valid": True,
                    "message": "公式语法正确"
                }
            }
            
    except Exception as e:
        return {
            "code": 0,
            "message": "success",
            "data": {
                "valid": False,
                "message": f"公式校验失败: {str(e)}"
            }
        }


@router.post("/models/{model_id}/preview")
async def preview_model_data(model_id: int, preview_params: dict):
    """预览模型数据"""
    try:
        limit = preview_params.get('limit', 100)
        
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField, ETLSourceField
            from backend.models.etl_config import MySQLConfig
            import pymysql
            from decimal import Decimal
            from datetime import datetime
            import os
            
            # 获取模型信息
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 检查必要字段
            if not model.source_database:
                raise HTTPException(status_code=400, detail="模型未配置源数据库")
            if not model.source_table:
                raise HTTPException(status_code=400, detail="模型未配置源表")
            
            # 获取字段配置
            model_fields = session.query(ETLModelField).filter(
                ETLModelField.model_id == model_id
            ).order_by(ETLModelField.sort_order, ETLModelField.id).all()
            
            if not model_fields:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "columns": [],
                        "rows": []
                    }
                }
            
            # 获取 MySQL 配置
            mysql_config = session.query(MySQLConfig).first()
            if not mysql_config:
                raise HTTPException(status_code=400, detail="未找到 MySQL 配置")
            
            # 解密密码
            from cryptography.fernet import Fernet
            encryption_key = os.getenv("ENCRYPTION_KEY")
            if encryption_key and mysql_config.password:
                try:
                    cipher = Fernet(encryption_key.encode())
                    password = cipher.decrypt(mysql_config.password.encode()).decode()
                except:
                    password = mysql_config.password
            else:
                password = mysql_config.password
            
            # 根据模型类型选择不同的预览逻辑
            if model.model_type == 'analysis':
                # 分析表预览：执行聚合查询
                return await preview_analysis_model(model, model_fields, limit, mysql_config, password)
            else:
                # 关联表预览：执行普通查询
                return await preview_link_model(model, model_fields, limit, mysql_config, password)
                
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"预览数据失败: {str(e)}")


async def preview_link_model(model, model_fields, limit, mysql_config, password):
    """预览关联表模型数据"""
    import pymysql
    from decimal import Decimal
    from datetime import datetime
    
    # 连接数据库
    connection = pymysql.connect(
        host=mysql_config.host,
        port=mysql_config.port,
        user=mysql_config.username,
        password=password,
        database=model.source_database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    # 检查表是否存在
    try:
        with connection.cursor() as check_cursor:
            check_cursor.execute(f"SHOW TABLES LIKE '{model.source_table}'")
            table_exists = check_cursor.fetchone()
            
            if not table_exists:
                raise HTTPException(
                    status_code=404, 
                    detail=f"表 '{model.source_database}.{model.source_table}' 不存在。请检查源表配置。"
                )
    except HTTPException:
        raise
    except Exception as check_error:
        pass
    
    try:
        # 按层级分组字段
        fields_by_level = {1: [], 2: []}
        for field in model_fields:
            fields_by_level[field.derive_level].append(field)
        
        # 生成 SQL
        # 如果只有层级1，直接查询
        if not fields_by_level[2]:
            # 构建 SELECT 子句
            select_parts = []
            for field in fields_by_level[1]:
                if field.mapping_type == 'direct':
                    # 直接映射：使用 source_field（新格式）
                    source_field_name = field.source_field if field.source_field and field.source_field.strip() else field.target_field
                    source_field_name = source_field_name.strip().strip('`')
                    
                    if source_field_name == field.target_field:
                        select_parts.append(f"`{source_field_name}`")
                    else:
                        select_parts.append(f"`{source_field_name}` AS `{field.target_field}`")
                
                elif field.mapping_type == 'derived':
                    # 派生字段：使用 formula
                    formula = field.formula.replace('[', '`').replace(']', '`')
                    formula = formula.replace('【', '`').replace('】', '`')
                    select_parts.append(f"{formula} AS `{field.target_field}`")
                
                elif field.mapping_type == 'constant':
                    # 固定值：使用 constant_value
                    constant_value = field.constant_value if field.constant_value else ''
                    select_parts.append(f"'{constant_value}' AS `{field.target_field}`")
            
            sql = f"""
SELECT {', '.join(select_parts)}
FROM `{model.source_database}`.`{model.source_table}`
LIMIT {limit}
"""
        else:
            # 使用 CTE 处理多层派生
            # 层级1
            level1_selects = []
            for field in fields_by_level[1]:
                if field.mapping_type == 'direct':
                    # 直接映射：使用 source_field（新格式）
                    source_field_name = field.source_field if field.source_field and field.source_field.strip() else field.target_field
                    source_field_name = source_field_name.strip().strip('`')
                    
                    if source_field_name == field.target_field:
                        level1_selects.append(f"`{source_field_name}`")
                    else:
                        level1_selects.append(f"`{source_field_name}` AS `{field.target_field}`")
                
                elif field.mapping_type == 'derived':
                    # 派生字段：使用 formula
                    formula = field.formula.replace('[', '`').replace(']', '`')
                    formula = formula.replace('【', '`').replace('】', '`')
                    level1_selects.append(f"{formula} AS `{field.target_field}`")
                
                elif field.mapping_type == 'constant':
                    # 固定值：使用 constant_value
                    constant_value = field.constant_value if field.constant_value else ''
                    level1_selects.append(f"'{constant_value}' AS `{field.target_field}`")
            
            # 层级2
            level2_selects = ['*']  # 保留层级1的所有字段
            for field in fields_by_level[2]:
                formula = field.formula.replace('[', '`').replace(']', '`')
                formula = formula.replace('【', '`').replace('】', '`')
                level2_selects.append(f"{formula} AS `{field.target_field}`")
            
            sql = f"""
WITH level1 AS (
  SELECT {', '.join(level1_selects)}
  FROM `{model.source_database}`.`{model.source_table}`
  LIMIT {limit}
)
SELECT {', '.join(level2_selects)}
FROM level1
"""
        
        # 执行查询
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            if not rows:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "columns": [],
                        "rows": []
                    }
                }
            
            # 获取列名
            columns = list(rows[0].keys())
            
            # 获取字段类型映射（用于百分比格式化）
            field_type_map = {}
            for field in model_fields:
                field_type_map[field.target_field] = field.field_type
            
            # 转换数据类型
            result_rows = []
            for row in rows:
                row_dict = {}
                for col in columns:
                    value = row[col]
                    # 处理特殊类型
                    if value is None:
                        row_dict[col] = None
                    elif isinstance(value, datetime):
                        row_dict[col] = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, Decimal):
                        # 检查是否为百分比类型
                        if field_type_map.get(col) == '百分比':
                            row_dict[col] = f"{float(value) * 100:.2f}%"
                        else:
                            row_dict[col] = float(value)
                    elif isinstance(value, (int, float)):
                        # 检查是否为百分比类型
                        if field_type_map.get(col) == '百分比':
                            row_dict[col] = f"{float(value) * 100:.2f}%"
                        else:
                            row_dict[col] = value
                    elif isinstance(value, bytes):
                        row_dict[col] = value.decode('utf-8', errors='ignore')
                    else:
                        row_dict[col] = value
                result_rows.append(row_dict)
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "columns": columns,
                    "rows": result_rows
                }
            }
    finally:
        connection.close()


async def preview_analysis_model(model, model_fields, limit, mysql_config, password):
    """预览分析表模型数据（执行聚合查询）"""
    import pymysql
    from decimal import Decimal
    from datetime import datetime
    
    # 连接数据库
    connection = pymysql.connect(
        host=mysql_config.host,
        port=mysql_config.port,
        user=mysql_config.username,
        password=password,
        database=model.source_database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )
    
    try:
        # 按字段类别分组
        dimension_fields = []
        measure_fields = []
        derived_fields = []
        
        for field in model_fields:
            category = field.field_category or ''
            derive_level = field.derive_level or 1
            
            if derive_level == 1:
                if category == 'dimension':
                    dimension_fields.append(field)
                elif category == 'measure':
                    measure_fields.append(field)
            elif derive_level == 2:
                if category == 'derived':
                    derived_fields.append(field)
        
        # 判断是否需要使用 CTE
        use_cte = len(derived_fields) > 0
        
        # 构建聚合查询
        select_parts = []
        group_by_parts = []
        
        # 1. 时间维度字段
        time_field = model.time_field or 'ServerTime'
        granularity = model.granularity or 'hour'
        time_field_name = model.time_field_name or 'hour'
        
        if granularity == 'hour':
            time_expr = f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d %H:00:00')"
        elif granularity == 'day':
            time_expr = f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d')"
        elif granularity == 'week':
            time_expr = f"DATE_FORMAT(`{time_field}`, '%Y-%u')"
        elif granularity == 'month':
            time_expr = f"DATE_FORMAT(`{time_field}`, '%Y-%m')"
        else:
            time_expr = f"DATE_FORMAT(`{time_field}`, '%Y-%m-%d %H:00:00')"
        
        select_parts.append(f"{time_expr} AS `{time_field_name}`")
        group_by_parts.append(time_expr)
        
        # 2. 维度字段
        for dim in dimension_fields:
            source = dim.source_field
            target = dim.target_field
            if source and target:
                select_parts.append(f"`{source}` AS `{target}`")
                group_by_parts.append(f"`{source}`")
        
        # 3. 度量字段
        for measure in measure_fields:
            source = measure.source_field
            target = measure.target_field
            func = measure.aggregate_func or 'SUM'
            
            if func == 'COUNT' and (not source or source == '*'):
                select_parts.append(f"COUNT(*) AS `{target}`")
            else:
                select_parts.append(f"{func}(`{source}`) AS `{target}`")
        
        # 构建 SQL
        # 预览策略：查询数据库中最近一个时间段的数据
        # 1. 先找到最新的时间
        # 2. 根据聚合细度计算时间范围
        # 3. 查询该时间范围的聚合数据
        
        if not use_cte:
            # 没有派生字段
            # 根据聚合细度确定时间范围
            if granularity == 'hour':
                time_range = "1 HOUR"
            elif granularity == 'day':
                time_range = "1 DAY"
            elif granularity == 'week':
                time_range = "7 DAY"
            elif granularity == 'month':
                time_range = "30 DAY"
            else:
                time_range = "1 HOUR"
            
            # 使用子查询获取最新时间，然后查询该时间段的数据
            sql = f"""
SELECT {', '.join(select_parts)}
FROM `{model.source_database}`.`{model.source_table}`
WHERE `{time_field}` >= (
    SELECT DATE_SUB(MAX(`{time_field}`), INTERVAL {time_range})
    FROM `{model.source_database}`.`{model.source_table}`
)
GROUP BY {', '.join(group_by_parts)}
ORDER BY `{time_field_name}` DESC
LIMIT {limit}
"""
            
            # 打印生成的 SQL（调试用）
            print("\n" + "=" * 80)
            print("🔍 分析表预览 SQL:")
            print(sql)
            print("=" * 80 + "\n")
            
        else:
            # 有派生字段，使用 CTE
            derived_select_parts = ['*']
            for derived in derived_fields:
                formula = derived.formula or ''
                target = derived.target_field
                
                if formula and target:
                    # 处理公式中的字段引用
                    processed_formula = formula.replace('[', '`').replace(']', '`')
                    processed_formula = processed_formula.replace('【', '`').replace('】', '`')
                    derived_select_parts.append(f"{processed_formula} AS `{target}`")
            
            # 根据聚合细度确定时间范围
            if granularity == 'hour':
                time_range = "1 HOUR"
            elif granularity == 'day':
                time_range = "1 DAY"
            elif granularity == 'week':
                time_range = "7 DAY"
            elif granularity == 'month':
                time_range = "30 DAY"
            else:
                time_range = "1 HOUR"
            
            # 使用子查询获取最新时间，然后查询该时间段的数据
            sql = f"""
WITH aggregated AS (
    SELECT {', '.join(select_parts)}
    FROM `{model.source_database}`.`{model.source_table}`
    WHERE `{time_field}` >= (
        SELECT DATE_SUB(MAX(`{time_field}`), INTERVAL {time_range})
        FROM `{model.source_database}`.`{model.source_table}`
    )
    GROUP BY {', '.join(group_by_parts)}
    ORDER BY `{time_field_name}` DESC
    LIMIT {limit}
)
SELECT {', '.join(derived_select_parts)}
FROM aggregated
"""
        
        # 打印生成的 SQL（调试用）
        print("\n" + "=" * 80)
        print("🔍 分析表预览 SQL:")
        print(sql)
        print("=" * 80 + "\n")
        
        # 执行查询
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            if not rows:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "columns": [],
                        "rows": []
                    }
                }
            
            # 获取列名
            columns = list(rows[0].keys())
            
            # 获取字段类型映射（用于百分比格式化）
            field_type_map = {}
            for field in model_fields:
                field_type_map[field.target_field] = field.field_type
            
            # 转换数据类型
            result_rows = []
            for row in rows:
                row_dict = {}
                for col in columns:
                    value = row[col]
                    # 处理特殊类型
                    if value is None:
                        row_dict[col] = None
                    elif isinstance(value, datetime):
                        row_dict[col] = value.strftime('%Y-%m-%d %H:%M:%S')
                    elif isinstance(value, Decimal):
                        # 检查是否为百分比类型
                        if field_type_map.get(col) == '百分比':
                            row_dict[col] = f"{float(value) * 100:.2f}%"
                        else:
                            row_dict[col] = float(value)
                    elif isinstance(value, (int, float)):
                        # 检查是否为百分比类型
                        if field_type_map.get(col) == '百分比':
                            row_dict[col] = f"{float(value) * 100:.2f}%"
                        else:
                            row_dict[col] = value
                    elif isinstance(value, bytes):
                        row_dict[col] = value.decode('utf-8', errors='ignore')
                    else:
                        row_dict[col] = value
                result_rows.append(row_dict)
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "columns": columns,
                    "rows": result_rows
                }
            }
    finally:
        connection.close()


@router.get("/models/{model_id}/sql-preview")
async def generate_sql_preview(model_id: int):
    """生成 SQL 预览"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField
            
            # 获取模型信息
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 获取字段配置
            model_fields = session.query(ETLModelField).filter(
                ETLModelField.model_id == model_id
            ).order_by(ETLModelField.sort_order, ETLModelField.id).all()
            
            if not model_fields:
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "sql": "-- 请先配置字段"
                    }
                }
            
            # 按层级分组字段
            fields_by_level = {1: [], 2: []}
            for field in model_fields:
                fields_by_level[field.derive_level].append(field)
            
            # 生成 SQL
            if not fields_by_level[2]:
                # 只有层级1，直接查询
                select_parts = []
                for field in fields_by_level[1]:
                    formula = field.formula.replace('[', '`').replace(']', '`')
                    formula = formula.replace('【', '`').replace('】', '`')
                    select_parts.append(f"  {formula} AS `{field.target_field}`")
                
                newline = '\n'
                sql = f"""-- 关联表模型: {model.name}
-- 目标表: {model.target_database}.{model.table_name}
-- 源表: {model.source_database}.{model.source_table}

SELECT
{f',{newline}'.join(select_parts)}
FROM `{model.source_database}`.`{model.source_table}`
"""
            else:
                # 使用 CTE 处理多层派生
                # 层级1
                level1_selects = []
                for field in fields_by_level[1]:
                    formula = field.formula.replace('[', '`').replace(']', '`')
                    formula = formula.replace('【', '`').replace('】', '`')
                    level1_selects.append(f"    {formula} AS `{field.target_field}`")
                
                # 层级2
                level2_selects = ['  *']  # 保留层级1的所有字段
                for field in fields_by_level[2]:
                    formula = field.formula.replace('[', '`').replace(']', '`')
                    formula = formula.replace('【', '`').replace('】', '`')
                    level2_selects.append(f"  {formula} AS `{field.target_field}`")
                
                newline = '\n'
                sql = f"""-- 关联表模型: {model.name}
-- 目标表: {model.target_database}.{model.table_name}
-- 源表: {model.source_database}.{model.source_table}

WITH level1 AS (
  SELECT
{f',{newline}'.join(level1_selects)}
  FROM `{model.source_database}`.`{model.source_table}`
)
SELECT
{f',{newline}'.join(level2_selects)}
FROM level1
"""
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "sql": sql
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成 SQL 失败: {str(e)}")
