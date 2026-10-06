"""
ETL 后端主程序入口
"""
import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 加载环境变量
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ 已加载环境变量: {env_path}")
else:
    print(f"⚠️  未找到 .env 文件: {env_path}")

# 添加当前目录到 Python 路径（ETL backend 优先）
current_dir = Path(__file__).parent
etl_root = current_dir.parent

# 只添加 ETL 根目录，不添加 DataLim4 backend
if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

from backend.api import router as api_router
from backend.config import init_etl_config
from backend.utils.system_config import get_system_setting


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    print("🚀 ETL 服务启动中...")
    
    # 初始化 ETL 配置
    try:
        config_manager = init_etl_config()
        print(f"✅ ETL 配置初始化完成")
        print(f"   配置数据库: {config_manager.cfg_db_path}")
    except Exception as e:
        print(f"⚠️  ETL 配置初始化失败: {e}")
    
    # 启动调度器
    try:
        from backend.core.scheduler import get_task_scheduler
        
        # 检查是否启用自动调度
        etl_config = config_manager.get_etl_config()
        if etl_config and etl_config.get('is_active', False):
            scheduler = get_task_scheduler()  # 使用全局单例
            scheduler.start()
            print(f"✅ ETL 调度器已启动")
            print(f"   循环间隔: {etl_config.get('run_interval', 60)} 分钟")
        else:
            print(f"ℹ️  ETL 调度器未启用（可在配置中启用）")
    except Exception as e:
        print(f"⚠️  ETL 调度器启动失败: {e}")
    
    # 读取系统配置
    try:
        backend_host = get_system_setting("backend_host", "0.0.0.0")
        backend_port = get_system_setting("backend_port", "8001")
        print(f"✅ ETL 服务启动完成")
        print(f"   监听地址: {backend_host}:{backend_port}")
        print(f"   API 文档: http://localhost:{backend_port}/docs")
    except Exception as e:
        print(f"⚠️  读取系统配置失败: {e}")
    
    yield
    
    # 关闭时执行
    print("👋 ETL 服务关闭中...")
    
    # 停止调度器
    try:
        from backend.core.scheduler import get_task_scheduler
        scheduler = get_task_scheduler()
        if scheduler.is_running:
            scheduler.stop()
            print("✅ ETL 调度器已停止")
    except Exception as e:
        print(f"⚠️  停止调度器失败: {e}")
    
    print("👋 ETL 服务已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="ETL API",
    description="ETL 数据转换服务",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS（从配置读取前端地址）
try:
    frontend_url = get_system_setting("frontend_url", "http://localhost:5174")
    allowed_origins = [frontend_url]
    
    # 同时支持 localhost 和 127.0.0.1
    if "localhost" in frontend_url:
        allowed_origins.append(frontend_url.replace("localhost", "127.0.0.1"))
    elif "127.0.0.1" in frontend_url:
        allowed_origins.append(frontend_url.replace("127.0.0.1", "localhost"))
except Exception:
    # 如果读取失败，使用默认值
    allowed_origins = ["http://localhost:5174", "http://127.0.0.1:5174"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router, prefix="/api/v1")

# 配置前端静态文件服务
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # 挂载静态资源目录
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
    
    # 根路径返回 index.html
    @app.get("/")
    async def serve_frontend():
        """提供前端页面"""
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"message": "Frontend not found"}
    
    # 所有其他路径也返回 index.html（支持前端路由）
    @app.get("/{full_path:path}")
    async def serve_frontend_routes(full_path: str):
        """支持前端路由"""
        # API 路径不处理
        if full_path.startswith("api/"):
            return {"error": "Not found"}
        
        # 检查是否是静态文件
        file_path = frontend_dist / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        
        # 否则返回 index.html（前端路由）
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        
        return {"error": "Not found"}
    
    print(f"✅ 前端静态文件服务已配置: {frontend_dist}")
else:
    @app.get("/")
    async def root():
        """根路径"""
        return {
            "service": "ETL API",
            "version": "1.0.0",
            "status": "running",
            "message": "Frontend not built. Please run 'npm run build' in frontend directory."
        }
    
    print(f"⚠️  前端构建文件不存在: {frontend_dist}")


if __name__ == "__main__":
    # 从配置读取启动参数
    try:
        host = get_system_setting("backend_host", "0.0.0.0")
        port = int(get_system_setting("backend_port", "8001"))
        log_level = get_system_setting("log_level", "info")
    except Exception as e:
        print(f"⚠️  读取配置失败，使用默认值: {e}")
        host = "0.0.0.0"
        port = 8001
        log_level = "info"
    
    # 启动服务（不使用 reload，避免模块导入问题）
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level
    )

