"""
资源监控工具 - 用于监控内存和数据库连接使用情况
"""
import os
import psutil
from typing import Dict, Any
from sqlalchemy import text


class ResourceMonitor:
    """资源监控器"""
    
    @staticmethod
    def get_process_memory() -> Dict[str, Any]:
        """
        获取当前进程的内存使用情况
        
        Returns:
            内存使用信息字典
        """
        try:
            process = psutil.Process(os.getpid())
            memory_info = process.memory_info()
            
            return {
                'rss_mb': round(memory_info.rss / 1024 / 1024, 2),  # 物理内存（MB）
                'vms_mb': round(memory_info.vms / 1024 / 1024, 2),  # 虚拟内存（MB）
                'percent': round(process.memory_percent(), 2),  # 内存占用百分比
                'num_threads': process.num_threads(),  # 线程数
                'num_fds': process.num_fds() if hasattr(process, 'num_fds') else None,  # 文件描述符数（Linux）
            }
        except Exception as e:
            return {
                'error': str(e)
            }
    
    @staticmethod
    def get_database_connections(engine) -> Dict[str, Any]:
        """
        获取数据库连接池状态
        
        Args:
            engine: SQLAlchemy 引擎
            
        Returns:
            连接池状态字典
        """
        try:
            pool = engine.pool
            
            return {
                'pool_size': pool.size(),  # 连接池大小
                'checked_in': pool.checkedin(),  # 已归还的连接数
                'checked_out': pool.checkedout(),  # 已借出的连接数
                'overflow': pool.overflow(),  # 溢出连接数
                'total_connections': pool.size() + pool.overflow(),  # 总连接数
            }
        except Exception as e:
            return {
                'error': str(e)
            }
    
    @staticmethod
    def get_mysql_connections(engine) -> Dict[str, Any]:
        """
        获取 MySQL 服务器的连接统计
        
        Args:
            engine: SQLAlchemy 引擎
            
        Returns:
            MySQL 连接统计字典
        """
        try:
            with engine.connect() as conn:
                # 获取当前连接数
                result = conn.execute(text("SHOW STATUS LIKE 'Threads_connected'")).fetchone()
                threads_connected = int(result[1]) if result else 0
                
                # 获取最大连接数
                result = conn.execute(text("SHOW VARIABLES LIKE 'max_connections'")).fetchone()
                max_connections = int(result[1]) if result else 0
                
                # 获取当前用户的连接数
                result = conn.execute(text(
                    "SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE USER = CURRENT_USER()"
                )).fetchone()
                current_user_connections = int(result[0]) if result else 0
                
                return {
                    'threads_connected': threads_connected,
                    'max_connections': max_connections,
                    'usage_percent': round(threads_connected / max_connections * 100, 2) if max_connections > 0 else 0,
                    'current_user_connections': current_user_connections,
                }
        except Exception as e:
            return {
                'error': str(e)
            }
    
    @staticmethod
    def get_full_report(engine=None) -> Dict[str, Any]:
        """
        获取完整的资源监控报告
        
        Args:
            engine: SQLAlchemy 引擎（可选）
            
        Returns:
            完整的监控报告字典
        """
        report = {
            'timestamp': psutil.time.time(),
            'process_memory': ResourceMonitor.get_process_memory(),
        }
        
        if engine:
            report['connection_pool'] = ResourceMonitor.get_database_connections(engine)
            report['mysql_connections'] = ResourceMonitor.get_mysql_connections(engine)
        
        return report
    
    @staticmethod
    def print_report(report: Dict[str, Any]):
        """
        打印资源监控报告
        
        Args:
            report: 监控报告字典
        """
        print("\n" + "=" * 60)
        print("📊 资源监控报告")
        print("=" * 60)
        
        # 进程内存
        if 'process_memory' in report:
            mem = report['process_memory']
            if 'error' not in mem:
                print(f"\n💾 进程内存:")
                print(f"   - 物理内存: {mem['rss_mb']} MB")
                print(f"   - 虚拟内存: {mem['vms_mb']} MB")
                print(f"   - 内存占用: {mem['percent']}%")
                print(f"   - 线程数: {mem['num_threads']}")
                if mem.get('num_fds'):
                    print(f"   - 文件描述符: {mem['num_fds']}")
        
        # 连接池状态
        if 'connection_pool' in report:
            pool = report['connection_pool']
            if 'error' not in pool:
                print(f"\n🔌 连接池状态:")
                print(f"   - 连接池大小: {pool['pool_size']}")
                print(f"   - 已归还连接: {pool['checked_in']}")
                print(f"   - 已借出连接: {pool['checked_out']}")
                print(f"   - 溢出连接: {pool['overflow']}")
                print(f"   - 总连接数: {pool['total_connections']}")
        
        # MySQL 连接统计
        if 'mysql_connections' in report:
            mysql = report['mysql_connections']
            if 'error' not in mysql:
                print(f"\n🗄️  MySQL 连接:")
                print(f"   - 当前连接数: {mysql['threads_connected']}")
                print(f"   - 最大连接数: {mysql['max_connections']}")
                print(f"   - 使用率: {mysql['usage_percent']}%")
                print(f"   - 当前用户连接: {mysql['current_user_connections']}")
        
        print("=" * 60 + "\n")


def monitor_resources(engine=None):
    """
    便捷函数：获取并打印资源监控报告
    
    Args:
        engine: SQLAlchemy 引擎（可选）
    """
    report = ResourceMonitor.get_full_report(engine)
    ResourceMonitor.print_report(report)
    return report


if __name__ == '__main__':
    # 测试资源监控
    print("测试资源监控功能...")
    report = ResourceMonitor.get_full_report()
    ResourceMonitor.print_report(report)
