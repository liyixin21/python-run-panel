"""
通用工具函数：
- 密码哈希与验证（PBKDF2-SHA256）
- 路径安全校验（防目录穿越）
- 时间统一处理（UTC 存储 + 带时区序列化）
"""
import hashlib
import hmac
import os
import re
from datetime import datetime, timezone

# 项目名白名单：字母/数字开头，允许 . _ - ，总长 1-128
# 显式排除 ".."，避免产生上溯路径
PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PathSecurityError(Exception):
    """路径越界：目标落在允许的根目录之外。"""


def hash_password(password: str) -> str:
    """对密码做 PBKDF2-SHA256 哈希，返回 "salt$hash" 格式的字符串"""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return salt.hex() + "$" + key.hex()


def verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希值（常量时间比较）"""
    try:
        salt_hex, key_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return hmac.compare_digest(new_key, key)
    except Exception:
        return False


def validate_project_name(name: str) -> str:
    """校验并规范化项目名，非法时抛 ValueError。

    项目名会被直接用作目录名，因此必须是受限字符集且不含 ".."，
    否则可构造 "../x" 之类路径在工作区之外读写。
    """
    cleaned = (name or "").strip()
    if not PROJECT_NAME_RE.match(cleaned) or ".." in cleaned:
        raise ValueError("项目名只能由字母、数字、点、下划线、连字符组成，且不能以符号开头")
    return cleaned


def safe_join(root: str, *parts: str) -> str:
    """把 parts 安全地拼接到 root 下，越界时抛 PathSecurityError。

    用 os.path.commonpath 按路径分量比较，因此 "/w/1_x" 不会被误判为
    位于 "/w/1" 之内（这正是 startswith 前缀匹配的漏洞）。
    """
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, *parts))
    if target == root_real:
        return target
    try:
        if os.path.commonpath([root_real, target]) != root_real:
            raise PathSecurityError(f"路径越界: {target}")
    except ValueError:
        # 不同驱动器 / 绝对路径混用
        raise PathSecurityError(f"路径越界: {target}")
    return target


def resolve_static(static_root: str, url_path: str) -> tuple[str | None, bool]:
    """解析静态文件路径。

    返回 (绝对路径或 None, 是否为越界尝试)。
    - 命中真实文件：返回 (路径, False)
    - 未命中（普通 404 / SPA 路由）：返回 (None, False)
    - 越出 STATIC_DIR：返回 (None, True)，调用方应直接 404，
      不要回落到 index.html，以免掩盖攻击探测行为
    """
    try:
        root = os.path.realpath(static_root)
        if not url_path:
            return None, False
        target = os.path.realpath(os.path.join(root, url_path.lstrip("/")))
        if os.path.commonpath([root, target]) != root:
            return None, True
    except (ValueError, OSError):
        return None, True
    return (target if os.path.isfile(target) else None), False


def safe_static_path(static_root: str, url_path: str) -> str | None:
    """解析静态文件路径，越界或不是文件时返回 None。"""
    path, _escaped = resolve_static(static_root, url_path)
    return path


def utcnow() -> datetime:
    """当前 UTC 时间（naive，统一入库格式，避免 datetime.utcnow 弃用告警）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(dt: datetime | None) -> str:
    """把库中的 naive UTC 时间序列化为带时区标记的 ISO 字符串。

    数据库统一存 naive UTC，若直接 isoformat() 输出，前端会按本地时间解析，
    造成 8 小时偏差。此处显式补上 +00:00。
    """
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()
