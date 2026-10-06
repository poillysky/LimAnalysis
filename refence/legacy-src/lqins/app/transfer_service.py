# -*- coding: utf-8 -*-
"""基于项目机台对应的文件转移服务"""

import logging
import shutil
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Deque, Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import Config
from .database import Database
from .path_utils import normalize_config_path_display, resolve_runtime_path


class TransferService:
    """按项目机台映射，将源目录当日 OK 图片复制到归档项目目录（扁平结构）"""

    IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}
    VIEWER_POINTS = {'A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R'}

    def __init__(self, config: Config, db: Database, project_root: Optional[Path] = None):
        self.config = config
        self.db = db
        self.project_root = (project_root or Path(__file__).parent.parent).resolve()
        self.logger = logging.getLogger('TransferService')
        self.logs: Deque[Dict[str, str]] = deque(maxlen=500)
        self.log_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.observer = None
        self.scheduler = None
        self.cleanup_scheduler = None
        self.enabled = False
        self.last_run_at: Optional[str] = None
        self.last_transferred_count = 0

    def _add_log(self, message: str, level: str = 'info'):
        with self.log_lock:
            if self.logs and self.logs[0]['message'] == message:
                return
            entry = {
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'level': level,
                'message': message,
            }
            self.logs.appendleft(entry)
        log_method = getattr(self.logger, level if level in ('info', 'warning', 'error', 'debug') else 'info')
        log_method(message)

    def get_logs(self, limit: int = 200) -> List[Dict[str, str]]:
        with self.log_lock:
            return list(self.logs)[:limit]

    def clear_logs(self):
        with self.log_lock:
            self.logs.clear()

    def _resolve_runtime_path(self, path_str: str, default_path: str) -> Path:
        return resolve_runtime_path(path_str, default_path, self.project_root)

    def get_source_dir_display(self) -> str:
        configured = self.db.get_config(
            'source_dir',
            self.config.get_paths().get('source_dir', 'data/source'),
        )
        return normalize_config_path_display(configured, '/data/source', self.project_root)

    def get_archive_dir_display(self) -> str:
        configured = self.db.get_config(
            'archive_dir',
            self.config.get_paths().get('archive_dir', 'data/archive'),
        )
        return normalize_config_path_display(configured, '/data/archive', self.project_root)

    def get_source_dir(self) -> Path:
        configured = self.db.get_config(
            'source_dir',
            self.config.get_paths().get('source_dir', 'data/source')
        )
        source_dir = self._resolve_runtime_path(configured, 'data/source')
        source_dir.mkdir(parents=True, exist_ok=True)
        return source_dir

    def get_archive_dir(self) -> Path:
        configured = self.db.get_config(
            'archive_dir',
            self.config.get_paths().get('archive_dir', 'data/archive')
        )
        archive_dir = self._resolve_runtime_path(configured, 'data/archive')
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir

    def _today_str(self) -> str:
        return datetime.now().strftime('%Y%m%d')

    def _build_machine_project_map(self) -> Dict[str, str]:
        mappings = self.db.get_project_machine_mappings()
        machine_map: Dict[str, str] = {}
        for item in mappings:
            machine_name = str(item.get('machine_name', '')).strip()
            project_name = str(item.get('project_name', '')).strip()
            if machine_name and project_name:
                machine_map[machine_name] = project_name
        return machine_map

    def _is_image_file(self, file_path: Path) -> bool:
        return file_path.is_file() and file_path.suffix.lower() in self.IMAGE_SUFFIXES

    def _collect_ok_images(self, machine_dir: Path, date_str: str) -> List[Path]:
        """收集机台当日目录下 OK 文件夹内的全部图片。"""
        date_dir = machine_dir / date_str
        if not date_dir.exists() or not date_dir.is_dir():
            return []

        images: List[Path] = []
        seen = set()

        direct_ok_dir = date_dir / 'OK'
        if direct_ok_dir.exists() and direct_ok_dir.is_dir():
            for image_file in direct_ok_dir.iterdir():
                if self._is_image_file(image_file):
                    key = str(image_file.resolve())
                    if key not in seen:
                        seen.add(key)
                        images.append(image_file)

        for sub_dir in date_dir.iterdir():
            if not sub_dir.is_dir() or sub_dir.name == 'OK':
                continue
            ok_dir = sub_dir / 'OK'
            if ok_dir.exists() and ok_dir.is_dir():
                for image_file in ok_dir.iterdir():
                    if self._is_image_file(image_file):
                        key = str(image_file.resolve())
                        if key not in seen:
                            seen.add(key)
                            images.append(image_file)

        return images

    def _unique_target_path(self, target_dir: Path, filename: str) -> Path:
        target_path = target_dir / filename
        if not target_path.exists():
            return target_path

        stem = Path(filename).stem
        suffix = Path(filename).suffix
        index = 1
        while True:
            candidate = target_dir / f'{stem}_{index}{suffix}'
            if not candidate.exists():
                return candidate
            index += 1

    def _format_date_display(self, date_str: str) -> str:
        if len(date_str) == 8 and date_str.isdigit():
            return f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}'
        return date_str

    def _extract_point_name(self, source_path: Path, parsed: Optional[Dict[str, str]] = None) -> str:
        """从源路径或文件名提取穴位名。"""
        if parsed and parsed.get('point_name'):
            return parsed['point_name']

        stem = source_path.stem
        candidate = stem.rsplit(',', 1)[-1].strip().upper()
        if candidate in self.VIEWER_POINTS:
            return candidate
        return ''

    def transfer_file(
        self,
        source_path: Path,
        project_name: str,
        machine_name: str,
        date_str: str,
        point_name: str = '',
        log_success: bool = True,
    ) -> str:
        """复制单张图片，返回 copied / skipped / missing / failed。"""
        if not source_path.exists():
            return 'missing'

        source_key = str(source_path.resolve())
        if self.db.get_image_by_source_path(source_key):
            return 'skipped'

        target_dir = self.get_archive_dir() / project_name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = self._unique_target_path(target_dir, source_path.name)
        archive_display = self.get_archive_dir_display()

        if not point_name:
            point_name = self._extract_point_name(source_path)

        try:
            shutil.copy2(str(source_path), str(target_path))
            self.db.add_archived_image(
                source_path=source_key,
                archive_path=str(target_path.resolve()),
                project_name=project_name,
                machine_name=machine_name,
                point_name=point_name,
                date_str=date_str,
                filename=target_path.name,
            )
            if log_success:
                self._add_log(
                    f'【复制成功】{source_path.name} → {archive_display}/{project_name}/'
                )
            return 'copied'
        except Exception as exc:
            self._add_log(
                f'【复制失败】{source_path.name}，原因：{exc}',
                'error',
            )
            return 'failed'

    def _parse_source_file(self, file_path: Path) -> Optional[Dict[str, str]]:
        try:
            rel_path = file_path.resolve().relative_to(self.get_source_dir().resolve())
        except ValueError:
            return None

        parts = rel_path.parts
        if len(parts) < 4:
            return None

        machine_name = parts[0]
        date_str = parts[1]
        if 'OK' not in parts:
            return None

        ok_index = parts.index('OK')
        if ok_index != len(parts) - 2:
            return None

        point_name = ''
        if ok_index >= 3:
            point_name = parts[ok_index - 1].strip().upper()

        return {
            'machine_name': machine_name,
            'date_str': date_str,
            'point_name': point_name,
        }

    def _try_transfer_path(self, file_path: Path) -> bool:
        if not self.enabled or not self._is_image_file(file_path):
            return False

        parsed = self._parse_source_file(file_path)
        if not parsed:
            return False

        if parsed['date_str'] != self._today_str():
            return False

        machine_map = self._build_machine_project_map()
        project_name = machine_map.get(parsed['machine_name'])
        if not project_name:
            return False

        return self.transfer_file(
            file_path,
            project_name,
            parsed['machine_name'],
            parsed['date_str'],
            point_name=parsed.get('point_name', ''),
            log_success=True,
        ) == 'copied'

    def run_transfer_cycle(self, scan_type: str = '定时') -> int:
        mappings = self.db.get_project_machine_mappings()
        if not mappings:
            self._add_log('【提示】请先在「项目机台对应」中配置项目和机台', 'warning')
            self.last_transferred_count = 0
            self.last_run_at = datetime.now().isoformat()
            return 0

        source_dir = self.get_source_dir()
        date_str = self._today_str()
        date_display = self._format_date_display(date_str)
        transferred_count = 0
        skipped_count = 0
        found_count = 0
        copied_details: List[str] = []

        for item in mappings:
            project_name = str(item.get('project_name', '')).strip()
            machine_name = str(item.get('machine_name', '')).strip()
            if not project_name or not machine_name:
                continue

            machine_dir = source_dir / machine_name
            images = self._collect_ok_images(machine_dir, date_str)
            if not images:
                continue

            machine_found = len(images)
            machine_copied = 0
            machine_skipped = 0

            for image_path in images:
                result = self.transfer_file(
                    image_path,
                    project_name,
                    machine_name,
                    date_str,
                    point_name=self._extract_point_name(
                        image_path,
                        self._parse_source_file(image_path),
                    ),
                    log_success=False,
                )
                if result == 'copied':
                    machine_copied += 1
                elif result == 'skipped':
                    machine_skipped += 1

            found_count += machine_found
            transferred_count += machine_copied
            skipped_count += machine_skipped

            if machine_copied > 0:
                copied_details.append(
                    f'机台 {machine_name} → 项目「{project_name}」新复制 {machine_copied} 张'
                )

        self.last_transferred_count = transferred_count
        self.last_run_at = datetime.now().isoformat()

        prefix = f'【{scan_type}扫描】'
        if found_count == 0:
            self._add_log(f'{prefix}{date_display} 源目录中没有找到 OK 图片')
        elif transferred_count == 0:
            self._add_log(
                f'{prefix}{date_display} 共检查 {found_count} 张，均已复制过，无需重复处理'
            )
        else:
            self._add_log(
                f'{prefix}{date_display} 新复制 {transferred_count} 张，'
                f'跳过 {skipped_count} 张已归档图片'
            )
            for detail in copied_details:
                self._add_log(detail)

        return transferred_count

    class _FileHandler(FileSystemEventHandler):
        def __init__(self, service: 'TransferService'):
            self.service = service

        def on_created(self, event):
            if event.is_directory:
                return
            self.service._try_transfer_path(Path(event.src_path))

        def on_modified(self, event):
            if event.is_directory:
                return
            self.service._try_transfer_path(Path(event.src_path))

    def start_watchdog(self, log: bool = True):
        if self.observer:
            return

        self.observer = Observer()
        handler = self._FileHandler(self)
        self.observer.schedule(handler, str(self.get_source_dir()), recursive=True)
        self.observer.start()
        if log:
            self._add_log(f'已开始监听源目录：{self.get_source_dir_display()}')

    def stop_watchdog(self, log: bool = True):
        if not self.observer:
            return
        self.observer.stop()
        self.observer.join()
        self.observer = None
        if log:
            self._add_log('已停止监听源目录')

    def get_scan_interval(self) -> int:
        """获取监控扫描间隔（秒）。"""
        configured = self.db.get_config(
            'transfer_scan_interval',
            self.config.get('archive_service.scan_interval', 300),
        )
        try:
            interval = int(configured)
        except (TypeError, ValueError):
            interval = 60
        return max(5, min(interval, 3600))

    def get_source_retention_days(self) -> int:
        """获取源数据文件保留天数。"""
        cleanup_config = self.config.get_cleanup_config()
        configured = self.db.get_config(
            'source_retention_days',
            cleanup_config.get('source_retention_days', 7),
        )
        try:
            days = int(configured)
        except (TypeError, ValueError):
            days = 7
        return max(1, min(days, 365))

    def set_source_retention_days(self, retention_days: int) -> int:
        """保存源数据文件保留天数。"""
        try:
            days = int(retention_days)
        except (TypeError, ValueError):
            raise ValueError('保留天数必须是数字')

        days = max(1, min(days, 365))
        self.db.set_config('source_retention_days', days, 'int', '源数据文件保留天数')
        return days

    def cleanup_source_files(self) -> int:
        """清理超过保留期限且已归档的源数据文件（以数据库归档记录为准，不要求 B 区文件仍存在）。"""
        retention_days = self.get_source_retention_days()
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0

        self.logger.info(f'开始清理源数据文件，保留天数: {retention_days}')

        for image in self.db.get_archived_images():
            try:
                if image.get('source_deleted'):
                    continue

                source_path = Path(image['source_path'])
                archive_path = Path(image['archive_path'])

                if not source_path.exists():
                    self.db.mark_source_deleted(str(source_path))
                    continue

                mtime = datetime.fromtimestamp(source_path.stat().st_mtime)
                if mtime >= cutoff_date:
                    continue

                # 数据库有归档记录即表示复制成功；B 区保留期更短时归档文件可能已被清理
                if not archive_path.exists():
                    self.logger.info(
                        f'归档文件已不存在，仍按保留策略删除源文件: {source_path}'
                    )

                source_path.unlink()
                self.db.mark_source_deleted(str(source_path))
                deleted_count += 1
                self.logger.info(f'删除源文件: {source_path}')
            except Exception as exc:
                self.logger.error(f'清理源文件失败: {exc}')

        if deleted_count > 0:
            self._add_log(
                f'【源文件清理】删除 {deleted_count} 个超过 {retention_days} 天的源数据文件'
            )
        else:
            self.logger.info('源数据文件清理完成，无需删除')

        return deleted_count

    def get_archive_retention_days(self) -> int:
        """获取归档目录图片保留天数。"""
        configured = self.db.get_config('archive_retention_days')
        if configured is None:
            legacy_hours = self.db.get_config('inspection_file_retention_hours')
            if legacy_hours is not None:
                try:
                    days = int(int(legacy_hours) / 24)
                    return max(1, min(days, 365))
                except (TypeError, ValueError):
                    pass
            cleanup_config = self.config.get_cleanup_config()
            configured = cleanup_config.get('archive_retention_days', 1)
        try:
            days = int(configured)
        except (TypeError, ValueError):
            days = 1
        return max(1, min(days, 365))

    def set_archive_retention_days(self, retention_days: int) -> int:
        """保存归档目录图片保留天数。"""
        try:
            days = int(retention_days)
        except (TypeError, ValueError):
            raise ValueError('保留天数必须是数字')

        days = max(1, min(days, 365))
        self.db.set_config('archive_retention_days', days, 'int', '归档目录图片保留天数')
        return days

    def cleanup_archive_files(self) -> int:
        """清理超过保留期限的归档图片文件。"""
        retention_days = self.get_archive_retention_days()
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        archive_dir = self.get_archive_dir()
        deleted_count = 0

        self.logger.info(f'开始清理归档文件，保留天数: {retention_days}')

        if not archive_dir.exists():
            return 0

        for file_path in archive_dir.rglob('*'):
            if not file_path.is_file() or file_path.suffix.lower() not in self.IMAGE_SUFFIXES:
                continue

            try:
                mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                if mtime >= cutoff_date:
                    continue

                archive_key = str(file_path.resolve())
                file_path.unlink()
                self.db.delete_archived_image_by_archive_path(archive_key)
                deleted_count += 1
                self.logger.info(f'删除归档文件: {file_path}')
            except Exception as exc:
                self.logger.error(f'删除归档文件失败: {exc}')

        if deleted_count > 0:
            self._add_log(
                f'【归档清理】删除 {deleted_count} 个超过 {retention_days} 天的归档文件'
            )
        else:
            self.logger.info('归档文件清理完成，无需删除')

        return deleted_count

    def run_scheduled_cleanup(self):
        """执行定时清理任务。"""
        self.cleanup_source_files()
        self.cleanup_archive_files()

    def start_cleanup_scheduler(self):
        """启动文件定时清理任务（独立于监控开关）。"""
        if self.cleanup_scheduler:
            return

        cleanup_cron = self.config.get('cleanup.schedule', '0 2 * * *')
        cron_parts = cleanup_cron.split()
        self.cleanup_scheduler = BackgroundScheduler()

        if len(cron_parts) == 5:
            self.cleanup_scheduler.add_job(
                self.run_scheduled_cleanup,
                'cron',
                minute=cron_parts[0],
                hour=cron_parts[1],
                day=cron_parts[2],
                month=cron_parts[3],
                day_of_week=cron_parts[4],
                id='scheduled_cleanup',
            )
        else:
            self.cleanup_scheduler.add_job(
                self.run_scheduled_cleanup,
                'cron',
                hour=2,
                minute=0,
                id='scheduled_cleanup',
            )

        self.cleanup_scheduler.start()
        self.logger.info('文件定时清理任务已启动')

    def stop_cleanup_scheduler(self):
        """停止文件定时清理任务。"""
        if not self.cleanup_scheduler:
            return
        self.cleanup_scheduler.shutdown(wait=False)
        self.cleanup_scheduler = None
        self.logger.info('文件定时清理任务已停止')

    def set_scan_interval(self, scan_interval: int) -> int:
        """保存扫描间隔，并在监控运行中立即生效。"""
        try:
            interval = int(scan_interval)
        except (TypeError, ValueError):
            raise ValueError('扫描间隔必须是数字')

        interval = max(5, min(interval, 3600))
        self.db.set_config('transfer_scan_interval', interval, 'int', '文件转移扫描间隔（秒）')

        if self.scheduler and self.enabled:
            self.scheduler.reschedule_job(
                'transfer_scan',
                trigger='interval',
                seconds=interval,
            )
            self._add_log(f'扫描间隔已改为 {interval} 秒')

        return interval

    def start_scheduler(self, log: bool = True):
        if self.scheduler:
            return

        scan_interval = self.get_scan_interval()
        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(
            lambda: self.run_transfer_cycle('定时'),
            'interval',
            seconds=scan_interval,
            id='transfer_scan',
        )
        self.scheduler.start()
        if log:
            self._add_log(f'已开启定时扫描，每 {scan_interval} 秒检查一次')

    def stop_scheduler(self, log: bool = True):
        if not self.scheduler:
            return
        self.scheduler.shutdown(wait=False)
        self.scheduler = None
        if log:
            self._add_log('已停止定时扫描')

    def _is_monitor_running(self) -> bool:
        """判断监控线程是否实际在运行。"""
        observer_alive = self.observer is not None and self.observer.is_alive()
        scheduler_running = self.scheduler is not None and self.scheduler.running
        return self.enabled and observer_alive and scheduler_running

    def sync_monitor_state(self):
        """根据数据库配置同步监控运行状态。"""
        should_enable = bool(self.db.get_config('transfer_monitor_enabled', False))
        if should_enable:
            if not self._is_monitor_running():
                self._start_internal('监控恢复')
        elif self.enabled:
            self.stop()

    def _start_internal(self, log_message: str):
        """内部启动监控，确保监听与定时任务实际运行。"""
        if self.observer and not self.observer.is_alive():
            self.stop_watchdog(log=False)
        if self.scheduler and not self.scheduler.running:
            self.stop_scheduler(log=False)

        self.enabled = True
        if not self.observer:
            self.start_watchdog(log=False)
        if not self.scheduler:
            self.start_scheduler(log=False)

        interval = self.get_scan_interval()
        title = '监控恢复' if log_message == '监控恢复' else '监控开启'
        self._add_log(
            f'【{title}】监听 {self.get_source_dir_display()}，'
            f'每 {interval} 秒自动扫描今日 OK 图片'
        )
        scan_type = '恢复' if log_message == '监控恢复' else '启动'
        self.run_transfer_cycle(scan_type)

    def start(self):
        with self.state_lock:
            if self._is_monitor_running():
                return
            self.db.set_config('transfer_monitor_enabled', True, 'bool', '文件转移监控开关')
            self._start_internal('监控开启')

    def stop(self):
        with self.state_lock:
            if not self.enabled:
                self.stop_watchdog(log=False)
                self.stop_scheduler(log=False)
                return
            self.enabled = False
            self.db.set_config('transfer_monitor_enabled', False, 'bool', '文件转移监控开关')
            self.stop_watchdog(log=False)
            self.stop_scheduler(log=False)
            self._add_log('【监控关闭】已停止文件复制监控')

    def init_on_startup(self):
        self.start_cleanup_scheduler()
        if self.db.get_config('transfer_monitor_enabled', False):
            with self.state_lock:
                if not self._is_monitor_running():
                    self._start_internal('监控恢复')

    def reload_paths(self):
        """路径变更后重新绑定监听目录。"""
        if not self.enabled:
            return
        self.stop_watchdog(log=False)
        self.start_watchdog(log=False)
        self._add_log(f'已切换监听目录：{self.get_source_dir_display()}')

    def get_status(self) -> Dict[str, object]:
        machine_map = self._build_machine_project_map()
        return {
            'enabled': self.enabled,
            'source_dir': self.get_source_dir_display(),
            'archive_dir': self.get_archive_dir_display(),
            'today': self._today_str(),
            'mapping_count': len(machine_map),
            'mappings': [
                {'project_name': project, 'machine_name': machine}
                for machine, project in sorted(machine_map.items(), key=lambda item: (item[1], item[0]))
            ],
            'last_run_at': self.last_run_at,
            'last_transferred_count': self.last_transferred_count,
            'scan_interval': self.get_scan_interval(),
        }
