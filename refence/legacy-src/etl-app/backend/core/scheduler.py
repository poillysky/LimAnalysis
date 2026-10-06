"""
ETL 任务调度器 - 使用 schedule 库实现轻量级定时任务
"""
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import schedule

from backend.config import get_config_manager
from backend.core.executor import ExecutionEngine
from backend.core.logger import get_etl_logger
from backend.utils.resource_monitor import ResourceMonitor


class TaskScheduler:
    """ETL 任务调度器"""
    
    def __init__(self):
        """初始化调度器"""
        self.config_manager = get_config_manager()
        self.logger = get_etl_logger()
        self.is_running = False
        self.scheduler_thread = None
        
        # 初始化执行引擎
        self.execution_engine = None
        self._init_execution_engine()
    
    def _init_execution_engine(self):
        """初始化执行引擎"""
        try:
            # 获取 ETL 配置，从中读取 MySQL 配置 ID 和超时时间
            from backend.models.etl_config import ETLConfig, MySQLConfig
            from cryptography.fernet import Fernet
            import os
            
            with self.config_manager.get_session() as session:
                # 获取 ETL 配置
                etl_config = session.query(ETLConfig).first()
                if not etl_config or not etl_config.mysql_config_id:
                    self.logger.log_scheduler_event(
                        event_type="engine_init_failed",
                        message="未配置 MySQL 连接"
                    )
                    print("⚠️  未配置 MySQL 连接，执行引擎初始化失败")
                    return
                
                # 获取超时配置
                timeout = etl_config.timeout if etl_config.timeout else 300
                
                # 获取 MySQL 配置
                mysql_config = session.query(MySQLConfig).filter(
                    MySQLConfig.id == etl_config.mysql_config_id
                ).first()
                
                if not mysql_config:
                    self.logger.log_scheduler_event(
                        event_type="engine_init_failed",
                        message="MySQL 配置不存在"
                    )
                    print("⚠️  MySQL 配置不存在，执行引擎初始化失败")
                    return
                
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
                
                # 构建配置字典
                mysql_config_dict = {
                    "host": mysql_config.host,
                    "port": mysql_config.port,
                    "username": mysql_config.username,
                    "password": password,
                    "database": mysql_config.database or "sfc_raw"
                }
                
                # 初始化执行引擎（传递超时参数）
                self.execution_engine = ExecutionEngine(mysql_config_dict, timeout=timeout)
                
                self.logger.log_scheduler_event(
                    event_type="engine_init",
                    message=f"执行引擎初始化成功（超时: {timeout}秒）"
                )
                print(f"✅ 执行引擎初始化成功（超时: {timeout}秒）")
                
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="engine_init_failed",
                message=f"执行引擎初始化失败: {str(e)}"
            )
            print(f"❌ 执行引擎初始化失败: {str(e)}")
    
    def start(self):
        """启动调度器"""
        if self.is_running:
            print("⚠️  调度器已在运行中")
            return
        
        self.is_running = True
        
        # 设置定时任务
        self._setup_scheduled_jobs()
        
        # 启动调度器线程
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        self.logger.log_scheduler_event(
            event_type="scheduler_start",
            message="ETL 调度器启动成功"
        )
        
        print("🚀 ETL 调度器启动成功")
    
    def stop(self):
        """停止调度器"""
        if not self.is_running:
            print("⚠️  调度器未在运行")
            return
        
        print("🛑 正在停止调度器...")
        self.is_running = False
        
        # 清除所有定时任务
        schedule.clear()
        print("✅ 已清除所有定时任务")
        
        # 等待调度器线程结束
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            print("⏳ 等待调度器线程结束...")
            self.scheduler_thread.join(timeout=30)  # 增加到 30 秒
            
            if self.scheduler_thread.is_alive():
                print("⚠️  调度器线程未在超时时间内结束")
            else:
                print("✅ 调度器线程已结束")
        
        # 清理执行引擎资源
        if self.execution_engine:
            print("🧹 正在清理执行引擎资源...")
            try:
                self.execution_engine.close()
                self.execution_engine = None
                print("✅ 执行引擎资源已释放")
            except Exception as e:
                print(f"⚠️  清理执行引擎时出错: {e}")
        
        self.logger.log_scheduler_event(
            event_type="scheduler_stop",
            message="ETL 调度器已停止"
        )
        
        print("🛑 ETL 调度器已完全停止")
    
    def _setup_scheduled_jobs(self):
        """设置定时任务"""
        # 每分钟检查一次是否需要执行 ETL
        schedule.every().minute.do(self._check_and_run_etl)
        
        # 每天凌晨 2 点清理旧日志
        schedule.every().day.at("02:00").do(self._cleanup_old_logs)
        
        # 每小时记录一次资源使用情况
        schedule.every().hour.do(self._log_resource_usage)
        
        print("📅 定时任务设置完成")
        print("- ETL 检查: 每分钟")
        print("- 日志清理: 每天 02:00")
        print("- 资源监控: 每小时")
    
    def _run_scheduler(self):
        """运行调度器主循环"""
        print("🔄 调度器主循环启动")
        
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(1)  # 每秒检查一次
            except Exception as e:
                self.logger.log_scheduler_event(
                    event_type="scheduler_error",
                    message=f"调度器运行错误: {str(e)}"
                )
                print(f"❌ 调度器运行错误: {e}")
                time.sleep(5)  # 出错后等待 5 秒再继续
        
        print("🔄 调度器主循环结束")
    
    def _check_and_run_etl(self):
        """检查并运行 ETL 任务"""
        try:
            # 获取 ETL 配置
            etl_config = self.config_manager.get_etl_config()
            if not etl_config:
                return
            
            if not etl_config['is_active']:
                return
            
            # 检查是否到了执行时间
            last_run_time = etl_config.get('last_run_time')
            run_interval = etl_config.get('run_interval', 60)  # 默认 60 分钟
            
            if last_run_time:
                next_run_time = last_run_time + timedelta(minutes=run_interval)
                # 使用东八区时间
                from backend.core.logger import CHINA_TZ
                now = datetime.now(CHINA_TZ)
                
                # 如果 last_run_time 没有时区信息，添加时区
                if last_run_time.tzinfo is None:
                    last_run_time = last_run_time.replace(tzinfo=CHINA_TZ)
                    next_run_time = last_run_time + timedelta(minutes=run_interval)
                
                if now < next_run_time:
                    # 还没到执行时间，计算剩余时间
                    remaining = (next_run_time - now).total_seconds() / 60
                    # 每10分钟打印一次等待信息
                    if int(remaining) % 10 == 0:
                        print(f"⏳ 等待下一次执行，剩余 {int(remaining)} 分钟")
                    return
                
                print(f"⏰ 到达执行时间，开始执行 ETL 循环")
            else:
                print(f"🎯 首次执行，立即开始 ETL 循环")
            
            # 执行 ETL 任务
            self._run_etl_tasks()
            
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="etl_check_error",
                message=f"ETL 检查失败: {str(e)}"
            )
    
    def _run_etl_tasks(self):
        """
        运行 ETL 任务
        
        执行顺序：
        1. 先执行所有关联表模型（link）
        2. 再执行所有分析表模型（analysis）
        3. 全部使用增量模式
        """
        print("\n" + "=" * 80)
        print("🔄 _run_etl_tasks 被调用")
        print("=" * 80)
        
        if not self.execution_engine:
            print("⚠️  执行引擎未初始化，尝试重新初始化...")
            self._init_execution_engine()
            if not self.execution_engine:
                print("❌ 执行引擎初始化失败，跳过执行")
                return
        
        self.logger.log_scheduler_event(
            event_type="etl_cycle_start",
            message="开始执行 ETL 循环任务"
        )
        
        print("🔄 开始 ETL 循环任务")
        print("=" * 80)
        
        # 获取启用的模型
        print("📋 正在获取启用的模型...")
        enabled_models = self._get_enabled_models()
        
        print(f"📋 获取到 {len(enabled_models)} 个启用的模型")
        
        if not enabled_models:
            self.logger.log_scheduler_event(
                event_type="etl_cycle_skip",
                message="没有启用的模型"
            )
            print("⚠️  没有启用的模型，跳过执行")
            print("=" * 80 + "\n")
            return
        
        # 按模型类型分组
        link_models = [m for m in enabled_models if m['model_type'] == 'link']
        analysis_models = [m for m in enabled_models if m['model_type'] == 'analysis']
        
        print(f"📋 任务统计:")
        print(f"   - 关联表模型: {len(link_models)} 个")
        print(f"   - 分析表模型: {len(analysis_models)} 个")
        print(f"   - 总计: {len(enabled_models)} 个")
        print()
        
        results = []
        
        # ========== 第一阶段：执行关联表模型 ==========
        if link_models:
            print("=" * 80)
            print("📊 第一阶段：执行关联表模型")
            print("=" * 80)
            
            self.logger.log_scheduler_event(
                event_type="link_phase_start",
                message=f"开始执行 {len(link_models)} 个关联表模型"
            )
            
            for idx, model in enumerate(link_models, 1):
                print(f"\n[{idx}/{len(link_models)}] 执行关联表: {model['name']}")
                print(f"   目标表: {model['target_database']}.{model['table_name']}")
                
                try:
                    result = self.execution_engine.execute_model(
                        model=model,
                        full_refresh=False,  # 增量模式
                        trigger_type='scheduled'
                    )
                    
                    results.append({
                        'model_id': model['id'],
                        'model_name': model['name'],
                        'model_type': 'link',
                        'success': result['success'],
                        'rows_affected': result['rows_affected'],
                        'duration': result['duration']
                    })
                    
                    if result['success']:
                        print(f"   ✅ 成功 - 影响行数: {result['rows_affected']}, 耗时: {result['duration']:.2f}秒")
                    else:
                        print(f"   ❌ 失败 - {result.get('message', '未知错误')}")
                    
                except Exception as e:
                    error_msg = str(e)
                    results.append({
                        'model_id': model['id'],
                        'model_name': model['name'],
                        'model_type': 'link',
                        'success': False,
                        'rows_affected': 0,
                        'duration': 0,
                        'error': error_msg
                    })
                    print(f"   ❌ 失败 - {error_msg}")
                    
                    self.logger.log_scheduler_event(
                        event_type="model_execution_error",
                        message=f"关联表 {model['name']} 执行失败: {error_msg}"
                    )
            
            link_success = sum(1 for r in results if r['model_type'] == 'link' and r['success'])
            print(f"\n📊 关联表阶段完成: {link_success}/{len(link_models)} 成功")
            
            self.logger.log_scheduler_event(
                event_type="link_phase_complete",
                message=f"关联表阶段完成: {link_success}/{len(link_models)} 成功"
            )
        
        # ========== 第二阶段：执行分析表模型 ==========
        if analysis_models:
            print("\n" + "=" * 80)
            print("📈 第二阶段：执行分析表模型")
            print("=" * 80)
            
            self.logger.log_scheduler_event(
                event_type="analysis_phase_start",
                message=f"开始执行 {len(analysis_models)} 个分析表模型"
            )
            
            for idx, model in enumerate(analysis_models, 1):
                print(f"\n[{idx}/{len(analysis_models)}] 执行分析表: {model['name']}")
                print(f"   目标表: {model['target_database']}.{model['table_name']}")
                print(f"   聚合细度: {model.get('granularity', 'hour')}")
                
                try:
                    result = self.execution_engine.execute_model(
                        model=model,
                        full_refresh=False,  # 增量模式
                        trigger_type='scheduled'
                    )
                    
                    results.append({
                        'model_id': model['id'],
                        'model_name': model['name'],
                        'model_type': 'analysis',
                        'success': result['success'],
                        'rows_affected': result['rows_affected'],
                        'duration': result['duration']
                    })
                    
                    if result['success']:
                        print(f"   ✅ 成功 - 影响行数: {result['rows_affected']}, 耗时: {result['duration']:.2f}秒")
                    else:
                        print(f"   ❌ 失败 - {result.get('message', '未知错误')}")
                    
                except Exception as e:
                    error_msg = str(e)
                    results.append({
                        'model_id': model['id'],
                        'model_name': model['name'],
                        'model_type': 'analysis',
                        'success': False,
                        'rows_affected': 0,
                        'duration': 0,
                        'error': error_msg
                    })
                    print(f"   ❌ 失败 - {error_msg}")
                    
                    self.logger.log_scheduler_event(
                        event_type="model_execution_error",
                        message=f"分析表 {model['name']} 执行失败: {error_msg}"
                    )
            
            analysis_success = sum(1 for r in results if r['model_type'] == 'analysis' and r['success'])
            print(f"\n📈 分析表阶段完成: {analysis_success}/{len(analysis_models)} 成功")
            
            self.logger.log_scheduler_event(
                event_type="analysis_phase_complete",
                message=f"分析表阶段完成: {analysis_success}/{len(analysis_models)} 成功"
            )
        
        # ========== 循环完成总结 ==========
        print("\n" + "=" * 80)
        success_count = sum(1 for r in results if r['success'])
        total_count = len(results)
        total_duration = sum(r['duration'] for r in results)
        
        print(f"✅ ETL 循环任务完成")
        print(f"   - 总计: {success_count}/{total_count} 成功")
        print(f"   - 总耗时: {total_duration:.2f} 秒")
        print("=" * 80 + "\n")
        
        # 更新最后执行时间
        self._update_last_run_time(results)
        
        # 记录循环执行结果
        self.logger.log_scheduler_event(
            event_type="etl_cycle_complete",
            message=f"ETL 循环任务完成: {success_count}/{total_count} 成功",
            details={
                'total_models': total_count,
                'success_models': success_count,
                'failed_models': total_count - success_count,
                'total_duration': total_duration,
                'link_models': len(link_models),
                'analysis_models': len(analysis_models),
                'results': results
            }
        )
    
    def _get_enabled_models(self) -> List[Dict[str, Any]]:
        """获取启用的模型"""
        try:
            from backend.models.etl_model import ETLModel
            from backend.models.etl_config import ETLConfig
            import json
            
            with self.config_manager.get_session() as session:
                # 获取全局配置的回算时间
                etl_config = session.query(ETLConfig).first()
                backfill_hours = etl_config.backfill_hours if etl_config else 24
                
                models = session.query(ETLModel).filter(
                    ETLModel.is_enabled == True,
                    ETLModel.is_draft == False
                ).all()
                
                result = []
                for m in models:
                    # 解析 unique_keys JSON
                    unique_keys = []
                    if m.unique_keys:
                        try:
                            unique_keys = json.loads(m.unique_keys)
                        except:
                            unique_keys = []
                    
                    model_dict = {
                        'id': m.id,
                        'name': m.name,
                        'table_name': m.table_name,
                        'model_type': m.model_type,
                        'source_table': m.source_table,
                        'source_database': m.source_database,
                        'target_database': m.target_database,
                        'sql_path': m.sql_path,
                        'backfill_hours': backfill_hours,
                        # 关联表专用字段
                        'unique_key_type': getattr(m, 'unique_key_type', 'none') or 'none',
                        'unique_key': getattr(m, 'unique_key', '') or '',
                        'unique_keys': unique_keys,
                        'incremental_field': getattr(m, 'incremental_field', 'upload_time') or 'upload_time',
                        # 分析表专用字段
                        'time_field': getattr(m, 'time_field', 'ServerTime'),
                        'granularity': getattr(m, 'granularity', 'hour'),
                        'time_field_name': getattr(m, 'time_field_name', 'hour')
                    }
                    result.append(model_dict)
                
                return result
                
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="get_models_error",
                message=f"获取启用模型失败: {str(e)}"
            )
            return []
    
    def _update_last_run_time(self, results: List[Dict[str, Any]]):
        """更新最后执行时间"""
        try:
            from backend.models.etl_config import ETLConfig
            from backend.core.logger import CHINA_TZ
            
            with self.config_manager.get_session() as session:
                config = session.query(ETLConfig).first()
                if config:
                    # 使用东八区时间
                    config.last_run_time = datetime.now(CHINA_TZ)
                    
                    # 判断整体执行状态
                    success_count = sum(1 for r in results if r['success'])
                    config.last_run_status = 'success' if success_count == len(results) else 'partial'
                    
                    session.commit()
                    
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="update_time_error",
                message=f"更新最后执行时间失败: {str(e)}"
            )
    
    def _cleanup_old_logs(self):
        """清理旧日志"""
        try:
            self.logger.cleanup_old_logs(keep_days=30)
            
            self.logger.log_scheduler_event(
                event_type="log_cleanup",
                message="旧日志清理完成"
            )
            
            print("🧹 旧日志清理完成")
            
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="log_cleanup_error",
                message=f"日志清理失败: {str(e)}"
            )
    
    def _log_resource_usage(self):
        """记录资源使用情况"""
        try:
            # 获取资源监控报告
            engine = self.execution_engine.engine if self.execution_engine else None
            report = ResourceMonitor.get_full_report(engine)
            
            # 提取关键指标
            mem = report.get('process_memory', {})
            pool = report.get('connection_pool', {})
            mysql = report.get('mysql_connections', {})
            
            # 构建日志消息
            message_parts = []
            if 'error' not in mem:
                message_parts.append(f"内存: {mem.get('rss_mb', 0)} MB ({mem.get('percent', 0)}%)")
                message_parts.append(f"线程: {mem.get('num_threads', 0)}")
            
            if 'error' not in pool:
                message_parts.append(f"连接池: {pool.get('checked_out', 0)}/{pool.get('total_connections', 0)}")
            
            if 'error' not in mysql:
                message_parts.append(f"MySQL: {mysql.get('threads_connected', 0)}/{mysql.get('max_connections', 0)}")
            
            message = " | ".join(message_parts)
            
            # 记录到日志
            self.logger.log_scheduler_event(
                event_type="resource_monitor",
                message=message
            )
            
            # 打印到控制台
            print(f"📊 资源监控: {message}")
            
            # 如果内存使用超过 80%，发出警告
            if mem.get('percent', 0) > 80:
                warning_msg = f"⚠️  内存使用率过高: {mem.get('percent', 0)}%"
                print(warning_msg)
                self.logger.log_scheduler_event(
                    event_type="resource_warning",
                    message=warning_msg
                )
            
            # 如果 MySQL 连接使用率超过 80%，发出警告
            if mysql.get('usage_percent', 0) > 80:
                warning_msg = f"⚠️  MySQL 连接使用率过高: {mysql.get('usage_percent', 0)}%"
                print(warning_msg)
                self.logger.log_scheduler_event(
                    event_type="resource_warning",
                    message=warning_msg
                )
            
        except Exception as e:
            print(f"❌ 资源监控失败: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """获取调度器状态"""
        etl_config = self.config_manager.get_etl_config()
        
        return {
            'is_running': self.is_running,
            'etl_active': etl_config['is_active'] if etl_config else False,
            'last_run_time': etl_config['last_run_time'] if etl_config else None,
            'last_run_status': etl_config['last_run_status'] if etl_config else None,
            'run_interval': etl_config['run_interval'] if etl_config else 60,
            'next_jobs': [str(job) for job in schedule.jobs] if self.is_running else []
        }
    
    def run_manual_etl(self, model_ids: Optional[List[int]] = None, full_refresh: bool = False) -> Dict[str, Any]:
        """
        手动执行 ETL 任务
        
        Args:
            model_ids: 要执行的模型ID列表，None 表示执行所有启用的模型
            full_refresh: 是否全量刷新
            
        Returns:
            执行结果
        """
        if not self.execution_engine:
            self._init_execution_engine()
            if not self.execution_engine:
                return {
                    'success': False,
                    'message': '执行引擎未初始化',
                    'results': []
                }
        
        # 获取要执行的模型
        if model_ids:
            models = self._get_models_by_ids(model_ids)
        else:
            models = self._get_enabled_models()
        
        if not models:
            return {
                'success': False,
                'message': '没有找到要执行的模型',
                'results': []
            }
        
        # 执行模型
        results = []
        for model in models:
            try:
                result = self.execution_engine.execute_model(
                    model, 
                    full_refresh=full_refresh,
                    trigger_type='manual'
                )
                results.append({
                    'model_id': model['id'],
                    'model_name': model['name'],
                    'success': result['success'],
                    'message': result['message'],
                    'rows_affected': result['rows_affected'],
                    'duration': result['duration']
                })
                
            except Exception as e:
                error_msg = str(e)
                # 检查是否是超时错误
                if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                    error_msg = f'执行超时（超过 {self.execution_engine.timeout} 秒）: {error_msg}'
                else:
                    error_msg = f'执行失败: {error_msg}'
                
                results.append({
                    'model_id': model['id'],
                    'model_name': model['name'],
                    'success': False,
                    'message': error_msg,
                    'rows_affected': 0,
                    'duration': 0
                })
        
        success_count = sum(1 for r in results if r['success'])
        
        return {
            'success': success_count > 0,
            'message': f'执行完成: {success_count}/{len(results)} 成功',
            'results': results
        }
    
    def _get_models_by_ids(self, model_ids: List[int]) -> List[Dict[str, Any]]:
        """根据ID获取模型"""
        try:
            from backend.models.etl_model import ETLModel
            from backend.models.etl_config import ETLConfig
            import json
            
            with self.config_manager.get_session() as session:
                # 获取全局配置的回算时间
                etl_config = session.query(ETLConfig).first()
                backfill_hours = etl_config.backfill_hours if etl_config else 24
                
                models = session.query(ETLModel).filter(
                    ETLModel.id.in_(model_ids)
                ).all()
                
                result = []
                for m in models:
                    # 解析 unique_keys JSON
                    unique_keys = []
                    if m.unique_keys:
                        try:
                            unique_keys = json.loads(m.unique_keys)
                        except:
                            unique_keys = []
                    
                    model_dict = {
                        'id': m.id,
                        'name': m.name,
                        'table_name': m.table_name,
                        'model_type': m.model_type,
                        'source_table': m.source_table,
                        'source_database': m.source_database,
                        'target_database': m.target_database,
                        'sql_path': m.sql_path,
                        'backfill_hours': backfill_hours,
                        # 关联表专用字段
                        'unique_key_type': getattr(m, 'unique_key_type', 'none') or 'none',
                        'unique_key': getattr(m, 'unique_key', '') or '',
                        'unique_keys': unique_keys,
                        'incremental_field': getattr(m, 'incremental_field', 'upload_time') or 'upload_time',
                        # 分析表专用字段
                        'time_field': getattr(m, 'time_field', 'ServerTime'),
                        'granularity': getattr(m, 'granularity', 'hour'),
                        'time_field_name': getattr(m, 'time_field_name', 'hour')
                    }
                    result.append(model_dict)
                
                return result
                
        except Exception as e:
            self.logger.log_scheduler_event(
                event_type="get_models_error",
                message=f"根据ID获取模型失败: {str(e)}"
            )
            return []


# 全局调度器实例
_task_scheduler: Optional[TaskScheduler] = None


def get_task_scheduler() -> TaskScheduler:
    """获取全局任务调度器实例"""
    global _task_scheduler
    
    if _task_scheduler is None:
        _task_scheduler = TaskScheduler()
    
    return _task_scheduler