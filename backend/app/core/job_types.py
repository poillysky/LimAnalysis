"""meta_jobs 任务类型与状态常量。

放在 app/core 而不是 collector/，是因为 app/core 是最底层，多个上层模块
（collector / processor / app.modules.*）都要用这些字符串常量。按架构守卫
的规则：下层需要上层的东西时，把那个东西**下沉**，而不是在下层反向 import。

真正的任务队列读写（enqueue / claim / finish）仍留在 collector/jobs.py，
那确实属于 Worker 层职责。这里只放纯字符串常量，零依赖。
"""

from __future__ import annotations

JOB_CRAWL = "sfc_crawl"
JOB_UPLOAD = "sfc_upload"
JOB_SYNC_SCHEMA = "sfc_sync_schema"
JOB_ETL_CLEAN = "etl_clean"
JOB_ETL_AGG = "etl_agg"
JOB_DISK_CLEANUP = "disk_cleanup"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

# 采集 Worker 消费的重任务类型（不含磁盘清理，避免清理阻塞清洗）
HEAVY_TYPES = (
    JOB_CRAWL,
    JOB_UPLOAD,
    JOB_SYNC_SCHEMA,
    JOB_ETL_CLEAN,
)
WORKER_TYPES = HEAVY_TYPES
# 聚合 Worker 消费的类型
AGG_WORKER_TYPES = (JOB_ETL_AGG,)
# 磁盘清理 Worker 消费的类型
CLEANUP_WORKER_TYPES = (JOB_DISK_CLEANUP,)
