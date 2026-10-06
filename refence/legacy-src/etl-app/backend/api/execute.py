"""
ETL 执行 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.config import get_config_manager
from backend.core.executor import ExecutionEngine
from backend.models.etl_config import MySQLConfig

router = APIRouter()


class ExecuteRequest(BaseModel):
    """执行请求"""
    model_id: int
    full_refresh: bool = False


@router.post("/execute")
async def execute_model(request: ExecuteRequest):
    """执行 ETL 模型"""
    try:
        config_manager = get_config_manager()
        
        with config_manager.get_session() as session:
            from backend.models.etl_model import ETLModel, ETLModelField
            import json
            
            # 获取模型信息
            model = session.query(ETLModel).filter(ETLModel.id == request.model_id).first()
            if not model:
                raise HTTPException(status_code=404, detail="模型不存在")
            
            # 检查模型是否是草稿
            if model.is_draft:
                raise HTTPException(status_code=400, detail="草稿模型不能执行")
            
            # 检查 SQL 文件是否存在
            if not model.sql_path:
                raise HTTPException(status_code=400, detail="模型未生成 SQL 文件")
            
            # 获取 MySQL 配置
            mysql_config = session.query(MySQLConfig).first()
            if not mysql_config:
                raise HTTPException(status_code=400, detail="未找到 MySQL 配置")
            
            # 解密密码
            import os
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
            
            # 准备 MySQL 配置
            mysql_config_dict = {
                'host': mysql_config.host,
                'port': mysql_config.port,
                'username': mysql_config.username,
                'password': password,
                'database': model.source_database or 'sfc_raw'
            }
            
            # 准备模型配置
            unique_keys = []
            if model.unique_keys:
                try:
                    unique_keys = json.loads(model.unique_keys)
                except:
                    unique_keys = []
            
            # 获取全局配置的回算时间
            from backend.models.etl_config import ETLConfig
            etl_config = session.query(ETLConfig).first()
            backfill_hours = etl_config.backfill_hours if etl_config else 24
            
            model_dict = {
                'id': model.id,
                'name': model.name,
                'table_name': model.table_name,
                'model_type': model.model_type,
                'source_table': model.source_table,
                'source_database': model.source_database,
                'target_database': model.target_database,
                'sql_path': model.sql_path,
                'unique_key_type': model.unique_key_type or 'none',
                'unique_key': model.unique_key or '',
                'unique_keys': unique_keys,
                'incremental_field': model.incremental_field or 'upload_time',
                'backfill_hours': backfill_hours,
                # 分析表专用字段
                'time_field': getattr(model, 'time_field', 'ServerTime'),
                'granularity': getattr(model, 'granularity', 'hour'),
                'time_field_name': getattr(model, 'time_field_name', 'hour')
            }
            
            # 创建执行引擎
            executor = ExecutionEngine(mysql_config_dict)
            
            # 执行模型（手动触发）
            result = executor.execute_model(
                model=model_dict,
                full_refresh=request.full_refresh,
                trigger_type='manual'  # 手动触发
            )
            
            return {
                "code": 0,
                "message": "success",
                "data": {
                    "success": result['success'],
                    "message": result['message'],
                    "rows_affected": result['rows_affected'],
                    "duration": result['duration'],
                    "execution_logs": result['execution_logs']
                }
            }
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行失败: {str(e)}")
