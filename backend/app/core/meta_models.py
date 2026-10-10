from sqlalchemy import JSON, Boolean, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MetaBase(DeclarativeBase):
    pass


class MetaSetting(MetaBase):
    """系统默认等键值。全部可改，不进代码。"""

    __tablename__ = "meta_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)


class MetaProject(MetaBase):
    """项目元数据。新增项目 = 插入一行，不改代码。"""

    __tablename__ = "meta_projects"

    project_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sfc_code: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    btype: Mapped[str] = mapped_column(String(50), default="0", nullable=False)
    prefix: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaSfcAccount(MetaBase):
    """SFC 账号池。密码加密存放。"""

    __tablename__ = "meta_sfc_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_enc: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_use_time: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    last_use_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)


class MetaSfcLog(MetaBase):
    """采集运行日志（对齐参考：按项目一条，含账号/行数/耗时）。"""

    __tablename__ = "meta_sfc_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    project_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    project_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    account: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    rows_affected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaEtlLog(MetaBase):
    """数据清洗运行日志（对齐参考 etl-app / SFC 运行日志）。"""

    __tablename__ = "meta_etl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    run_mode: Mapped[str] = mapped_column(String(20), default="incremental", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    rows_affected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaAggLog(MetaBase):
    """数据聚合运行日志（结构对齐 meta_etl_logs）。"""

    __tablename__ = "meta_agg_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    run_mode: Mapped[str] = mapped_column(String(20), default="incremental", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    rows_affected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaDiskCleanupLog(MetaBase):
    """磁盘清理运行日志。"""

    __tablename__ = "meta_disk_cleanup_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[str] = mapped_column(String(40), nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    deleted_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_files: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaUser(MetaBase):
    """本地用户。车间离线使用，密码只存哈希。"""

    __tablename__ = "meta_users"

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="common", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MetaPerson(MetaBase):
    """车间人员通讯录，与登录账号分开。"""

    __tablename__ = "meta_persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), default="", nullable=False)
    shift: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="", nullable=False)


class MetaJob(MetaBase):
    """重任务队列：API 投递，Worker 消费。"""

    __tablename__ = "meta_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    started_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    ended_at: Mapped[str] = mapped_column(String(40), default="", nullable=False)


class MetaEtlModel(MetaBase):
    """ETL link 模型：按项目一份，先配字段再执行。"""

    __tablename__ = "meta_etl_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_table: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    target_table: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    unique_key: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    incremental_field: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    sql_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_time: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    last_run_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    last_run_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaEtlModelField(MetaBase):
    """ETL 模型字段映射（link：direct / derived / constant）。"""

    __tablename__ = "meta_etl_model_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_field: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    target_field: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(20), default="direct", nullable=False)
    derive_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    formula: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    constant_value: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)


class MetaAggModel(MetaBase):
    """ADS 聚合模型：按项目一份，从 DWD 按时间+维度汇总。"""

    __tablename__ = "meta_agg_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_table: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    target_table: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    time_field: Mapped[str] = mapped_column(String(100), default="ServerTime", nullable=False)
    granularity: Mapped[str] = mapped_column(String(20), default="hour", nullable=False)
    time_field_name: Mapped[str] = mapped_column(String(100), default="hour", nullable=False)
    lookback_hours: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    backfill_hours: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    sql_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_time: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    last_run_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    last_run_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_run_message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class MetaAggModelField(MetaBase):
    """聚合字段：dimension / measure / derived。"""

    __tablename__ = "meta_agg_model_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source_field: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    target_field: Mapped[str] = mapped_column(String(100), nullable=False)
    field_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    field_category: Mapped[str] = mapped_column(String(20), default="dimension", nullable=False)
    aggregate_func: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    derive_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    formula: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)

