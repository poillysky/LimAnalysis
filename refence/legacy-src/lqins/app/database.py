# -*- coding: utf-8 -*-
"""数据库管理模块"""

import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import contextmanager


class Database:
    """数据库管理类"""
    
    def __init__(self, db_path: str):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_tables()
    
    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
    
    @contextmanager
    def _get_connection(self):
        """获取数据库连接的上下文管理器"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=30000')
        conn.execute('PRAGMA synchronous=NORMAL')
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_tables(self):
        """初始化数据库表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 图片归档记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archived_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL,
                    archive_path TEXT NOT NULL,
                    project_name TEXT,
                    machine_name TEXT,
                    point_name TEXT,
                    date_str TEXT,
                    filename TEXT,
                    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source_deleted INTEGER DEFAULT 0,
                    UNIQUE(source_path, archive_path)
                )
            ''')
            
            # 巡机审核记录表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inspection_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER,
                    project_name TEXT NOT NULL,
                    machine_name TEXT NOT NULL,
                    point_name TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    defect_type INTEGER NOT NULL,
                    defect_name TEXT,
                    custom_defect TEXT,
                    reviewer TEXT,
                    reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    need_review INTEGER DEFAULT 0,
                    notes TEXT,
                    FOREIGN KEY (image_id) REFERENCES archived_images(id)
                )
            ''')
            
            # 巡机进度表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inspection_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    machine_name TEXT NOT NULL,
                    point_name TEXT NOT NULL,
                    last_image_index INTEGER DEFAULT 0,
                    last_reviewed_at TIMESTAMP,
                    UNIQUE(project_name, machine_name, point_name)
                )
            ''')
            
            # 用户表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_key TEXT NOT NULL UNIQUE,
                    config_value TEXT,
                    config_type TEXT DEFAULT 'string',
                    description TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 项目机台对应关系表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS project_machine_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    machine_name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(project_name, machine_name)
                )
            ''')
            
            # 归档规则表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archive_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_dir TEXT DEFAULT '',
                    archive_dir TEXT DEFAULT '',
                    source_pattern TEXT NOT NULL,
                    target_pattern TEXT NOT NULL,
                    rename_pattern TEXT DEFAULT '{filename}',
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("PRAGMA table_info(archive_rules)")
            archive_rule_columns = {row[1] for row in cursor.fetchall()}
            if 'source_dir' not in archive_rule_columns:
                cursor.execute("ALTER TABLE archive_rules ADD COLUMN source_dir TEXT DEFAULT ''")
            if 'archive_dir' not in archive_rule_columns:
                cursor.execute("ALTER TABLE archive_rules ADD COLUMN archive_dir TEXT DEFAULT ''")
            
            # 插入默认管理员用户
            try:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (username, password, role)
                    VALUES (?, ?, ?)
                ''', ('admin', 'admin123', 'admin'))
            except:
                pass
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_archived_date ON archived_images(date_str)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_archived_project ON archived_images(project_name)')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_archived_machine_point
                ON archived_images(project_name, machine_name, point_name, date_str)
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_project ON inspection_records(project_name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_inspection_date ON inspection_records(reviewed_at)')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS inspection_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_name TEXT NOT NULL,
                    reviewer TEXT,
                    total_images INTEGER DEFAULT 0,
                    reviewed_count INTEGER DEFAULT 0,
                    pass_count INTEGER DEFAULT 0,
                    defect_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'in_progress',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')

            cursor.execute("PRAGMA table_info(inspection_records)")
            inspection_record_columns = {row[1] for row in cursor.fetchall()}
            if 'session_id' not in inspection_record_columns:
                cursor.execute('ALTER TABLE inspection_records ADD COLUMN session_id INTEGER')

            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_inspection_session
                ON inspection_records(session_id)
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS client_heartbeats (
                    machine_name TEXT PRIMARY KEY,
                    project_name TEXT,
                    client_id TEXT,
                    client_version TEXT,
                    client_status TEXT,
                    ip_address TEXT,
                    host_name TEXT,
                    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_client_heartbeat_last_seen
                ON client_heartbeats(last_seen_at)
            ''')
    
    # ==================== 归档图片相关方法 ====================
    
    def add_archived_image(self, source_path: str, archive_path: str, 
                          project_name: str = None, machine_name: str = None,
                          point_name: str = None, date_str: str = None, 
                          filename: str = None) -> int:
        """
        添加归档图片记录
        
        Returns:
            记录ID
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO archived_images 
                (source_path, archive_path, project_name, machine_name, point_name, date_str, filename)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (source_path, archive_path, project_name, machine_name, point_name, date_str, filename))
            return cursor.lastrowid
    
    def mark_source_deleted(self, source_path: str):
        """标记源文件已删除"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE archived_images SET source_deleted = 1 WHERE source_path = ?
            ''', (source_path,))

    def delete_archived_image_by_archive_path(self, archive_path: str) -> bool:
        """根据归档路径删除图片记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM archived_images WHERE archive_path = ?',
                (archive_path,),
            )
            return cursor.rowcount > 0
    
    def get_image_by_archive_path(self, archive_path: str) -> Optional[Dict]:
        """根据归档路径获取图片记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM archived_images WHERE archive_path = ?', (archive_path,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_archived_images(self, project_name: str = None, machine_name: str = None,
                           point_name: str = None, date_str: str = None,
                           limit: int = None, offset: int = 0) -> List[Dict]:
        """获取归档图片列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM archived_images WHERE 1=1'
            params = []
            
            if project_name:
                query += ' AND project_name = ?'
                params.append(project_name)
            if machine_name:
                query += ' AND machine_name = ?'
                params.append(machine_name)
            if point_name:
                query += ' AND point_name = ?'
                params.append(point_name)
            if date_str:
                query += ' AND date_str = ?'
                params.append(date_str)
            
            query += ' ORDER BY archived_at DESC'
            
            if limit:
                query += ' LIMIT ? OFFSET ?'
                params.extend([limit, offset])
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_archived_images_for_project(self, project_name: str, limit: int = 10000) -> List[Dict]:
        """获取项目下的归档图片，按日期倒序。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM archived_images
                WHERE project_name = ?
                ORDER BY date_str DESC, archived_at DESC
                LIMIT ?
            ''', (project_name, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_recent_archived_images_for_inspection(
        self,
        project_name: str,
        machine_names: List[str],
        point_names: List[str],
        per_point_limit: int,
        date_str: Optional[str] = None,
    ) -> List[Dict]:
        """按机台/穴位分组取指定日期最近 N 张归档图片（在线巡机快速路径）。"""
        machines = [name.strip() for name in machine_names if str(name).strip()]
        points = [name.strip().upper() for name in point_names if str(name).strip()]
        if not machines or not points:
            return []

        per_point_limit = max(1, min(int(per_point_limit or 1), 100))
        machine_placeholders = ','.join('?' * len(machines))
        point_placeholders = ','.join('?' * len(points))
        date_filter = ''
        params: List[Any] = [project_name, *machines, *points]
        if date_str:
            date_filter = ' AND date_str = ?'
            params.append(str(date_str).strip())

        query = f'''
            SELECT * FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY machine_name, point_name
                           ORDER BY archived_at DESC, id DESC
                       ) AS rn
                FROM archived_images
                WHERE project_name = ?
                  AND machine_name IN ({machine_placeholders})
                  AND point_name IN ({point_placeholders}){date_filter}
            )
            WHERE rn <= ?
            ORDER BY machine_name, point_name, archived_at DESC
        '''
        params.append(per_point_limit)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                row.pop('rn', None)
            return rows
    def get_projects(self) -> List[str]:
        """获取所有项目名称"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT project_name FROM project_machine_mappings
                WHERE project_name IS NOT NULL AND TRIM(project_name) != ''
                ORDER BY project_name
            ''')
            return [row[0] for row in cursor.fetchall()]
    
    def get_machines(self, project_name: str) -> List[str]:
        """获取项目下的所有机台"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT machine_name FROM project_machine_mappings
                WHERE project_name = ? AND machine_name IS NOT NULL AND TRIM(machine_name) != ''
                ORDER BY machine_name
            ''', (project_name,))
            return [row[0] for row in cursor.fetchall()]

    def get_project_machine_mappings(self) -> List[Dict]:
        """获取项目与机台的对应关系列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id, project_name, machine_name, created_at, updated_at
                FROM project_machine_mappings
                ORDER BY project_name, machine_name
            ''')
            return [dict(row) for row in cursor.fetchall()]
    
    def get_points(self, project_name: str, machine_name: str) -> List[str]:
        """获取机台下的所有穴位"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT point_name FROM archived_images 
                WHERE project_name = ? AND machine_name = ?
            ''', (project_name, machine_name))
            return [row[0] for row in cursor.fetchall()]
    
    def get_dates(self, project_name: str, machine_name: str, point_name: str) -> List[str]:
        """获取穴位下的所有日期"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT DISTINCT date_str FROM archived_images 
                WHERE project_name = ? AND machine_name = ? AND point_name = ?
                ORDER BY date_str DESC
            ''', (project_name, machine_name, point_name))
            return [row[0] for row in cursor.fetchall()]
    
    # ==================== 巡机审核相关方法 ====================
    
    def add_inspection_record(self, image_id: int = None, project_name: str = None,
                             machine_name: str = None, point_name: str = None,
                             image_path: str = None, defect_type: int = None,
                             defect_name: str = None, custom_defect: str = None,
                             reviewer: str = None, need_review: bool = False,
                             notes: str = None, session_id: int = None) -> int:
        """添加或更新审核记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            if session_id and image_id:
                cursor.execute('''
                    SELECT id FROM inspection_records
                    WHERE session_id = ? AND image_id = ?
                ''', (session_id, image_id))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute('''
                        UPDATE inspection_records
                        SET project_name = ?, machine_name = ?, point_name = ?, image_path = ?,
                            defect_type = ?, defect_name = ?, custom_defect = ?, reviewer = ?,
                            need_review = ?, notes = ?, reviewed_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (
                        project_name, machine_name, point_name, image_path,
                        defect_type, defect_name, custom_defect, reviewer,
                        1 if need_review else 0, notes, existing['id'],
                    ))
                    record_id = existing['id']
                else:
                    cursor.execute('''
                        INSERT INTO inspection_records
                        (image_id, project_name, machine_name, point_name, image_path,
                         defect_type, defect_name, custom_defect, reviewer, need_review, notes, session_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        image_id, project_name, machine_name, point_name, image_path,
                        defect_type, defect_name, custom_defect, reviewer,
                        1 if need_review else 0, notes, session_id,
                    ))
                    record_id = cursor.lastrowid
            elif session_id and image_path:
                cursor.execute('''
                    SELECT id FROM inspection_records
                    WHERE session_id = ? AND image_path = ?
                ''', (session_id, image_path))
                existing = cursor.fetchone()
                if existing:
                    cursor.execute('''
                        UPDATE inspection_records
                        SET project_name = ?, machine_name = ?, point_name = ?, image_id = ?,
                            defect_type = ?, defect_name = ?, custom_defect = ?, reviewer = ?,
                            need_review = ?, notes = ?, reviewed_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (
                        project_name, machine_name, point_name, image_id,
                        defect_type, defect_name, custom_defect, reviewer,
                        1 if need_review else 0, notes, existing['id'],
                    ))
                    record_id = existing['id']
                else:
                    cursor.execute('''
                        INSERT INTO inspection_records
                        (image_id, project_name, machine_name, point_name, image_path,
                         defect_type, defect_name, custom_defect, reviewer, need_review, notes, session_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        image_id, project_name, machine_name, point_name, image_path,
                        defect_type, defect_name, custom_defect, reviewer,
                        1 if need_review else 0, notes, session_id,
                    ))
                    record_id = cursor.lastrowid
            else:
                cursor.execute('''
                    INSERT INTO inspection_records
                    (image_id, project_name, machine_name, point_name, image_path,
                     defect_type, defect_name, custom_defect, reviewer, need_review, notes, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    image_id, project_name, machine_name, point_name, image_path,
                    defect_type, defect_name, custom_defect, reviewer,
                    1 if need_review else 0, notes, session_id,
                ))
                record_id = cursor.lastrowid

            if session_id:
                self._refresh_inspection_session_stats(cursor, session_id)

            return record_id

    def create_inspection_session(self, project_name: str, reviewer: str = '',
                                  total_images: int = 0) -> int:
        """创建巡机会话"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO inspection_sessions
                (project_name, reviewer, total_images, status)
                VALUES (?, ?, ?, 'in_progress')
            ''', (project_name, reviewer, total_images))
            return cursor.lastrowid

    def get_inspection_session(self, session_id: int) -> Optional[Dict]:
        """获取巡机会话详情"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM inspection_sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def complete_inspection_session(self, session_id: int) -> Optional[Dict]:
        """完成巡机会话并返回汇总（仅当全部图片已判定时）"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            self._refresh_inspection_session_stats(cursor, session_id)
            cursor.execute('SELECT * FROM inspection_sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            if not row:
                return None

            session = dict(row)
            total_images = session.get('total_images') or 0
            reviewed_count = session.get('reviewed_count') or 0
            if total_images <= 0 or reviewed_count < total_images:
                return None

            cursor.execute('''
                UPDATE inspection_sessions
                SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (session_id,))
            cursor.execute('SELECT * FROM inspection_sessions WHERE id = ?', (session_id,))
            completed = cursor.fetchone()
            return dict(completed) if completed else None

    def delete_inspection_session(self, session_id: int) -> bool:
        """删除巡机会话及其判定记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM inspection_records WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM inspection_sessions WHERE id = ?', (session_id,))
            return cursor.rowcount > 0

    def cleanup_stale_incomplete_sessions(self, max_age_hours: int = 48) -> int:
        """清理超过指定时间仍未完成的巡机会话（不影响进行中的巡机）。"""
        max_age_hours = max(1, int(max_age_hours or 48))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT id FROM inspection_sessions
                WHERE status != 'completed'
                  AND datetime(started_at) < datetime('now', ?)
            ''', (f'-{max_age_hours} hours',))
            session_ids = [row['id'] for row in cursor.fetchall()]
            if not session_ids:
                return 0

            placeholders = ','.join('?' * len(session_ids))
            cursor.execute(
                f'DELETE FROM inspection_records WHERE session_id IN ({placeholders})',
                session_ids,
            )
            cursor.execute(
                f'DELETE FROM inspection_sessions WHERE id IN ({placeholders})',
                session_ids,
            )
            return len(session_ids)

    def cleanup_incomplete_sessions(self) -> int:
        """清理所有未完成的巡机会话（仅用于显式维护，常规流程勿调用）。"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM inspection_sessions WHERE status != 'completed'")
            session_ids = [row['id'] for row in cursor.fetchall()]
            if not session_ids:
                return 0

            placeholders = ','.join('?' * len(session_ids))
            cursor.execute(
                f'DELETE FROM inspection_records WHERE session_id IN ({placeholders})',
                session_ids,
            )
            cursor.execute("DELETE FROM inspection_sessions WHERE status != 'completed'")
            return len(session_ids)

    def _refresh_inspection_session_stats(self, cursor, session_id: int):
        """刷新巡机会话统计数据"""
        cursor.execute('''
            SELECT
                COUNT(*) as reviewed_count,
                SUM(CASE WHEN defect_type = 1 THEN 1 ELSE 0 END) as pass_count,
                SUM(CASE WHEN defect_type != 1 THEN 1 ELSE 0 END) as defect_count
            FROM inspection_records
            WHERE session_id = ?
        ''', (session_id,))
        row = cursor.fetchone()
        reviewed_count = row['reviewed_count'] or 0
        pass_count = row['pass_count'] or 0
        defect_count = row['defect_count'] or 0
        cursor.execute('''
            UPDATE inspection_sessions
            SET reviewed_count = ?, pass_count = ?, defect_count = ?
            WHERE id = ?
        ''', (reviewed_count, pass_count, defect_count, session_id))

    def get_inspection_sessions(self, project_name: str = None,
                                start_date: str = None, end_date: str = None,
                                limit: int = None) -> List[Dict]:
        """获取巡机会话列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM inspection_sessions WHERE status = 'completed'"
            params = []

            if project_name:
                query += ' AND project_name = ?'
                params.append(project_name)
            if start_date:
                query += ' AND date(COALESCE(completed_at, started_at)) >= date(?)'
                params.append(start_date)
            if end_date:
                query += ' AND date(COALESCE(completed_at, started_at)) <= date(?)'
                params.append(end_date)

            query += ' ORDER BY COALESCE(completed_at, started_at) DESC, id DESC'

            if limit:
                query += ' LIMIT ?'
                params.append(limit)

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _resolve_defect_label(self, row, defect_labels: Dict = None) -> str:
        """解析单条记录的缺陷名称，优先使用自定义/已存名称，否则从类型映射反查。"""
        custom_defect = str(row['custom_defect'] or '').strip()
        defect_name = str(row['defect_name'] or '').strip()
        defect_type = row['defect_type']

        if custom_defect:
            return custom_defect
        if defect_name:
            return defect_name
        if defect_labels and defect_type is not None:
            label = defect_labels.get(defect_type)
            if label is None:
                label = defect_labels.get(str(defect_type), '')
            label = str(label or '').strip()
            if label and label != '合格':
                return label
        return ''

    def get_session_defect_issues_map(
        self, session_ids: List[int], defect_labels: Dict = None
    ) -> Dict[int, List[str]]:
        """获取各巡机会话的缺陷问题描述，如「D6 · A穴 · 缺胶」"""
        if not session_ids:
            return {}

        placeholders = ','.join('?' * len(session_ids))
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'''
                SELECT session_id, machine_name, point_name, defect_name, custom_defect, defect_type
                FROM inspection_records
                WHERE session_id IN ({placeholders}) AND defect_type != 1
                ORDER BY session_id, machine_name, point_name, reviewed_at
            ''', session_ids)

            grouped: Dict[int, Dict[tuple, List[str]]] = {}
            for row in cursor.fetchall():
                session_id = row['session_id']
                if session_id is None:
                    continue

                machine_name = str(row['machine_name'] or '').strip() or '-'
                point_name = str(row['point_name'] or '').strip() or '-'
                issue = self._resolve_defect_label(row, defect_labels)
                if not issue:
                    continue
                group_key = (machine_name, point_name)
                if session_id not in grouped:
                    grouped[session_id] = {}
                if issue not in grouped[session_id].setdefault(group_key, []):
                    grouped[session_id][group_key].append(issue)

        result: Dict[int, List[str]] = {}
        for session_id, group_map in grouped.items():
            result[session_id] = [
                f'{machine} · {point}穴 · {"、".join(issues)}'
                for (machine, point), issues in sorted(group_map.items(), key=lambda item: (item[0][0], item[0][1]))
            ]
        return result
    
    def get_inspection_records(self, project_name: str = None, machine_name: str = None,
                              point_name: str = None, start_date: str = None,
                              end_date: str = None, limit: int = None,
                              session_id: int = None) -> List[Dict]:
        """获取审核记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM inspection_records WHERE 1=1'
            params = []
            
            if session_id:
                query += ' AND session_id = ?'
                params.append(session_id)
            if project_name:
                query += ' AND project_name = ?'
                params.append(project_name)
            if machine_name:
                query += ' AND machine_name = ?'
                params.append(machine_name)
            if point_name:
                query += ' AND point_name = ?'
                params.append(point_name)
            if start_date:
                query += ' AND reviewed_at >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND reviewed_at <= ?'
                params.append(end_date)
            
            query += ' ORDER BY reviewed_at DESC'
            
            if limit:
                query += ' LIMIT ?'
                params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_statistics(self, project_name: str = None, start_date: str = None,
                      end_date: str = None) -> Dict[str, Any]:
        """获取统计数据"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN defect_type = 1 THEN 1 ELSE 0 END) as pass_count,
                    SUM(CASE WHEN defect_type != 1 THEN 1 ELSE 0 END) as defect_count
                FROM inspection_records
                WHERE 1=1
            '''
            params = []
            
            if project_name:
                query += ' AND project_name = ?'
                params.append(project_name)
            if start_date:
                query += ' AND reviewed_at >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND reviewed_at <= ?'
                params.append(end_date)
            
            cursor.execute(query, params)
            row = cursor.fetchone()
            total = row[0] or 0
            pass_count = row[1] or 0
            defect_count = row[2] or 0
            
            return {
                'total': total,
                'pass_count': pass_count,
                'defect_count': defect_count,
                'pass_rate': (pass_count / total * 100) if total > 0 else 0
            }
    
    # ==================== 巡机进度相关方法 ====================
    
    def save_inspection_progress(self, project_name: str, machine_name: str,
                                 point_name: str, last_image_index: int):
        """保存巡机进度"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO inspection_progress 
                (project_name, machine_name, point_name, last_image_index, last_reviewed_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (project_name, machine_name, point_name, last_image_index))
    
    def get_inspection_progress(self, project_name: str, machine_name: str,
                               point_name: str) -> Optional[Dict]:
        """获取巡机进度"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM inspection_progress 
                WHERE project_name = ? AND machine_name = ? AND point_name = ?
            ''', (project_name, machine_name, point_name))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    # ==================== 用户管理相关方法 ====================
    
    def verify_user(self, username: str, password: str) -> Optional[Dict]:
        """验证用户登录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users WHERE username = ? AND password = ?
            ''', (username, password))
            row = cursor.fetchone()
            if row:
                user = dict(row)
                user.pop('password', None)  # 不返回密码
                return user
            return None
    
    def get_all_users(self) -> List[Dict]:
        """获取所有用户"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, role, created_at FROM users')
            return [dict(row) for row in cursor.fetchall()]
    
    def add_user(self, username: str, password: str, role: str = 'user') -> int:
        """添加用户"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO users (username, password, role)
                VALUES (?, ?, ?)
            ''', (username, password, role))
            return cursor.lastrowid
    
    def update_user_password(self, user_id: int, new_password: str) -> bool:
        """更新用户密码"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE users SET password = ? WHERE id = ?
            ''', (new_password, user_id))
            return cursor.rowcount > 0
    
    def delete_user(self, user_id: int) -> bool:
        """删除用户"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
            return cursor.rowcount > 0
    
    # ==================== 配置管理相关方法 ====================
    
    def get_config(self, config_key: str, default: Any = None) -> Any:
        """获取配置项"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT config_value, config_type FROM system_config
                WHERE config_key = ?
            ''', (config_key,))
            row = cursor.fetchone()
            if row:
                value = row['config_value']
                config_type = row['config_type']
                if config_type == 'int':
                    return int(value)
                elif config_type == 'float':
                    return float(value)
                elif config_type == 'bool':
                    return value.lower() in ('true', '1', 'yes')
                return value
            return default
    
    def set_config(self, config_key: str, config_value: Any, 
                  config_type: str = 'string', description: str = '') -> bool:
        """设置配置项"""
        str_value = str(config_value)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO system_config 
                (config_key, config_value, config_type, description, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (config_key, str_value, config_type, description))
            return True
    
    def get_all_configs(self) -> List[Dict]:
        """获取所有配置"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM system_config ORDER BY config_key')
            return [dict(row) for row in cursor.fetchall()]

    def replace_project_machine_mappings(self, mappings: List[Dict[str, str]]) -> bool:
        """覆盖保存项目与机台的对应关系"""
        cleaned_mappings = []
        seen_pairs = set()

        for item in mappings:
            project_name = str(item.get('project_name', '')).strip()
            machine_name = str(item.get('machine_name', '')).strip()

            if not project_name or not machine_name:
                continue

            pair_key = (project_name, machine_name)
            if pair_key in seen_pairs:
                continue

            seen_pairs.add(pair_key)
            cleaned_mappings.append(pair_key)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM project_machine_mappings')

            for project_name, machine_name in cleaned_mappings:
                cursor.execute('''
                    INSERT INTO project_machine_mappings
                    (project_name, machine_name, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                ''', (project_name, machine_name))

            return True
    
    # ==================== 归档规则相关方法 ====================
    
    def add_archive_rule(self, name: str, source_dir: str, archive_dir: str, source_pattern: str,
                       target_pattern: str, rename_pattern: str = '{filename}',
                       enabled: bool = True) -> int:
        """添加归档规则"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO archive_rules 
                (name, source_dir, archive_dir, source_pattern, target_pattern, rename_pattern, enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (name, source_dir, archive_dir, source_pattern, target_pattern, rename_pattern, 1 if enabled else 0))
            return cursor.lastrowid
    
    def update_archive_rule(self, rule_id: int, name: str = None, 
                          source_dir: str = None, archive_dir: str = None,
                          source_pattern: str = None, target_pattern: str = None,
                          rename_pattern: str = None, enabled: bool = None) -> bool:
        """更新归档规则"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = []
            params = []
            
            if name is not None:
                updates.append('name = ?')
                params.append(name)
            if source_dir is not None:
                updates.append('source_dir = ?')
                params.append(source_dir)
            if archive_dir is not None:
                updates.append('archive_dir = ?')
                params.append(archive_dir)
            if source_pattern is not None:
                updates.append('source_pattern = ?')
                params.append(source_pattern)
            if target_pattern is not None:
                updates.append('target_pattern = ?')
                params.append(target_pattern)
            if rename_pattern is not None:
                updates.append('rename_pattern = ?')
                params.append(rename_pattern)
            if enabled is not None:
                updates.append('enabled = ?')
                params.append(1 if enabled else 0)
            
            if updates:
                updates.append('updated_at = CURRENT_TIMESTAMP')
                params.append(rule_id)
                
                query = f'UPDATE archive_rules SET {", ".join(updates)} WHERE id = ?'
                cursor.execute(query, params)
                return cursor.rowcount > 0
            return False
    
    def delete_archive_rule(self, rule_id: int) -> bool:
        """删除归档规则"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM archive_rules WHERE id = ?', (rule_id,))
            return cursor.rowcount > 0
    
    def get_image_by_source_path(self, source_path: str) -> Optional[Dict]:
        """根据源文件路径获取归档记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM archived_images WHERE source_path = ? LIMIT 1',
                (source_path,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_archive_rules(self, enabled_only: bool = False) -> List[Dict]:
        """获取归档规则列表"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = 'SELECT * FROM archive_rules'
            params = []
            
            if enabled_only:
                query += ' WHERE enabled = 1'
            
            query += ' ORDER BY id'
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    def get_archive_rule(self, rule_id: int) -> Optional[Dict]:
        """获取单个归档规则"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM archive_rules WHERE id = ?', (rule_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== 机台客户端心跳 ====================

    def upsert_client_heartbeat(
        self,
        machine_name: str,
        project_name: str = None,
        client_id: str = None,
        client_version: str = None,
        client_status: str = None,
        ip_address: str = None,
        host_name: str = None,
    ) -> None:
        """记录或更新机台客户端心跳"""
        now_text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO client_heartbeats
                (machine_name, project_name, client_id, client_version, client_status,
                 ip_address, host_name, last_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(machine_name) DO UPDATE SET
                    project_name = COALESCE(excluded.project_name, client_heartbeats.project_name),
                    client_id = COALESCE(excluded.client_id, client_heartbeats.client_id),
                    client_version = COALESCE(excluded.client_version, client_heartbeats.client_version),
                    client_status = COALESCE(excluded.client_status, client_heartbeats.client_status),
                    ip_address = COALESCE(excluded.ip_address, client_heartbeats.ip_address),
                    host_name = COALESCE(excluded.host_name, client_heartbeats.host_name),
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
            ''', (
                machine_name,
                project_name,
                client_id,
                client_version,
                client_status,
                ip_address,
                host_name,
                now_text,
                now_text,
            ))

    def get_all_client_heartbeats(self) -> List[Dict]:
        """获取全部机台客户端心跳记录"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM client_heartbeats
                ORDER BY machine_name
            ''')
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _parse_db_timestamp(value) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T', 1))
        except ValueError:
            try:
                return datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return None

    def get_client_monitor_status(self, timeout_seconds: int = 60) -> Dict[str, Any]:
        """汇总机台客户端在线状态"""
        timeout_seconds = max(10, int(timeout_seconds or 60))
        now = datetime.now()
        mappings = self.get_project_machine_mappings()
        heartbeat_map = {
            row['machine_name']: row for row in self.get_all_client_heartbeats()
        }
        seen_machines = set()
        machines = []

        def build_status(project_name: str, machine_name: str, heartbeat_row=None) -> Dict[str, Any]:
            last_seen_at = None
            seconds_since_last = None
            client_status = ''
            ip_address = ''
            host_name = ''
            client_version = ''
            client_id = ''

            if heartbeat_row:
                last_seen_dt = self._parse_db_timestamp(heartbeat_row.get('last_seen_at'))
                if last_seen_dt:
                    last_seen_at = last_seen_dt.strftime('%Y-%m-%d %H:%M:%S')
                    seconds_since_last = max(0, int((now - last_seen_dt).total_seconds()))
                client_status = str(heartbeat_row.get('client_status') or '').strip()
                ip_address = str(heartbeat_row.get('ip_address') or '').strip()
                host_name = str(heartbeat_row.get('host_name') or '').strip()
                client_version = str(heartbeat_row.get('client_version') or '').strip()
                client_id = str(heartbeat_row.get('client_id') or '').strip()

            if heartbeat_row is None:
                runtime_status = 'never'
                online = False
            elif seconds_since_last is not None and seconds_since_last <= timeout_seconds:
                runtime_status = 'online'
                online = True
            else:
                runtime_status = 'offline'
                online = False

            return {
                'project_name': project_name or '-',
                'machine_name': machine_name,
                'online': online,
                'runtime_status': runtime_status,
                'client_status': client_status or ('running' if online else ''),
                'last_seen_at': last_seen_at,
                'seconds_since_last': seconds_since_last,
                'ip_address': ip_address,
                'host_name': host_name,
                'client_version': client_version,
                'client_id': client_id,
            }

        for mapping in mappings:
            machine_name = str(mapping.get('machine_name') or '').strip()
            project_name = str(mapping.get('project_name') or '').strip()
            if not machine_name:
                continue
            seen_machines.add(machine_name)
            machines.append(build_status(
                project_name,
                machine_name,
                heartbeat_map.get(machine_name),
            ))

        for machine_name, heartbeat_row in heartbeat_map.items():
            if machine_name in seen_machines:
                continue
            project_name = str(heartbeat_row.get('project_name') or '').strip() or '未配置项目'
            machines.append(build_status(project_name, machine_name, heartbeat_row))

        machines.sort(key=lambda item: (item['project_name'], item['machine_name']))

        online_count = sum(1 for item in machines if item['runtime_status'] == 'online')
        offline_count = sum(1 for item in machines if item['runtime_status'] == 'offline')
        never_count = sum(1 for item in machines if item['runtime_status'] == 'never')

        offline_machines = [
            {
                'project_name': item['project_name'],
                'machine_name': item['machine_name'],
                'last_seen_at': item['last_seen_at'],
                'seconds_since_last': item['seconds_since_last'],
            }
            for item in machines if item['runtime_status'] == 'offline'
        ]
        never_machines = [
            {
                'project_name': item['project_name'],
                'machine_name': item['machine_name'],
            }
            for item in machines if item['runtime_status'] == 'never'
        ]

        return {
            'timeout_seconds': timeout_seconds,
            'checked_at': now.strftime('%Y-%m-%d %H:%M:%S'),
            'summary': {
                'total': len(machines),
                'online': online_count,
                'offline': offline_count,
                'never': never_count,
            },
            'offline_machines': offline_machines,
            'never_machines': never_machines,
            'machines': machines,
        }
