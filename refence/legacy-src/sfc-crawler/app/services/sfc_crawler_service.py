"""
SFC 爬虫服务

功能：
1. 账号池轮换登录
2. 下载项目数据（重试 3 次）
3. 批量上传数据（UPSERT）
4. 动态表结构管理
"""
import time
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
import urllib.parse

import requests
import pandas as pd
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session

from app.db.engines import get_cfg_engine
from app.core.encryption import encryption_manager
from app.models.sfc_crawler import (
    SfcCrawlerConfig,
    SfcAccount,
    SfcProject,
)

# 配置日志
logger = logging.getLogger(__name__)


# ==================== 自定义异常 ====================

class NetworkUnreachableError(Exception):
    """网络不可达异常"""
    pass


class AccountError(Exception):
    """账号认证失败异常"""
    pass


class TimeoutError(Exception):
    """超时异常"""
    pass


class ServerLimitError(Exception):
    """服务器限制异常"""
    pass


class SessionExpiredError(Exception):
    """Session 过期异常"""
    pass



# ==================== 辅助函数 ====================

def get_crawler_config(db: Session) -> Optional[SfcCrawlerConfig]:
    """获取爬虫配置（不过滤 is_active 状态）"""
    return db.query(SfcCrawlerConfig).first()


def get_enabled_accounts(db: Session) -> List[SfcAccount]:
    """获取启用的账号列表（按 sort_order 排序）"""
    return db.query(SfcAccount).filter(
        SfcAccount.is_active == True
    ).order_by(SfcAccount.sort_order).all()


def get_enabled_projects(db: Session) -> List[SfcProject]:
    """获取启用的项目列表"""
    return db.query(SfcProject).filter(SfcProject.is_enabled == True).all()


def update_account_stats(db: Session, account: SfcAccount, success: bool, error_msg: str = None):
    """更新账号统计信息"""
    account.total_use_count += 1
    account.last_use_time = datetime.now()
    
    if success:
        account.success_count += 1
        account.last_use_status = 'success'
        account.last_error_message = None
    else:
        account.failed_count += 1
        account.last_use_status = 'failed'
        account.last_error_message = error_msg
    
    db.commit()


def create_crawler_log(
    db: Session,
    project_id: int = None,
    project_name: str = None,
    account_id: int = None,
    account_username: str = None,
    trigger_type: str = 'auto',
    status: str = 'running',
    message: str = None,
    error_message: str = None,
    data_count: int = 0,
    file_size: int = 0,
    start_time: datetime = None,
    end_time: datetime = None,
    duration: int = 0,
    execution_logs: list = None,
):
    """创建爬虫日志（使用文件存储）"""
    logger.info(f"准备创建日志: project={project_name}, account={account_username}, trigger={trigger_type}, status={status}, message={message}")
    
    try:
        # 使用文件日志工具
        from app.utils.file_logger import file_logger
        
        # 写入文件日志
        log_file = file_logger.write_sfc_log(
            config_id=project_id,
            config_name=project_name or '',
            account=account_username or '',
            status=status,
            trigger_type=trigger_type,
            message=message or '',
            records_count=data_count,
            duration=duration,
            execution_logs=execution_logs
        )
        
        logger.info(f"日志写入成功: {log_file}")
        
        # 返回一个简单的对象（兼容旧代码）
        class LogResult:
            def __init__(self):
                from datetime import datetime
                self.id = int(datetime.now().timestamp() * 1000)  # 使用时间戳作为 ID
        
        return LogResult()
        
    except Exception as e:
        logger.error(f"创建日志失败: {e}")
        raise


def update_project_stats(db: Session, project: SfcProject, success: bool):
    """更新项目统计信息"""
    project.last_crawl_time = datetime.now()
    project.last_crawl_status = 'success' if success else 'failed'
    project.total_crawl_count += 1
    db.commit()



# ==================== 第一步：登录 ====================

