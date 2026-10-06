"""
ETL 模块主程序入口
"""
import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backend.config import init_etl_config, get_config_manager
from backend.core.logger import get_etl_logger


def main():
    """主程序入口"""
    print("=" * 50)
    print("ETL 数据处理模块")
    print("版本: v1.0.0")
    print("=" * 50)
    
    try:
        # 初始化配置
        print("正在初始化配置...")
        config_manager = init_etl_config()
        print("✅ 配置初始化完成")
        
        # 初始化日志
        print("正在初始化日志系统...")
        logger = get_etl_logger()
        print("✅ 日志系统初始化完成")
        
        # 记录启动日志
        logger.log_scheduler_event(
            event_type="system_start",
            message="ETL 系统启动",
            details={"version": "1.0.0"}
        )
        
        print("\n🚀 ETL 系统启动成功！")
        print("\n可用功能:")
        print("1. 模型管理 - 创建和管理 ETL 模型")
        print("2. SQL 生成 - 自动生成标准 SQL 文件")
        print("3. 执行引擎 - 执行 ETL 任务")
        print("4. 任务调度 - 定时执行 ETL 任务")
        print("5. 日志查看 - 查看执行日志和统计")
        
        # 显示配置信息
        etl_config = config_manager.get_etl_config()
        if etl_config:
            print(f"\n当前配置:")
            print(f"- 源数据库: {etl_config['source_database']}")
            print(f"- 目标数据库: {etl_config['target_database']}")
            print(f"- 分析数据库: {etl_config['analytics_database']}")
            print(f"- 执行间隔: {etl_config['run_interval']} 分钟")
            print(f"- 状态: {'启用' if etl_config['is_active'] else '禁用'}")
        
        print(f"\n日志目录: {logger.log_dir}")
        
        # 简单的交互式菜单
        show_menu()
        
    except Exception as e:
        print(f"❌ 系统启动失败: {e}")
        sys.exit(1)


def show_menu():
    """显示交互式菜单"""
    while True:
        print("\n" + "=" * 30)
        print("ETL 管理菜单")
        print("=" * 30)
        print("1. 查看系统状态")
        print("2. 查看执行统计")
        print("3. 查看最近日志")
        print("4. 测试数据库连接")
        print("5. 清理旧日志")
        print("0. 退出")
        
        try:
            choice = input("\n请选择操作 (0-5): ").strip()
            
            if choice == "0":
                print("👋 再见！")
                break
            elif choice == "1":
                show_system_status()
            elif choice == "2":
                show_execution_stats()
            elif choice == "3":
                show_recent_logs()
            elif choice == "4":
                test_database_connection()
            elif choice == "5":
                cleanup_old_logs()
            else:
                print("❌ 无效选择，请重新输入")
                
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 操作失败: {e}")


def show_system_status():
    """显示系统状态"""
    print("\n📊 系统状态")
    print("-" * 20)
    
    config_manager = get_config_manager()
    etl_config = config_manager.get_etl_config()
    
    if etl_config:
        print(f"系统状态: {'🟢 运行中' if etl_config['is_active'] else '🔴 已停止'}")
        print(f"最后运行: {etl_config['last_run_time'] or '从未运行'}")
        print(f"运行状态: {etl_config['last_run_status'] or '无'}")
    else:
        print("❌ 未找到系统配置")


def show_execution_stats():
    """显示执行统计"""
    print("\n📈 执行统计（最近7天）")
    print("-" * 25)
    
    logger = get_etl_logger()
    stats = logger.get_etl_statistics(days=7)
    
    print(f"总执行次数: {stats['total_runs']}")
    print(f"成功次数: {stats['success_runs']}")
    print(f"失败次数: {stats['failed_runs']}")
    print(f"成功率: {stats['success_rate']}%")


def show_recent_logs():
    """显示最近日志"""
    print("\n📝 最近执行日志（最新10条）")
    print("-" * 30)
    
    logger = get_etl_logger()
    logs = logger.read_etl_logs(limit=10)
    
    if not logs:
        print("暂无执行日志")
        return
    
    for log in logs:
        status_icon = "✅" if log['status'] == 'success' else "❌"
        print(f"{status_icon} {log['timestamp']} - {log['model_name']} ({log['status']})")
        if log.get('message'):
            print(f"   {log['message']}")


def test_database_connection():
    """测试数据库连接"""
    print("\n🔗 测试数据库连接")
    print("-" * 20)
    
    config_manager = get_config_manager()
    mysql_config = config_manager.get_mysql_config()
    
    if not mysql_config:
        print("❌ 未找到 MySQL 配置")
        return
    
    from backend.utils.database import test_mysql_connection
    
    print("正在测试连接...")
    result = test_mysql_connection(mysql_config)
    
    if result['success']:
        print(f"✅ {result['message']}")
    else:
        print(f"❌ {result['message']}")


def cleanup_old_logs():
    """清理旧日志"""
    print("\n🧹 清理旧日志")
    print("-" * 15)
    
    try:
        days = int(input("请输入保留天数 (默认30): ") or "30")
        
        logger = get_etl_logger()
        logger.cleanup_old_logs(keep_days=days)
        
        print(f"✅ 已清理 {days} 天前的日志文件")
        
    except ValueError:
        print("❌ 请输入有效的数字")
    except Exception as e:
        print(f"❌ 清理失败: {e}")


if __name__ == "__main__":
    main()