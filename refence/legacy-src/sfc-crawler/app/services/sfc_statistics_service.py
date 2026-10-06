"""
SFC 爬虫统计服务
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.sfc_crawler import (
    SfcProject,
    SfcAccount,
)
from app.utils.file_logger import file_logger

logger = logging.getLogger(__name__)


def get_crawler_statistics(db: Session, days: int = 7) -> Dict[str, Any]:
    """
    获取爬虫统计信息
    
    参数：
    - days: 统计最近 N 天的数据
    
    返回：
    - 总体统计
    - 项目统计
    - 账号统计
    - 趋势数据
    """
    from datetime import timedelta
    
    # 计算时间范围
    start_date = datetime.now() - timedelta(days=days)
    
    # 从文件读取最近 N 天的所有日志
    all_logs = []
    
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        day_logs = file_logger.read_sfc_logs(date=date, limit=10000)  # 每天最多读取 10000 条
        all_logs.extend(day_logs)
    
    # 1. 总体统计
    total_runs = len(all_logs)
    success_runs = len([log for log in all_logs if log.get('status') == 'success'])
    failed_runs = len([log for log in all_logs if log.get('status') == 'failed'])
    success_rate = (success_runs / total_runs * 100) if total_runs > 0 else 0
    
    # 平均耗时
    success_logs = [log for log in all_logs if log.get('status') == 'success' and log.get('duration')]
    avg_duration = sum(log.get('duration', 0) for log in success_logs) / len(success_logs) if success_logs else 0
    
    # 总数据量
    total_data_count = sum(log.get('records_count', 0) for log in success_logs)
    
    overall_stats = {
        'total_runs': total_runs,
        'success_runs': success_runs,
        'failed_runs': failed_runs,
        'success_rate': round(success_rate, 2),
        'avg_duration': round(avg_duration, 2),
        'total_data_count': total_data_count,
    }
    
    # 2. 项目统计
    projects = db.query(SfcProject).all()
    project_stats = []
    
    for project in projects:
        project_logs = [log for log in all_logs if log.get('config_name') == project.name]
        project_runs = len(project_logs)
        project_success = len([log for log in project_logs if log.get('status') == 'success'])
        project_success_rate = (project_success / project_runs * 100) if project_runs > 0 else 0
        
        project_success_logs = [log for log in project_logs if log.get('status') == 'success' and log.get('duration')]
        project_avg_duration = sum(log.get('duration', 0) for log in project_success_logs) / len(project_success_logs) if project_success_logs else 0
        project_data_count = sum(log.get('records_count', 0) for log in project_success_logs)
        
        project_stats.append({
            'project_id': project.id,
            'project_name': project.name,
            'total_runs': project_runs,
            'success_runs': project_success,
            'success_rate': round(project_success_rate, 2),
            'avg_duration': round(project_avg_duration, 2),
            'total_data_count': project_data_count,
        })
    
    # 3. 账号统计
    accounts = db.query(SfcAccount).all()
    account_stats = []
    
    for account in accounts:
        account_stats.append({
            'account_id': account.id,
            'username': account.username,
            'total_use_count': account.total_use_count,
            'success_count': account.success_count,
            'failed_count': account.failed_count,
            'success_rate': round((account.success_count / account.total_use_count * 100) if account.total_use_count > 0 else 0, 2),
            'last_use_time': account.last_use_time.isoformat() if account.last_use_time else None,
            'last_use_status': account.last_use_status,
        })
    
    # 4. 趋势数据（按天统计）
    trend_data = []
    for i in range(days):
        day = datetime.now() - timedelta(days=days - i - 1)
        date_str = day.strftime('%Y%m%d')
        
        day_logs = file_logger.read_sfc_logs(date=date_str, limit=10000)
        
        day_runs = len(day_logs)
        day_success = len([log for log in day_logs if log.get('status') == 'success'])
        day_data_count = sum(log.get('records_count', 0) for log in day_logs if log.get('status') == 'success')
        
        trend_data.append({
            'date': day.strftime('%Y-%m-%d'),
            'total_runs': day_runs,
            'success_runs': day_success,
            'data_count': day_data_count,
        })
    
    return {
        'overall': overall_stats,
        'projects': project_stats,
        'accounts': account_stats,
        'trend': trend_data,
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': datetime.now().isoformat(),
            'days': days,
        }
    }


def get_project_detail_statistics(db: Session, project_id: int, days: int = 30) -> Dict[str, Any]:
    """
    获取单个项目的详细统计
    """
    from datetime import timedelta
    
    project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
    if not project:
        return {}
    
    # 从文件读取最近 N 天的日志
    all_logs = []
    
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        day_logs = file_logger.read_sfc_logs(date=date, config_name=project.name, limit=10000)
        all_logs.extend(day_logs)
    
    # 基础统计
    total_runs = len(all_logs)
    success_runs = len([log for log in all_logs if log.get('status') == 'success'])
    
    # 最近 10 次运行记录
    recent_logs = sorted(all_logs, key=lambda x: x.get('timestamp', ''), reverse=True)[:10]
    
    recent_runs = [
        {
            'id': hash(log.get('timestamp', '')),
            'status': log.get('status'),
            'message': log.get('message'),
            'data_count': log.get('records_count', 0),
            'duration': log.get('duration', 0),
            'created_at': log.get('timestamp'),
        }
        for log in recent_logs
    ]
    
    return {
        'project': {
            'id': project.id,
            'name': project.name,
            'prefix': project.prefix,
            'is_enabled': project.is_enabled,
        },
        'statistics': {
            'total_runs': total_runs,
            'success_runs': success_runs,
            'success_rate': round((success_runs / total_runs * 100) if total_runs > 0 else 0, 2),
        },
        'recent_runs': recent_runs,
    }
