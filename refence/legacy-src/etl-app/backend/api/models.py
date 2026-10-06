"""
ETL 模型管理 API
"""
import os
from fastapi import APIRouter, HTTPException
from typing import List, Optional
from pydantic import BaseModel

from backend.config import get_config_manager

router = APIRouter()


class ModelResponse(BaseModel):
    """模型响应"""
    # 配置 Pydantic 以允许 model_ 开头的字段名
    model_config = {"protected_namespaces": ()}
    
    id: int
    name: str
    table_name: str
    model_type: str
    source_table: Optional[str] = None
    source_database: Optional[str] = None
    target_database: Optional[str] = None
    description: Optional[str] = None
    is_enabled: bool = True
    is_draft: bool = True


@router.get("/models")
async def get_models(model_type: Optional[str] = None):
    """获取模型列表"""
    try:
        config_manager = get_config_manager()
        
        # 调试信息
        print(f"🔍 [DEBUG] 数据库路径: {config_manager.cfg_db_path}")
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel
            
            query = session.query(ETLModel)
            if model_type:
                query = query.filter(ETLModel.model_type == model_type)
            
            models = query.all()
            
            # 调试信息
            print(f"🔍 [DEBUG] 查询到 {len(models)} 个模型")
            for m in models:
                print(f"  - ID: {m.id}, Name: {m.name}, Enabled: {m.is_enabled}, Draft: {m.is_draft}")
            
            return {
                "code": 0,
                "message": "success",
                "data": [{
                    "id": m.id,
                    "name": m.name,
                    "table_name": m.table_name,
                    "model_type": m.model_type,
                    "source_table": m.source_table,
                    "source_database": m.source_database,
                    "target_database": m.target_database,
                    "description": m.description,
                    "is_enabled": m.is_enabled,
                    "is_draft": m.is_draft,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None
                } for m in models]
            }
    except Exception as e:
        print(f"❌ [DEBUG] 错误: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


@router.get("/models/{model_id}")
async def get_model(model_id: int):
    """获取单个模型"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 处理 unique_keys（JSON 字符串转数组）
            unique_keys = []
            if model.unique_keys:
                try:
                    import json
                    unique_keys = json.loads(model.unique_keys)
                except:
                    unique_keys = []
            # 获取全局配置的回算时间
            from backend.models.etl_config import ETLConfig
            etl_config = session.query(ETLConfig).first()
            backfill_hours = etl_config.backfill_hours if etl_config else 24
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "id": model.id,
                    "name": model.name,
                    "table_name": model.table_name,
                    "model_type": model.model_type,
                    "source_table": model.source_table,
                    "source_database": model.source_database,
                    "target_database": model.target_database,
                    "description": model.description,
                    "is_enabled": model.is_enabled,
                    "is_draft": model.is_draft,
                    "unique_key_type": model.unique_key_type or 'none',
                    "unique_key": model.unique_key or '',
                    "unique_keys": unique_keys,
                    "incremental_field": model.incremental_field or '',
                    "view_time_field": model.view_time_field or '',
                    "backfill_hours": backfill_hours,
                    "time_field": getattr(model, 'time_field', ''),
                    "granularity": getattr(model, 'granularity', 'hour'),
                    "time_field_name": getattr(model, 'time_field_name', 'hour'),
                    "created_at": model.created_at.isoformat() if model.created_at else None,
                    "updated_at": model.updated_at.isoformat() if model.updated_at else None
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型失败: {str(e)}")


@router.post("/models")
async def create_model(model_data: dict):
    """创建模型"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel
            from datetime import datetime
            from backend.core.logger import CHINA_TZ
            
            model = ETLModel(
                name=model_data.get("name"),
                table_name=model_data.get("table_name"),
                source_table=model_data.get("source_table"),
                model_type=model_data.get("model_type"),
                source_database=model_data.get("source_database"),
                target_database=model_data.get("target_database"),
                description=model_data.get("description"),
                is_enabled=model_data.get("is_enabled", False),
                is_draft=True,
                created_at=datetime.now(CHINA_TZ),
                updated_at=datetime.now(CHINA_TZ)
            )
            
            session.add(model)
            session.commit()
            session.refresh(model)
            
            return {
                "code": 0,
                "message": "模型创建成功",
                "data": {"id": model.id}
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建模型失败: {str(e)}")


@router.put("/models/{model_id}")
async def update_model(model_id: int, model_data: dict):
    """更新模型"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel
            from datetime import datetime
            from backend.core.logger import CHINA_TZ
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 更新字段
            for key, value in model_data.items():
                if hasattr(model, key):
                    setattr(model, key, value)
            
            model.updated_at = datetime.now(CHINA_TZ)
            
            session.commit()
            
            return {
                "code": 0,
                "message": "模型更新成功",
                "data": None
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新模型失败: {str(e)}")


@router.delete("/models/{model_id}")
async def delete_model(model_id: int):
    """删除模型"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField, ETLSourceField
            
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 删除关联的字段配置
            session.query(ETLModelField).filter(ETLModelField.model_id == model_id).delete()
            
            # 删除关联的源字段信息
            session.query(ETLSourceField).filter(ETLSourceField.model_id == model_id).delete()
            
            # 删除模型本身
            session.delete(model)
            session.commit()
            
            # 删除 SQL 文件
            try:
                from pathlib import Path
                
                # 获取项目根目录
                project_root = Path(__file__).parent.parent.parent
                
                # 删除模型 SQL 文件
                if model.sql_path:
                    # 如果是相对路径，转换为绝对路径
                    if not Path(model.sql_path).is_absolute():
                        sql_file = project_root / model.sql_path
                    else:
                        sql_file = Path(model.sql_path)
                    
                    if sql_file.exists():
                        sql_file.unlink()
                        print(f"✅ 已删除模型 SQL 文件: {sql_file}")
                    else:
                        print(f"⚠️  模型 SQL 文件不存在: {sql_file}")
                
                # 删除对应的视图 SQL 文件
                view_name = f"v_{model.table_name}_recent"
                view_file = project_root / "sql_models" / "views" / f"{view_name}.sql"
                if view_file.exists():
                    view_file.unlink()
                    print(f"✅ 已删除视图 SQL 文件: {view_file}")
                else:
                    print(f"⚠️  视图 SQL 文件不存在: {view_file}")
                    
            except Exception as e:
                print(f"⚠️  删除 SQL 文件时出错: {e}")
                # 不抛出异常，因为文件删除失败不应该影响数据库删除
            
            return {
                "code": 0,
                "message": "模型删除成功",
                "data": None
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除模型失败: {str(e)}")


@router.get("/models/{model_id}/statistics")
async def get_model_statistics(model_id: int):
    """获取单个模型的统计信息"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel
            
            # 验证模型是否存在
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 尝试查询日志统计（如果日志表不存在，返回默认值）
            try:
                from backend.models.etl_model import ETLLog
                from sqlalchemy import func
                
                # 统计总执行次数
                total_runs = session.query(func.count(ETLLog.id)).filter(
                    ETLLog.model_id == model_id
                ).scalar() or 0
                
                # 统计成功次数
                success_runs = session.query(func.count(ETLLog.id)).filter(
                    ETLLog.model_id == model_id,
                    ETLLog.status == 'success'
                ).scalar() or 0
                
                # 计算成功率
                success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0, 1)
            except Exception:
                # 如果日志表不存在或查询失败，返回默认值
                total_runs = 0
                success_runs = 0
                success_rate = 0
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "total_runs": total_runs,
                    "success_runs": success_runs,
                    "success_rate": success_rate
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型统计信息失败: {str(e)}")


@router.get("/models/{model_id}/source-fields")
async def get_source_fields(model_id: int):
    """获取模型的源表字段"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLSourceField
            
            # 验证模型是否存在
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 查询源表字段
            fields = session.query(ETLSourceField).filter(
                ETLSourceField.model_id == model_id
            ).all()
            
            return {
                "code": 0,
                "message": "success",
                "data": [{
                    "field_name": f.field_name,
                    "field_type": f.field_type,
                    "field_category": f.field_category,
                    "nullable": f.nullable,
                    "default_value": f.default_value,
                    "comment": f.comment,
                    "is_selected": f.is_selected
                } for f in fields]
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取源表字段失败: {str(e)}")


@router.post("/models/{model_id}/source-fields")
async def save_source_fields(model_id: int, data: dict):
    """保存模型的源表字段"""
    try:
        # 调试：打印接收到的数据
        print("\n" + "=" * 80)
        print(f"📥 保存源表字段 - 模型 ID: {model_id}")
        print("=" * 80)
        print(f"source_table: {data.get('source_table', 'NOT PROVIDED')}")
        print(f"source_database: {data.get('source_database', 'NOT PROVIDED')}")
        print(f"字段数量: {len(data.get('fields', []))}")
        
        if data.get('fields'):
            print("\n字段列表（前3个）:")
            for idx, field in enumerate(data.get('fields', [])[:3], 1):
                print(f"  {idx}. {field.get('field_name')} - {field.get('field_type')} - field_category: {field.get('field_category', '未提供')}")
        print("=" * 80 + "\n")
        
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLSourceField
            
            # 验证模型是否存在
            model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 只在前端明确提供时才更新源表信息（避免意外清空）
            if 'source_table' in data and data['source_table']:
                model.source_table = data['source_table']
            if 'source_database' in data and data['source_database']:
                model.source_database = data['source_database']
            
            # 删除旧的字段配置
            session.query(ETLSourceField).filter(
                ETLSourceField.model_id == model_id
            ).delete()
            
            # 添加新的字段配置
            fields = data.get('fields', [])
            saved_count = 0
            for field_data in fields:
                field_category = field_data.get('field_category', '文本')
                
                # 🔧 调试：打印每个字段的 field_category
                if saved_count < 3:
                    print(f"💾 保存字段 {saved_count + 1}: {field_data['field_name']} - field_category: {field_category}")
                
                field = ETLSourceField(
                    model_id=model_id,
                    field_name=field_data['field_name'],
                    field_type=field_data['field_type'],
                    field_category=field_category,
                    nullable=field_data.get('nullable', True),
                    default_value=field_data.get('default_value'),
                    comment=field_data.get('comment'),
                    is_selected=field_data.get('is_selected', True)
                )
                session.add(field)
                saved_count += 1
            
            session.commit()
            
            print(f"✅ 成功保存 {saved_count} 个字段\n")
            
            return {
                "code": 0,
                "message": "success",
                "data": {"saved_count": saved_count}
            }
    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"保存源表字段失败: {str(e)}")


@router.get("/table-structure")
async def get_table_structure(database: str, table: str):
    """获取表结构"""
    try:
        print(f"\n🔍 [DEBUG] 获取表结构: database={database}, table={table}")
        
        config_manager = get_config_manager()
        
        # 获取 MySQL 配置并立即提取需要的信息
        with config_manager.get_session() as session:
            from backend.models.etl_config import MySQLConfig
            
            # 获取第一个 MySQL 配置
            mysql_config = session.query(MySQLConfig).first()
            
            if not mysql_config:
                print(f"❌ [DEBUG] 未找到 MySQL 配置")
                raise HTTPException(status_code=400, detail="未找到 MySQL 配置")
            
            print(f"✅ [DEBUG] 找到 MySQL 配置: {mysql_config.name} ({mysql_config.host}:{mysql_config.port})")
            
            # ⚠️ 关键修复：在 session 关闭前提取所有需要的信息
            mysql_host = mysql_config.host
            mysql_port = mysql_config.port
            mysql_username = mysql_config.username
            mysql_password = mysql_config.password
        
        # 使用 MySQL 配置创建连接
        from sqlalchemy import create_engine, text
        from backend.utils.database import decrypt_password
        
        # 解密密码
        encryption_key = os.getenv("ENCRYPTION_KEY")
        print(f"🔍 [DEBUG] ENCRYPTION_KEY exists: {bool(encryption_key)}")
        
        if encryption_key:
            try:
                password = decrypt_password(mysql_password, encryption_key)
                print(f"✅ [DEBUG] 密码解密成功")
            except Exception as e:
                print(f"❌ [DEBUG] 密码解密失败: {e}")
                raise HTTPException(status_code=500, detail=f"密码解密失败: {str(e)}")
        else:
            password = mysql_password
            print(f"⚠️  [DEBUG] 未设置 ENCRYPTION_KEY，使用明文密码")
        
        # 创建数据库连接 URL
        db_url = f"mysql+pymysql://{mysql_username}:***@{mysql_host}:{mysql_port}/{database}"
        print(f"🔍 [DEBUG] 连接 URL: {db_url}")
        
        # 创建引擎
        engine = create_engine(
            f"mysql+pymysql://{mysql_username}:{password}@{mysql_host}:{mysql_port}/{database}",
            pool_pre_ping=True
        )
        
        try:
            print(f"🔍 [DEBUG] 尝试连接数据库...")
            with engine.connect() as conn:
                print(f"✅ [DEBUG] 数据库连接成功")
                
                # 查询表结构
                query = text("""
                    SELECT 
                        COLUMN_NAME as column_name,
                        COLUMN_TYPE as column_type,
                        IS_NULLABLE as is_nullable,
                        COLUMN_DEFAULT as column_default,
                        COLUMN_COMMENT as column_comment
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = :database
                    AND TABLE_NAME = :table
                    ORDER BY ORDINAL_POSITION
                """)
                
                result = conn.execute(query, {"database": database, "table": table})
                fields = []
                
                for row in result:
                    fields.append({
                        "columnName": row.column_name,
                        "columnType": row.column_type,
                        "isNullable": row.is_nullable,
                        "columnDefault": row.column_default,
                        "columnComment": row.column_comment
                    })
                
                print(f"✅ [DEBUG] 查询到 {len(fields)} 个字段")
                
                return {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "database": database,
                        "table": table,
                        "fields": fields
                    }
                }
        except Exception as e:
            print(f"❌ [DEBUG] 数据库查询失败: {e}")
            raise
        finally:
            # 释放临时引擎
            engine.dispose()
            print(f"🔍 [DEBUG] 引擎已释放")
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [DEBUG] 获取表结构失败: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"获取表结构失败: {str(e)}")
