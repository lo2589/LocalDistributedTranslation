"""
Master 地址解析

查找顺序:
    1. 环境变量 LOCALTRANS_MASTER_URL
    2. ~/.localtrans/config.yaml 里的 master_url 字段
    3. 兜底 http://localhost:8000
"""

import os
from pathlib import Path

DEFAULT_MASTER_URL = "http://localhost:8000"
ENV_KEY = "LOCALTRANS_MASTER_URL"


def _config_path() -> Path:
    """~/.localtrans/config.yaml"""
    return Path.home() / ".localtrans" / "config.yaml"


def get_master_url() -> str:
    """获取 Master 服务地址"""
    # 1. 环境变量
    env_url = os.environ.get(ENV_KEY)
    if env_url:
        return env_url.rstrip("/")

    # 2. 用户配置文件
    cfg = _config_path()
    if cfg.exists():
        try:
            import yaml
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            url = data.get("master_url")
            if url:
                return str(url).rstrip("/")
        except Exception:
            # 配置解析失败兜底到默认
            pass

    # 3. 默认值
    return DEFAULT_MASTER_URL


def save_master_url(url: str) -> None:
    """保存 Master 地址到 ~/.localtrans/config.yaml"""
    cfg = _config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(f"master_url: {url}\n", encoding="utf-8")


def save_master_url_cli() -> None:
    """命令行入口: localtrans-save http://192.168.1.100:8000"""
    import sys
    if len(sys.argv) < 2:
        print("Usage: localtrans-save <master_url>")
        print("Example: localtrans-save http://192.168.1.100:8000")
        sys.exit(1)
    url = sys.argv[1].rstrip("/")
    save_master_url(url)
    print(f"Saved: master_url = {url}")
    print(f"File: {_config_path()}")


__all__ = [
    "DEFAULT_MASTER_URL",
    "ENV_KEY",
    "get_master_url",
    "save_master_url",
    "save_master_url_cli",
]
