# -*- coding: utf-8 -*-
"""API接口模块"""

import heapq
import logging
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from .config import Config
from .database import Database
from .transfer_service import TransferService
from .path_utils import normalize_config_path_display, resolve_image_view_path, to_virtual_path


def create_app(config: Config, db: Database, transfer_service: TransferService) -> Flask:
    """
    创建Flask应用
    
    Args:
        config: 配置对象
        db: 数据库对象
        transfer_service: 文件转移服务对象
    
    Returns:
        Flask应用实例
    """
    # 计算正确的静态文件目录路径
    import sys
    current_dir = Path(__file__).parent.parent
    static_folder = current_dir / 'static'
    
    app = Flask(__name__, static_folder=str(static_folder), static_url_path='')
    CORS(app)
    
    archive_dir = Path(config.get_paths().get('archive_dir', '/data/archive'))
    inspection_config = config.get_inspection_config()
    defect_types = inspection_config.get('defect_types', {})
    project_dir = current_dir.resolve()
    data_dir = (current_dir / 'data').resolve()
    virtual_roots = {
        '/app': project_dir,
        '/data': data_dir,
    }
    viewer_points = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'Q', 'R']
    viewer_point_set = set(viewer_points)
    viewer_statuses = ['OK', '定位NG', '底涂不良', '无料NG', '扫码不良', '相机掉线']
    viewer_status_set = set(viewer_statuses)
    image_suffixes = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'}

    def resolve_runtime_path(path_str: str, default_path: str) -> Path:
        """将配置中的路径解析为当前运行环境下的真实路径。"""
        normalized_path = str(path_str or default_path).strip()
        if not normalized_path:
            normalized_path = default_path

        normalized_virtual_path = normalized_path.replace('\\', '/').rstrip('/')
        for virtual_root, real_root in virtual_roots.items():
            if normalized_virtual_path == virtual_root:
                return real_root.resolve()
            if normalized_virtual_path.startswith(f'{virtual_root}/'):
                suffix = normalized_virtual_path[len(virtual_root) + 1:]
                return (real_root / Path(suffix)).resolve()

        path_obj = Path(normalized_path)
        if not path_obj.is_absolute():
            path_obj = (current_dir / path_obj).resolve()
        return path_obj.resolve()

    def prepare_image_item(item: dict, skip_existence_check: bool = False) -> dict:
        """将图片记录规范为客户端可用的虚拟路径与 view_url。"""
        prepared = dict(item)
        raw_path = str(prepared.get('archive_path') or prepared.get('source_path') or '').strip()
        virtual = normalize_config_path_display(raw_path, 'data/archive', project_dir)
        if not skip_existence_check:
            try:
                resolved = resolve_image_view_path(raw_path, project_dir)
                if resolved.is_file():
                    virtual = to_virtual_path(resolved, project_dir)
            except Exception:
                pass
        prepared['archive_path'] = virtual
        prepared['view_url'] = f'/api/image/view?path={quote(virtual, safe="")}'
        return prepared

    def prepare_image_list(items: list, skip_existence_check: bool = False) -> list:
        return [prepare_image_item(item, skip_existence_check=skip_existence_check) for item in items]

    def serve_image_file(filepath: str):
        """读取磁盘图片并返回给浏览器。"""
        full_path = resolve_image_view_path(filepath, project_dir)
        if not full_path.is_file():
            return jsonify({'error': '图片不存在', 'path': str(full_path)}), 404

        mimetype, _ = mimetypes.guess_type(str(full_path))
        return send_file(str(full_path), mimetype=mimetype or 'application/octet-stream')

    def get_viewer_root_dir() -> Path:
        """获取图片查阅页使用的根目录。"""
        viewer_root_path = db.get_config(
            'viewer_root_path',
            config.get_paths().get('archive_dir', 'data/archive')
        )
        return resolve_runtime_path(
            viewer_root_path,
            config.get_paths().get('archive_dir', 'data/archive')
        )

    def get_inspection_root_dir() -> Path:
        """获取在线巡机读取图片的根目录。"""
        inspection_root_path = db.get_config(
            'inspection_root_path',
            config.get_paths().get('archive_dir', 'data/archive')
        )
        return resolve_runtime_path(
            inspection_root_path,
            config.get_paths().get('archive_dir', 'data/archive')
        )

    def get_machine_context_from_root(
        root_dir: Path,
        project_name: str,
        machine_name: str,
    ) -> tuple[Path, str]:
        """识别根目录的层级结构，兼容 source、archive、flat 三种布局。"""
        viewer_root_dir = root_dir.resolve()
        source_machine_dir = (viewer_root_dir / machine_name).resolve()
        archive_machine_dir = (viewer_root_dir / project_name / machine_name).resolve()
        flat_project_dir = (viewer_root_dir / project_name).resolve()

        source_machine_dir.relative_to(viewer_root_dir)
        archive_machine_dir.relative_to(viewer_root_dir)
        flat_project_dir.relative_to(viewer_root_dir)

        if source_machine_dir.exists() and source_machine_dir.is_dir():
            return source_machine_dir, 'source'
        if archive_machine_dir.exists() and archive_machine_dir.is_dir():
            return archive_machine_dir, 'archive'
        if flat_project_dir.exists() and flat_project_dir.is_dir():
            has_direct_images = any(
                item.is_file() and item.suffix.lower() in image_suffixes
                for item in flat_project_dir.iterdir()
            )
            if has_direct_images:
                return flat_project_dir, 'flat'

        return source_machine_dir, 'source'

    def get_viewer_machine_context(project_name: str, machine_name: str) -> tuple[Path, str]:
        """识别图片查阅根目录的层级结构，兼容 source、archive、flat 三种布局。"""
        return get_machine_context_from_root(get_viewer_root_dir(), project_name, machine_name)

    def collect_flat_project_images(
        project_dir: Path,
        project_name: str,
        machine_name: str,
        point_name: str,
        date_str: str,
        status_name: str,
    ) -> list[dict]:
        """从扁平归档项目目录收集图片，按修改日期与文件名筛选。"""
        images = []
        if not project_dir.exists() or not project_dir.is_dir():
            return images

        for image_file in project_dir.iterdir():
            if not image_file.is_file() or image_file.suffix.lower() not in image_suffixes:
                continue

            detected_point = extract_viewer_point(image_file.name)
            if detected_point and detected_point != point_name:
                continue

            detected_status = extract_viewer_status(image_file.name)
            if detected_status and detected_status != status_name:
                continue

            file_stat = image_file.stat()
            file_date = datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y%m%d')
            if file_date != date_str:
                continue

            resolved_path = str(image_file.resolve())
            images.append({
                'id': resolved_path,
                'project_name': project_name,
                'machine_name': machine_name,
                'point_name': point_name,
                'date_str': date_str,
                'status_name': status_name,
                'folder_name': project_dir.name,
                'filename': image_file.name,
                'archive_path': resolved_path,
                'archived_at': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                '_mtime': file_stat.st_mtime,
            })

        images.sort(key=lambda item: (-item['_mtime'], item['filename'].lower()))
        for image in images:
            image.pop('_mtime', None)
        return images

    def list_viewer_dates(project_dir: Path, layout_mode: str) -> list[str]:
        """读取图片查阅可用日期列表。"""
        date_names = set()
        if layout_mode == 'source':
            for date_dir in project_dir.iterdir():
                if date_dir.is_dir():
                    date_names.add(date_dir.name)
        elif layout_mode == 'archive':
            for point_dir in project_dir.iterdir():
                if not point_dir.is_dir():
                    continue
                for date_dir in point_dir.iterdir():
                    if date_dir.is_dir():
                        date_names.add(date_dir.name)
        elif layout_mode == 'flat':
            for image_file in project_dir.iterdir():
                if not image_file.is_file() or image_file.suffix.lower() not in image_suffixes:
                    continue
                file_stat = image_file.stat()
                date_names.add(datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y%m%d'))

        return sorted(date_names, reverse=True)

    def extract_viewer_point(filename: str) -> str:
        """从图片文件名末尾提取穴位字母。"""
        stem = Path(filename).stem
        candidate = stem.rsplit(',', 1)[-1].strip().upper()
        return candidate if candidate in viewer_point_set else ''

    def extract_viewer_status(filename: str) -> str:
        """从图片文件名前缀提取状态名称。"""
        stem = Path(filename).stem
        candidate = stem.split(',', 1)[0].strip()
        return candidate if candidate in viewer_status_set else ''

    def resolve_defect_name(defect_type, custom_defect=None, preferred_name=None) -> str:
        """根据缺陷类型解析具体名称，如缺胶、溢胶。"""
        if preferred_name:
            return str(preferred_name).strip()
        if custom_defect:
            return str(custom_defect).strip()
        if defect_type is None:
            return ''
        try:
            defect_type = int(defect_type)
        except (TypeError, ValueError):
            return ''
        if defect_type == 7:
            return str(custom_defect or '').strip()
        label = defect_types.get(defect_type)
        if label is None:
            label = defect_types.get(str(defect_type), '')
        return str(label or '').strip()

    def get_inspection_recent_count() -> int:
        """读取巡机配置页保存的每个穴位取图数量。"""
        configured = db.get_config(
            'inspection_recent_count',
            inspection_config.get('recent_count', 20),
        )
        try:
            count = int(configured)
        except (TypeError, ValueError):
            count = int(inspection_config.get('recent_count', 20))
        return max(1, min(count, 100))

    def enrich_inspection_session(session: dict) -> dict:
        """补充巡机会话的缺陷问题描述。"""
        if not session:
            return session

        session_id = session.get('id')
        defect_issues = db.get_session_defect_issues_map(
            [session_id], defect_labels=defect_types
        ).get(session_id, []) if session_id else []
        reviewed_count = session.get('reviewed_count') or 0
        defect_count = session.get('defect_count') or 0
        defect_issue_text = '；'.join(defect_issues) if defect_issues else '无'

        enriched = dict(session)
        enriched['defect_issues'] = defect_issues
        enriched['defect_issue_text'] = defect_issue_text
        enriched['result_text'] = (
            f"项目：{session.get('project_name') or '-'}，"
            f"检查 {reviewed_count} 张，缺陷 {defect_count} 张，"
            f"问题点：{defect_issue_text}，"
            f"检查人：{session.get('reviewer') or '-'}"
        )
        return enriched
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """健康检查"""
        return jsonify({'status': 'ok', 'version': '2.1.0'})
    
    @app.route('/api/projects', methods=['GET'])
    def get_projects():
        """获取所有项目列表"""
        projects = db.get_projects()
        return jsonify({'projects': projects})
    
    @app.route('/api/projects/<project_name>/machines', methods=['GET'])
    def get_machines(project_name: str):
        """获取项目下的机台列表"""
        machines = db.get_machines(project_name)
        return jsonify({'machines': machines})
    
    @app.route('/api/projects/<project_name>/machines/<machine_name>/points', methods=['GET'])
    def get_points(project_name: str, machine_name: str):
        """获取机台下的穴位列表"""
        points = db.get_points(project_name, machine_name)
        return jsonify({'points': points})
    
    @app.route('/api/projects/<project_name>/machines/<machine_name>/points/<point_name>/dates', methods=['GET'])
    def get_dates(project_name: str, machine_name: str, point_name: str):
        """获取穴位下的日期列表"""
        dates = db.get_dates(project_name, machine_name, point_name)
        return jsonify({'dates': dates})

    @app.route('/api/viewer/projects/<project_name>/machines/<machine_name>/points', methods=['GET'])
    def get_viewer_points(project_name: str, machine_name: str):
        """获取图片查阅页固定穴位列表"""
        return jsonify({'points': viewer_points})

    @app.route('/api/viewer/projects/<project_name>/machines/<machine_name>/dates', methods=['GET'])
    def get_viewer_dates(project_name: str, machine_name: str):
        """从图片查阅根目录读取项目/机台下的日期文件夹"""
        today_str = datetime.now().strftime('%Y%m%d')

        try:
            machine_dir, layout_mode = get_viewer_machine_context(project_name, machine_name)
        except ValueError:
            return jsonify({'dates': [], 'today': today_str, 'default_date': ''}), 400

        if not machine_dir.exists() or not machine_dir.is_dir():
            return jsonify({'dates': [], 'today': today_str, 'default_date': ''})

        dates = list_viewer_dates(machine_dir, layout_mode)
        default_date = today_str if today_str in dates else (dates[0] if dates else '')
        return jsonify({
            'dates': dates,
            'today': today_str,
            'default_date': default_date
        })

    def collect_viewer_folder_images(
        search_dirs: list[Path],
        project_name: str,
        machine_name: str,
        point_name: str,
        date_str: str,
        status_name: str,
        filter_by_status: bool = False,
    ) -> list[dict]:
        """收集指定文件夹内的全部图片，按修改时间倒序排列。"""
        images = []
        seen_paths = set()

        for search_dir in search_dirs:
            if not search_dir.exists() or not search_dir.is_dir():
                continue

            for image_file in search_dir.iterdir():
                if not image_file.is_file() or image_file.suffix.lower() not in image_suffixes:
                    continue

                if filter_by_status:
                    detected_status = extract_viewer_status(image_file.name)
                    if detected_status and detected_status != status_name:
                        continue

                resolved_path = str(image_file.resolve())
                if resolved_path in seen_paths:
                    continue
                seen_paths.add(resolved_path)

                file_stat = image_file.stat()
                images.append({
                    'id': resolved_path,
                    'project_name': project_name,
                    'machine_name': machine_name,
                    'point_name': point_name,
                    'date_str': date_str,
                    'status_name': status_name,
                    'folder_name': search_dir.name,
                    'filename': image_file.name,
                    'archive_path': resolved_path,
                    'archived_at': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                    '_mtime': file_stat.st_mtime,
                })

        images.sort(key=lambda item: (-item['_mtime'], item['filename'].lower()))
        for image in images:
            image.pop('_mtime', None)
        return images

    class _InspectionImageCollector:
        """按修改时间保留每个穴位最近 N 张图片。"""

        def __init__(self, limit: int, point_name: str, date_str: str = ''):
            self.limit = max(1, limit)
            self.point_name = point_name.upper()
            self.date_str = str(date_str or '').strip()
            self.heap: list[tuple] = []
            self.seen_paths: set[str] = set()

        def consider(self, image_file: Path, project_name: str, machine_name: str,
                     date_str: str = '') -> None:
            if not image_file.is_file():
                return
            if image_file.suffix.lower() not in image_suffixes:
                return

            path_key = str(image_file)
            if path_key in self.seen_paths:
                return

            detected_point = extract_viewer_point(image_file.name)
            if detected_point and detected_point != self.point_name:
                return

            try:
                file_stat = image_file.stat()
            except OSError:
                return

            image_date = date_str or datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y%m%d')
            if self.date_str and image_date != self.date_str:
                return

            self.seen_paths.add(path_key)

            item = {
                'id': path_key,
                'project_name': project_name,
                'machine_name': machine_name,
                'point_name': self.point_name,
                'date_str': image_date,
                'status_name': extract_viewer_status(image_file.name) or 'OK',
                'folder_name': image_file.parent.name,
                'filename': image_file.name,
                'archive_path': path_key,
                'archived_at': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                '_mtime': file_stat.st_mtime,
            }
            entry = (file_stat.st_mtime, image_file.name.lower(), item)
            if len(self.heap) < self.limit:
                heapq.heappush(self.heap, entry)
            elif entry[0] > self.heap[0][0]:
                heapq.heapreplace(self.heap, entry)

        def results(self) -> list[dict]:
            ordered = sorted(self.heap, key=lambda entry: (-entry[0], entry[1]))
            images = []
            for _, _, item in ordered:
                cleaned = dict(item)
                cleaned.pop('_mtime', None)
                images.append(cleaned)
            return images

        @property
        def count(self) -> int:
            return len(self.heap)

    def _inspection_today_str() -> str:
        return datetime.now().strftime('%Y%m%d')

    def _scan_image_files_in_dir(
        collector: _InspectionImageCollector,
        image_dir: Path,
        project_name: str,
        machine_name: str,
        date_str: str = '',
    ) -> None:
        if not image_dir.exists() or not image_dir.is_dir():
            return
        try:
            entries = list(image_dir.iterdir())
        except OSError:
            return
        for image_file in entries:
            collector.consider(image_file, project_name, machine_name, date_str)

    def _scan_today_point_images(
        collector: _InspectionImageCollector,
        date_dir: Path,
        project_name: str,
        machine_name: str,
        point_name: str,
        date_str: str,
    ) -> None:
        if not date_dir.is_dir():
            return

        point_dir = date_dir / point_name
        if point_dir.exists() and point_dir.is_dir():
            ok_dir = point_dir / 'OK'
            if ok_dir.exists() and ok_dir.is_dir():
                _scan_image_files_in_dir(
                    collector,
                    ok_dir,
                    project_name,
                    machine_name,
                    date_str,
                )
            _scan_image_files_in_dir(
                collector,
                point_dir,
                project_name,
                machine_name,
                date_str,
            )

    def collect_inspection_point_images(
        machine_dir: Path,
        layout_mode: str,
        project_name: str,
        machine_name: str,
        point_name: str,
        limit: int,
        date_str: str | None = None,
    ) -> list[dict]:
        """从巡机根目录收集指定机台穴位当日最近 N 张图片，不足则返回实际数量。"""
        target_date = (date_str or _inspection_today_str()).strip()
        collector = _InspectionImageCollector(limit, point_name, target_date)
        if not machine_dir.exists() or not machine_dir.is_dir():
            return []

        if layout_mode == 'flat':
            _scan_image_files_in_dir(collector, machine_dir, project_name, machine_name, target_date)
            return collector.results()

        if layout_mode == 'source':
            _scan_today_point_images(
                collector,
                machine_dir / target_date,
                project_name,
                machine_name,
                point_name,
                target_date,
            )
            return collector.results()

        point_dir = machine_dir / point_name
        if point_dir.exists() and point_dir.is_dir():
            _scan_image_files_in_dir(
                collector,
                point_dir / target_date,
                project_name,
                machine_name,
                target_date,
            )
            return collector.results()

        for nested_point_dir in machine_dir.iterdir():
            if not nested_point_dir.is_dir() or nested_point_dir.name.upper() != point_name:
                continue
            _scan_image_files_in_dir(
                collector,
                nested_point_dir / target_date,
                project_name,
                machine_name,
                target_date,
            )
        return collector.results()

    def _inspection_root_matches_archive() -> bool:
        inspection_root = get_inspection_root_dir().resolve()
        archive_path = db.get_config(
            'archive_dir',
            config.get_paths().get('archive_dir', 'data/archive'),
        )
        archive_root = resolve_runtime_path(
            archive_path,
            config.get_paths().get('archive_dir', 'data/archive'),
        ).resolve()
        return inspection_root == archive_root

    def _archived_row_to_inspection_image(row: dict) -> dict:
        return {
            'id': row.get('id') or row.get('archive_path'),
            'project_name': row.get('project_name') or '',
            'machine_name': row.get('machine_name') or '',
            'point_name': str(row.get('point_name') or '').upper(),
            'date_str': row.get('date_str') or '',
            'status_name': 'OK',
            'folder_name': Path(str(row.get('archive_path') or '')).parent.name,
            'filename': row.get('filename') or Path(str(row.get('archive_path') or '')).name,
            'archive_path': row.get('archive_path') or '',
            'archived_at': row.get('archived_at') or '',
        }

    def collect_inspection_project_images(
        project_name: str,
        machines: list[str],
        per_point_count: int,
    ) -> list[dict]:
        """从巡机根目录扫描项目下各机台各穴位当日图片。"""
        today_str = _inspection_today_str()
        grouped: dict[tuple[str, str], list[dict]] = {}

        if _inspection_root_matches_archive():
            db_rows = db.get_recent_archived_images_for_inspection(
                project_name,
                machines,
                viewer_points,
                per_point_count,
                date_str=today_str,
            )
            for row in db_rows:
                machine_name = str(row.get('machine_name') or '').strip()
                point_name = str(row.get('point_name') or '').strip().upper()
                if not machine_name or point_name not in viewer_point_set:
                    continue
                bucket_key = (machine_name, point_name)
                grouped.setdefault(bucket_key, []).append(_archived_row_to_inspection_image(row))

        inspection_root_dir = get_inspection_root_dir()

        def collect_machine(machine_name: str) -> list[dict]:
            machine_images = []
            for point in viewer_points:
                bucket_key = (machine_name, point)
                if len(grouped.get(bucket_key, [])) >= per_point_count:
                    continue
                try:
                    machine_dir, layout_mode = get_machine_context_from_root(
                        inspection_root_dir,
                        project_name,
                        machine_name,
                    )
                except ValueError:
                    continue
                machine_images.extend(
                    collect_inspection_point_images(
                        machine_dir,
                        layout_mode,
                        project_name,
                        machine_name,
                        point,
                        per_point_count,
                        today_str,
                    )
                )
            return machine_images

        fs_images: list[dict] = []
        if machines:
            max_workers = min(4, len(machines))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(collect_machine, machine_name) for machine_name in machines]
                for future in as_completed(futures):
                    fs_images.extend(future.result())

        for image in fs_images:
            machine_name = str(image.get('machine_name') or '').strip()
            point_name = str(image.get('point_name') or '').strip().upper()
            if not machine_name or point_name not in viewer_point_set:
                continue
            bucket_key = (machine_name, point_name)
            bucket = grouped.setdefault(bucket_key, [])
            if len(bucket) >= per_point_count:
                continue
            existing_paths = {str(item.get('archive_path') or '') for item in bucket}
            archive_path = str(image.get('archive_path') or '')
            if archive_path and archive_path in existing_paths:
                continue
            bucket.append(image)

        project_images = []
        for machine_name in machines:
            for point in viewer_points:
                project_images.extend(grouped.get((machine_name, point), [])[:per_point_count])

        project_images.sort(
            key=lambda item: (
                str(item.get('machine_name') or ''),
                str(item.get('point_name') or ''),
                str(item.get('archived_at') or ''),
            ),
            reverse=True,
        )
        return project_images

    @app.route('/api/viewer/images', methods=['GET'])
    def get_viewer_images():
        """按筛选目录获取文件夹内全部图片，按修改时间倒序展示"""
        project_name = request.args.get('project_name', '').strip()
        machine_name = request.args.get('machine_name', '').strip()
        point_name = request.args.get('point_name', '').strip().upper()
        date_str = request.args.get('date', '').strip()
        status_name = request.args.get('status', 'OK').strip()
        limit = request.args.get('limit', type=int, default=1000)
        offset = request.args.get('offset', type=int, default=0)

        if not project_name or not machine_name or not point_name or not date_str:
            return jsonify({'images': []})

        if point_name not in viewer_point_set:
            return jsonify({'images': []})

        if status_name not in viewer_status_set:
            return jsonify({'images': []})

        try:
            machine_dir, layout_mode = get_viewer_machine_context(project_name, machine_name)
        except ValueError:
            return jsonify({'images': []}), 400

        if not machine_dir.exists() or not machine_dir.is_dir():
            return jsonify({'images': []})

        if layout_mode == 'flat':
            images = collect_flat_project_images(
                machine_dir,
                project_name,
                machine_name,
                point_name,
                date_str,
                status_name,
            )
            paged_images = prepare_image_list(images[offset: offset + limit if limit else None])
            return jsonify({'images': paged_images})

        search_dirs = []
        if layout_mode == 'source':
            point_dir = machine_dir / date_str / point_name
            if not point_dir.exists() or not point_dir.is_dir():
                return jsonify({'images': []})

            status_dir = point_dir / status_name
            if status_dir.exists() and status_dir.is_dir():
                search_dirs = [status_dir]
            else:
                search_dirs = [point_dir]
        else:
            direct_date_dir = machine_dir / point_name / date_str
            if direct_date_dir.exists() and direct_date_dir.is_dir():
                search_dirs = [direct_date_dir]
            else:
                for point_dir in sorted(machine_dir.iterdir(), key=lambda item: item.name.lower()):
                    if not point_dir.is_dir():
                        continue
                    date_dir = point_dir / date_str
                    if date_dir.exists() and date_dir.is_dir():
                        search_dirs.append(date_dir)

        images = collect_viewer_folder_images(
            search_dirs,
            project_name,
            machine_name,
            point_name,
            date_str,
            status_name,
            filter_by_status=(layout_mode == 'archive'),
        )
        paged_images = prepare_image_list(images[offset: offset + limit if limit else None])
        return jsonify({'images': paged_images})
    
    @app.route('/api/images', methods=['GET'])
    def get_images():
        """获取图片列表"""
        project_name = request.args.get('project_name')
        machine_name = request.args.get('machine_name')
        point_name = request.args.get('point_name')
        date_str = request.args.get('date')
        limit = request.args.get('limit', type=int, default=50)
        offset = request.args.get('offset', type=int, default=0)
        
        images = db.get_archived_images(
            project_name=project_name,
            machine_name=machine_name,
            point_name=point_name,
            date_str=date_str,
            limit=limit,
            offset=offset
        )
        
        return jsonify({'images': prepare_image_list(images)})
    
    @app.route('/api/image/<int:image_id>', methods=['GET'])
    def get_image_detail(image_id: int):
        """获取图片详情"""
        images = db.get_archived_images()
        image = next((img for img in images if img['id'] == image_id), None)
        
        if not image:
            return jsonify({'error': '图片不存在'}), 404
        
        return jsonify({'image': image})
    
    @app.route('/api/image/view', methods=['GET'])
    def view_image_query():
        """查看图片（query 传 path，兼容特殊字符文件名）。"""
        filepath = request.args.get('path', '').strip()
        if not filepath:
            return jsonify({'error': '缺少 path 参数'}), 400
        try:
            return serve_image_file(filepath)
        except Exception as e:
            return jsonify({'error': str(e)}), 404

    @app.route('/api/image/view/<path:filepath>')
    def view_image(filepath: str):
        """查看图片（路径参数，兼容旧链接）。"""
        try:
            return serve_image_file(filepath)
        except Exception as e:
            return jsonify({'error': str(e)}), 404
    
    @app.route('/api/inspection/recent', methods=['GET'])
    def get_inspection_images():
        """获取巡机审核的图片列表"""
        project_name = request.args.get('project_name', '').strip()
        machine_name = request.args.get('machine_name', '').strip()
        point_name = request.args.get('point_name', '').strip().upper()
        recent_count = request.args.get('count', type=int)
        if recent_count is None:
            recent_count = get_inspection_recent_count()

        if not project_name or not machine_name or not point_name:
            return jsonify({'images': []})

        if point_name not in viewer_point_set:
            return jsonify({'images': []})

        try:
            machine_dir, layout_mode = get_machine_context_from_root(
                get_inspection_root_dir(),
                project_name,
                machine_name,
            )
        except ValueError:
            return jsonify({'images': []}), 400

        images = collect_inspection_point_images(
            machine_dir,
            layout_mode,
            project_name,
            machine_name,
            point_name,
            recent_count,
        )

        return jsonify({'images': prepare_image_list(images)})

    @app.route('/api/inspection/project-images', methods=['GET'])
    def get_inspection_project_images():
        """获取项目下各机台各穴位当日最近 N 张图片（在线巡机，不足则返回实际数量）。"""
        project_name = request.args.get('project_name', '').strip()
        if not project_name:
            return jsonify({'error': '缺少项目参数'}), 400

        per_point_count = get_inspection_recent_count()
        machine_names_param = request.args.get('machine_names', '').strip()
        selected_machine_set = None
        if machine_names_param:
            selected_machine_set = {
                name.strip()
                for name in machine_names_param.split(',')
                if name.strip()
            }
            if not selected_machine_set:
                return jsonify({'error': '请至少选择一台机台'}), 400

        machines = db.get_machines(project_name)
        grouped = {}

        if not machines:
            return jsonify({'error': '请先在「项目机台对应」中配置机台'}), 400

        if selected_machine_set is not None:
            machines = [machine for machine in machines if machine in selected_machine_set]
            if not machines:
                return jsonify({'error': '所选机台无效或暂无图片'}), 400

        for machine_name in machines:
            for point in viewer_points:
                grouped[(machine_name, point)] = []

        project_images = collect_inspection_project_images(
            project_name,
            machines,
            per_point_count,
        )

        for image in project_images:
            machine_name = str(image.get('machine_name') or '').strip()
            if not machine_name:
                continue
            if selected_machine_set is not None and machine_name not in selected_machine_set:
                continue

            point = str(image.get('point_name') or '').strip().upper()
            if not point:
                point = extract_viewer_point(image.get('filename') or '')
            if point not in viewer_point_set:
                continue

            bucket_key = (machine_name, point)
            if bucket_key not in grouped:
                grouped[bucket_key] = []
            if len(grouped[bucket_key]) >= per_point_count:
                continue

            enriched = prepare_image_item(
                dict(image),
                skip_existence_check=_inspection_root_matches_archive(),
            )
            enriched['point_name'] = point
            enriched['machine_name'] = machine_name
            grouped[bucket_key].append(enriched)

        machine_groups = []
        point_groups = []
        flat_images = []
        for machine_name in machines:
            machine_points = []
            for point in viewer_points:
                images = grouped.get((machine_name, point), [])
                machine_points.append({
                    'point_name': point,
                    'images': images,
                })
                point_groups.append({
                    'machine_name': machine_name,
                    'point_name': point,
                    'images': images,
                })
                flat_images.extend(images)
            machine_groups.append({
                'machine_name': machine_name,
                'points': machine_points,
            })

        expected_count = len(machines) * len(viewer_points) * per_point_count

        return jsonify({
            'project_name': project_name,
            'date_str': _inspection_today_str(),
            'per_point_count': per_point_count,
            'machine_count': len(machines),
            'selected_machines': machines,
            'point_count': len(viewer_points),
            'expected_count': expected_count,
            'total_count': len(flat_images),
            'machines': machine_groups,
            'points': point_groups,
            'images': flat_images,
        })
    
    @app.route('/api/inspection/sessions', methods=['GET'])
    def get_inspection_sessions():
        """获取巡机会话列表（巡机报告页，仅已完成）"""
        project_name = request.args.get('project_name', '').strip() or None
        start_date = request.args.get('start_date', '').strip() or None
        end_date = request.args.get('end_date', '').strip() or None
        limit = request.args.get('limit', type=int)

        sessions = db.get_inspection_sessions(
            project_name=project_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

        enriched_sessions = [enrich_inspection_session(session) for session in sessions]

        total_sessions = len(enriched_sessions)
        total_reviewed = sum(session.get('reviewed_count') or 0 for session in enriched_sessions)
        total_pass = sum(session.get('pass_count') or 0 for session in enriched_sessions)
        total_defect = sum(session.get('defect_count') or 0 for session in enriched_sessions)
        pass_rate = (total_pass / total_reviewed * 100) if total_reviewed else 0

        return jsonify({
            'sessions': enriched_sessions,
            'summary': {
                'session_count': total_sessions,
                'reviewed_count': total_reviewed,
                'pass_count': total_pass,
                'defect_count': total_defect,
                'pass_rate': pass_rate,
            },
        })

    @app.route('/api/inspection/session/start', methods=['POST'])
    def start_inspection_session():
        """创建在线巡机会话"""
        data = request.get_json() or {}
        project_name = str(data.get('project_name', '')).strip()
        reviewer = str(data.get('reviewer', '')).strip()
        total_images = int(data.get('total_images') or 0)

        if not project_name:
            return jsonify({'success': False, 'error': '缺少项目参数'}), 400

        session_id = db.create_inspection_session(project_name, reviewer, total_images)
        session = db.get_inspection_session(session_id)
        return jsonify({'success': True, 'session': session})

    @app.route('/api/inspection/session/<int:session_id>', methods=['GET', 'DELETE'])
    def inspection_session_detail(session_id: int):
        """获取或删除巡机会话"""
        if request.method == 'DELETE':
            session = db.get_inspection_session(session_id)
            if not session:
                return jsonify({'success': True})
            if session.get('status') != 'completed':
                return jsonify({'success': False, 'error': '进行中的巡机请使用取消操作'}), 400
            db.delete_inspection_session(session_id)
            return jsonify({'success': True})

        session = db.get_inspection_session(session_id)
        if not session:
            return jsonify({'error': '会话不存在'}), 404
        if session.get('status') != 'completed':
            return jsonify({'error': '该巡机尚未完成'}), 404

        records = db.get_inspection_records(session_id=session_id)
        enriched_records = []
        for record in records:
            item = dict(record)
            image_path = str(item.get('image_path') or '').strip()
            if image_path:
                prepared = prepare_image_item({'archive_path': image_path})
                item['archive_path'] = prepared.get('archive_path') or image_path
                item['view_url'] = prepared.get('view_url')
            enriched_records.append(item)
        return jsonify({'session': enrich_inspection_session(session), 'records': enriched_records})

    @app.route('/api/inspection/session/<int:session_id>/cancel', methods=['POST'])
    def cancel_inspection_session(session_id: int):
        """取消并删除未完成的巡机会话"""
        session = db.get_inspection_session(session_id)
        if not session:
            return jsonify({'success': True})

        if session.get('status') == 'completed':
            return jsonify({'success': False, 'error': '已完成的巡机记录不能删除'}), 400

        db.delete_inspection_session(session_id)
        return jsonify({'success': True})

    @app.route('/api/inspection/session/<int:session_id>/complete', methods=['POST'])
    def complete_inspection_session(session_id: int):
        """完成巡机会话（全部图片判定后才可完成）"""
        session = db.get_inspection_session(session_id)
        if not session:
            return jsonify({'success': False, 'error': '会话不存在'}), 404

        records = db.get_inspection_records(session_id=session_id)
        total_images = session.get('total_images') or 0
        reviewed_count = len(records)
        if total_images <= 0 or reviewed_count < total_images:
            db.delete_inspection_session(session_id)
            return jsonify({
                'success': False,
                'error': f'检查未完成（{reviewed_count}/{total_images}），记录已删除',
            }), 400

        session = db.complete_inspection_session(session_id)
        if not session:
            db.delete_inspection_session(session_id)
            return jsonify({'success': False, 'error': '检查未完成，记录已删除'}), 400
        return jsonify({'success': True, 'session': enrich_inspection_session(session)})

    @app.route('/api/inspection/record', methods=['POST'])
    def add_inspection_record():
        """添加审核记录"""
        data = request.get_json() or {}
        defect_type = data.get('defect_type')
        custom_defect = data.get('custom_defect')
        defect_name = resolve_defect_name(
            defect_type,
            custom_defect=custom_defect,
            preferred_name=data.get('defect_name'),
        )
        
        record_id = db.add_inspection_record(
            image_id=data.get('image_id'),
            project_name=data.get('project_name'),
            machine_name=data.get('machine_name'),
            point_name=data.get('point_name'),
            image_path=data.get('image_path'),
            defect_type=defect_type,
            defect_name=defect_name,
            custom_defect=data.get('custom_defect'),
            reviewer=data.get('reviewer'),
            need_review=data.get('need_review', False),
            notes=data.get('notes'),
            session_id=data.get('session_id'),
        )
        
        if data.get('project_name') and data.get('machine_name') and data.get('point_name'):
            db.save_inspection_progress(
                data['project_name'],
                data['machine_name'],
                data['point_name'],
                data.get('image_index', 0)
            )

        session = None
        if data.get('session_id'):
            session = db.get_inspection_session(data.get('session_id'))
        
        return jsonify({
            'success': True,
            'record_id': record_id,
            'defect_name': defect_name,
            'session': session,
        })
    
    @app.route('/api/inspection/progress', methods=['GET'])
    def get_inspection_progress():
        """获取巡机进度"""
        project_name = request.args.get('project_name')
        machine_name = request.args.get('machine_name')
        point_name = request.args.get('point_name')
        
        progress = db.get_inspection_progress(project_name, machine_name, point_name)
        
        return jsonify({'progress': progress})
    
    @app.route('/api/inspection/records', methods=['GET'])
    def get_inspection_records():
        """获取审核记录"""
        project_name = request.args.get('project_name')
        machine_name = request.args.get('machine_name')
        point_name = request.args.get('point_name')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        limit = request.args.get('limit', type=int)
        
        records = db.get_inspection_records(
            project_name=project_name,
            machine_name=machine_name,
            point_name=point_name,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            session_id=request.args.get('session_id', type=int),
        )
        
        return jsonify({'records': records})
    
    @app.route('/api/statistics', methods=['GET'])
    def get_statistics():
        """获取统计数据"""
        project_name = request.args.get('project_name')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        stats = db.get_statistics(
            project_name=project_name,
            start_date=start_date,
            end_date=end_date
        )
        
        return jsonify({'statistics': stats})
    
    @app.route('/api/defect-types', methods=['GET'])
    def get_defect_types():
        """获取缺陷类型列表"""
        return jsonify({'defect_types': defect_types})
    
    # ==================== 用户认证 API ====================
    
    @app.route('/api/login', methods=['POST'])
    def login():
        """用户登录"""
        data = request.get_json()
        username = data.get('username', '')
        password = data.get('password', '')
        
        user = db.verify_user(username, password)
        if user:
            return jsonify({'success': True, 'user': user})
        else:
            return jsonify({'success': False, 'error': '用户名或密码错误'}), 401
    
    @app.route('/api/logout', methods=['POST'])
    def logout():
        """用户登出"""
        return jsonify({'success': True})
    
    @app.route('/api/users', methods=['GET'])
    def get_users():
        """获取用户列表"""
        users = db.get_all_users()
        return jsonify({'users': users})
    
    @app.route('/api/users', methods=['POST'])
    def create_user():
        """创建用户"""
        data = request.get_json()
        username = data.get('username', '')
        password = data.get('password', '')
        role = data.get('role', 'user')
        
        try:
            user_id = db.add_user(username, password, role)
            return jsonify({'success': True, 'user_id': user_id})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    @app.route('/api/users/<int:user_id>/password', methods=['PUT'])
    def update_user_password(user_id):
        """更新用户密码"""
        data = request.get_json()
        new_password = data.get('password', '')
        
        success = db.update_user_password(user_id, new_password)
        return jsonify({'success': success})
    
    @app.route('/api/users/<int:user_id>', methods=['DELETE'])
    def delete_user(user_id):
        """删除用户"""
        success = db.delete_user(user_id)
        return jsonify({'success': success})
    
    # ==================== 配置管理 API ====================
    
    @app.route('/api/configs', methods=['GET'])
    def get_configs():
        """获取所有配置"""
        configs = db.get_all_configs()
        return jsonify({'configs': configs})
    
    @app.route('/api/configs/<config_key>', methods=['GET'])
    def get_config_by_key(config_key):
        """获取单个配置"""
        value = db.get_config(config_key)
        return jsonify({'key': config_key, 'value': value})
    
    @app.route('/api/configs', methods=['POST'])
    def set_configs():
        """设置配置项"""
        data = request.get_json()
        config_key = data.get('key', '')
        config_value = data.get('value', '')
        config_type = data.get('type', 'string')
        description = data.get('description', '')
        
        success = db.set_config(config_key, config_value, config_type, description)
        return jsonify({'success': success})

    @app.route('/api/project-machine-mappings', methods=['GET'])
    def get_project_machine_mappings():
        """获取项目与机台对应关系"""
        mappings = db.get_project_machine_mappings()
        return jsonify({'mappings': mappings})

    @app.route('/api/project-machine-mappings', methods=['POST'])
    def save_project_machine_mappings():
        """保存项目与机台对应关系"""
        data = request.get_json() or {}
        mappings = data.get('mappings', [])

        if not isinstance(mappings, list):
            return jsonify({'success': False, 'error': 'mappings 必须为数组'}), 400

        success = db.replace_project_machine_mappings(mappings)
        return jsonify({'success': success})
    
    @app.route('/api/configs/reload', methods=['POST'])
    def reload_config():
        """重新加载配置（重启归档服务）"""
        return jsonify({'success': True})
    
    # ==================== 归档规则 API ====================
    
    @app.route('/api/archive-rules', methods=['GET'])
    def get_archive_rules():
        """获取归档规则列表"""
        enabled_only = request.args.get('enabled_only', 'false').lower() == 'true'
        rules = db.get_archive_rules(enabled_only=enabled_only)
        return jsonify({'rules': rules})
    
    @app.route('/api/archive-rules/<int:rule_id>', methods=['GET'])
    def get_archive_rule(rule_id: int):
        """获取单个归档规则"""
        rule = db.get_archive_rule(rule_id)
        if rule:
            return jsonify({'rule': rule})
        return jsonify({'error': '规则不存在'}), 404
    
    @app.route('/api/archive-rules', methods=['POST'])
    def add_archive_rule():
        """添加归档规则"""
        data = request.get_json()
        try:
            rule_id = db.add_archive_rule(
                name=data.get('name', ''),
                source_dir=data.get('source_dir', ''),
                archive_dir=data.get('archive_dir', ''),
                source_pattern=data.get('source_pattern', ''),
                target_pattern=data.get('target_pattern', ''),
                rename_pattern=data.get('rename_pattern', '{filename}'),
                enabled=data.get('enabled', True)
            )
            return jsonify({'success': True, 'rule_id': rule_id})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 400
    
    @app.route('/api/archive-rules/<int:rule_id>', methods=['PUT'])
    def update_archive_rule(rule_id: int):
        """更新归档规则"""
        data = request.get_json()
        success = db.update_archive_rule(
            rule_id,
            name=data.get('name'),
            source_dir=data.get('source_dir'),
            archive_dir=data.get('archive_dir'),
            source_pattern=data.get('source_pattern'),
            target_pattern=data.get('target_pattern'),
            rename_pattern=data.get('rename_pattern'),
            enabled=data.get('enabled')
        )
        return jsonify({'success': success})
    
    @app.route('/api/archive-rules/<int:rule_id>', methods=['DELETE'])
    def delete_archive_rule(rule_id: int):
        """删除归档规则"""
        success = db.delete_archive_rule(rule_id)
        return jsonify({'success': success})
    
    # ==================== 路径配置 API ====================
    
    @app.route('/api/paths', methods=['GET'])
    def get_paths_config():
        """获取路径配置（容器虚拟路径）"""
        project_dir = current_dir.resolve()
        source_configured = db.get_config(
            'source_dir',
            config.get_paths().get('source_dir', 'data/source'),
        )
        archive_configured = db.get_config(
            'archive_dir',
            config.get_paths().get('archive_dir', 'data/archive'),
        )
        return jsonify({
            'source_dir': normalize_config_path_display(source_configured, '/data/source', project_dir),
            'archive_dir': normalize_config_path_display(archive_configured, '/data/archive', project_dir),
        })

    @app.route('/api/paths/check', methods=['GET'])
    def check_path_exists():
        """检测配置路径是否存在且可读。"""
        path_str = request.args.get('path', '').strip()
        if not path_str:
            return jsonify({'exists': False, 'readable': False, 'is_dir': False, 'error': '路径为空'}), 400

        try:
            resolved = resolve_runtime_path(path_str, 'data/archive')
            exists = resolved.exists()
            is_dir = resolved.is_dir() if exists else False
            readable = os.access(resolved, os.R_OK) if exists else False
            return jsonify({
                'exists': exists,
                'is_dir': is_dir,
                'readable': readable,
                'resolved_path': to_virtual_path(resolved, project_dir) if exists else '',
            })
        except Exception as exc:
            return jsonify({
                'exists': False,
                'readable': False,
                'is_dir': False,
                'error': str(exc),
            })
    
    @app.route('/api/paths', methods=['POST'])
    def set_paths_config():
        """设置路径配置"""
        data = request.get_json()
        project_dir = current_dir.resolve()
        if 'source_dir' in data:
            db.set_config(
                'source_dir',
                normalize_config_path_display(data['source_dir'], '/data/source', project_dir),
                'string',
                '源数据目录',
            )
        if 'archive_dir' in data:
            db.set_config(
                'archive_dir',
                normalize_config_path_display(data['archive_dir'], '/data/archive', project_dir),
                'string',
                '归档目录',
            )
        transfer_service.reload_paths()
        return jsonify({'success': True})
    
    @app.route('/api/transfer/settings', methods=['POST'])
    def save_transfer_settings():
        """保存文件转移监控配置"""
        data = request.get_json() or {}
        try:
            scan_interval = transfer_service.set_scan_interval(data.get('scan_interval'))
            return jsonify({
                'success': True,
                'scan_interval': scan_interval,
                'status': transfer_service.get_status(),
            })
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

    @app.route('/api/transfer/status', methods=['GET'])
    def get_transfer_status():
        """获取文件转移监控状态"""
        return jsonify(transfer_service.get_status())

    @app.route('/api/transfer/logs', methods=['GET'])
    def get_transfer_logs():
        """获取文件转移日志"""
        limit = request.args.get('limit', type=int, default=200)
        return jsonify({'logs': transfer_service.get_logs(limit=limit)})

    @app.route('/api/transfer/logs', methods=['DELETE'])
    def clear_transfer_logs():
        """清空文件转移日志"""
        transfer_service.clear_logs()
        return jsonify({'success': True})

    @app.route('/api/transfer/start', methods=['POST'])
    def start_transfer_monitor():
        """启动文件转移监控"""
        transfer_service.start()
        return jsonify({'success': True, 'status': transfer_service.get_status()})

    @app.route('/api/transfer/stop', methods=['POST'])
    def stop_transfer_monitor():
        """停止文件转移监控"""
        transfer_service.stop()
        return jsonify({'success': True, 'status': transfer_service.get_status()})

    @app.route('/api/transfer/run-once', methods=['POST'])
    def run_transfer_once():
        """手动执行一次文件转移扫描"""
        transferred_count = transfer_service.run_transfer_cycle('立即')
        return jsonify({
            'success': True,
            'transferred_count': transferred_count,
            'status': transfer_service.get_status(),
        })
    
    @app.route('/')
    def index():
        """主页 - 登录页面"""
        return app.send_static_file('login.html')
    
    @app.route('/<path:path>')
    def static_files(path: str):
        """静态文件"""
        return app.send_static_file(path)

    @app.route('/api/system/directories', methods=['GET'])
    def browse_directories():
        """浏览服务器/容器内可见目录"""
        requested_path = request.args.get('path', '').strip()

        project_dir = current_dir.resolve()
        data_dir = (current_dir / 'data').resolve()

        virtual_roots = {
            '/app': project_dir,
            '/data': data_dir,
        }

        def resolve_config_path(path_str: str) -> Path:
            path_obj = Path(path_str)
            if not path_obj.is_absolute():
                path_obj = (current_dir / path_obj).resolve()
            return path_obj.resolve()

        def to_virtual_path(actual_path: Path) -> str:
            actual_path = actual_path.resolve()
            for virtual_root, real_root in virtual_roots.items():
                try:
                    relative_path = actual_path.relative_to(real_root)
                    relative_text = relative_path.as_posix()
                    return virtual_root if relative_text in ('', '.') else f'{virtual_root}/{relative_text}'
                except ValueError:
                    continue
            return '/app'

        def to_real_path(virtual_path: str) -> Path:
            normalized_path = virtual_path.replace('\\', '/').rstrip('/') or '/app'
            for virtual_root, real_root in virtual_roots.items():
                if normalized_path == virtual_root:
                    return real_root
                if normalized_path.startswith(f'{virtual_root}/'):
                    suffix = normalized_path[len(virtual_root) + 1:]
                    return (real_root / Path(suffix)).resolve()
            raise ValueError('非法目录路径')

        try:
            configured_paths = config.get_paths()
            source_dir = resolve_config_path(configured_paths.get('source_dir', 'data/source'))
            archive_dir = resolve_config_path(configured_paths.get('archive_dir', 'data/archive'))

            preferred_entries = []
            seen_paths = set()
            for label, path_obj in [
                ('项目目录', project_dir),
                ('源数据目录', source_dir),
                ('归档目录', archive_dir),
            ]:
                path_str = to_virtual_path(path_obj)
                if path_str not in seen_paths and path_obj.exists():
                    preferred_entries.append({'name': label, 'path': path_str, 'type': 'favorite'})
                    seen_paths.add(path_str)

            if not requested_path:
                return jsonify({
                    'current_path': '',
                    'parent_path': '',
                    'directories': preferred_entries,
                })

            current_path = to_real_path(requested_path)
            if not current_path.exists() or not current_path.is_dir():
                return jsonify({'success': False, 'error': '目录不存在'}), 404

            directories = []
            for child in sorted(current_path.iterdir(), key=lambda item: item.name.lower()):
                if child.is_dir():
                    directories.append({
                        'name': child.name,
                        'path': to_virtual_path(child.resolve()),
                        'type': 'directory',
                    })

            current_virtual_path = to_virtual_path(current_path)
            parent_real_path = current_path.parent if current_path.parent != current_path else current_path
            parent_virtual_path = to_virtual_path(parent_real_path)
            if current_virtual_path in virtual_roots:
                parent_virtual_path = ''

            return jsonify({
                'success': True,
                'current_path': current_virtual_path,
                'parent_path': parent_virtual_path,
                'directories': directories,
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    def get_client_heartbeat_timeout() -> int:
        configured = db.get_config(
            'client_heartbeat_timeout',
            config.get('client_heartbeat', {}).get('timeout_seconds', 60),
        )
        try:
            timeout = int(configured)
        except (TypeError, ValueError):
            timeout = int(config.get('client_heartbeat', {}).get('timeout_seconds', 60))
        return max(10, min(timeout, 3600))

    def parse_heartbeat_payload() -> dict:
        """兼容 JSON、表单、URL 参数等多种客户端上报格式。"""
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = request.form.to_dict()
        if not data:
            data = request.args.to_dict()
        return data or {}

    def extract_heartbeat_machine_name(data: dict) -> str:
        for key in (
            'machine_name', 'machine', 'machineName', 'machine_no', 'machineNo',
            'DeviceName', 'deviceName', 'device_name',
            '机台', '机台号', '机台名称',
        ):
            value = data.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ''

    @app.route('/api/client/heartbeat', methods=['POST', 'GET'])
    @app.route('/api/heartbeat', methods=['POST', 'GET'])
    def receive_client_heartbeat():
        """接收机台客户端心跳"""
        data = parse_heartbeat_payload()
        machine_name = extract_heartbeat_machine_name(data)
        if not machine_name:
            logging.getLogger(__name__).warning(
                '心跳上报缺少机台号: method=%s path=%s content_type=%s data=%s',
                request.method,
                request.path,
                request.content_type,
                data,
            )
            return jsonify({
                'success': False,
                'error': '缺少 machine_name 参数（机台号）',
                'hint': '请使用 POST JSON、表单或 GET 参数传递 machine_name，例如 D6',
            }), 400

        project_name = str(
            data.get('project_name') or data.get('project') or data.get('ProjectName') or data.get('项目') or ''
        ).strip() or None
        client_id = str(
            data.get('client_id') or data.get('clientId') or data.get('DeviceId') or data.get('deviceId') or ''
        ).strip() or None
        client_version = str(
            data.get('client_version') or data.get('clientVersion')
            or data.get('version') or data.get('Version') or data.get('ver') or ''
        ).strip() or None
        client_status = str(
            data.get('status') or data.get('client_status') or data.get('clientStatus')
            or data.get('state') or data.get('State') or 'running'
        ).strip() or 'running'
        host_name = str(
            data.get('host_name') or data.get('hostname') or data.get('host')
            or data.get('ComputerName') or data.get('computerName') or ''
        ).strip() or None
        ip_address = str(data.get('ip_address') or data.get('ip') or '').strip() or request.remote_addr

        db.upsert_client_heartbeat(
            machine_name=machine_name,
            project_name=project_name,
            client_id=client_id,
            client_version=client_version,
            client_status=client_status,
            ip_address=ip_address,
            host_name=host_name,
        )

        return jsonify({
            'success': True,
            'machine_name': machine_name,
            'received_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'timeout_seconds': get_client_heartbeat_timeout(),
        })

    @app.route('/api/client/heartbeat/status', methods=['GET'])
    def get_client_heartbeat_status():
        """获取机台客户端在线状态汇总"""
        timeout_seconds = request.args.get('timeout_seconds', type=int)
        if timeout_seconds is None:
            timeout_seconds = get_client_heartbeat_timeout()
        status = db.get_client_monitor_status(timeout_seconds=timeout_seconds)
        return jsonify(status)

    @app.after_request
    def add_static_cache_headers(response):
        if request.method == 'GET' and not request.path.startswith('/api/'):
            if request.path.endswith(('.js', '.css', '.html', '.ico')):
                response.cache_control.public = True
                response.cache_control.max_age = 3600
        return response
    
    return app