def try_login_account(config: SfcCrawlerConfig, account: SfcAccount) -> requests.Session:
    """
    尝试使用单个账号登录
    
    返回：Session 对象
    抛出：NetworkUnreachableError, AccountError, TimeoutError, ServerLimitError
    """
    try:
        # 解密密码
        password = encryption_manager.decrypt(account.password)
        
        # 构造 SSO 登录 URL
        sfc_logon_url = f"{config.sfc_base_url}{config.sfc_logon_path}"
        encoded_url = urllib.parse.quote(sfc_logon_url, safe='')
        sso_url = f"{config.sso_login_url}?url={encoded_url}"
        
        logger.info(f"尝试登录账号: {account.username}")
        
        # 创建 Session
        session = requests.Session()
        
        # 第零步：检查网络连通性（先访问 SSO 登录页面）
        logger.info(f"检查网络连通性: {config.sso_login_url}")
        try:
            check_response = session.get(config.sso_login_url, timeout=10)
            if check_response.status_code >= 500:
                raise NetworkUnreachableError(f"SSO 服务器错误 (HTTP {check_response.status_code})，请检查服务器状态")
            logger.info(f"网络连通性检查通过 (HTTP {check_response.status_code})")
        except requests.exceptions.ConnectionError as e:
            raise NetworkUnreachableError(f"无法连接到 SSO 服务器，请检查网络连接或服务器地址是否正确")
        except requests.exceptions.Timeout as e:
            raise NetworkUnreachableError(f"连接 SSO 服务器超时，请检查网络状况")
        
        # 第一步：POST 登录到 login.aspx
        # 注意：表单字段名是 txtUserNo 和 txtPass，不是 username 和 password
        response = session.post(
            sso_url,
            data={
                'txtUserNo': account.username,
                'txtPass': password,
                'txtUrl': sfc_logon_url,  # 登录成功后跳转的地址
                'txtEffectiveTime': '720',  # 有效时间（分钟）
            },
            timeout=30,
            allow_redirects=False,  # 不自动跳转，需要手动处理
        )
        
        # 判断响应
        if response.status_code == 401 or response.status_code == 403:
            raise AccountError(f"账号密码错误或无权限")
        
        if response.status_code == 429:
            raise ServerLimitError("请求过于频繁，请稍后再试")
        
        if response.status_code == 503:
            raise ServerLimitError("服务器暂时不可用，请稍后再试")
        
        if response.status_code >= 500:
            raise Exception(f"服务器错误 (HTTP {response.status_code})")
        
        if response.status_code != 200:
            raise Exception(f"登录请求失败 (HTTP {response.status_code})")
        
        # 检查响应内容（login.aspx 返回 "1" 表示成功）
        response_text = response.text.strip()
        if response_text != "1":
            # 登录失败，响应内容是错误信息
            error_msg = response_text.replace('未知的', '').strip()
            if not error_msg:
                error_msg = "登录失败，用户名或密码错误"
            raise AccountError(error_msg)
        
        logger.info(f"第一步登录成功，准备访问 ValidateTaken.aspx")
        
        # 第二步：访问 ValidateTaken.aspx 设置 cookies 并跳转
        # 这一步会设置认证 cookies 并重定向到目标 URL
        sso_base_url = config.sso_login_url.rsplit('/', 1)[0]
        validate_url = f"{sso_base_url}/ValidateTaken.aspx?url={urllib.parse.quote(sfc_logon_url)}"
        
        validate_response = session.get(validate_url, timeout=10, allow_redirects=True)
        
        if validate_response.status_code != 200:
            raise AccountError(f"设置 Session 失败 (HTTP {validate_response.status_code})")
        
        logger.info(f"第二步 ValidateTaken 完成，cookies 已设置")
        
        # 第三步：验证登录是否成功 - 访问 SFC 首页
        verify_url = f"{config.sfc_base_url}{config.sfc_logon_path}"
        verify_response = session.get(verify_url, timeout=10)
        
        if verify_response.status_code != 200:
            raise AccountError(f"登录验证失败：无法访问 SFC 系统 (HTTP {verify_response.status_code})")
        
        # 检查是否被重定向回登录页（说明 Session 无效）
        if 'login' in verify_response.url.lower() or 'sso' in verify_response.url.lower():
            raise AccountError("登录验证失败：Session 无效，被重定向到登录页")
        
        # 检查响应内容长度（太短可能是错误页面）
        if len(verify_response.text) < 100:
            raise AccountError(f"登录验证失败：响应内容异常（长度: {len(verify_response.text)}）")
        
        # 第四步：访问数据页面的父页面（确保 Session 完全建立）
        # 有些系统需要先访问主页面才能访问子页面
        try:
            # 访问 Views 目录的默认页面
            default_page_url = f"{config.sfc_base_url}/SFCS/Views/Default.aspx"
            default_response = session.get(default_page_url, timeout=10, allow_redirects=True)
            logger.info(f"访问默认页面成功 (HTTP {default_response.status_code})")
        except Exception as e:
            logger.warning(f"访问默认页面失败（可忽略）: {e}")
        
        logger.info(f"账号 {account.username} 登录成功")
        return session
        
    except requests.exceptions.ConnectionError as e:
        raise NetworkUnreachableError(f"无法连接到服务器，请检查网络连接")
    
    except requests.exceptions.Timeout as e:
        raise TimeoutError(f"请求超时，请检查网络状况")
    
    except (NetworkUnreachableError, AccountError, TimeoutError, ServerLimitError):
        raise
    
    except Exception as e:
        raise Exception(f"登录异常: {e}")


def login_sfc(db: Session) -> Optional[tuple]:
    """
    账号池轮换登录
    
    返回：(Session 对象, SfcAccount 对象, 执行日志列表) 或 (None, None, 执行日志列表)
    """
    execution_logs = []
    
    def add_log(level: str, message: str):
        """添加执行日志"""
        execution_logs.append({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'level': level,
            'message': message
        })
        logger.info(f"[{level.upper()}] {message}")
    
    # 获取配置
    add_log('info', '开始登录流程')
    config = get_crawler_config(db)
    if not config:
        add_log('error', '未找到爬虫配置')
        return (None, None, execution_logs)
    
    # 获取账号池
    accounts = get_enabled_accounts(db)
    if not accounts:
        add_log('error', '没有可用账号')
        return (None, None, execution_logs)
    
    add_log('info', f'账号池数量: {len(accounts)}')
    
    # 遍历账号池
    for account in accounts:
        add_log('info', f'尝试使用账号: {account.username}')
        
        # 每个账号最多重试 2 次（共 3 次尝试）
        for retry in range(3):
            try:
                if retry > 0:
                    add_log('info', f'第 {retry + 1} 次尝试登录账号: {account.username}')
                
                session = try_login_account(config, account)
                update_account_stats(db, account, success=True)
                add_log('success', f'账号 {account.username} 登录成功')
                return (session, account, execution_logs)  # 返回 session、account 和日志
                
            except NetworkUnreachableError as e:
                # 网络不可达 - 直接结束本轮
                add_log('error', f'网络不可达: {e}')
                update_account_stats(db, account, success=False, error_msg=str(e))
                return (None, None, execution_logs)
                
            except AccountError as e:
                # 账号错误 - 不重试，下一个账号
                add_log('warning', f'账号 {account.username} 认证失败: {e}')
                update_account_stats(db, account, success=False, error_msg=str(e))
                break
                
            except (TimeoutError, ServerLimitError) as e:
                # 超时/限制 - 重试 2 次
                if retry < 2:
                    add_log('warning', f'账号 {account.username} {type(e).__name__} (第{retry+1}次)，5秒后重试...')
                    time.sleep(5)
                    continue
                else:
                    add_log('error', f'账号 {account.username} 重试 2 次后仍失败')
                    update_account_stats(db, account, success=False, error_msg=str(e))
                    break
                    
            except Exception as e:
                # 其他错误 - 重试 2 次
                if retry < 2:
                    add_log('warning', f'账号 {account.username} 未知错误 (第{retry+1}次)，5秒后重试...')
                    time.sleep(5)
                    continue
                else:
                    add_log('error', f'账号 {account.username} 重试 2 次后仍失败: {e}')
                    update_account_stats(db, account, success=False, error_msg=str(e))
                    break
    
    # 所有账号都失败
    add_log('error', '所有账号都失败')
    return (None, None, execution_logs)



