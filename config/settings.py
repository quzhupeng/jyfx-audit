"""应用级设置."""

from __future__ import annotations

import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    """加载 .env 文件到 os.environ."""
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v


def _load_streamlit_secrets():
    """加载 .streamlit/secrets.toml 到 os.environ（非 Streamlit 运行时）."""
    secrets_file = ROOT_DIR / ".streamlit" / "secrets.toml"
    if not secrets_file.exists():
        return
    with open(secrets_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                # 去掉引号
                v = v.strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v


# 加载配置：先 .env，再 secrets.toml
_load_env_file()
_load_streamlit_secrets()


def _get_config(key: str, default: str = "") -> str:
    """从 os.environ 读取（.env 和 secrets.toml 已加载到 environ）."""
    return os.environ.get(key, default)


# 上传文件配置
UPLOAD_DIR = ROOT_DIR / "uploads"
UPLOAD_MAX_SIZE_MB = int(os.environ.get("UPLOAD_MAX_SIZE_MB", "50"))

# API 配置 — Anthropic（可选）
ANTHROPIC_API_KEY = _get_config("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = _get_config("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# API 配置 — DeepSeek（默认 AI 提供商）
DEEPSEEK_API_KEY = _get_config("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get_config("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _get_config("DEEPSEEK_MODEL", "deepseek-v4-flash")

# AI 提供商选择: deepseek | anthropic
AI_PROVIDER = _get_config("AI_PROVIDER", "deepseek")

# 模板配置
DEFAULT_TEMPLATE = os.environ.get(
    "TEMPLATE_PATH",
    str(ROOT_DIR / "templates" / "default_template.yaml"),
)

# AI 分析配置
AI_MAX_CHARS_PER_SECTION = int(os.environ.get("AI_MAX_CHARS_PER_SECTION", "2000"))
AI_ENABLED = bool(DEEPSEEK_API_KEY) or bool(ANTHROPIC_API_KEY)

# 确保上传目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
