"""inspection 子模块集合。

原 app/core/inspection.py 单文件 1600+ 行，按职责把内聚性强的工具簇拆到这里，
inspection.py 保留为对外门面（re-export），保证既有 import 路径不变。

- browse: 磁盘目录浏览（根目录枚举 / 子目录列举）
"""
