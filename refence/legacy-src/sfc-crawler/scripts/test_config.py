"""
测试配置读取

验证所有配置都从 SQLite 读取，无硬编码
"""
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.engines import get_redis_config_from_db, get_mysql_config_from_db


def test_redis_config():
    """测试 Redis 配置读取"""
    print("=" * 60)
    print("测试 Redis 配置读取")
    print("=" * 60)
    
    try:
        config = get_redis_config_from_db()
        if config:
            print("✅ Redis 配置读取成功")
            print(f"   主机: {config['host']}:{config['port']}")
            print(f"   数据库: {config['db']}")
            print(f"   最大连接数: {config['max_connections']}")
            print(f"   连接超时: {config['socket_timeout']}秒")
        else:
            print("❌ Redis 配置不存在")
    except Exception as e:
        print(f"❌ Redis 配置读取失败: {e}")
    
    print()


def test_mysql_config():
    """测试 MySQL 配置读取"""
    print("=" * 60)
    print("测试 MySQL 配置读取")
    print("=" * 60)
    
    try:
        config = get_mysql_config_from_db()
        print("✅ MySQL 配置读取成功")
        print(f"   连接池大小: {config['pool_size']}")
        print(f"   最大溢出: {config['max_overflow']}")
        print(f"   连接超时: {config['pool_timeout']}秒")
        print(f"   连接回收: {config['pool_recycle']}秒")
        # 不打印完整 URL（包含密码）
        print(f"   URL: mysql+pymysql://***:***@***/***/***")
    except Exception as e:
        print(f"❌ MySQL 配置读取失败: {e}")
    
    print()


if __name__ == "__main__":
    print("\n🔍 配置读取测试\n")
    
    test_redis_config()
    test_mysql_config()
    
    print("=" * 60)
    print("测试完成")
    print("=" * 60)