# ==================== 第二步：下载数据 ====================

def download_project_data(
    session: requests.Session,
    config: SfcCrawlerConfig,
    project: SfcProject,
    max_retries: int = 3
) -> str:
    """
    下载项目数据（重试 3 次）
    
    返回：CSV 数据（字符串）
    抛出：SessionExpiredError, Exception
    """
    for retry in range(max_retries):
        try:
            # 构造数据页面 URL（注意：使用双 & 符号）
            url = f"{config.sfc_base_url}{config.sfc_data_path}?p={project.sfc_code}&&type={project.btype}"
            
            # 先访问页面（建立 Session 状态，并获取表单字段）
            page_response = session.get(url, timeout=30)
            
            # 检查 Session 是否过期
            if 'login' in page_response.url.lower() or page_response.status_code == 401:
                raise SessionExpiredError("Session 已过期，需要重新登录")
            
            if page_response.status_code != 200:
                raise Exception(f"访问页面失败: HTTP {page_response.status_code}")
            
            # 从页面提取必需的 ASP.NET ViewState 字段和默认时间
            import re
            
            # 提取 ViewState 字段（ASP.NET 必需）
            viewstate_match = re.search(r'name="__VIEWSTATE"[^>]*value="([^"]*)"', page_response.text)
            viewstate_gen_match = re.search(r'name="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"', page_response.text)
            event_val_match = re.search(r'name="__EVENTVALIDATION"[^>]*value="([^"]*)"', page_response.text)
            
            # 提取时间字段
            start_time_match = re.search(r'name="ctl00\$pageBody\$txtStartTime"[^>]*value="([^"]*)"', page_response.text)
            end_time_match = re.search(r'name="ctl00\$pageBody\$txtEndTime"[^>]*value="([^"]*)"', page_response.text)
            
            logger.info(f"下载项目 {project.name} 数据 (第{retry+1}次尝试)")
            
            # 构造 POST 表单数据（包含 ViewState 和时间）
            form_data = {
                'ctl00$pageBody$txtLine': config.line_option,      # 线别（如 all）
                'ctl00$pageBody$txtSection': config.section_option, # 区域（如 LIM）
                'ctl00$pageBody$btnDownload': '下载',               # 下载按钮
            }
            
            # 添加 ViewState 字段（ASP.NET 必需）
            if viewstate_match:
                form_data['__VIEWSTATE'] = viewstate_match.group(1)
            if viewstate_gen_match:
                form_data['__VIEWSTATEGENERATOR'] = viewstate_gen_match.group(1)
            if event_val_match:
                form_data['__EVENTVALIDATION'] = event_val_match.group(1)
            
            # 添加时间字段
            if start_time_match:
                start_time = start_time_match.group(1)
                form_data['ctl00$pageBody$txtStartTime'] = start_time
                logger.info(f"使用页面默认开始时间: {start_time}")
            if end_time_match:
                end_time = end_time_match.group(1)
                form_data['ctl00$pageBody$txtEndTime'] = end_time
                logger.info(f"使用页面默认结束时间: {end_time}")
            
            # 设置 Referer 头
            headers = {
                'Referer': url,
            }
            
            # 发送 POST 请求下载 CSV
            response = session.post(url, data=form_data, headers=headers, timeout=120)
            
            # 检查 Session 是否过期
            if 'login' in response.url.lower() or response.status_code == 401:
                raise SessionExpiredError("Session 已过期，需要重新登录")
            
            if response.status_code == 200:
                # 检查是否返回了 CSV 文件
                content_type = response.headers.get('Content-Type', '')
                content_disp = response.headers.get('Content-Disposition', '')
                
                if 'application/octet-stream' in content_type or 'attachment' in content_disp:
                    logger.info(f"项目 {project.name} 数据下载成功，大小: {len(response.text)} 字节")
                    return response.text
                else:
                    # 可能返回的是 HTML 页面（错误或 Session 过期）
                    if '<!DOCTYPE' in response.text[:100] or '<html' in response.text[:100]:
                        raise SessionExpiredError("返回了 HTML 页面，可能 Session 已过期")
                    else:
                        logger.info(f"项目 {project.name} 数据下载成功，大小: {len(response.text)} 字节")
                        return response.text
            else:
                raise Exception(f"HTTP {response.status_code}")
                
        except SessionExpiredError:
            raise
            
        except Exception as e:
            if retry < max_retries - 1:
                logger.warning(f"下载失败 (第{retry+1}次)，5秒后重试: {e}")
                time.sleep(5)
            else:
                raise Exception(f"下载失败，已重试 {max_retries} 次: {e}")
    
    raise Exception("下载失败")



# ==================== 第三步：上传数据 ====================


def table_exists(engine, table_name: str) -> bool:
    """检查表是否存在"""
    with engine.connect() as conn:
        result = conn.execute(text(
            f"SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_schema = DATABASE() AND table_name = '{table_name}'"
        ))
        return result.scalar() > 0


def get_table_columns(engine, table_name: str) -> List[str]:
    """获取表的列名"""
    with engine.connect() as conn:
        result = conn.execute(text(f"SHOW COLUMNS FROM `{table_name}`"))
        return [row[0] for row in result]


