from typing import Any, Literal

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, max_length=50)
    enabled: bool = True
    sfc_code: str = ""
    btype: str = ""
    prefix: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    machines: list[str] = Field(default_factory=list)
    owners: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    sfc_code: str | None = None
    btype: str | None = None
    prefix: str | None = None
    config: dict[str, Any] | None = None
    machines: list[str] | None = None
    owners: dict[str, Any] | None = None


class DefaultsUpdate(BaseModel):
    value: dict[str, Any]


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    nickname: str = ""
    password: str = Field(min_length=6, max_length=100)
    role: str = "common"
    enabled: bool = True


class UserUpdate(BaseModel):
    nickname: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=100)
    role: str | None = None
    enabled: bool | None = None


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    phone: str = ""
    shift: str = ""
    department: str = ""


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    phone: str | None = None
    shift: str | None = None
    department: str | None = None


class DutyRosterCreate(BaseModel):
    person_id: int | None = None
    name: str = ""
    duty: Literal["白班", "夜班"]
    machines: list[str] = Field(default_factory=list)


class DutyRosterUpdate(BaseModel):
    person_id: int | None = None
    name: str | None = None
    duty: Literal["白班", "夜班"] | None = None
    machines: list[str] | None = None


class ManualNoticeRecipientIn(BaseModel):
    department: str = ""
    name: str = ""
    phone: str = ""


class ManualNoticeCreate(BaseModel):
    from_dept: str = ""
    topic: str = ""
    body: str = ""
    recipients: list[ManualNoticeRecipientIn] = Field(default_factory=list)


class CavityAlertRulesIn(BaseModel):
    cavity_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    cavity_min_qty: float | None = Field(default=None, ge=0)
    machine_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    machine_min_qty: float | None = Field(default=None, ge=0)
    lim_cavity_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    lim_cavity_min_qty: float | None = Field(default=None, ge=0)
    lim_machine_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    lim_machine_min_qty: float | None = Field(default=None, ge=0)
    body_cavity_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    body_cavity_min_qty: float | None = Field(default=None, ge=0)
    body_machine_rate_above_pct: float | None = Field(default=None, ge=0, le=100)
    body_machine_min_qty: float | None = Field(default=None, ge=0)


class PgConnIn(BaseModel):
    host: str = Field(min_length=1, max_length=200)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str = ""


class DbwebIn(BaseModel):
    url: str = Field(min_length=1, max_length=300)
    sqlite_path: str = Field(default="/data/meta/lim_meta.sqlite", max_length=300)


class DbwebTest(BaseModel):
    url: str | None = Field(default=None, max_length=300)


class MetabaseIn(BaseModel):
    url: str = Field(min_length=1, max_length=300)
    username: str = Field(default="", max_length=200)
    password: str = ""


class MetabaseTest(BaseModel):
    url: str | None = Field(default=None, max_length=300)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)


class ConnectionsUpdate(BaseModel):
    raw: PgConnIn
    dwh: PgConnIn
    defect: PgConnIn | None = None
    dbweb: DbwebIn | None = None
    metabase: MetabaseIn | None = None


class ConnectionTest(BaseModel):
    target: Literal["raw", "dwh", "defect"]
    host: str = Field(min_length=1, max_length=200)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=100)
    password: str = ""
