"""
ETL 执行引擎 - 执行 SQL 文件和数据转换任务
"""
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy import text

from backend.utils.database import get_mysql_engine
from backend.utils.helpers import format_duration, get_current_timestamp
from backend.core.logger import get_etl_logger


class ExecutionEngine:
    """ETL 执行引擎"""
    
    def __init__(self, mysql_config: Dict[str, Any], timeout: int = 300):
        """
        初始化执行引擎
        
        Args:
            mysql_config: MySQL 配置
            timeout: SQL 执行超时时间（秒），默认 300 秒
        """
        self.mysql_config = mysql_config
        self.engine = get_mysql_engine(mysql_config)
        self.logger = get_etl_logger()
        self.timeout = timeout
    
    def close(self):
        """关闭数据库引擎，释放连接池资源"""
        if self.engine:
            try:
                self.engine.dispose()
                print("✅ 执行引擎数据库连接已释放")
            except Exception as e:
                print(f"⚠️  释放数据库连接时出错: {e}")
            finally:
                self.engine = None
    
    def __del__(self):
        """析构函数，确保资源释放"""
        self.close()
    
    def execute_model(
        self,
        model: Dict[str, Any],
        full_refresh: bool = False,
        trigger_type: str = 'manual'
    ) -> Dict[str, Any]:
        """
        执行 ETL 模型
        
        Args:
            model: 模型配置字典
            full_refresh: 是否全量刷新
            
        Returns:
            执行结果
        """
        start_time = time.time()
        execution_logs = []
        
        def add_log(level: str, message: str):
            """添加执行日志"""
            execution_logs.append({
                'time': get_current_timestamp(),
                'level': level,
                'message': message
            })
        
        try:
            model_id = model.get('id', 0)
            model_name = model.get('name', 'Unknown')
            model_type = model.get('model_type', 'link')
            sql_path = model.get('sql_path', '')
            
            add_log('info', f'开始执行模型: {model_name}')
            add_log('info', f'模型类型: {model_type}')
            add_log('info', f'运行模式: {"全量刷新" if full_refresh else "增量更新"}')
            add_log('info', f'SQL 文件: {sql_path}')
            
            # 读取 SQL 文件
            sql_content = self._read_sql_file(sql_path)
            add_log('info', '成功读取 SQL 文件')
            
            # 根据模型类型执行
            if model_type == 'link':
                result = self._execute_link_model(model, sql_content, full_refresh, add_log)
            elif model_type == 'analysis':
                result = self._execute_analysis_model(model, sql_content, full_refresh, add_log)
            else:
                raise ValueError(f"不支持的模型类型: {model_type}")
            
            duration = time.time() - start_time
            
            if result['success']:
                add_log('success', f'模型执行成功')
                add_log('info', f'执行耗时: {format_duration(duration)}')
            else:
                add_log('error', f'模型执行失败: {result["message"]}')
            
            # 记录执行日志
            self.logger.log_etl_execution(
                model_id=model_id,
                model_name=model_name,
                model_type=model_type,
                status='success' if result['success'] else 'failed',
                run_mode='full' if full_refresh else 'incremental',
                trigger_type=trigger_type,  # 使用传入的触发类型
                message=result['message'],
                rows_affected=result['rows_affected'],
                duration=duration,
                execution_logs=execution_logs
            )
            
            return {
                'success': result['success'],
                'message': result['message'],
                'rows_affected': result['rows_affected'],
                'duration': duration,
                'execution_logs': execution_logs
            }
            
        except Exception as e:
            duration = time.time() - start_time
            error_msg = str(e)
            
            # 检查是否是超时错误
            if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                error_msg = f'执行超时（超过 {self.timeout} 秒）: {error_msg}'
            else:
                error_msg = f'执行失败: {error_msg}'
            
            add_log('error', error_msg)
            
            # 记录错误日志
            self.logger.log_etl_execution(
                model_id=model.get('id', 0),
                model_name=model.get('name', 'Unknown'),
                model_type=model.get('model_type', 'link'),
                status='failed',
                run_mode='full' if full_refresh else 'incremental',
                trigger_type=trigger_type,  # 使用传入的触发类型
                message=error_msg,
                rows_affected=0,
                duration=duration,
                execution_logs=execution_logs
            )
            
            return {
                'success': False,
                'message': error_msg,
                'rows_affected': 0,
                'duration': duration,
                'execution_logs': execution_logs
            }
    
    def _read_sql_file(self, sql_path: str) -> str:
        """
        读取 SQL 文件
        
        Args:
            sql_path: SQL 文件路径
            
        Returns:
            SQL 内容
        """
        # 如果是相对路径，转换为绝对路径
        if not Path(sql_path).is_absolute():
            etl_root = Path(__file__).parent.parent.parent
            sql_path = str(etl_root / sql_path)
        
        file_path = Path(sql_path)
        if not file_path.exists():
            raise FileNotFoundError(f"SQL 文件不存在: {sql_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    def _execute_link_model(
        self,
        model: Dict[str, Any],
        sql_content: str,
        full_refresh: bool,
        add_log: callable
    ) -> Dict[str, Any]:
        """
        执行关联表模型
        
        Args:
            model: 模型配置
            sql_content: SQL 内容
            full_refresh: 是否全量刷新
            add_log: 日志记录函数
            
        Returns:
            执行结果
        """
        target_database = model.get('target_database', 'link_db')
        table_name = model.get('table_name')
        target_table = f"{target_database}.{table_name}"
        
        # 获取唯一键配置
        unique_key_type = model.get('unique_key_type', 'none')
        unique_key = model.get('unique_key')
        unique_keys = model.get('unique_keys', [])
        
        # 获取增量更新字段
        incremental_field = model.get('incremental_field', 'upload_time')
        
        with self.engine.connect().execution_options(timeout=self.timeout) as conn:
            if full_refresh:
                # 全量刷新：删表重建
                add_log('info', f'全量刷新：删除表 {target_table}')
                
                try:
                    # 1. 删除表
                    conn.execute(text(f"DROP TABLE IF EXISTS {target_table}"))
                    conn.commit()
                    add_log('info', f'表已删除: {target_table}')
                    
                    # 2. 重新创建表（使用 CREATE TABLE AS SELECT）
                    add_log('info', f'重新创建表: {target_table}')
                    create_sql = f"CREATE TABLE {target_table} AS\n{sql_content}"
                    conn.execute(text(create_sql))
                    conn.commit()
                    
                    # 3. 创建唯一索引
                    if unique_key_type == 'single' and unique_key:
                        index_name = f"uk_{table_name}_{unique_key}"
                        add_log('info', f'创建唯一索引: {index_name}')
                        index_sql = f"ALTER TABLE {target_table} ADD UNIQUE KEY `{index_name}` (`{unique_key}`)"
                        conn.execute(text(index_sql))
                        conn.commit()
                        add_log('info', f'唯一索引创建成功: {index_name}')
                    
                    elif unique_key_type == 'composite' and unique_keys:
                        index_name = f"uk_{table_name}_composite"
                        index_fields = ', '.join([f"`{key}`" for key in unique_keys])
                        add_log('info', f'创建复合唯一索引: {index_name}')
                        index_sql = f"ALTER TABLE {target_table} ADD UNIQUE KEY `{index_name}` ({index_fields})"
                        conn.execute(text(index_sql))
                        conn.commit()
                        add_log('info', f'复合唯一索引创建成功: {index_name}')
                    
                    # 4. 查询行数
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {target_table}"))
                    rows_affected = result.scalar()
                    add_log('info', f'表重建完成，共 {rows_affected} 行数据')
                    
                except Exception as e:
                    add_log('error', f'删表重建失败: {str(e)}')
                    raise
                
            else:
                # 增量更新：获取最后更新时间
                add_log('info', f'增量更新：查询表 {target_table} 的最后更新时间')
                add_log('info', f'增量更新字段: {incremental_field}')
                
                try:
                    # 查询最大时间（使用配置的增量字段）
                    max_time_sql = f"""
                        SELECT COALESCE(MAX(`{incremental_field}`), '1970-01-01 00:00:00')
                        FROM {target_table}
                    """
                    result = conn.execute(text(max_time_sql))
                    last_update_time = result.scalar()
                    
                    add_log('info', f'最后更新时间: {last_update_time}')
                    
                    # WHERE 子句应该使用目标字段名（因为它在 SELECT 外部）
                    # 增量字段就是目标表中的字段名
                    add_log('info', f'使用目标字段名作为增量字段: {incremental_field}')
                    where_clause = f"WHERE `{incremental_field}` > '{last_update_time}'"
                    
                    # 根据唯一键类型选择插入方式
                    if unique_key_type != 'none':
                        # 使用 REPLACE INTO（自动处理新增和更新）
                        add_log('info', f'使用 REPLACE INTO 增量更新（唯一键类型: {unique_key_type}）')
                        insert_sql = f"""
                            REPLACE INTO {target_table}
                            {sql_content}
                            {where_clause}
                        """
                    else:
                        # 使用普通 INSERT
                        add_log('info', f'使用 INSERT INTO 增量更新（无唯一键）')
                        insert_sql = f"""
                            INSERT INTO {target_table}
                            {sql_content}
                            {where_clause}
                        """
                    
                    result = conn.execute(text(insert_sql))
                    conn.commit()
                    
                    rows_affected = result.rowcount
                    
                except Exception as e:
                    # 如果查询失败，可能是表不存在或字段不存在
                    error_msg = str(e)
                    
                    # 检查是否是表不存在的错误
                    if "doesn't exist" in error_msg or "Table" in error_msg and "doesn't exist" in error_msg:
                        add_log('warning', f'目标表不存在，自动创建表')
                        
                        try:
                            # 创建表（使用 CREATE TABLE AS SELECT）
                            create_sql = f"CREATE TABLE {target_table} AS\n{sql_content}"
                            conn.execute(text(create_sql))
                            conn.commit()
                            add_log('info', f'表创建成功: {target_table}')
                            
                            # 创建唯一索引
                            if unique_key_type == 'single' and unique_key:
                                index_name = f"uk_{table_name}_{unique_key}"
                                add_log('info', f'创建唯一索引: {index_name}')
                                index_sql = f"ALTER TABLE {target_table} ADD UNIQUE KEY `{index_name}` (`{unique_key}`)"
                                conn.execute(text(index_sql))
                                conn.commit()
                                add_log('info', f'唯一索引创建成功: {index_name}')
                            
                            elif unique_key_type == 'composite' and unique_keys:
                                index_name = f"uk_{table_name}_composite"
                                index_fields = ', '.join([f"`{key}`" for key in unique_keys])
                                add_log('info', f'创建复合唯一索引: {index_name}')
                                index_sql = f"ALTER TABLE {target_table} ADD UNIQUE KEY `{index_name}` ({index_fields})"
                                conn.execute(text(index_sql))
                                conn.commit()
                                add_log('info', f'复合唯一索引创建成功: {index_name}')
                            
                            # 查询行数
                            result = conn.execute(text(f"SELECT COUNT(*) FROM {target_table}"))
                            rows_affected = result.scalar()
                            add_log('info', f'表创建完成，共 {rows_affected} 行数据')
                            
                        except Exception as create_error:
                            add_log('error', f'创建表失败: {str(create_error)}')
                            raise
                    else:
                        # 其他错误，执行全量插入
                        add_log('warning', f'增量查询失败，执行全量插入: {error_msg}')
                        
                        if unique_key_type != 'none':
                            add_log('info', f'使用 REPLACE INTO 全量插入（唯一键类型: {unique_key_type}）')
                            insert_sql = f"REPLACE INTO {target_table}\n{sql_content}"
                        else:
                            add_log('info', f'使用 INSERT INTO 全量插入（无唯一键）')
                            insert_sql = f"INSERT INTO {target_table}\n{sql_content}"
                        
                        result = conn.execute(text(insert_sql))
                        conn.commit()
                        rows_affected = result.rowcount
            
            add_log('info', f'关联表执行完成，影响行数: {rows_affected}')
            
            # 创建或更新视图
            try:
                view_name = f"v_{table_name}_recent"
                view_full_name = f"{target_database}.{view_name}"
                add_log('info', f'开始创建/更新视图: {view_full_name}')
                
                # 读取视图 SQL 文件（使用绝对路径）
                from pathlib import Path
                # 获取项目根目录（backend 的父目录）
                project_root = Path(__file__).parent.parent.parent
                views_dir = project_root / "sql_models" / "views"
                view_file = views_dir / f"{view_name}.sql"
                
                if view_file.exists():
                    with open(view_file, 'r', encoding='utf-8') as f:
                        view_sql = f.read()
                    
                    # 执行视图创建
                    conn.execute(text(view_sql))
                    conn.commit()
                    
                    # 查询视图中的实际数据量
                    try:
                        view_count_result = conn.execute(text(f"SELECT COUNT(*) FROM {view_full_name}"))
                        view_count = view_count_result.scalar()
                        add_log('success', f'视图创建/更新成功: {view_full_name}')
                        add_log('info', f'视图数据量: {view_count}')
                    except Exception as count_error:
                        add_log('success', f'视图创建/更新成功: {view_full_name}')
                        add_log('warning', f'无法查询视图数据量: {str(count_error)}')
                else:
                    add_log('warning', f'视图 SQL 文件不存在: {view_file}')
            except Exception as view_error:
                add_log('warning', f'视图创建失败（不影响主流程）: {str(view_error)}')
            
            return {
                'success': True,
                'message': '执行成功',
                'rows_affected': rows_affected
            }
    
    def _execute_analysis_model(
        self,
        model: Dict[str, Any],
        sql_content: str,
        full_refresh: bool,
        add_log: callable
    ) -> Dict[str, Any]:
        """
        执行分析表模型
        
        全量逻辑：删除表的所有数据，重新生成
        增量逻辑：删除时间分组字段在回算时间范围内的数据，重新生成这部分数据
        
        Args:
            model: 模型配置
            sql_content: SQL 内容
            full_refresh: 是否全量刷新
            add_log: 日志记录函数
            
        Returns:
            执行结果
        """
        target_database = model.get('target_database', 'analytics_dw')
        table_name = model.get('table_name')
        target_table = f"{target_database}.{table_name}"
        backfill_hours = model.get('backfill_hours', 24)
        
        # 获取时间分组字段名（生成的时间字段）
        time_field_name = model.get('time_field_name', 'hour')
        granularity = model.get('granularity', 'hour')
        
        with self.engine.connect().execution_options(timeout=self.timeout) as conn:
            # ========== 检查表是否存在 ==========
            check_table_sql = f"""
                SELECT COUNT(*) as count
                FROM information_schema.tables
                WHERE table_schema = '{target_database}'
                AND table_name = '{table_name}'
            """
            result = conn.execute(text(check_table_sql))
            table_exists = result.fetchone()[0] > 0
            
            if full_refresh:
                # ========== 全量刷新：删除表并重建 ==========
                if table_exists:
                    add_log('info', f'全量刷新：删除表 {target_table}')
                    try:
                        drop_sql = f"DROP TABLE {target_table}"
                        conn.execute(text(drop_sql))
                        conn.commit()
                        add_log('info', f'表已删除: {target_table}')
                    except Exception as e:
                        add_log('warning', f'删除表失败: {str(e)}')
                else:
                    add_log('info', f'表不存在，将创建新表: {target_table}')
                
                # 创建表并插入数据（使用 CREATE TABLE AS SELECT）
                add_log('info', f'开始创建表并生成全量数据...')
                create_sql = f"CREATE TABLE {target_table} AS\n{sql_content}"
                result = conn.execute(text(create_sql))
                conn.commit()
                
                # 查询实际生成的行数
                count_sql = f"SELECT COUNT(*) as count FROM {target_table}"
                count_result = conn.execute(text(count_sql))
                rows_affected = count_result.fetchone()[0]
                
                add_log('info', f'全量刷新完成，生成 {rows_affected} 条数据')
                
            else:
                # ========== 增量更新：删除回算时间范围内的数据 ==========
                
                # 如果表不存在，转为全量刷新
                if not table_exists:
                    add_log('warning', f'表不存在，转为全量刷新模式')
                    add_log('info', f'开始创建表并生成全量数据...')
                    create_sql = f"CREATE TABLE {target_table} AS\n{sql_content}"
                    result = conn.execute(text(create_sql))
                    conn.commit()
                    
                    # 查询实际生成的行数
                    count_sql = f"SELECT COUNT(*) as count FROM {target_table}"
                    count_result = conn.execute(text(count_sql))
                    rows_affected = count_result.fetchone()[0]
                    
                    add_log('info', f'全量刷新完成，生成 {rows_affected} 条数据')
                else:
                    # 表存在，执行增量更新
                    add_log('info', f'增量更新：删除表 {target_table} 最近 {backfill_hours} 小时的数据')
                    
                    try:
                        # 根据聚合细度构建删除条件
                        if granularity == 'hour':
                            # 小时聚合：删除最近 N 小时的数据
                            delete_condition = f"`{time_field_name}` >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL {backfill_hours} HOUR), '%Y-%m-%d %H:00:00')"
                        elif granularity == 'day':
                            # 天聚合：删除最近 N 小时对应的天数
                            days = max(1, backfill_hours // 24)
                            delete_condition = f"`{time_field_name}` >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL {days} DAY), '%Y-%m-%d')"
                        elif granularity == 'week':
                            # 周聚合：删除最近 N 小时对应的周数
                            weeks = max(1, backfill_hours // (24 * 7))
                            delete_condition = f"`{time_field_name}` >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL {weeks} WEEK), '%Y-%u')"
                        elif granularity == 'month':
                            # 月聚合：删除最近 N 小时对应的月数
                            months = max(1, backfill_hours // (24 * 30))
                            delete_condition = f"`{time_field_name}` >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL {months} MONTH), '%Y-%m')"
                        else:
                            # 默认按小时
                            delete_condition = f"`{time_field_name}` >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL {backfill_hours} HOUR), '%Y-%m-%d %H:00:00')"
                        
                        # 删除回算时间范围内的数据
                        delete_sql = f"DELETE FROM {target_table} WHERE {delete_condition}"
                        delete_result = conn.execute(text(delete_sql))
                        conn.commit()
                        
                        deleted_rows = delete_result.rowcount
                        add_log('info', f'已删除 {deleted_rows} 条旧数据')
                        
                        # 执行插入（只生成回算时间范围内的数据）
                        add_log('info', f'开始生成最近 {backfill_hours} 小时的数据...')
                        
                        # 在 SQL 中添加 WHERE 条件，只计算回算时间范围内的源数据
                        # 需要获取源表的时间字段
                        source_time_field = model.get('time_field', 'ServerTime')
                        
                        # 在 SQL 的 FROM 子句后添加 WHERE 条件
                        # 如果 SQL 包含 WITH 子句，需要在 CTE 内部添加
                        if 'WITH' in sql_content.upper():
                            # 有 CTE，在 CTE 的 FROM 后添加 WHERE
                            # 查找 "FROM source_database.source_table" 并在后面添加 WHERE
                            source_database = model.get('source_database', 'link_db')
                            source_table = model.get('source_table', '')
                            from_clause = f"FROM {source_database}.{source_table}"
                            
                            if from_clause in sql_content:
                                where_clause = f"\n    WHERE `{source_time_field}` >= DATE_SUB(NOW(), INTERVAL {backfill_hours} HOUR)"
                                sql_with_filter = sql_content.replace(
                                    from_clause,
                                    f"{from_clause}{where_clause}"
                                )
                            else:
                                # 找不到 FROM 子句，使用原始 SQL
                                sql_with_filter = sql_content
                                add_log('warning', '无法在 SQL 中添加时间过滤条件，将计算所有数据')
                        else:
                            # 没有 CTE，直接在 FROM 后添加 WHERE
                            source_database = model.get('source_database', 'link_db')
                            source_table = model.get('source_table', '')
                            from_clause = f"FROM {source_database}.{source_table}"
                            
                            if from_clause in sql_content:
                                where_clause = f"\nWHERE `{source_time_field}` >= DATE_SUB(NOW(), INTERVAL {backfill_hours} HOUR)"
                                sql_with_filter = sql_content.replace(
                                    from_clause,
                                    f"{from_clause}{where_clause}"
                                )
                            else:
                                # 找不到 FROM 子句，使用原始 SQL
                                sql_with_filter = sql_content
                                add_log('warning', '无法在 SQL 中添加时间过滤条件，将计算所有数据')
                        
                        insert_sql = f"INSERT INTO {target_table}\n{sql_with_filter}"
                        result = conn.execute(text(insert_sql))
                        conn.commit()
                        
                        rows_affected = result.rowcount
                        add_log('info', f'增量更新完成，生成 {rows_affected} 条新数据')
                        
                    except Exception as e:
                        add_log('error', f'增量更新失败: {str(e)}')
                        raise
            
            return {
                'success': True,
                'message': '执行成功',
                'rows_affected': rows_affected
            }
    
    def test_sql(self, sql_content: str, limit: int = 10) -> Dict[str, Any]:
        """
        测试 SQL 语句
        
        Args:
            sql_content: SQL 内容
            limit: 返回行数限制
            
        Returns:
            测试结果
        """
        try:
            # 添加 LIMIT 限制
            test_sql = f"SELECT * FROM ({sql_content}) AS test_query LIMIT {limit}"
            
            with self.engine.connect().execution_options(timeout=self.timeout) as conn:
                result = conn.execute(text(test_sql))
                rows = result.fetchall()
                columns = list(result.keys())
                
                return {
                    'success': True,
                    'message': '测试成功',
                    'columns': columns,
                    'rows': [dict(zip(columns, row)) for row in rows],
                    'row_count': len(rows)
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'测试失败: {str(e)}',
                'columns': [],
                'rows': [],
                'row_count': 0
            }