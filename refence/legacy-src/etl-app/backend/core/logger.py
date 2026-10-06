"""
ETL 日志记录器
"""
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# 东八区时区
CHINA_TZ = timezone(timedelta(hours=8))


class ETLLogger:
    """ETL 日志记录器"""
    
    def __init__(self, log_dir: str = "data/logs"):
        """
        初始化日志记录器
        
        Args:
            log_dir: 日志目录路径
        """
        self.log_dir = Path(log_dir)
        self.etl_dir = self.log_dir / "etl"
        self.scheduler_dir = self.log_dir / "scheduler"
        
        # 创建日志目录
        self.etl_dir.mkdir(parents=True, exist_ok=True)
        self.scheduler_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_china_time(self) -> datetime:
        """获取东八区时间"""
        return datetime.now(CHINA_TZ)
    
    def log_etl_execution(
        self,
        model_id: int,
        model_name: str,
        model_type: str,
        status: str,
        run_mode: str,
        trigger_type: str,
        message: str,
        rows_affected: Optional[int] = None,
        duration: Optional[float] = None,
        execution_logs: Optional[List[Dict]] = None
    ) -> str:
        """
        记录 ETL 执行日志
        
        Args:
            model_id: 模型ID
            model_name: 模型名称
            model_type: 模型类型
            status: 执行状态
            run_mode: 运行模式
            trigger_type: 触发类型
            message: 执行消息
            rows_affected: 影响行数
            duration: 执行时长
            execution_logs: 详细执行日志
            
        Returns:
            日志文件路径
        """
        # 按日期分文件（使用东八区时间）
        china_time = self._get_china_time()
        date_str = china_time.strftime('%Y%m%d')
        log_file = self.etl_dir / f"{date_str}.jsonl"
        
        # 构造日志记录（使用东八区时间）
        log_entry = {
            "timestamp": china_time.isoformat(),
            "model_id": model_id,
            "model_name": model_name,
            "model_type": model_type,
            "status": status,
            "run_mode": run_mode,
            "trigger_type": trigger_type,
            "message": message,
            "rows_affected": rows_affected,
            "duration": duration,
            "execution_logs": execution_logs or []
        }
        
        # 写入日志文件
        self._write_log(log_file, log_entry)
        
        return str(log_file)
    
    def log_scheduler_event(
        self,
        event_type: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        记录调度器事件日志
        
        Args:
            event_type: 事件类型
            message: 事件消息
            details: 事件详情
            
        Returns:
            日志文件路径
        """
        china_time = self._get_china_time()
        date_str = china_time.strftime('%Y%m%d')
        log_file = self.scheduler_dir / f"{date_str}.jsonl"
        
        log_entry = {
            "timestamp": china_time.isoformat(),
            "event_type": event_type,
            "message": message,
            "details": details or {}
        }
        
        self._write_log(log_file, log_entry)
        
        return str(log_file)
    
    def _write_log(self, log_file: Path, log_entry: Dict[str, Any]):
        """
        写入日志到文件
        
        Args:
            log_file: 日志文件路径
            log_entry: 日志条目
        """
        try:
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            print(f"写入日志失败: {e}")
    
    def read_etl_logs(
        self,
        date: Optional[str] = None,
        model_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        读取 ETL 执行日志
        
        Args:
            date: 日期（YYYYMMDD），None 表示今天
            model_name: 模型名称过滤
            limit: 返回记录数限制
            
        Returns:
            日志列表（倒序）
        """
        if date is None:
            china_time = self._get_china_time()
            date = china_time.strftime('%Y%m%d')
        
        log_file = self.etl_dir / f"{date}.jsonl"
        
        if not log_file.exists():
            return []
        
        logs = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log = json.loads(line.strip())
                        if model_name is None or log.get('model_name') == model_name:
                            logs.append(log)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"读取日志失败: {e}")
            return []
        
        # 倒序返回最新的记录
        return logs[-limit:][::-1]
    
    def read_scheduler_logs(
        self,
        date: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        读取调度器日志
        
        Args:
            date: 日期（YYYYMMDD），None 表示今天
            event_type: 事件类型过滤
            limit: 返回记录数限制
            
        Returns:
            日志列表（倒序）
        """
        if date is None:
            china_time = self._get_china_time()
            date = china_time.strftime('%Y%m%d')
        
        log_file = self.scheduler_dir / f"{date}.jsonl"
        
        if not log_file.exists():
            return []
        
        logs = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log = json.loads(line.strip())
                        if event_type is None or log.get('event_type') == event_type:
                            logs.append(log)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            print(f"读取日志失败: {e}")
            return []
        
        return logs[-limit:][::-1]
    
    def get_etl_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        获取 ETL 统计信息
        
        Args:
            days: 统计天数
            
        Returns:
            统计信息
        """
        from datetime import timedelta
        
        total_runs = 0
        success_runs = 0
        failed_runs = 0
        
        # 遍历最近 N 天的日志文件
        for i in range(days):
            # 使用东八区时间
            date = (self._get_china_time() - timedelta(days=i)).strftime('%Y%m%d')
            logs = self.read_etl_logs(date=date, limit=1000)
            
            for log in logs:
                total_runs += 1
                if log.get('status') == 'success':
                    success_runs += 1
                elif log.get('status') == 'failed':
                    failed_runs += 1
        
        # 计算成功率
        success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0, 1)
        
        return {
            'total_runs': total_runs,
            'success_runs': success_runs,
            'failed_runs': failed_runs,
            'success_rate': success_rate,
            'days': days
        }
    
    def cleanup_old_logs(self, keep_days: int = 30):
        """
        清理旧日志文件
        
        Args:
            keep_days: 保留天数
        """
        from datetime import timedelta
        
        # 使用东八区时间
        cutoff_date = self._get_china_time() - timedelta(days=keep_days)
        cutoff_str = cutoff_date.strftime('%Y%m%d')
        
        # 清理 ETL 日志
        for log_file in self.etl_dir.glob("*.jsonl"):
            if log_file.stem < cutoff_str:
                try:
                    log_file.unlink()
                    print(f"删除旧日志文件: {log_file}")
                except Exception as e:
                    print(f"删除日志文件失败: {e}")
        
        # 清理调度器日志
        for log_file in self.scheduler_dir.glob("*.jsonl"):
            if log_file.stem < cutoff_str:
                try:
                    log_file.unlink()
                    print(f"删除旧日志文件: {log_file}")
                except Exception as e:
                    print(f"删除日志文件失败: {e}")


# 全局日志实例
_etl_logger: Optional[ETLLogger] = None


def get_etl_logger(log_dir: Optional[str] = None) -> ETLLogger:
    """获取全局日志记录器实例"""
    global _etl_logger
    
    if _etl_logger is None:
        _etl_logger = ETLLogger(log_dir or "data/logs")
    
    return _etl_logger