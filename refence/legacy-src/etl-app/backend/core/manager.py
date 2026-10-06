"""
ETL 管理器 - 整个 ETL 模块的核心入口
"""
from typing import Dict, Any, List, Optional

from backend.config import get_config_manager, ConfigManager
from backend.core.sql_generator import SqlGenerator
from backend.core.executor import ExecutionEngine
from backend.core.scheduler import get_task_scheduler, TaskScheduler
from backend.core.logger import get_etl_logger, ETLLogger
from backend.models.etl_model import ETLModel, ETLModelField
from backend.models.field_mapping import FieldMapping, MappingType
from backend.utils.validators import validate_model_config, validate_field_mapping


class ETLManager:
    """ETL 管理器 - 统一管理所有 ETL 功能"""
    
    def __init__(self, config_db_path: Optional[str] = None):
        """
        初始化 ETL 管理器
        
        Args:
            config_db_path: 配置数据库路径
        """
        # 初始化配置管理器
        self.config: ConfigManager = get_config_manager(config_db_path)
        
        # 初始化各个组件
        self.sql_generator = SqlGenerator()
        self.logger: ETLLogger = get_etl_logger()
        self.scheduler: TaskScheduler = get_task_scheduler()
        
        # 执行引擎（延迟初始化）
        self._execution_engine: Optional[ExecutionEngine] = None
    
    @property
    def execution_engine(self) -> ExecutionEngine:
        """获取执行引擎（延迟初始化）"""
        if self._execution_engine is None:
            mysql_config = self.config.get_mysql_config()
            if not mysql_config:
                raise ValueError("未找到 MySQL 配置，请先配置数据库连接")
            
            self._execution_engine = ExecutionEngine(mysql_config)
        
        return self._execution_engine
    
    def init_system(self) -> Dict[str, Any]:
        """
        初始化 ETL 系统
        
        Returns:
            初始化结果
        """
        try:
            # 初始化数据库表结构
            self.config.init_database()
            
            # 记录系统初始化日志
            self.logger.log_scheduler_event(
                event_type="system_init",
                message="ETL 系统初始化完成"
            )
            
            return {
                'success': True,
                'message': 'ETL 系统初始化完成',
                'config_db_path': self.config.settings.config_db_path,
                'log_dir': str(self.logger.log_dir)
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f'系统初始化失败: {str(e)}'
            }
    
    # ==================== 模型管理 ====================
    
    def create_link_model(
        self,
        name: str,
        table_name: str,
        source_table: str,
        source_database: str = "sfc_raw",
        target_database: str = "link_db",
        description: str = "",
        project_name: str = "default"
    ) -> Dict[str, Any]:
        """
        创建关联表模型
        
        Args:
            name: 模型名称
            table_name: 目标表名
            source_table: 源表名
            source_database: 源数据库
            target_database: 目标数据库
            description: 描述
            project_name: 项目名称
            
        Returns:
            创建结果
        """
        try:
            # 验证模型配置
            model_config = {
                'name': name,
                'table_name': table_name,
                'model_type': 'link'
            }
            
            validation = validate_model_config(model_config)
            if not validation['valid']:
                return {
                    'success': False,
                    'message': f"模型配置验证失败: {', '.join(validation['errors'])}"
                }
            
            # 创建模型记录
            with self.config.get_session() as session:
                model = ETLModel(
                    name=name,
                    table_name=table_name,
                    source_table=source_table,
                    model_type='link',
                    source_database=source_database,
                    target_database=target_database,
                    description=description,
                    is_draft=True
                )
                
                session.add(model)
                session.commit()
                session.refresh(model)
                
                return {
                    'success': True,
                    'message': '关联表模型创建成功',
                    'model_id': model.id,
                    'model': {
                        'id': model.id,
                        'name': model.name,
                        'table_name': model.table_name,
                        'model_type': model.model_type,
                        'is_draft': model.is_draft
                    }
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'创建模型失败: {str(e)}'
            }
    
    def create_analysis_model(
        self,
        name: str,
        table_name: str,
        source_table: str,
        source_database: str = "link_db",
        target_database: str = "analytics_dw",
        description: str = "",
        project_name: str = "default"
    ) -> Dict[str, Any]:
        """
        创建分析表模型
        
        注意：回算时间使用全局配置（etl_config.backfill_hours）
        
        Args:
            name: 模型名称
            table_name: 目标表名
            source_table: 源表名
            source_database: 源数据库
            target_database: 目标数据库
            description: 描述
            project_name: 项目名称
            
        Returns:
            创建结果
        """
        try:
            # 验证模型配置
            model_config = {
                'name': name,
                'table_name': table_name,
                'model_type': 'analysis'
            }
            
            validation = validate_model_config(model_config)
            if not validation['valid']:
                return {
                    'success': False,
                    'message': f"模型配置验证失败: {', '.join(validation['errors'])}"
                }
            
            # 创建模型记录
            with self.config.get_session() as session:
                model = ETLModel(
                    name=name,
                    table_name=table_name,
                    source_table=source_table,
                    model_type='analysis',
                    source_database=source_database,
                    target_database=target_database,
                    description=description,
                    is_draft=True
                )
                
                session.add(model)
                session.commit()
                session.refresh(model)
                
                return {
                    'success': True,
                    'message': '分析表模型创建成功',
                    'model_id': model.id,
                    'model': {
                        'id': model.id,
                        'name': model.name,
                        'table_name': model.table_name,
                        'model_type': model.model_type,
                        'is_draft': model.is_draft
                    }
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'创建模型失败: {str(e)}'
            }
    
    def add_field_mapping(
        self,
        model_id: int,
        source_field: str,
        target_field: str,
        mapping_type: str = "direct",
        **kwargs
    ) -> Dict[str, Any]:
        """
        添加字段映射
        
        Args:
            model_id: 模型ID
            source_field: 源字段名
            target_field: 目标字段名
            mapping_type: 映射类型
            **kwargs: 其他配置参数
            
        Returns:
            添加结果
        """
        try:
            # 创建字段映射对象
            mapping = FieldMapping(
                source_field=source_field,
                target_field=target_field,
                mapping_type=MappingType(mapping_type),
                **kwargs
            )
            
            # 验证映射配置
            validation = validate_field_mapping(mapping.to_dict())
            if not validation['valid']:
                return {
                    'success': False,
                    'message': f"字段映射验证失败: {', '.join(validation['errors'])}"
                }
            
            # 保存到数据库
            with self.config.get_session() as session:
                field = ETLModelField(
                    model_id=model_id,
                    source_field=source_field,
                    target_field=target_field,
                    mapping_type=mapping_type,
                    formula=kwargs.get('formula'),
                    constant_value=kwargs.get('constant_value'),
                    aggregate_function=kwargs.get('aggregate_function'),
                    default_value=kwargs.get('default_value'),
                    description=kwargs.get('description'),
                    sort_order=kwargs.get('sort_order', 0),
                    is_required=kwargs.get('is_required', False)
                )
                
                session.add(field)
                session.commit()
                session.refresh(field)
                
                return {
                    'success': True,
                    'message': '字段映射添加成功',
                    'field_id': field.id
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'添加字段映射失败: {str(e)}'
            }
    
    def generate_model_sql(self, model_id: int, project_name: str = "default") -> Dict[str, Any]:
        """
        生成模型 SQL 文件
        
        Args:
            model_id: 模型ID
            project_name: 项目名称
            
        Returns:
            生成结果
        """
        try:
            with self.config.get_session() as session:
                # 获取模型信息
                model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
                if not model:
                    return {
                        'success': False,
                        'message': '模型不存在'
                    }
                
                # 获取字段映射
                fields = session.query(ETLModelField).filter(
                    ETLModelField.model_id == model_id
                ).order_by(ETLModelField.sort_order).all()
                
                if not fields:
                    return {
                        'success': False,
                        'message': '模型没有配置字段映射'
                    }
                
                # 转换字段配置
                field_configs = []
                for field in fields:
                    field_configs.append({
                        'source_field': field.source_field,
                        'target_field': field.target_field,
                        'mapping_type': field.mapping_type,
                        'formula': field.formula,
                        'constant_value': field.constant_value,
                        'aggregate_function': field.aggregate_function
                    })
                
                # 生成 SQL 文件
                if model.model_type == 'link':
                    sql_path = self.sql_generator.generate_link_model_sql(
                        model_name=model.name,
                        table_name=model.table_name,
                        source_table=model.source_table,
                        source_database=model.source_database,
                        target_database=model.target_database,
                        fields=field_configs,
                        unique_key_type=model.unique_key_type,
                        unique_key=model.unique_key,
                        description=model.description,
                        project_name=project_name
                    )
                elif model.model_type == 'analysis':
                    sql_path = self.sql_generator.generate_analysis_model_sql(
                        model_name=model.name,
                        table_name=model.table_name,
                        source_table=model.source_table,
                        source_database=model.source_database,
                        target_database=model.target_database,
                        fields=field_configs,
                        description=model.description,
                        project_name=project_name
                    )
                else:
                    return {
                        'success': False,
                        'message': f'不支持的模型类型: {model.model_type}'
                    }
                
                # 更新模型的 SQL 路径
                model.sql_path = sql_path
                session.commit()
                
                return {
                    'success': True,
                    'message': 'SQL 文件生成成功',
                    'sql_path': sql_path
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'生成 SQL 失败: {str(e)}'
            }
    
    def execute_model(self, model_id: int, full_refresh: bool = False) -> Dict[str, Any]:
        """
        执行模型
        
        Args:
            model_id: 模型ID
            full_refresh: 是否全量刷新
            
        Returns:
            执行结果
        """
        try:
            with self.config.get_session() as session:
                model = session.query(ETLModel).filter(ETLModel.id == model_id).first()
                if not model:
                    return {
                        'success': False,
                        'message': '模型不存在'
                    }
                
                if not model.sql_path:
                    return {
                        'success': False,
                        'message': '模型未生成 SQL 文件，请先生成 SQL'
                    }
                
                # 获取全局配置的回算时间
                from backend.models.etl_config import ETLConfig
                etl_config = session.query(ETLConfig).first()
                backfill_hours = etl_config.backfill_hours if etl_config else 24
                
                # 转换为字典格式
                model_dict = {
                    'id': model.id,
                    'name': model.name,
                    'table_name': model.table_name,
                    'model_type': model.model_type,
                    'source_database': model.source_database,
                    'target_database': model.target_database,
                    'sql_path': model.sql_path,
                    'backfill_hours': backfill_hours,
                    # 分析表专用字段
                    'time_field': getattr(model, 'time_field', 'ServerTime'),
                    'granularity': getattr(model, 'granularity', 'hour'),
                    'time_field_name': getattr(model, 'time_field_name', 'hour'),
                    'source_table': model.source_table
                }
                
                # 执行模型
                return self.execution_engine.execute_model(model_dict, full_refresh)
                
        except Exception as e:
            return {
                'success': False,
                'message': f'执行模型失败: {str(e)}'
            }
    
    # ==================== 调度管理 ====================
    
    def start_scheduler(self) -> Dict[str, Any]:
        """启动调度器"""
        try:
            self.scheduler.start()
            return {
                'success': True,
                'message': '调度器启动成功'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'启动调度器失败: {str(e)}'
            }
    
    def stop_scheduler(self) -> Dict[str, Any]:
        """停止调度器"""
        try:
            self.scheduler.stop()
            return {
                'success': True,
                'message': '调度器停止成功'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'停止调度器失败: {str(e)}'
            }
    
    def get_scheduler_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        return self.scheduler.get_status()
    
    def run_manual_etl(self, model_ids: Optional[List[int]] = None, full_refresh: bool = False) -> Dict[str, Any]:
        """手动执行 ETL"""
        return self.scheduler.run_manual_etl(model_ids, full_refresh)
    
    # ==================== 系统管理 ====================
    
    def get_system_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        etl_config = self.config.get_etl_config()
        mysql_config = self.config.get_mysql_config()
        scheduler_status = self.scheduler.get_status()
        etl_stats = self.logger.get_etl_statistics(days=7)
        
        return {
            'etl_config': etl_config,
            'mysql_connected': mysql_config is not None,
            'scheduler_status': scheduler_status,
            'etl_statistics': etl_stats,
            'config_db_path': self.config.settings.config_db_path,
            'log_dir': str(self.logger.log_dir)
        }
    
    def get_execution_logs(self, days: int = 7, limit: int = 100) -> List[Dict[str, Any]]:
        """获取执行日志"""
        return self.logger.read_etl_logs(limit=limit)
    
    def cleanup_old_logs(self, keep_days: int = 30) -> Dict[str, Any]:
        """清理旧日志"""
        try:
            self.logger.cleanup_old_logs(keep_days)
            return {
                'success': True,
                'message': f'已清理 {keep_days} 天前的日志'
            }
        except Exception as e:
            return {
                'success': False,
                'message': f'清理日志失败: {str(e)}'
            }