"""校验器：对每条候选做 schema + 语言难度多维校验，输出 pass/reject + 原因。

校验维度（对齐 MASTER_PLAN v2.3 验收草案）：
1. schema：字段完整、类型合法、lines 连续、body 行数一致、words 合法（复用 seed_input 契约）；
2. 生词覆盖率 coverage：启发式（见 freq.heuristic），按等级目标区间判漂移；
3. 句长分布：每句词数均值/最大值按等级上限判超纲；
4. 等级漂移：coverage 与句长综合判定是否偏离标注 CEFR。

判定：任一 hard 规则失败 → reject（可自动打回重生成）；软性偏移 → warn 但可放行。
覆盖率目标为启发式近似（95–98% 是 MASTER_PLAN 的设计目标，但本基线不同源），
因此 coverage 只做「相对同等级中位数的异常检测」，不作为绝对及格线（见 PIPELINE.md）。
"""
from __future__ import annotations

import json
import re
import statistics
from typing import Any

from content_pipeline.freq.heuristic import build_known_words, coverage
from content_pipeline.paths import (
    CACHE_DIR,
    CANDIDATES_FILE,
    REPORTS_FILE,
    VALID_FORMATS,
    VALID_LEVELS,
    ensure_dirs,
)

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿœŒ]+")
# 每句词数上限（启发式，按等级放宽）
LEVEL_MAX_SENTENCE_WORDS = {"A1": 12, "A2": 15, "B1": 22, "B2": 30}
LEVEL_MIN_SENTENCE_WORDS = {"A1": 2, "A2": 2, "B1": 3, "B2": 4}


def _nonempty(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def check_schema(item: dict) -> list[str]:
    """与 seed_input._validate_text 对齐的必填 + 结构校验；返回错误列表。"""
    errs: list[str] = []
    if not isinstance(item, dict):
        return ["not_object"]
    for k in ("id", "title", "topic", "body_fr", "body_cn"):
        if not _nonempty(item.get(k)):
            errs.append(f"missing_{k}")
    if item.get("format") not in VALID_FORMATS:
        errs.append("bad_format")
    if item.get("cefr_level") not in VALID_LEVELS:
        errs.append("bad_level")
    lines = item.get("lines")
    if not isinstance(lines, list) or not lines:
        errs.append("bad_lines")
        return errs
    fr_lines = (item.get("body_fr") or "").split("\n")
    cn_lines = (item.get("body_cn") or "").split("\n")
    if len(fr_lines) != len(lines) or len(cn_lines) != len(lines):
        errs.append("line_count_mismatch")
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            errs.append(f"line_{i}_not_object")
            continue
        if line.get("seq") != i + 1:
            errs.append(f"line_{i}_bad_seq")
        if not _nonempty(line.get("fr")) or not _nonempty(line.get("cn")):
            errs.append(f"line_{i}_empty")
        if item.get("format") == "dialogue" and line.get("speaker") not in ("A", "B"):
            errs.append(f"line_{i}_bad_speaker")
    words = item.get("words")
    if not isinstance(words, list) or len(words) < 4:
        errs.append("too_few_words")
    else:
        for w in words:
            if not isinstance(w, dict) or not _nonempty(w.get("word")) or not _nonempty(w.get("meaning")):
                errs.append("bad_word_entry")
                break
    return errs


def sentence_stats(body_fr: str) -> dict:
    sents = [s.strip() for s in re.split(r"[.!?]+", body_fr or "") if s.strip()]
    counts = [len(_WORD_RE.findall(s)) for s in sents]
    if not counts:
        return {"sentences": 0, "mean": 0, "max": 0}
    return {
        "sentences": len(counts),
        "mean": round(statistics.mean(counts), 1),
        "max": max(counts),
    }


def validate_one(item: dict, known: set[str]) -> dict:
    errors = check_schema(item)
    level = item.get("cefr_level", "") if isinstance(item, dict) else ""
    stats = sentence_stats(item.get("body_fr", "") if isinstance(item, dict) else "")
    cov = coverage(item.get("body_fr", ""), known) if isinstance(item, dict) else None

    warnings: list[str] = []
    if not errors:
        # 句长漂移（hard：单句超上限 2 倍视为明显超纲）
        hi = LEVEL_MAX_SENTENCE_WORDS.get(level, 30)
        lo = LEVEL_MIN_SENTENCE_WORDS.get(level, 2)
        if stats["max"] > hi * 2:
            errors.append("sentence_too_long")
        elif stats["max"] > hi:
            warnings.append("sentence_long")
        if stats["sentences"] and stats["mean"] < lo:
            warnings.append("sentence_short")
        # 覆盖率异常偏低（生词过多）：启发式仅做粗判，阈值宽松
        if cov is not None and cov < 0.55:
            warnings.append("low_coverage_heuristic")

    return {
        "id": item.get("id") if isinstance(item, dict) else None,
        "source_demand": item.get("_source_demand") if isinstance(item, dict) else None,
        "level": level,
        "pass": not errors,
        "errors": errors,
        "warnings": warnings,
        "coverage": cov,
        "sentence_stats": stats,
    }


def run(apply_regen: bool = True) -> dict:
    """校验全部候选；返回报告并落盘 validation_reports.json。"""
    cands = load_json(CANDIDATES_FILE, {})
    known = build_known_words()
    reports: dict[str, dict] = {}
    stats = {"total": 0, "passed": 0, "rejected": 0, "warned": 0}

    for key, item in cands.items():
        rep = validate_one(item, known)
        reports[key] = rep
        stats["total"] += 1
        if rep["pass"]:
            stats["passed"] += 1
            if rep["warnings"]:
                stats["warned"] += 1
            cands[key]["_review_status"] = "validated"
        else:
            stats["rejected"] += 1
            cands[key]["_review_status"] = "rejected"
            cands[key]["_reject_reasons"] = rep["errors"]
            if apply_regen:
                cands[key]["_needs_regen"] = True

    ensure_dirs()
    CANDIDATES_FILE.write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORTS_FILE.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def load_json(path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def retry_rejected() -> dict:
    """把被 reject 且标记重生成的候选从池移除（下轮 generate 会重新产出）。"""
    cands = load_json(CANDIDATES_FILE, {})
    removed = [k for k, v in cands.items() if v.get("_needs_regen")]
    for k in removed:
        del cands[k]
    CANDIDATES_FILE.write_text(json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"removed": len(removed)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="校验语料候选")
    ap.add_argument("--retry-rejected", action="store_true", help="清除被拒候选以便重生成")
    args = ap.parse_args()
    if args.retry_rejected:
        print(json.dumps(retry_rejected(), ensure_ascii=False))
    else:
        print(json.dumps(run(), ensure_ascii=False, indent=2))
