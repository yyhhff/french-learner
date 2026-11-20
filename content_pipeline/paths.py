"""路径与常量集中定义，供管线各模块共享（避免相对路径漂移）。"""
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent          # content_pipeline/
PROJECT_ROOT = PACKAGE_ROOT.parent                       # french-learner/
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = DATA_DIR / "input"
CACHE_DIR = DATA_DIR / "cache" / "content_pipeline"
AUDIO_DIR = CACHE_DIR / "audio"

TEXTS_FILE = INPUT_DIR / "texts.json"                   # 入库语料（入 git）
DEMAND_FILE = CACHE_DIR / "demand_queue.json"           # 需求队列
CANDIDATES_FILE = CACHE_DIR / "candidates.json"         # 生成候选池
REPORTS_FILE = CACHE_DIR / "validation_reports.json"    # 校验报告
AUDIT_FILE = CACHE_DIR / "review_audit.jsonl"           # 审校审计（追加式）
PROGRESS_FILE = CACHE_DIR / "progress.json"             # 管线进度

# 四档语料，目标 200+ 篇（A1 约 50 / A2 约 50 / B1 约 50 / B2 约 50）
TARGET_LEVELS = ("A1", "A2", "B1", "B2")
PER_LEVEL_TARGET = 50

VALID_FORMATS = {"dialogue", "monologue"}
VALID_LEVELS = set(TARGET_LEVELS)


def ensure_dirs() -> None:
    for d in (CACHE_DIR, AUDIO_DIR):
        d.mkdir(parents=True, exist_ok=True)
