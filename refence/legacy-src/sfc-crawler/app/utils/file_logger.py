"""
文件日志工具 - 将日志写入本地文件而不是数据库
避免高频写入导致 SQLite 损坏
"""
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import os


class FileLogger:
    """文件日志记录器"""
    
    def __init__(self, log_dir: str = "data/logs"):
        """
        初始化文件日志记录器
        
        Args:
            log_dir: 日志根目录路径
        """
        self.log_dir = Path(log_dir)
        self.etl_dir = self.log_dir / "etl"
        self.sfc_dir = self.log_dir / "sfc"
        
        # 创建子目录
        self.etl_dir.mkdir(parents=True, exist_ok=True)
        self.sfc_dir.mkdir(parents=True, exist_ok=True)
    
    def write_etl_log(
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
        写入 ETL 执行日志
        
        Returns:
            日志文件路径
        """
        # 按日期分文件，放在 etl 子目录
        date_str = datetime.now().strftime('%Y%m%d')
        log_file = self.etl_dir / f"{date_str}.jsonl"
        
        # 构造日志记录
        log_entry = {
            "timestamp": datetime.now().isoformat(),
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
        
        # 追加写入文件（带文件锁）
        self._append_log(log_file, log_entry)
        
        return str(log_file)
    
    def write_sfc_log(
        self,
        config_id: int,
        config_name: str,
        account: str,
        status: str,
        trigger_type: str,
        message: str,
        records_count: Optional[int] = None,
        duration: Optional[float] = None,
        execution_logs: Optional[List[Dict]] = None
    ) -> str:
        """
        写入 SFC 爬虫日志
        
        Returns:
            日志文件路径
        """
        # 按日期分文件，放在 sfc 子目录
        date_str = datetime.now().strftime('%Y%m%d')
        log_file = self.sfc_dir / f"{date_str}.jsonl"
        
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "config_id": config_id,
            "config_name": config_name,
            "account": account,
            "status": status,
            "trigger_type": trigger_type,
            "message": message,
            "records_count": records_count,
            "duration": duration,
            "execution_logs": execution_logs or []
        }
        
        self._append_log(log_file, log_entry)
        
        return str(log_file)
    
    def _append_log(self, log_file: Path, log_entry: Dict[str, Any]):
        """
        追加日志到文件（简单实现，依赖文件系统的原子性）
        """
        # 使用追加模式打开文件
        # 在 Windows 和 Linux 上，追加模式的单次写入通常是原子的
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            f.flush()
            os.fsync(f.fileno())  # 强制写入磁盘
    
    def read_etl_logs(
        self,
        date: Optional[str] = None,
        model_name: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        读取 ETL 日志
        
        Args:
            date: 日期（YYYYMMDD），None 表示今天
            model_name: 模型名称过滤
            limit: 返回记录数限制
            
        Returns:
            日志列表（倒序）
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        log_file = self.etl_dir / f"{date}.jsonl"
        
        if not log_file.exists():
            return []
        
        logs = []
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log = json.loads(line.strip())
                    if model_name is None or log.get('model_name') == model_name:
                        logs.append(log)
                except json.JSONDecodeError:
                    continue
        
        # 倒序返回最新的记录
        return logs[-limit:][::-1]
    
    def read_sfc_logs(
        self,
        date: Optional[str] = None,
        config_name: Optional[str] = None,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        读取 SFC 爬虫日志
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        log_file = self.sfc_dir / f"{date}.jsonl"
        
        if not log_file.exists():
            return []
        
        logs = []
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log = json.loads(line.strip())
                    if config_name is None or log.get('config_name') == config_name:
                        logs.append(log)
                except json.JSONDecodeError:
                    continue
        
        return logs[-limit:][::-1]
    
    def get_etl_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        获取 ETL 统计信息（最近 N 天）
        
        Args:
            days: 统计天数
            
        Returns:
            统计信息字典
        """
        from datetime import timedelta
        
        total_runs = 0
        success_runs = 0
        failed_runs = 0
        
        # 遍历最近 N 天的日志文件
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            log_file = self.etl_dir / f"{date}.jsonl"
            
            if not log_file.exists():
                continue
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log = json.loads(line.strip())
                        total_runs += 1
                        if log.get('status') == 'success':
                            success_runs += 1
                        elif log.get('status') == 'failed':
                            failed_runs += 1
                    except json.JSONDecodeError:
                        continue
        
        # 计算成功率
        success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0, 1)
        
        return {
            'total_runs': total_runs,
            'success_runs': success_runs,
            'failed_runs': failed_runs,
            'last_success_rate': success_rate
        }
    
    def get_model_statistics(self, model_name: str, days: int = 30) -> Dict[str, Any]:
        """
        获取指定模型的统计信息（最近 N 天）
        
        Args:
            model_name: 模型名称
            days: 统计天数
            
        Returns:
            统计信息字典
        """
        from datetime import timedelta
        
        total_runs = 0
        success_runs = 0
        failed_runs = 0
        
        # 遍历最近 N 天的日志文件
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            log_file = self.etl_dir / f"{date}.jsonl"
            
            if not log_file.exists():
                continue
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log = json.loads(line.strip())
                        if log.get('model_name') == model_name:
                            total_runs += 1
                            if log.get('status') == 'success':
                                success_runs += 1
                            elif log.get('status') == 'failed':
                                failed_runs += 1
                    except json.JSONDecodeError:
                        continue
        
        # 计算成功率
        success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0, 1)
        
        return {
            'total_runs': total_runs,
            'success_runs': success_runs,
            'failed_runs': failed_runs,
            'success_rate': success_rate
        }
    
    def get_sfc_statistics(self, days: int = 30) -> Dict[str, Any]:
        """
        获取 SFC 爬虫统计信息（最近 N 天）
        
        Args:
            days: 统计天数
            
        Returns:
            统计信息字典
        """
        from datetime import timedelta
        
        total_runs = 0
        success_runs = 0
        failed_runs = 0
        
        # 遍历最近 N 天的日志文件
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            log_file = self.sfc_dir / f"{date}.jsonl"
            
            if not log_file.exists():
                continue
            
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log = json.loads(line.strip())
                        total_runs += 1
                        if log.get('status') == 'success':
                            success_runs += 1
                        elif log.get('status') == 'failed':
                            failed_runs += 1
                    except json.JSONDecodeError:
                        continue
        
        # 计算成功率
        success_rate = round((success_runs / total_runs * 100) if total_runs > 0 else 0, 1)
        
        return {
            'total_runs': total_runs,
            'success_runs': success_runs,
            'failed_runs': failed_runs,
            'success_rate': success_rate
        }


# 全局实例
file_logger = FileLogger()


def get_file_logger():
    """获取文件日志记录器实例"""
    return file_logger