def infer_column_type_from_data(df: pd.DataFrame, column_name: str) -> str:
    """根据列数据推断列类型"""
    import numpy as np
    
    # SN 列固定为 VARCHAR
    if column_name.upper() == 'SN':
        return 'VARCHAR(100)'
    
    # 获取该列的数据（去除 None）
    col_data = df[column_name].dropna()
    
    if len(col_data) == 0:
        return 'TEXT'
    
    # 检查是否是时间类型
    if 'time' in column_name.lower() or 'date' in column_name.lower():
        return 'DATETIME'
    
    # 尝试转换为数值类型
    try:
        # 尝试转换为数字
        numeric_data = pd.to_numeric(col_data, errors='coerce')
        non_null_numeric = numeric_data.dropna()
        
        # 如果超过 80% 的数据可以转换为数字，认为是数值类型
        if len(non_null_numeric) / len(col_data) > 0.8:
            # 检查是否是整数
            if (non_null_numeric == non_null_numeric.astype(int)).all():
                # 检查数值范围
                max_val = non_null_numeric.max()
                min_val = non_null_numeric.min()
                
                if min_val >= -128 and max_val <= 127:
                    return 'TINYINT'
                elif min_val >= -32768 and max_val <= 32767:
                    return 'SMALLINT'
                elif min_val >= -2147483648 and max_val <= 2147483647:
                    return 'INT'
                else:
                    return 'BIGINT'
            else:
                # 小数类型
                return 'DECIMAL(20, 6)'
    except:
        pass
    
    # 检查字符串长度
    max_length = col_data.astype(str).str.len().max()
    
    if max_length <= 50:
        return 'VARCHAR(50)'
    elif max_length <= 100:
        return 'VARCHAR(100)'
    elif max_length <= 255:
        return 'VARCHAR(255)'
    else:
        return 'TEXT'


def infer_column_type(column_name: str) -> str:
    """根据列名推断列类型（简单版本，用于兼容）"""
    if column_name.upper() == 'SN':
        return 'VARCHAR(100)'
    
    if 'time' in column_name.lower() or 'date' in column_name.lower():
        return 'DATETIME'
    
    # 默认为 TEXT
    return 'TEXT'


