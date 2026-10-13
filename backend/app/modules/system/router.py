"""system 模块总入口路由。

原实现是一个 668 行、53 个路由的单文件。现按职责拆到 routes/ 子模块，
本文件只负责聚合，保持 prefix 与 tags 不变（对外路径完全一致）。
"""

from fastapi import APIRouter

from app.modules.system.routes import (
    a2b_heartbeat,
    config,
    connections,
    db_browser,
    people,
    projects,
    query,
)

router = APIRouter(prefix="/system", tags=["system"])
router.include_router(connections.router)
router.include_router(query.router)
router.include_router(config.router)
router.include_router(db_browser.router)
router.include_router(projects.router)
router.include_router(people.router)
router.include_router(a2b_heartbeat.router)
