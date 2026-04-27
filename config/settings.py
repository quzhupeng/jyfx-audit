"""应用级设置."""

from __future__ import annotations

import os
from pathlib import Path

# 上传文件配置
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_MAX_SIZE_MB = int(os.environ.get("UPLOAD_MAX_SIZE_MB", "50"))

# API 配置
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# 模板配置
DEFAULT_TEMPLATE = os.environ.get(
    "TEMPLATE_PATH",
    str(Path(__file__).resolve().parent.parent / "templates" / "default_template.yaml"),
)

# AI 分析配置
AI_MAX_CHARS_PER_SECTION = int(os.environ.get("AI_MAX_CHARS_PER_SECTION", "2000"))
AI_ENABLED = bool(ANTHROPIC_API_KEY)

# 确保上传目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
