"""
SFC 爬虫配置模型
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, declarative_base

Base = declarative_base()


class SfcCrawlerConfig(Base):
    """SFC 爬虫配置表"""
    
    __tablename__ = "sfc_crawler_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称")
    description: Mapped[str] = mapped_column(String(255), nullable=True, comment="描述")
    
    # SSO 配置
    sso_login_url: Mapped[str] = mapped_column(String(500), nullable=False, comment="SSO 登录地址")
    
    # SFC 配置
    sfc_base_url: Mapped[str] = mapped_column(String(255), nullable=False, comment="SFC 基础地址")
    sfc_logon_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/SFCS/LogOn.aspx", comment="SFC 登录页面路径")
    sfc_data_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="数据页面路径")
    
    # 下拉框默认值
    line_option: Mapped[str] = mapped_column(String(50), default="all", comment="Line 选项")
    section_option: Mapped[str] = mapped_column(String(50), default="LIM", comment="Section 选项")
    
    # 爬虫间隔
    crawl_interval: Mapped[int] = mapped_column(Integer, default=10, comment="爬虫间隔（分钟）")
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    is_running: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否正在运行")
    last_run_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="最后运行时间")
    last_run_status: Mapped[str] = mapped_column(String(20), nullable=True, comment="最后运行状态")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class SfcAccount(Base):
    """SFC 账号池表"""
    
    __tablename__ = "sfc_accounts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="账号名称")
    username: Mapped[str] = mapped_column(String(100), nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(Text, nullable=False, comment="密码（加密）")
    description: Mapped[str] = mapped_column(String(200), nullable=True, comment="描述")
    
    # 优先级和状态
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序（数字越小优先级越高）")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    
    # 使用统计
    total_use_count: Mapped[int] = mapped_column(Integer, default=0, comment="总使用次数")
    success_count: Mapped[int] = mapped_column(Integer, default=0, comment="成功次数")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败次数")
    last_use_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="最后使用时间")
    last_use_status: Mapped[str] = mapped_column(String(20), nullable=True, comment="最后使用状态（success/failed）")
    last_error_message: Mapped[str] = mapped_column(Text, nullable=True, comment="最后错误信息")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class SfcProject(Base):
    """SFC 项目配置表"""
    
    __tablename__ = "sfc_projects"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="项目名称")
    prefix: Mapped[str] = mapped_column(String(100), nullable=False, comment="项目前缀")
    sfc_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="SFC 代码（P 参数）")
    btype: Mapped[str] = mapped_column(String(20), nullable=False, comment="业务类型（type 参数）")
    
    # 爬取间隔
    crawl_interval: Mapped[int] = mapped_column(Integer, default=10, comment="爬取间隔（分钟，项目之间的等待时间）")
    
    # 状态
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    
    # 统计
    last_crawl_time: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="最后爬取时间")
    last_crawl_status: Mapped[str] = mapped_column(String(20), nullable=True, comment="最后爬取状态")
    total_crawl_count: Mapped[int] = mapped_column(Integer, default=0, comment="总爬取次数")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )


class MysqlConfig(Base):
    """MySQL 配置表"""
    
    __tablename__ = "mysql_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="配置名称")
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="主机地址")
    port: Mapped[int] = mapped_column(Integer, default=3306, comment="端口")
    username: Mapped[str] = mapped_column(String(100), nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(String(500), nullable=False, comment="密码（加密）")
    database: Mapped[str] = mapped_column(String(100), nullable=False, comment="数据库名")
    
    # 连接池配置
    max_connections: Mapped[int] = mapped_column(Integer, default=10, comment="最大连接数")
    min_connections: Mapped[int] = mapped_column(Integer, default=1, comment="最小连接数")
    connection_timeout: Mapped[int] = mapped_column(Integer, default=30, comment="连接超时（秒）")
    
    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间"
    )
