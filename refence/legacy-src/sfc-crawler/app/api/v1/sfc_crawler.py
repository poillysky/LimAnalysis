"""
SFC 爬虫配置 API
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.common.response import ok
from app.core.encryption import encryption_manager
from app.models.sfc_crawler import SfcCrawlerConfig, SfcAccount, SfcProject, MysqlConfig
from app.schemas.sfc_crawler import (
    SfcCrawlerConfigCreate,
    SfcCrawlerConfigUpdate,
    SfcCrawlerConfigResponse,
    SfcAccountCreate,
    SfcAccountUpdate,
    SfcAccountResponse,
    SfcProjectCreate,
    SfcProjectUpdate,
    SfcProjectResponse,
)

router = APIRouter()


# ==================== SFC 爬虫配置 ====================

@router.get("/config")
def get_crawler_config(db: Session = Depends(get_db)):
    """获取 SFC 爬虫配置"""
    config = db.query(SfcCrawlerConfig).first()
    
    # 如果配置不存在，创建默认配置
    if not config:
        config = SfcCrawlerConfig(
            name="SFC 爬虫配置",
            description="SFC 数据爬虫默认配置",
            sso_login_url="http://sso.aac.com/login.aspx",
            sfc_base_url="http://sfc-bjm.aac.tech",
            sfc_logon_path="/SFCS/LogOn.aspx",
            sfc_data_path="/SFCS/Views/GetTableData2.aspx",
            line_option="all",
            section_option="LIM",
            crawl_interval=10,
            is_active=True,
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    # 最后执行状态从配置表的 last_run_status 字段获取
    last_run_status = getattr(config, 'last_run_status', None)
    
    return ok({
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "sso_login_url": config.sso_login_url,
        "sfc_base_url": config.sfc_base_url,
        "sfc_logon_path": config.sfc_logon_path,
        "sfc_data_path": config.sfc_data_path,
        "line_option": config.line_option,
        "section_option": config.section_option,
        "crawl_interval": config.crawl_interval,
        "is_active": config.is_active,
        "last_run_time": config.last_run_time.isoformat() if config.last_run_time else None,
        "last_run_status": last_run_status,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    })


@router.put("/config")
def update_crawler_config(
    data: SfcCrawlerConfigUpdate,
    db: Session = Depends(get_db)
):
    """更新 SFC 爬虫配置"""
    config = db.query(SfcCrawlerConfig).first()
    if not config:
        return ok({})
    
    # 更新字段
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    
    return ok({
        "id": config.id,
        "name": config.name,
        "description": config.description,
        "sso_login_url": config.sso_login_url,
        "sfc_base_url": config.sfc_base_url,
        "sfc_logon_path": config.sfc_logon_path,
        "sfc_data_path": config.sfc_data_path,
        "line_option": config.line_option,
        "section_option": config.section_option,
        "crawl_interval": config.crawl_interval,
        "is_active": config.is_active,
        "last_run_time": config.last_run_time.isoformat() if config.last_run_time else None,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    })


# ==================== SFC 账号池 ====================

@router.get("/accounts")
def get_accounts(db: Session = Depends(get_db)):
    """获取 SFC 账号列表"""
    accounts = db.query(SfcAccount).order_by(SfcAccount.sort_order).all()
    
    return ok([
        {
            "id": acc.id,
            "name": acc.name,
            "username": acc.username,
            "description": acc.description,
            "sort_order": acc.sort_order,
            "is_active": acc.is_active,
            "total_use_count": acc.total_use_count,
            "success_count": acc.success_count,
            "failed_count": acc.failed_count,
            "last_use_time": acc.last_use_time.isoformat() if acc.last_use_time else None,
            "last_use_status": acc.last_use_status,
            "last_error_message": acc.last_error_message,
            "created_at": acc.created_at.isoformat() if acc.created_at else None,
            "updated_at": acc.updated_at.isoformat() if acc.updated_at else None,
        }
        for acc in accounts
    ])


@router.post("/accounts")
def create_account(
    data: SfcAccountCreate,
    db: Session = Depends(get_db)
):
    """创建 SFC 账号"""
    # 加密密码
    encrypted_password = encryption_manager.encrypt(data.password)
    
    account = SfcAccount(
        name=data.name,
        username=data.username,
        password=encrypted_password,
        description=data.description,
        sort_order=data.sort_order,
        is_active=data.is_active,
    )
    
    db.add(account)
    db.commit()
    db.refresh(account)
    
    return ok({
        "id": account.id,
        "name": account.name,
        "username": account.username,
        "description": account.description,
        "sort_order": account.sort_order,
        "is_active": account.is_active,
        "total_use_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "last_use_time": None,
        "last_use_status": None,
        "last_error_message": None,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    })


@router.put("/accounts/{account_id}")
def update_account(
    account_id: int,
    data: SfcAccountUpdate,
    db: Session = Depends(get_db)
):
    """更新 SFC 账号"""
    account = db.query(SfcAccount).filter(SfcAccount.id == account_id).first()
    if not account:
        return ok({})
    
    # 更新字段
    update_data = data.dict(exclude_unset=True)
    
    # 如果更新密码，需要加密
    if "password" in update_data and update_data["password"]:
        update_data["password"] = encryption_manager.encrypt(update_data["password"])
    
    for key, value in update_data.items():
        setattr(account, key, value)
    
    db.commit()
    db.refresh(account)
    
    return ok({
        "id": account.id,
        "name": account.name,
        "username": account.username,
        "description": account.description,
        "sort_order": account.sort_order,
        "is_active": account.is_active,
        "total_use_count": account.total_use_count,
        "success_count": account.success_count,
        "failed_count": account.failed_count,
        "last_use_time": account.last_use_time.isoformat() if account.last_use_time else None,
        "last_use_status": account.last_use_status,
        "last_error_message": account.last_error_message,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    })


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """删除 SFC 账号"""
    account = db.query(SfcAccount).filter(SfcAccount.id == account_id).first()
    if not account:
        return ok({"message": "账号不存在"})
    
    db.delete(account)
    db.commit()
    
    return ok({"message": "删除成功"})


# ==================== SFC 项目配置 ====================

@router.get("/projects")
def get_projects(db: Session = Depends(get_db)):
    """获取 SFC 项目列表"""
    projects = db.query(SfcProject).all()
    
    return ok([
        {
            "id": proj.id,
            "name": proj.name,
            "prefix": proj.prefix,
            "sfc_code": proj.sfc_code,
            "btype": proj.btype,
            "crawl_interval": proj.crawl_interval,
            "is_enabled": proj.is_enabled,
            "last_crawl_time": proj.last_crawl_time.isoformat() if proj.last_crawl_time else None,
            "last_crawl_status": proj.last_crawl_status,
            "total_crawl_count": proj.total_crawl_count,
            "created_at": proj.created_at.isoformat() if proj.created_at else None,
            "updated_at": proj.updated_at.isoformat() if proj.updated_at else None,
        }
        for proj in projects
    ])


@router.post("/projects")
def create_project(
    data: SfcProjectCreate,
    db: Session = Depends(get_db)
):
    """创建 SFC 项目"""
    project = SfcProject(
        name=data.name,
        prefix=data.prefix,
        sfc_code=data.sfc_code,
        btype=data.btype,
        crawl_interval=data.crawl_interval,
        is_enabled=data.is_enabled,
    )
    
    db.add(project)
    db.commit()
    db.refresh(project)
    
    return ok({
        "id": project.id,
        "name": project.name,
        "prefix": project.prefix,
        "sfc_code": project.sfc_code,
        "btype": project.btype,
        "crawl_interval": project.crawl_interval,
        "is_enabled": project.is_enabled,
        "last_crawl_time": None,
        "last_crawl_status": None,
        "total_crawl_count": 0,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    })


@router.put("/projects/{project_id}")
def update_project(
    project_id: int,
    data: SfcProjectUpdate,
    db: Session = Depends(get_db)
):
    """更新 SFC 项目"""
    project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
    if not project:
        return ok({"message": "项目不存在"})
    
    # 更新字段
    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(project, key, value)
    
    db.commit()
    db.refresh(project)
    
    return ok({
        "id": project.id,
        "name": project.name,
        "prefix": project.prefix,
        "sfc_code": project.sfc_code,
        "btype": project.btype,
        "crawl_interval": project.crawl_interval,
        "is_enabled": project.is_enabled,
        "last_crawl_time": project.last_crawl_time.isoformat() if project.last_crawl_time else None,
        "last_crawl_status": project.last_crawl_status,
        "total_crawl_count": project.total_crawl_count,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    })


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """删除 SFC 项目"""
    project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
    if not project:
        return ok({"message": "项目不存在"})
    
    db.delete(project)
    db.commit()
    
    return ok({"message": "删除成功"})


# ==================== SFC 爬虫日志 ====================
# 注意：此路由已废弃，现在使用文件日志（见文件末尾的 /logs 和 /sfc-logs 路由）


@router.delete("/logs/{log_id}")
def delete_log(log_id: int, db: Session = Depends(get_db)):
    """删除 SFC 爬虫日志（文件日志不支持删除单条）"""
    # 文件日志不支持删除单条记录
    # 返回成功，避免前端报错
    return ok({"message": "文件日志不支持删除单条记录"})


@router.get("/accounts/{account_id}/statistics")
def get_account_statistics(
    account_id: int,
    db: Session = Depends(get_db),
):
    """
    获取账号的真实爬取统计（从文件日志）
    
    返回：
    - totalCrawls: 总爬取次数
    - successCrawls: 成功次数
    - failedCrawls: 失败次数
    - successRate: 成功率
    - lastCrawlTime: 最后爬取时间
    - lastCrawlStatus: 最后爬取状态
    """
    from app.utils.file_logger import file_logger
    
    # 获取账号信息
    account = db.query(SfcAccount).filter(SfcAccount.id == account_id).first()
    if not account:
        return ok({
            "totalCrawls": 0,
            "successCrawls": 0,
            "failedCrawls": 0,
            "successRate": 0,
            "lastCrawlTime": None,
            "lastCrawlStatus": None,
        })
    
    # 从文件读取所有日志（读取多天的日志）
    all_logs = []
    from datetime import datetime, timedelta
    for i in range(30):  # 读取最近 30 天
        date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        logs = file_logger.read_sfc_logs(date=date, limit=10000)
        all_logs.extend(logs)
    
    # 过滤该账号相关的日志（使用 account 字段匹配用户名）
    account_logs = [
        log for log in all_logs
        if log.get("account") == account.username
    ]
    
    # 统计
    total_crawls = len(account_logs)
    success_crawls = len([log for log in account_logs if log.get("status") == "success"])
    failed_crawls = len([log for log in account_logs if log.get("status") == "failed"])
    success_rate = round((success_crawls / total_crawls * 100) if total_crawls > 0 else 0, 2)
    
    # 最后一次爬取
    last_log = account_logs[0] if account_logs else None
    last_crawl_time = last_log.get("timestamp") if last_log else None
    last_crawl_status = last_log.get("status") if last_log else None
    
    return ok({
        "totalCrawls": total_crawls,
        "successCrawls": success_crawls,
        "failedCrawls": failed_crawls,
        "successRate": success_rate,
        "lastCrawlTime": last_crawl_time,
        "lastCrawlStatus": last_crawl_status,
    })


@router.get("/projects/{project_id}/statistics")
def get_project_statistics(
    project_id: int,
    db: Session = Depends(get_db),
):
    """
    获取项目的真实爬取统计（从文件日志）
    
    返回：
    - totalCrawls: 总爬取次数
    - successCrawls: 成功次数
    - failedCrawls: 失败次数
    - successRate: 成功率
    - lastCrawlTime: 最后爬取时间
    - lastCrawlStatus: 最后爬取状态
    - totalDataCount: 总数据量
    """
    from app.utils.file_logger import file_logger
    
    # 获取项目信息
    project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
    if not project:
        return ok({
            "totalCrawls": 0,
            "successCrawls": 0,
            "failedCrawls": 0,
            "successRate": 0,
            "lastCrawlTime": None,
            "lastCrawlStatus": None,
            "totalDataCount": 0,
        })
    
    # 从文件读取所有日志（读取多天的日志）
    all_logs = []
    from datetime import datetime, timedelta
    for i in range(30):  # 读取最近 30 天
        date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
        logs = file_logger.read_sfc_logs(date=date, limit=10000)
        all_logs.extend(logs)
    
    # 过滤该项目的日志（使用 config_name 字段匹配项目名称）
    project_logs = [
        log for log in all_logs
        if log.get("config_name") == project.name
    ]
    
    # 统计
    total_crawls = len(project_logs)
    success_crawls = len([log for log in project_logs if log.get("status") == "success"])
    failed_crawls = len([log for log in project_logs if log.get("status") == "failed"])
    success_rate = round((success_crawls / total_crawls * 100) if total_crawls > 0 else 0, 2)
    
    # 总数据量
    total_data_count = sum(log.get("records_count", 0) for log in project_logs if log.get("status") == "success")
    
    # 最后一次爬取
    last_log = project_logs[0] if project_logs else None
    last_crawl_time = last_log.get("timestamp") if last_log else None
    last_crawl_status = last_log.get("status") if last_log else None
    
    return ok({
        "totalCrawls": total_crawls,
        "successCrawls": success_crawls,
        "failedCrawls": failed_crawls,
        "successRate": success_rate,
        "lastCrawlTime": last_crawl_time,
        "lastCrawlStatus": last_crawl_status,
        "totalDataCount": total_data_count,
    })



# ==================== 爬虫控制 ====================

@router.post("/control/stop")
def stop_crawler():
    """停止爬虫任务"""
    from app.scheduler import stop_scheduler
    
    try:
        stop_scheduler()
        return ok({
            "status": "success",
            "message": "爬虫已停止"
        })
    except Exception as e:
        return ok({
            "status": "failed",
            "message": f"停止失败: {str(e)}"
        })


@router.get("/control/status")
def get_crawler_status(db: Session = Depends(get_db)):
    """获取爬虫状态"""
    from app.utils.file_logger import file_logger
    
    try:
        # 从文件读取最近的日志
        recent_logs = file_logger.read_sfc_logs(limit=1)
        recent_log = recent_logs[0] if recent_logs else None
        
        # 获取配置
        config = db.query(SfcCrawlerConfig).first()
        
        # 获取项目统计
        total_projects = db.query(SfcProject).count()
        enabled_projects = db.query(SfcProject).filter(
            SfcProject.is_enabled == True
        ).count()
        
        # 获取账号统计
        total_accounts = db.query(SfcAccount).count()
        enabled_accounts = db.query(SfcAccount).filter(
            SfcAccount.is_active == True
        ).count()
        
        return ok({
            "config": {
                "is_active": config.is_active if config else False,
                "crawl_interval": config.crawl_interval if config else 10,
            },
            "statistics": {
                "total_projects": total_projects,
                "enabled_projects": enabled_projects,
                "total_accounts": total_accounts,
                "enabled_accounts": enabled_accounts,
            },
            "last_run": {
                "time": recent_log.created_at.isoformat() if recent_log and recent_log.created_at else None,
                "status": recent_log.status if recent_log else None,
                "message": recent_log.message if recent_log else None,
            } if recent_log else None,
        })
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"获取状态失败: {str(e)}"
        })


# ==================== 手动上传 ====================

@router.post("/upload")
async def upload_csv_files(
    project_id: int = Form(...),
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    手动上传CSV文件到数据库
    
    参数：
        project_id: 项目ID
        files: CSV文件列表（支持单个或多个文件）
    
    返回：
        上传结果统计
    """
    from app.services.sfc_crawler_service import upload_data
    from datetime import datetime
    
    # 获取项目
    project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
    if not project:
        return ok({
            "status": "failed",
            "message": f"项目不存在: {project_id}"
        })
    
    results = {
        "total": len(files),
        "success": 0,
        "failed": 0,
        "details": []
    }
    
    for file in files:
        start_time = datetime.now()
        
        try:
            # 检查文件类型
            if not file.filename.endswith('.csv'):
                results["failed"] += 1
                results["details"].append({
                    "filename": file.filename,
                    "status": "failed",
                    "message": "文件类型错误，只支持CSV文件"
                })
                continue
            
            # 读取文件内容（自动检测编码）
            content = await file.read()
            
            # 尝试多种编码
            csv_data = None
            for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
                try:
                    csv_data = content.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            
            if csv_data is None:
                results["failed"] += 1
                results["details"].append({
                    "filename": file.filename,
                    "status": "failed",
                    "message": "文件编码错误，无法解析"
                })
                continue
            
            # 上传数据（使用爬虫相同的逻辑）
            upload_result = upload_data(db, project, csv_data)
            
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            results["success"] += 1
            results["details"].append({
                "filename": file.filename,
                "status": "success",
                "message": "上传成功",
                "duration": duration,
                "uploaded_rows": upload_result.get('total', 0),
                "inserted": upload_result.get('inserted', 0),
                "updated": upload_result.get('updated', 0)
            })
            
        except Exception as e:
            end_time = datetime.now()
            duration = int((end_time - start_time).total_seconds())
            
            results["failed"] += 1
            results["details"].append({
                "filename": file.filename,
                "status": "failed",
                "message": str(e),
                "duration": duration
            })
    
    return ok(results)


