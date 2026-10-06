
from pydantic import BaseModel, Field


class SfcConfigUpdate(BaseModel):
    sso_login_url: str | None = None
    sfc_base_url: str | None = None
    sfc_logon_path: str | None = None
    sfc_data_path: str | None = None
    line_option: str | None = None
    section_option: str | None = None
    crawl_interval: int | None = Field(default=None, ge=1, le=1440)
    retry: int | None = Field(default=None, ge=1, le=10)
    is_active: bool | None = None


class SfcAccountCreate(BaseModel):
    name: str = ""
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    enabled: bool = True


class SfcAccountUpdate(BaseModel):
    name: str | None = None
    username: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = None
    sort_order: int | None = None
    enabled: bool | None = None
