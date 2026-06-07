"""
工具函数：密码哈希与验证（PBKDF2-SHA256）
"""
import hashlib
import os


def hash_password(password: str) -> str:
    """对密码做 PBKDF2-SHA256 哈希，返回 "salt$hash" 格式的字符串"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + "$" + key.hex()


def verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希值"""
    try:
        salt_hex, key_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return new_key == key
    except Exception:
        return False