# ==================== 统计信息 ====================

@router.get("/statistics")
def get_statistics(days: int = 7, db: Session = Depends(get_db)):
    """
    获取爬虫统计信息
    
    参数：
    - days: 统计最近 N 天的数据（默认 7 天）
    """
    try:
        from app.services.sfc_statistics_service import get_crawler_statistics
        
        stats = get_crawler_statistics(db, days=days)
        return ok(stats)
        
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"获取统计失败: {str(e)}"
        })


@router.get("/statistics/project/{project_id}")
def get_project_detail_statistics_api(project_id: int, days: int = 30, db: Session = Depends(get_db)):
    """
    获取单个项目的详细统计
    
    参数：
    - project_id: 项目 ID
    - days: 统计最近 N 天的数据（默认 30 天）
    """
    try:
        from app.services.sfc_statistics_service import get_project_detail_statistics
        
        stats = get_project_detail_statistics(db, project_id, days=days)
        return ok(stats)
        
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"获取统计失败: {str(e)}"
        })


# ==================== 数据清理 ====================

@router.post("/cleanup/logs")
def cleanup_logs(db: Session = Depends(get_db)):
    """清理 30 天前的爬虫日志"""
    try:
        from app.tasks.cleanup_tasks import cleanup_old_logs
        
        deleted_count = cleanup_old_logs()
        return ok({
            "status": "success",
            "message": f"清理完成，删除 {deleted_count} 条日志",
            "deleted_count": deleted_count
        })
        
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"清理失败: {str(e)}"
        })


