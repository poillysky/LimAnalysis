# -*- coding: utf-8 -*-
"""配置管理模块"""

import os
import yaml
from typing import Dict, Any


class Config:
    """系统配置类"""
    
    def __init__(self, config_path: str = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认从环境变量读取或使用默认路径
        """
        if config_path is None:
            config_path = os.environ.get("CONFIG_PATH", "config.yaml")
        
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项
        
        Args:
            key: 配置键，支持点号分隔，如 "paths.source_dir"
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def get_paths(self) -> Dict[str, str]:
        """获取路径配置"""
        return self.get('paths', {})
    
    def get_archive_rules(self) -> list:
        """获取归档规则"""
        return self.get('archive_rules', [])
    
    def get_cleanup_config(self) -> Dict[str, Any]:
        """获取清理配置"""
        return self.get('cleanup', {})
    
    def get_inspection_config(self) -> Dict[str, Any]:
        """获取巡机审核配置"""
        return self.get('inspection', {})
