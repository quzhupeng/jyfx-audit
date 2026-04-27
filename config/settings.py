"""应用级设置."""

from __future__ import annotations

import os
from pathlib import Path

# 自动加载 .env 文件到环境变量
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
if _ENV_FILE.exists():
    with open(_ENV_FILE, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _k, _v = _k.strip(), _v.strip()
                if _k and _k not in os.environ:
                    os.environ[_k] = _v


def _get_secret(key: str, default: str = "") -> str:
    """优先从环境变量读取，其次从 Streamlit secrets 读取."""
    value = os.environ.get(key, "")
    if value:
        return value
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


# 上传文件配置
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_MAX_SIZE_MB = int(os.environ.get("UPLOAD_MAX_SIZE_MB", "50"))

# API 配置 — Anthropic（可选）
ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get_secret("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# API 配置 — DeepSeek（默认 AI 提供商）
DEEPSEEK_API_KEY = _get_secret("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get_secret("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _get_secret("DEEPSEEK_MODEL", "deepseek-chat")

# AI 提供商选择: deepseek | anthropic
AI_PROVIDER = _get_secret("AI_PROVIDER", "deepseek")

# 模板配置
DEFAULT_TEMPLATE = os.environ.get(
    "TEMPLATE_PATH",
    str(Path(__file__).resolve().parent.parent / "templates" / "default_template.yaml"),
)

# AI 分析配置
AI_MAX_CHARS_PER_SECTION = int(os.environ.get("AI_MAX_CHARS_PER_SECTION", "2000"))
AI_ENABLED = bool(DEEPSEEK_API_KEY) or bool(ANTHROPIC_API_KEY)

# 确保上传目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