@router.post("/cleanup/raw-data")
def cleanup_raw_data(db: Session = Depends(get_db)):
    """清理 90 天前的 raw 数据"""
    try:
        from app.tasks.cleanup_tasks import cleanup_old_raw_data
        
        deleted_count = cleanup_old_raw_data()
        return ok({
            "status": "success",
            "message": f"清理完成，删除 {deleted_count} 条数据",
            "deleted_count": deleted_count
        })
        
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"清理失败: {str(e)}"
        })


@router.post("/cleanup/all")
def cleanup_all_data(db: Session = Depends(get_db)):
    """执行所有清理任务"""
    try:
        from app.tasks.cleanup_tasks import cleanup_all
        
        result = cleanup_all()
        return ok({
            "status": "success",
            "message": f"清理完成 - 日志: {result['logs_deleted']} 条, Raw 数据: {result['raw_data_deleted']} 条",
            "result": result
        })
        
    except Exception as e:
        return ok({
            "status": "error",
            "message": f"清理失败: {str(e)}"
        })


# ==================== 测试账号连接 ====================

@router.post("/accounts/{account_id}/test")
def test_account_connection(account_id: int, db: Session = Depends(get_db)):
    """测试 SFC 账号连接"""
    from app.services.sfc_crawler_service import (
        get_crawler_config, 
        try_login_account,
        NetworkUnreachableError,
        AccountError,
        TimeoutError,
    )
    
    # 获取账号
    account = db.query(SfcAccount).filter(SfcAccount.id == account_id).first()
    if not account:
        return ok({
            "success": False,
            "message": "账号不存在"
        })
    
    # 获取爬虫配置
    config = get_crawler_config(db)
    if not config:
        return ok({
            "success": False,
            "message": "未找到爬虫配置"
        })
    
    try:
        # 尝试登录
        session = try_login_account(config, account)
        
        return ok({
            "success": True,
            "message": f"账号 {account.username} 连接成功"
        })
    
    except NetworkUnreachableError as e:
        return ok({
            "success": False,
            "message": f"网络不可达: {str(e)}"
        })
    
    except AccountError as e:
        return ok({
            "success": False,
            "message": f"账号认证失败: {str(e)}"
        })
    
    except TimeoutError as e:
        return ok({
            "success": False,
            "message": f"连接超时: {str(e)}"
        })
    
    except Exception as e:
        return ok({
            "success": False,
            "message": f"测试失败: {str(e)}"
        })


