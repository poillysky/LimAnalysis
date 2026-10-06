"""
加密管理模块
"""
from cryptography.fernet import Fernet

from app.settings import settings


class EncryptionManager:
    """加密管理器"""
    
    def __init__(self, key: str):
        """
        初始化加密管理器
        
        Args:
            key: Fernet 密钥
        """
        self.cipher = Fernet(key.encode())
    
    def encrypt(self, plain_text: str) -> str:
        """
        加密文本
        
        Args:
            plain_text: 明文
            
        Returns:
            密文
        """
        if not plain_text:
            return ""
        
        encrypted = self.cipher.encrypt(plain_text.encode())
        return encrypted.decode()
    
    def decrypt(self, encrypted_text: str) -> str:
        """
        解密文本
        
        Args:
            encrypted_text: 密文
            
        Returns:
            明文
        """
        if not encrypted_text:
            return ""
        
        decrypted = self.cipher.decrypt(encrypted_text.encode())
        return decrypted.decode()


# 全局加密管理器实例
encryption_manager = EncryptionManager(settings.encryption_key)
