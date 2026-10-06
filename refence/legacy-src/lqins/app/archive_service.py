# -*- coding: utf-8 -*-
"""自动归档与清理服务"""

import os
import re
import shutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from apscheduler.schedulers.background import BackgroundScheduler
from .config import Config
from .database import Database


class ArchiveService:
    """归档服务类"""
    
    def __init__(self, config: Config, db: Database):
        """
        初始化归档服务
        
        Args:
            config: 配置对象
            db: 数据库对象
        """
        self.config = config
        self.db = db
        self.logger = self._setup_logger()
        self.observer = None
        self.scheduler = None
        
        paths = config.get_paths()
        self.source_dir = Path(paths.get('source_dir', '/data/source'))
        self.archive_dir = Path(paths.get('archive_dir', '/data/archive'))
        
        self._ensure_directories()
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志"""
        logger = logging.getLogger('ArchiveService')
        logger.setLevel(logging.INFO)
        return logger
    
    def _ensure_directories(self):
        """确保目录存在"""
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
    
    # ==================== 归档核心方法 ====================
    
    def parse_path_info(self, source_path: Path, rule: Dict) -> Optional[Dict]:
        """
        解析路径信息，提取项目、机台、穴位等信息
        
        Args:
            source_path: 源文件路径
            rule: 归档规则
        
        Returns:
            解析后的信息字典
        """
        try:
            rel_path = source_path.relative_to(self.source_dir)
            path_parts = list(rel_path.parts)
            
            info = {
                'source_path': str(source_path),
                'filename': source_path.name,
                'date_str': datetime.now().strftime('%Y%m%d')
            }
            
            mtime = datetime.fromtimestamp(source_path.stat().st_mtime)
            info['date_str'] = mtime.strftime('%Y%m%d')
            
            # 解析路径: D6/工位1/OK/test1.jpg -> machine_name=D6, point_name=工位1
            if len(path_parts) >= 1:
                info['machine_name'] = path_parts[0]
            
            if len(path_parts) >= 2:
                info['point_name'] = path_parts[1]
            
            info['project_name'] = rule.get('name', '未分类')
            
            return info
        except Exception as e:
            self.logger.error(f"解析路径信息失败: {source_path}, 错误: {e}")
            return None
    
    def get_target_path(self, info: Dict, rule: Dict) -> Optional[Path]:
        """
        根据规则生成目标路径
        
        Args:
            info: 解析后的文件信息
            rule: 归档规则
        
        Returns:
            目标文件路径
        """
        try:
            target_pattern = rule.get('target_pattern', '{project_name}/{machine_name}/{point_name}/{date}/')
            
            template_vars = {
                'project_name': info.get('project_name', ''),
                'machine_name': info.get('machine_name', ''),
                'point_name': info.get('point_name', ''),
                'date': info.get('date_str', ''),
                'filename': info.get('filename', '')
            }
            
            target_dir_str = target_pattern.format(**template_vars)
            target_dir = self.archive_dir / target_dir_str
            target_dir.mkdir(parents=True, exist_ok=True)
            
            rename_pattern = rule.get('rename', '{filename}')
            target_filename = rename_pattern.format(**template_vars)
            
            return target_dir / target_filename
            
        except Exception as e:
            self.logger.error(f"生成目标路径失败: {e}")
            return None
    
    def archive_file(self, source_path: Path, rule: Dict) -> bool:
        """
        归档单个文件
        
        Args:
            source_path: 源文件路径
            rule: 归档规则
        
        Returns:
            是否成功
        """
        try:
            if not source_path.exists():
                self.logger.warning(f"源文件不存在: {source_path}")
                return False
            
            info = self.parse_path_info(source_path, rule)
            if not info:
                return False
            
            target_path = self.get_target_path(info, rule)
            if not target_path:
                return False
            
            if target_path.exists():
                self.logger.debug(f"目标文件已存在，跳过: {target_path}")
                return True
            
            shutil.copy2(str(source_path), str(target_path))
            self.logger.info(f"归档成功: {source_path} -> {target_path}")
            
            self.db.add_archived_image(
                source_path=str(source_path),
                archive_path=str(target_path),
                project_name=info.get('project_name'),
                machine_name=info.get('machine_name'),
                point_name=info.get('point_name'),
                date_str=info.get('date_str'),
                filename=info.get('filename')
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"归档失败: {source_path}, 错误: {e}")
            return False
    
    def matches_rule(self, file_path: Path, rule: Dict) -> bool:
        """
        检查文件是否匹配规则
        
        Args:
            file_path: 文件路径
            rule: 归档规则
        
        Returns:
            是否匹配
        """
        try:
            source_pattern = rule.get('source_pattern', '')
            if not source_pattern:
                return False
            
            rel_path = file_path.relative_to(self.source_dir)
            # 标准化路径分隔符
            rel_path_str = str(rel_path).replace('\\', '/')
            
            # 将source_pattern转换为正则表达式
            pattern = source_pattern.replace('*', '.*')
            pattern = f'^{pattern}$'
            
            return bool(re.match(pattern, rel_path_str))
        except Exception as e:
            self.logger.debug(f"匹配规则失败: {file_path}, 规则: {source_pattern}, 错误: {e}")
            return False
    
    def scan_and_archive(self):
        """扫描并归档所有匹配的文件"""
        self.logger.info("开始扫描并归档...")
        
        rules = self.config.get_archive_rules()
        archived_count = 0
        
        for root, _, files in os.walk(self.source_dir):
            for filename in files:
                file_path = Path(root) / filename
                
                for rule in rules:
                    if self.matches_rule(file_path, rule):
                        if self.archive_file(file_path, rule):
                            archived_count += 1
                        break
        
        self.logger.info(f"扫描归档完成，共归档 {archived_count} 个文件")
    
    # ==================== 清理核心方法 ====================
    
    def cleanup_source(self):
        """清理A区源文件"""
        cleanup_config = self.config.get_cleanup_config()
        retention_days = cleanup_config.get('source_retention_days', 7)
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        self.logger.info(f"开始清理A区源文件，保留天数: {retention_days}")
        
        deleted_count = 0
        
        images = self.db.get_archived_images()
        
        for image in images:
            try:
                source_path = Path(image['source_path'])
                archive_path = Path(image['archive_path'])
                
                if image.get('source_deleted'):
                    continue
                
                if not source_path.exists():
                    self.db.mark_source_deleted(str(source_path))
                    continue
                
                mtime = datetime.fromtimestamp(source_path.stat().st_mtime)
                if mtime < cutoff_date:
                    if archive_path.exists():
                        source_path.unlink()
                        self.db.mark_source_deleted(str(source_path))
                        deleted_count += 1
                        self.logger.info(f"删除源文件: {source_path}")
            
            except Exception as e:
                self.logger.error(f"清理源文件失败: {e}")
        
        self.logger.info(f"A区清理完成，共删除 {deleted_count} 个文件")
    
    def cleanup_archive(self):
        """清理B区归档文件"""
        cleanup_config = self.config.get_cleanup_config()
        retention_days = cleanup_config.get('archive_retention_days', 1)
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        self.logger.info(f"开始清理B区归档文件，保留天数: {retention_days}")
        
        deleted_count = 0
        
        for root, _, files in os.walk(self.archive_dir):
            for filename in files:
                try:
                    file_path = Path(root) / filename
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    if mtime < cutoff_date:
                        file_path.unlink()
                        deleted_count += 1
                        self.logger.info(f"删除归档文件: {file_path}")
                
                except Exception as e:
                    self.logger.error(f"删除归档文件失败: {e}")
        
        self.logger.info(f"B区清理完成，共删除 {deleted_count} 个文件")
    
    def cleanup_all(self):
        """执行完整的清理流程"""
        self.scan_and_archive()
        self.cleanup_source()
        self.cleanup_archive()
    
    # ==================== 实时监听 ====================
    
    class FileHandler(FileSystemEventHandler):
        """文件系统事件处理器"""
        
        def __init__(self, service):
            self.service = service
        
        def on_created(self, event):
            if not event.is_directory:
                self.service._handle_file_event(Path(event.src_path))
        
        def on_modified(self, event):
            if not event.is_directory:
                self.service._handle_file_event(Path(event.src_path))
    
    def _handle_file_event(self, file_path: Path):
        """处理文件事件"""
        rules = self.config.get_archive_rules()
        
        for rule in rules:
            if self.matches_rule(file_path, rule):
                self.archive_file(file_path, rule)
                break
    
    def start_watchdog(self):
        """启动文件系统监听"""
        if self.config.get('archive_service.watch_enabled', True):
            self.observer = Observer()
            event_handler = self.FileHandler(self)
            self.observer.schedule(event_handler, str(self.source_dir), recursive=True)
            self.observer.start()
            self.logger.info("文件系统监听已启动")
    
    def stop_watchdog(self):
        """停止文件系统监听"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.logger.info("文件系统监听已停止")
    
    # ==================== 定时任务 ====================
    
    def start_scheduler(self):
        """启动定时任务"""
        self.scheduler = BackgroundScheduler()
        
        scan_interval = self.config.get('archive_service.scan_interval', 300)
        self.scheduler.add_job(
            self.scan_and_archive,
            'interval',
            seconds=scan_interval,
            id='scan_archive'
        )
        
        cleanup_cron = self.config.get('cleanup.schedule', '0 2 * * *')
        cron_parts = cleanup_cron.split()
        if len(cron_parts) == 5:
            self.scheduler.add_job(
            self.cleanup_all,
            'cron',
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4],
            id='cleanup_all'
        )
        
        self.scheduler.start()
        self.logger.info("定时任务已启动")
    
    def stop_scheduler(self):
        """停止定时任务"""
        if self.scheduler:
            self.scheduler.shutdown()
            self.logger.info("定时任务已停止")
    
    def start(self):
        """启动归档服务"""
        self.start_watchdog()
        self.start_scheduler()
        self.scan_and_archive()
    
    def stop(self):
        """停止归档服务"""
        self.stop_watchdog()
        self.stop_scheduler()