# ==================== SFC 爬虫日志相关 ====================

@router.get("/logs")
def get_sfc_crawler_logs(
    project_id: int = None,
    date: str = None,
    limit: int = 200,
    db: Session = Depends(get_db)
):
    """获取 SFC 爬虫日志（从文件读取）"""
    from app.utils.file_logger import file_logger
    
    # 如果指定了 project_id，先查询项目名称
    config_name = None
    if project_id:
        project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
        if project:
            config_name = project.name
    
    # 从文件读取日志
    logs = file_logger.read_sfc_logs(
        date=date,
        config_name=config_name,
        limit=limit
    )
    
    # 转换字段名以匹配前端期望的格式
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            "id": hash(log.get("timestamp", "")),  # 生成一个伪 ID
            "accountUsername": log.get("account", ""),
            "projectName": log.get("config_name", ""),
            "triggerType": log.get("trigger_type", ""),
            "status": log.get("status", ""),
            "message": log.get("message", ""),
            "dataCount": log.get("records_count", 0),
            "duration": log.get("duration", 0),
            "executionLogs": log.get("execution_logs", []),
            "createdAt": log.get("timestamp", ""),
        })
    
    return ok(data=formatted_logs)


@router.get("/sfc-logs")
def get_sfc_logs_new(
    project_id: int = None,
    date: str = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取 SFC 爬虫日志（从文件读取）- 新路由"""
    from app.utils.file_logger import file_logger
    
    # 如果指定了 project_id，先查询项目名称
    config_name = None
    if project_id:
        project = db.query(SfcProject).filter(SfcProject.id == project_id).first()
        if project:
            config_name = project.name
    
    # 从文件读取日志
    logs = file_logger.read_sfc_logs(
        date=date,
        config_name=config_name,
        limit=limit
    )
    
    # 转换字段名以匹配前端期望的格式
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            "id": hash(log.get("timestamp", "")),  # 生成一个伪 ID
            "accountUsername": log.get("account", ""),
            "projectName": log.get("config_name", ""),
            "triggerType": log.get("trigger_type", ""),
            "status": log.get("status", ""),
            "message": log.get("message", ""),
            "dataCount": log.get("records_count", 0),
            "duration": log.get("duration", 0),
            "executionLogs": log.get("execution_logs", []),
            "createdAt": log.get("timestamp", ""),
        })
    
    return ok(data=formatted_logs)


# ==================== 调度器管理 ====================

@router.get("/scheduler/status")
def get_scheduler_status():
    """获取调度器状态"""
    from app.scheduler import get_scheduler_status
    
    status = get_scheduler_status()
    return ok(status)


@router.post("/scheduler/trigger")
def trigger_crawler_manually():
    """手动触发爬虫任务"""
    from app.scheduler import trigger_crawler_manually
    
    trigger_crawler_manually()
    
    return ok({
        "message": "爬虫任务已提交到后台执行",
        "note": "任务在后台异步执行，请查看日志了解执行情况"
    })


# ==================== MySQL 配置 ====================

@router.get("/mysql-configs")
def get_mysql_configs(db: Session = Depends(get_db)):
    """获取 MySQL 配置列表"""
    configs = db.query(MysqlConfig).all()
    
    return ok([
        {
            "id": cfg.id,
            "name": cfg.name,
            "host": cfg.host,
            "port": cfg.port,
            "username": cfg.username,
            "database": cfg.database,
            "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
            "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        }
        for cfg in configs
    ])


@router.post("/mysql-configs")
def create_mysql_config(
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(3306),
    username: str = Form(...),
    password: str = Form(...),
    database: str = Form(...),
    db: Session = Depends(get_db)
):
    """创建 MySQL 配置"""
    # 加密密码
    encrypted_password = encryption_manager.encrypt(password)
    
    config = MysqlConfig(
        name=name,
        host=host,
        port=port,
        username=username,
        password=encrypted_password,
        database=database,
    )
    
    db.add(config)
    db.commit()
    db.refresh(config)
    
    return ok({
        "id": config.id,
        "name": config.name,
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "database": config.database,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    })


@router.put("/mysql-configs/{config_id}")
def update_mysql_config(
    config_id: int,
    name: str = Form(...),
    host: str = Form(...),
    port: int = Form(3306),
    username: str = Form(...),
    password: str = Form(None),
    database: str = Form(...),
    db: Session = Depends(get_db)
):
    """更新 MySQL 配置"""
    config = db.query(MysqlConfig).filter(MysqlConfig.id == config_id).first()
    if not config:
        return ok({"message": "配置不存在"})
    
    # 更新字段
    config.name = name
    config.host = host
    config.port = port
    config.username = username
    config.database = database
    
    # 如果提供了新密码，则加密并更新
    if password:
        config.password = encryption_manager.encrypt(password)
    
    db.commit()
    db.refresh(config)
    
    return ok({
        "id": config.id,
        "name": config.name,
        "host": config.host,
        "port": config.port,
        "username": config.username,
        "database": config.database,
        "created_at": config.created_at.isoformat() if config.created_at else None,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
    })


@router.delete("/mysql-configs/{config_id}")
def delete_mysql_config(config_id: int, db: Session = Depends(get_db)):
    """删除 MySQL 配置"""
    config = db.query(MysqlConfig).filter(MysqlConfig.id == config_id).first()
    if not config:
        return ok({"message": "配置不存在"})
    
    db.delete(config)
    db.commit()
    
    return ok({"message": "删除成功"})


@router.post("/mysql-configs/{config_id}/test")
def test_mysql_connection(config_id: int, db: Session = Depends(get_db)):
    """测试 MySQL 连接"""
    import pymysql
    
    config = db.query(MysqlConfig).filter(MysqlConfig.id == config_id).first()
    if not config:
        return ok({
            "success": False,
            "message": "配置不存在"
        })
    
    try:
        # 解密密码
        password = encryption_manager.decrypt(config.password)
        
        # 尝试连接
        conn = pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.username,
            password=password,
            database=config.database,
            connect_timeout=10
        )
        conn.close()
        
        return ok({
            "success": True,
            "message": f"连接成功：{config.host}:{config.port}/{config.database}"
        })
    
    except Exception as e:
        return ok({
            "success": False,
            "message": f"连接失败：{str(e)}"
        })
