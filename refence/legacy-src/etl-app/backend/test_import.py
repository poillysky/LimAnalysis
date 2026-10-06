"""
测试模块导入
"""
import sys
from pathlib import Path

# 添加 ETL 根目录到 Python 路径
current_dir = Path(__file__).parent
etl_root = current_dir.parent

if str(etl_root) not in sys.path:
    sys.path.insert(0, str(etl_root))

print("测试模块导入...")
print()

# 测试导入 FastAPI
print("1. 导入 FastAPI")
try:
    from fastapi import FastAPI
    print("   ✅ FastAPI 导入成功")
except Exception as e:
    print(f"   ❌ FastAPI 导入失败: {e}")
print()

# 测试导入 backend.api
print("2. 导入 backend.api")
try:
    from backend.api import router as api_router
    print("   ✅ backend.api 导入成功")
    print(f"   路由对象: {api_router}")
    print(f"   路由数量: {len(api_router.routes)}")
except Exception as e:
    print(f"   ❌ backend.api 导入失败: {e}")
    import traceback
    traceback.print_exc()
print()

# 测试导入 backend.config
print("3. 导入 backend.config")
try:
    from backend.config import init_etl_config
    print("   ✅ backend.config 导入成功")
except Exception as e:
    print(f"   ❌ backend.config 导入失败: {e}")
    import traceback
    traceback.print_exc()