def create_raw_table(engine, table_name: str, columns: List[str], df: pd.DataFrame = None):
    """创建 raw 表"""
    # 第一列固定为 SN（主键，大写）
    col_definitions = ["`SN` VARCHAR(100) PRIMARY KEY"]
    
    # 其他列
    for col in columns[1:]:
        if df is not None:
            # 根据数据推断类型
            col_type = infer_column_type_from_data(df, col)
        else:
            # 根据列名推断类型
            col_type = infer_column_type(col)
        col_definitions.append(f"`{col}` {col_type}")
    
    # 系统列
    col_definitions.append("`upload_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    col_definitions.append("`created_at` DATETIME DEFAULT CURRENT_TIMESTAMP")
    
    # 创建表
    create_sql = f"""
        CREATE TABLE IF NOT EXISTS `{table_name}` (
            {', '.join(col_definitions)},
            INDEX idx_sn (SN),
            INDEX idx_upload_time (upload_time)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """
    
    with engine.connect() as conn:
        conn.execute(text(create_sql))
        conn.commit()
    
    logger.info(f"表 {table_name} 创建成功")


def ensure_table_schema(engine, table_name: str, csv_columns: List[str]):
    """
    确保表结构与 CSV 匹配
    如果 CSV 有新列，自动添加到表中
    """
    # 获取现有列
    existing_columns = get_table_columns(engine, table_name)
    
    # 找出新列（排除系统列）
    system_columns = ['upload_time', 'created_at']
    new_columns = [
        col for col in csv_columns 
        if col not in existing_columns and col not in system_columns
    ]
    
    # 添加新列
    if new_columns:
        with engine.connect() as conn:
            for col in new_columns:
                col_type = infer_column_type(col)
                sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{col}` {col_type}"
                conn.execute(text(sql))
                logger.info(f"表 {table_name} 新增列: {col} ({col_type})")
            conn.commit()


def batch_upsert(engine, table_name: str, df: pd.DataFrame, batch_size: int = 1000):
    """
    批量 UPSERT 数据
    
    策略：SN 存在则更新，不存在则插入
    使用真正的批量插入，一次性插入多条数据
    
    ✅ 优化：使用连接池，避免频繁创建/销毁连接
    ✅ 优化：每批次后清理内存
    
    返回：
        {
            'total': 总行数,
            'inserted': 新增行数,
            'updated': 覆盖行数
        }
    """
    total = len(df)
    total_inserted = 0
    total_updated = 0
    
    logger.info(f"开始批量上传数据到 {table_name}，总数: {total}")
    
    # ✅ 使用连接池：先查询哪些 SN 已存在
    with engine.connect() as conn:
        try:
            # 获取所有要上传的唯一 SN（去重）
            unique_sn_list = df['SN'].unique().tolist()
            
            # 查询已存在的 SN
            placeholders = ','.join([':sn' + str(i) for i in range(len(unique_sn_list))])
            check_sql = text(f"SELECT `SN` FROM `{table_name}` WHERE `SN` IN ({placeholders})")
            
            # 构造参数字典
            params = {f'sn{i}': sn for i, sn in enumerate(unique_sn_list)}
            
            result = conn.execute(check_sql, params)
            existing_sns = set(row[0] for row in result)
            
            # 计算新增和更新数量（基于唯一SN）
            total_inserted = len([sn for sn in unique_sn_list if sn not in existing_sns])
            total_updated = len([sn for sn in unique_sn_list if sn in existing_sns])
            
            logger.info(f"唯一SN数: {len(unique_sn_list)}, 预计新增: {total_inserted}, 预计覆盖: {total_updated}")
            
        except Exception as e:
            logger.warning(f"无法预查询 SN，将使用批量插入: {e}")
            # 如果表不存在或查询失败，假设全部是新增
            unique_sn_count = df['SN'].nunique()
            total_inserted = unique_sn_count
            total_updated = 0
    
    # ✅ 使用连接池：批量插入数据
    # 注意：批量插入使用原生连接以支持 executemany，但从连接池获取
    for i in range(0, total, batch_size):
        batch = df.iloc[i:i+batch_size]
        
        # 构造列名
        columns = ', '.join([f'`{col}`' for col in batch.columns])
        
        # 构造 VALUES 占位符（每行一组）
        single_row_placeholders = ', '.join(['%s'] * len(batch.columns))
        values_placeholders = ', '.join([f"({single_row_placeholders}, NOW())" for _ in range(len(batch))])
        
        # 构造 UPDATE 子句（排除 sn）
        update_parts = []
        for col in batch.columns:
            if col.upper() != 'SN':
                update_parts.append(f"`{col}` = VALUES(`{col}`)")
        update_parts.append("upload_time = NOW()")
        update_clause = ', '.join(update_parts)
        
        # 构造 SQL（一次性插入多条）
        sql = f"""
            INSERT INTO `{table_name}` ({columns}, upload_time)
            VALUES {values_placeholders}
            ON DUPLICATE KEY UPDATE {update_clause}
        """
        
        # 准备参数（将所有行的数据展平成一维列表）
        params = []
        for _, row in batch.iterrows():
            params.extend(list(row))
        
        # ✅ 使用连接池：从池中获取连接，执行后自动归还
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute(sql, params)
            raw_conn.commit()
            cursor.close()
        finally:
            # ✅ 关键：归还连接到池中（不是真正关闭）
            raw_conn.close()
        
        # ✅ 清理批次数据，释放内存
        del params
        del batch
        
        # 记录进度
        uploaded = min(i + batch_size, total)
        logger.info(f"已上传 {uploaded}/{total} 条 ({int(uploaded/total*100)}%)")
    
    logger.info(f"数据上传完成，共 {total} 条（新增: {total_inserted}, 覆盖: {total_updated}）")
    
    return {
        'total': total,
        'inserted': total_inserted,
        'updated': total_updated
    }


def upload_data(db: Session, project: SfcProject, csv_data: str):
    """
    上传数据到数据库
    
    步骤：
    1. 解析 CSV（第一列为 SN）
    2. 检查/创建表
    3. 批量 UPSERT
    4. ✅ 显式释放内存
    
    返回：
        {
            'total': 总行数,
            'inserted': 新增行数,
            'updated': 覆盖行数
        }
    """
    df = None  # 初始化 DataFrame 变量
    try:
        # 1. 解析 CSV
        from io import StringIO
        import numpy as np
        df = pd.read_csv(StringIO(csv_data), low_memory=False)
        
        if df.empty:
            logger.warning(f"项目 {project.name} 数据为空")
            return {'total': 0, 'inserted': 0, 'updated': 0}
        
        # 确保第一列为 SN（大写）
        columns = df.columns.tolist()
        if columns[0].upper() != 'SN':
            # 将第一列重命名为 SN
            df.rename(columns={columns[0]: 'SN'}, inplace=True)
            columns[0] = 'SN'
        
        # 向下填充 SN（将空的 SN 填充为上一行的 SN）
        df['SN'] = df['SN'].fillna(method='ffill')
        
        # 将其他列的 NaN 替换为 None（MySQL 的 NULL）
        df = df.replace({np.nan: None})
        
        # 过滤掉 SN 仍然为空的行（第一行之前没有 SN 的情况）
        df = df[df['SN'].notna()]
        df = df[df['SN'] != '']
        
        if df.empty:
            logger.warning(f"项目 {project.name} 过滤后数据为空（所有 SN 都为空）")
            return {'total': 0, 'inserted': 0, 'updated': 0}
        
        logger.info(f"解析 CSV 成功，列数: {len(columns)}, 行数: {len(df)}")
        
        # 2. 获取 MySQL 引擎
        from app.db.engines import get_mysql_engine
        engine = get_mysql_engine()
        
        # 3. 表名
        table_name = f"{project.prefix}_raw"
        
        # 4. 检查表是否存在
        if not table_exists(engine, table_name):
            logger.info(f"表 {table_name} 不存在，创建表")
            create_raw_table(engine, table_name, columns, df)
        else:
            logger.info(f"表 {table_name} 已存在，检查列是否匹配")
            ensure_table_schema(engine, table_name, columns)
        
        # 5. 批量 UPSERT
        result = batch_upsert(engine, table_name, df, batch_size=1000)
        
        logger.info(f"项目 {project.name} 数据上传成功")
        
        return result
        
    except Exception as e:
        logger.error(f"项目 {project.name} 数据上传失败: {e}")
        raise
    finally:
        # ✅ 关键：显式释放 DataFrame 内存
        if df is not None:
            try:
                # 删除 DataFrame 对象
                del df
                logger.debug("已释放 DataFrame 内存")
            except Exception as e:
                logger.warning(f"释放 DataFrame 内存失败: {e}")
        
        # ✅ 释放 csv_data 字符串（可能很大）
        try:
            del csv_data
            logger.debug("已释放 csv_data 内存")
        except Exception as e:
            logger.warning(f"释放 csv_data 内存失败: {e}")
        
        # ✅ 强制垃圾回收
        import gc
        collected = gc.collect()
        logger.debug(f"垃圾回收完成，回收对象数: {collected}")



# ==================== 主爬虫任务 ====================

def should_run_crawler(db: Session, manual: bool = False) -> bool:
    """
    检查是否应该运行爬虫
    
    参数：
        db: 数据库会话
        manual: 是否手动触发（手动触发时跳过 is_active 和间隔检查）
    
    条件：
    1. 爬虫未在运行中（防止并发执行）
    2. 爬虫配置已启用（手动触发时跳过此检查）
    3. 距离上次执行已经过了配置的间隔时间（手动触发时跳过此检查）
    
    返回：True 表示应该运行，False 表示跳过
    """
    # 获取配置
    config = get_crawler_config(db)
    if not config:
        logger.info("未找到爬虫配置")
        return False
    
    # ✅ 检查是否正在运行（防止并发执行）
    if config.is_running:
        logger.info("爬虫任务正在运行，跳过本次执行")
        return False
    
    # 手动触发时跳过其他检查
    if manual:
        logger.info("手动触发爬虫，跳过状态和间隔检查")
        return True
    
    # 自动触发时检查是否启用
    if not config.is_active:
        logger.info("爬虫配置未启用，跳过本次执行")
        return False
    
    # 优先使用配置表的 last_run_time
    if config.last_run_time:
        last_run = config.last_run_time
        logger.info(f"使用配置表的 last_run_time: {last_run}")
    else:
        # 如果配置表没有记录，说明是首次运行
        logger.info("首次运行爬虫（配置表无 last_run_time）")
        return True
    
    # 计算距离上次执行的时间（分钟）
    from datetime import datetime
    now = datetime.now()
    elapsed_minutes = (now - last_run).total_seconds() / 60
    
    # 检查是否已经过了配置的间隔时间
    if elapsed_minutes >= config.crawl_interval:
        logger.info(f"距离上次执行已过 {int(elapsed_minutes)} 分钟，满足间隔 {config.crawl_interval} 分钟，开始执行")
        return True
    else:
        logger.info(f"距离上次执行仅 {int(elapsed_minutes)} 分钟，未满足间隔 {config.crawl_interval} 分钟，跳过本次执行")
        return False


def update_crawler_last_run_time(db: Session, status: str = None):
    """
    更新爬虫配置的最后运行时间和状态
    
    参数：
        status: 'success' | 'failed' | None (不更新状态)
    """
    config = get_crawler_config(db)
    if config:
        config.last_run_time = datetime.now()
        if status:
            config.last_run_status = status
        db.commit()
        logger.info(f"更新爬虫最后运行时间: {config.last_run_time}, 状态: {status or '未更新'}")


def crawl_single_project(db: Session, session: requests.Session, config: SfcCrawlerConfig, project: SfcProject, account: SfcAccount, trigger_type: str):
    """
    爬取单个项目并收集详细执行日志
    
    ✅ 优化：显式释放 DataFrame 和 csv_data 内存
    
    返回：
        {
            'success': bool,
            'execution_logs': [
                {'time': '2026-01-01 10:00:00', 'level': 'info', 'message': '...'},
                ...
            ],
            'data_count': int,
            'file_size': int,
            'error_message': str
        }
    """
    execution_logs = []
    start_time = datetime.now()
    csv_data = None  # 初始化变量
    df = None  # 初始化变量
    
    def add_log(level: str, message: str):
        """添加执行日志"""
        execution_logs.append({
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'level': level,
            'message': str(message)
        })
        logger.info(f"[{level.upper()}] {message}")
    
    try:
        add_log('info', f'开始爬取项目: {project.name}')
        add_log('info', f'使用账号: {account.username}')
        add_log('info', f'SFC 代码: {project.sfc_code}, 类型: {project.btype}')
        
        # 使用新的 download_project_data 函数（支持 POST 方法）
        add_log('info', '开始下载数据...')
        try:
            csv_data = download_project_data(session, config, project, max_retries=3)
            add_log('success', f'数据下载成功，大小: {len(csv_data)} 字节')
        except SessionExpiredError as e:
            add_log('error', f'Session 过期: {e}')
            raise
        except Exception as e:
            add_log('error', f'下载失败: {e}')
            raise
        
        # 解析 CSV
        add_log('info', '开始解析 CSV 数据...')
        from io import StringIO
        import numpy as np
        import pandas as pd
        
        # 尝试多种方式解析 CSV（容错处理）
        parse_errors = []
        
        # 方法 1：标准解析
        try:
            df = pd.read_csv(StringIO(csv_data), low_memory=False)
            add_log('info', '使用标准方式解析成功')
        except Exception as e1:
            parse_errors.append(f"标准解析失败: {str(e1)}")
            
            # 方法 2：跳过错误行（不使用 low_memory）
            try:
                df = pd.read_csv(
                    StringIO(csv_data), 
                    on_bad_lines='skip',  # 跳过错误行
                    engine='python'
                )
                add_log('warning', f'使用容错方式解析成功（跳过了部分错误行）')
            except Exception as e2:
                parse_errors.append(f"容错解析失败: {str(e2)}")
                
                # 方法 3：手动清理数据后解析
                try:
                    # 清理数据：移除空行和只有逗号的行
                    lines = csv_data.strip().split('\n')
                    if not lines:
                        raise Exception("CSV 数据为空")
                    
                    # 获取表头（第一行）
                    header = lines[0]
                    header_fields = len(header.split(','))
                    
                    cleaned_lines = [header]
                    skipped_count = 0
                    
                    for i, line in enumerate(lines[1:], start=2):
                        # 跳过空行
                        if not line.strip():
                            skipped_count += 1
                            continue
                        
                        # 跳过只有逗号的行
                        if line.strip().replace(',', '').replace(' ', '') == '':
                            skipped_count += 1
                            continue
                        
                        # 检查字段数量是否匹配
                        fields = line.split(',')
                        if len(fields) != header_fields:
                            # 字段数量不匹配，尝试修复或跳过
                            skipped_count += 1
                            continue
                        
                        cleaned_lines.append(line)
                    
                    if len(cleaned_lines) <= 1:
                        raise Exception("清理后没有数据行")
                    
                    cleaned_csv = '\n'.join(cleaned_lines)
                    df = pd.read_csv(StringIO(cleaned_csv), low_memory=False)
                    add_log('warning', f'使用数据清理方式解析成功（跳过了 {skipped_count} 行错误数据）')
                except Exception as e3:
                    parse_errors.append(f"数据清理解析失败: {str(e3)}")
                    
                    # 方法 4：最宽松的解析（使用 sep 和 quoting）
                    try:
                        df = pd.read_csv(
                            StringIO(csv_data),
                            sep=',',
                            engine='python',
                            on_bad_lines='skip',
                            quoting=3,  # QUOTE_NONE
                            encoding='utf-8',
                            skipinitialspace=True
                        )
                        add_log('warning', f'使用最宽松方式解析成功（可能丢失部分数据）')
                    except Exception as e4:
                        parse_errors.append(f"最宽松解析失败: {str(e4)}")
                        raise Exception(f"CSV 解析失败，尝试了 4 种方法:\n" + "\n".join(parse_errors))
        
        if df is None:
            raise Exception(f"CSV 解析失败:\n" + "\n".join(parse_errors))
        
        if df.empty:
            add_log('warning', 'CSV 数据为空')
            return {
                'success': True,
                'execution_logs': execution_logs,
                'data_count': 0,
                'file_size': len(csv_data) if csv_data else 0,
                'error_message': None
            }
        
        # 确保第一列为 SN
        columns = df.columns.tolist()
        if columns[0].upper() != 'SN':
            df.rename(columns={columns[0]: 'SN'}, inplace=True)
            columns[0] = 'SN'
        
        # 向下填充 SN
        df['SN'] = df['SN'].fillna(method='ffill')
        df = df.replace({np.nan: None})
        df = df[df['SN'].notna()]
        df = df[df['SN'] != '']
        
        add_log('info', f'解析成功，列数: {len(columns)}, 行数: {len(df)}')
        
        # 上传数据
        add_log('info', '开始上传数据到数据库...')
        from app.db.engines import get_mysql_engine
        engine = get_mysql_engine()
        table_name = f"{project.prefix}_raw"
        
        # 检查表是否存在
        if not table_exists(engine, table_name):
            add_log('info', f'表 {table_name} 不存在，创建表')
            create_raw_table(engine, table_name, columns, df)
        else:
            add_log('info', f'表 {table_name} 已存在，检查列是否匹配')
            ensure_table_schema(engine, table_name, columns)
        
        # 批量 UPSERT
        add_log('info', f'开始批量上传 {len(df)} 条数据...')
        result = batch_upsert(engine, table_name, df, batch_size=1000)
        add_log('success', f'数据上传成功，新增: {result["inserted"]} 条, 覆盖: {result["updated"]} 条')
        
        return {
            'success': True,
            'execution_logs': execution_logs,
            'data_count': len(df),
            'file_size': len(csv_data) if csv_data else 0,
            'error_message': None
        }
        
    except SessionExpiredError:
        add_log('error', 'Session 过期，需要重新登录')
        raise
    except Exception as e:
        add_log('error', f'爬取失败: {str(e)}')
        return {
            'success': False,
            'execution_logs': execution_logs,
            'data_count': 0,
            'file_size': 0,
            'error_message': str(e)
        }
    finally:
        # ✅ 关键：显式释放大对象内存
        try:
            if df is not None:
                # 清空 DataFrame 内部缓存
                df._clear_item_cache() if hasattr(df, '_clear_item_cache') else None
                del df
                add_log('debug', '已释放 DataFrame 内存')
        except Exception as e:
            logger.warning(f"释放 DataFrame 失败: {e}")
        
        try:
            if csv_data is not None:
                del csv_data
                add_log('debug', '已释放 csv_data 内存')
        except Exception as e:
            logger.warning(f"释放 csv_data 失败: {e}")
        
        # ✅ 清理局部变量
        try:
            if 'columns' in locals():
                del columns
            if 'result' in locals():
                del result
            if 'engine' in locals():
                # 不要关闭 engine，它是共享的
                del engine
        except Exception as e:
            logger.warning(f"清理局部变量失败: {e}")
        
        # ✅ 强制垃圾回收（三代全回收）
        try:
            import gc
            gc.collect(0)
            gc.collect(1)
            collected = gc.collect(2)
            add_log('debug', f'垃圾回收完成，回收对象数: {collected}')
        except Exception as e:
            logger.warning(f"垃圾回收失败: {e}")


def crawl_all_projects(manual: bool = False):
    """
    爬取所有启用的项目
    
    参数：
        manual: 是否手动触发（手动触发时跳过 is_active 和间隔检查）
    
    流程：
    0. 检查是否满足执行条件（间隔时间）
    1. 登录（账号池轮换）
    2. 遍历项目
       - 下载数据（重试 3 次）
       - 上传数据
       - 等待项目间隔时间
    3. 记录日志
    
    返回：
        {
            "total": 总项目数,
            "success": 成功数,
            "failed": 失败数,
            "skipped": 跳过数
        }
        如果任务被跳过，返回 None
    """
    # 获取数据库 Session
    cfg_engine = get_cfg_engine()
    db = Session(cfg_engine)
    
    # 确定触发类型
    trigger_type = 'manual' if manual else 'auto'
    
    # 统计信息
    stats = {
        "total": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0
    }
    
    try:
        logger.info("=" * 60)
        logger.info(f"SFC 爬虫任务开始 {'(手动触发)' if manual else '(自动触发)'}")
        logger.info(f"数据库引擎 URL: {cfg_engine.url}")
        logger.info("=" * 60)
        
        # 第零步：检查是否满足执行条件
        if not should_run_crawler(db, manual=manual):
            logger.info("不满足执行条件，跳过本次执行")
            return None
        
        # ✅ 设置运行状态为 True（防止并发执行）
        config = get_crawler_config(db)
        config.is_running = True
        db.commit()
        logger.info("已设置 is_running = True，防止并发执行")
        
        # ✅ 立即更新 last_run_time，防止并发执行
        # 在任务开始时就标记为"正在运行"，避免下一分钟的触发重复执行
        update_crawler_last_run_time(db)
        logger.info("已更新 last_run_time，防止并发执行")
        
        # 第一步：登录
        session, account, login_logs = login_sfc(db)
        if not session:
            logger.error("登录失败，本轮结束")
            
            # 尝试从登录日志中提取账号信息
            account_username = None
            for log in login_logs:
                if '尝试使用账号:' in log.get('message', ''):
                    # 从消息中提取账号名（格式：尝试使用账号: b-60003814）
                    account_username = log['message'].split(':')[-1].strip()
                    break
            
            create_crawler_log(
                db,
                account_username=account_username,  # ✅ 传递账号名
                trigger_type=trigger_type,
                status='failed',
                message='登录失败',
                error_message='所有账号都失败或网络不可达',
                execution_logs=login_logs,  # ✅ 传递登录执行日志
            )
            # 登录失败也更新状态为失败
            update_crawler_last_run_time(db, status='failed')
            # 登录失败也更新 last_run_time，避免频繁重试
            update_crawler_last_run_time(db)
            return stats
        
        logger.info(f"登录成功，使用账号: {account.username}")
        logger.info("开始爬取项目")
        
        # 获取配置
        config = get_crawler_config(db)
        if not config:
            logger.error("未找到爬虫配置")
            return stats
        
        # 第二步：遍历项目
        projects = get_enabled_projects(db)
        if not projects:
            logger.warning("没有启用的项目")
            return stats
        
        logger.info(f"启用的项目数量: {len(projects)}")
        stats["total"] = len(projects)
        
        for i, project in enumerate(projects):
            start_time = datetime.now()
            
            try:
                logger.info(f"开始处理项目 {i+1}/{len(projects)}: {project.name}")
                
                # 使用新的函数爬取项目（包含详细日志）
                result = crawl_single_project(db, session, config, project, account, trigger_type)
                
                # 处理 Session 过期 - 重新登录并重试
                if not result['success'] and 'Session 过期' in str(result.get('error_message', '')):
                    logger.warning("Session 过期，重新登录")
                    session, account, login_logs = login_sfc(db)
                    if not session:
                        logger.error("重新登录失败，跳过剩余项目")
                        break
                    logger.info(f"重新登录成功，使用账号: {account.username}")
                    # 重试当前项目（不记录第一次失败）
                    result = crawl_single_project(db, session, config, project, account, trigger_type)
                
                # 更新项目统计
                update_project_stats(db, project, success=result['success'])
                
                # 只记录最终结果的日志
                end_time = datetime.now()
                duration = int((end_time - start_time).total_seconds())
                create_crawler_log(
                    db,
                    project_id=project.id,
                    project_name=project.name,
                    account_id=account.id,
                    account_username=account.username,
                    trigger_type=trigger_type,
                    status='success' if result['success'] else 'failed',
                    message='爬取成功' if result['success'] else '爬取失败',
                    error_message=result.get('error_message'),
                    data_count=result.get('data_count', 0),
                    file_size=result.get('file_size', 0),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    execution_logs=result.get('execution_logs', []),
                )
                
                if result['success']:
                    logger.info(f"项目 {project.name} 处理成功，耗时 {duration} 秒")
                    stats["success"] += 1
                else:
                    logger.error(f"项目 {project.name} 处理失败")
                    stats["failed"] += 1
                
                # ✅ 每个项目处理完后立即清理内存
                try:
                    import gc
                    # 强制执行三代垃圾回收
                    gc.collect(0)  # 年轻代
                    gc.collect(1)  # 中年代
                    collected = gc.collect(2)  # 老年代
                    logger.info(f"项目 {project.name} 处理完成后垃圾回收，回收对象数: {collected}")
                except Exception as e:
                    logger.warning(f"垃圾回收失败: {e}")
                
                # 如果不是最后一个项目，等待间隔时间
                if i < len(projects) - 1:
                    wait_minutes = project.crawl_interval
                    logger.info(f"等待 {wait_minutes} 分钟后处理下一个项目...")
                    time.sleep(wait_minutes * 60)
                
            except Exception as e:
                logger.error(f"项目 {project.name} 处理异常: {e}")
                
                # 更新项目统计
                update_project_stats(db, project, success=False)
                
                # 记录日志
                end_time = datetime.now()
                duration = int((end_time - start_time).total_seconds())
                create_crawler_log(
                    db,
                    project_id=project.id,
                    project_name=project.name,
                    account_id=account.id,
                    account_username=account.username,
                    trigger_type=trigger_type,
                    status='failed',
                    message='爬取失败',
                    error_message=str(e),
                    start_time=start_time,
                    end_time=end_time,
                    duration=duration,
                    execution_logs=[
                        {'time': start_time.strftime('%Y-%m-%d %H:%M:%S'), 'level': 'error', 'message': f'异常: {str(e)}'}
                    ],
                )
                
                # 继续下一个项目
                stats["failed"] += 1
                continue
        
        logger.info("所有项目处理完成")
        logger.info(f"统计: 总数={stats['total']}, 成功={stats['success']}, 失败={stats['failed']}")
        logger.info("=" * 60)
        
        # 更新最后运行时间和状态
        if stats['success'] > 0 and stats['failed'] == 0:
            # 全部成功
            update_crawler_last_run_time(db, status='success')
        elif stats['success'] == 0 and stats['failed'] > 0:
            # 全部失败
            update_crawler_last_run_time(db, status='failed')
        else:
            # 部分成功
            update_crawler_last_run_time(db, status='success')  # 有成功就算成功
        
        return stats
        
    except Exception as e:
        logger.error(f"爬虫任务异常: {e}")
        create_crawler_log(
            db,
            trigger_type=trigger_type,
            status='failed',
            message='爬虫任务异常',
            error_message=str(e),
        )
        # 异常时更新为失败状态
        update_crawler_last_run_time(db, status='failed')
        return stats
    finally:
        # ✅ 关闭 requests.Session，释放连接
        try:
            if 'session' in locals() and session:
                session.close()
                logger.info("已关闭 requests.Session")
        except Exception as e:
            logger.error(f"关闭 Session 失败: {e}")
        
        # ✅ 无论成功或失败，都清除运行状态
        try:
            config = get_crawler_config(db)
            if config:
                config.is_running = False
                db.commit()
                logger.info("已清除 is_running 标志")
        except Exception as e:
            logger.error(f"清除运行状态失败: {e}")
        finally:
            db.close()
