"""
SFC 爬虫相关的 Pydantic schemas
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ==================== SFC 爬虫配置 ====================

class SfcCrawlerConfigBase(BaseModel):
    """SFC 爬虫配置基础模型"""
    name: str = Field(..., description="配置名称")
    description: Optional[str] = Field(None, description="描述")
    sso_login_url: str = Field(..., description="SSO 登录地址")
    sfc_base_url: str = Field(..., description="SFC 基础地址")
    sfc_logon_path: str = Field(default="/SFCS/LogOn.aspx", description="SFC 登录页面路径")
    sfc_data_path: str = Field(..., description="数据页面路径")
    line_option: str = Field(default="all", description="Line 选项")
    section_option: str = Field(default="LIM", description="Section 选项")
    crawl_interval: int = Field(default=10, description="爬虫间隔（分钟）")
    is_active: bool = Field(default=True, description="是否启用")


class SfcCrawlerConfigCreate(SfcCrawlerConfigBase):
    """创建 SFC 爬虫配置"""
    pass


class SfcCrawlerConfigUpdate(BaseModel):
    """更新 SFC 爬虫配置"""
    name: Optional[str] = None
    description: Optional[str] = None
    sso_login_url: Optional[str] = None
    sfc_base_url: Optional[str] = None
    sfc_logon_path: Optional[str] = None
    sfc_data_path: Optional[str] = None
    line_option: Optional[str] = None
    section_option: Optional[str] = None
    crawl_interval: Optional[int] = None
    is_active: Optional[bool] = None


class SfcCrawlerConfigResponse(SfcCrawlerConfigBase):
    """SFC 爬虫配置响应"""
    id: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== SFC 账号池 ====================

class SfcAccountBase(BaseModel):
    """SFC 账号基础模型"""
    name: str = Field(..., description="账号名称")
    username: str = Field(..., description="用户名")
    description: Optional[str] = Field(None, description="描述")
    sort_order: int = Field(default=0, description="排序（数字越小优先级越高）")
    is_active: bool = Field(default=True, description="是否启用")


class SfcAccountCreate(SfcAccountBase):
    """创建 SFC 账号"""
    password: str = Field(..., description="密码")


class SfcAccountUpdate(BaseModel):
    """更新 SFC 账号"""
    name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class SfcAccountResponse(SfcAccountBase):
    """SFC 账号响应"""
    id: int
    total_use_count: int
    success_count: int
    failed_count: int
    last_use_time: Optional[datetime] = None
    last_use_status: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== SFC 项目配置 ====================

class SfcProjectBase(BaseModel):
    """SFC 项目基础模型"""
    name: str = Field(..., description="项目名称")
    prefix: str = Field(..., description="项目前缀")
    sfc_code: str = Field(..., description="SFC 代码（P 参数）")
    btype: str = Field(..., description="业务类型（type 参数）")
    crawl_interval: int = Field(default=10, description="爬取间隔（分钟，项目之间的等待时间）")
    is_enabled: bool = Field(default=True, description="是否启用")


class SfcProjectCreate(SfcProjectBase):
    """创建 SFC 项目"""
    pass


class SfcProjectUpdate(BaseModel):
    """更新 SFC 项目"""
    name: Optional[str] = None
    prefix: Optional[str] = None
    sfc_code: Optional[str] = None
    btype: Optional[str] = None
    crawl_interval: Optional[int] = None
    is_enabled: Optional[bool] = None


class SfcProjectResponse(SfcProjectBase):
    """SFC 项目响应"""
    id: int
    last_crawl_time: Optional[datetime] = None
    last_crawl_status: Optional[str] = None
    total_crawl_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ==================== SFC 爬虫日志 ====================

class SfcCrawlerLogResponse(BaseModel):
    """SFC 爬虫日志响应"""
    id: int
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    status: str
    message: Optional[str] = None
    error_message: Optional[str] = None
    data_count: int
    file_size: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== 认证相关 ====================

class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
