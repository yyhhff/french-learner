"""审校入库：候选 → 审校通过 → 唯一可写 texts.json 的通道。

红线：只有经审校（人工或本期 AI 审校）通过的条目才能进 texts.json。
- 审校数据结构写在候选条目的 _review_status / _reviewed_by / _review_note / _reviewed_at；
- approve(slot_id) 把候选转成 texts.json 条目（去下划线私有字段），按 id 幂等 upsert；
- reject(slot_id, note) 只改状态、不入库；
- approve_all_validated(reviewed_by) 批量通过（本期 AI 审校入口），逐条写审计日志；
- 审计日志 review_audit.jsonl 追加式，记录每次动作的 slot/id/审核者/时间/结果。

人工否决通道：前端/API 可对已通过条目调用 veto(text_id) 从 texts.json 移除并留审计。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from content_pipeline.paths import (
    AUDIT_FILE,
    CACHE_DIR,
    CANDIDATES_FILE,
    TEXTS_FILE,
    ensure_dirs,
)

PUBLIC_FIELDS = (
    "id", "title", "format", "cefr_level", "topic", "body_fr", "body_cn",
    "audio_url", "sort_order", "lines", "words",
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_candidates() -> dict[str, dict]:
    if not CANDIDATES_FILE.is_file():
        return {}
    try:
        d = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_candidates(d: dict[str, dict]) -> None:
    ensure_dirs()
    CANDIDATES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def load_texts() -> dict:
    if not TEXTS_FILE.is_file():
        return {"version": 2, "texts": []}
    try:
        d = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("texts"), list) else {"version": 2, "texts": []}
    except (OSError, ValueError):
        return {"version": 2, "texts": []}


def _dump_texts(d: dict) -> str:
    """按 texts.json 既有风格序列化：顶层 indent=2，但 lines/words 每个元素单行。

    用哨兵占位：序列化前把每个 line/word 对象换成唯一标记字符串，序列化后
    再把标记替换为紧凑 JSON。这样既保持原文件格式、让 git diff 只显示新增篇目，
    也不手写脆弱的括号解析。
    """
    import copy

    payload = copy.deepcopy(d)
    slots: dict[str, str] = {}
    for idx, text in enumerate(payload.get("texts", [])):
        for key in ("lines", "words"):
            arr = text.get(key)
            if not isinstance(arr, list):
                continue
            # 原文件风格：'{ "seq": 1, ... }'（花括号内侧带空格）；元素无嵌套，安全替换
            def _fmt(obj):
                s = json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))
                if s.startswith("{") and s.endswith("}"):
                    return "{ " + s[1:-1] + " }" if s[1:-1] else "{}"
                return s
            compact = [_fmt(x) for x in arr]
            for j, _ in enumerate(arr):
                marker = f"@@CP_{idx}_{key}_{j}@@"
                slots[marker] = compact[j]
                arr[j] = marker
    out = json.dumps(payload, ensure_ascii=False, indent=2)
    for marker, compact in slots.items():
        out = out.replace(f'"{marker}"', compact)
    return out + "\n"


def save_texts(d: dict) -> None:
    """原子写：先写临时文件再替换，避免中断损坏入库语料。"""
    tmp = TEXTS_FILE.with_suffix(".json.tmp")
    # newline="\n"：原文件是 LF，Windows 文本模式默认会写 CRLF 导致全文件 diff
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(_dump_texts(d))
    # 自检：写回必须能被解析且篇数不减（哨兵序列化非平凡，防格式损坏）
    check = json.loads(tmp.read_text(encoding="utf-8"))
    assert len(check.get("texts", [])) == len(d.get("texts", [])), "texts.json 序列化自检失败"
    tmp.replace(TEXTS_FILE)


def _audit(action: str, slot: str, text_id: str, reviewer: str, note: str = "", result: str = "ok") -> None:
    ensure_dirs()
    rec = {
        "at": _now(), "action": action, "slot": slot, "text_id": text_id,
        "reviewer": reviewer, "note": note, "result": result,
    }
    with AUDIT_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _to_public(item: dict) -> dict:
    out = {k: item.get(k) for k in PUBLIC_FIELDS}
    out["sort_order"] = out.get("sort_order") if isinstance(out.get("sort_order"), int) else 0
    return out


def approve(slot_id: str, reviewer: str, note: str = "") -> dict:
    """通过单条候选并入库（幂等）。"""
    cands = load_candidates()
    item = cands.get(slot_id)
    if not item:
        return {"ok": False, "error": "slot_not_found"}
    if item.get("_review_status") == "approved":
        return {"ok": True, "id": item.get("id"), "already": True}
    texts = load_texts()
    public = _to_public(item)
    ids = {t.get("id") for t in texts["texts"] if isinstance(t, dict)}
    if public["id"] not in ids:
        texts["texts"].append(public)
        save_texts(texts)
    item["_review_status"] = "approved"
    item["_reviewed_by"] = reviewer
    item["_review_note"] = note
    item["_reviewed_at"] = _now()
    save_candidates(cands)
    _audit("approve", slot_id, public["id"], reviewer, note)
    return {"ok": True, "id": public["id"]}


def reject(slot_id: str, reviewer: str, note: str = "") -> dict:
    cands = load_candidates()
    item = cands.get(slot_id)
    if not item:
        return {"ok": False, "error": "slot_not_found"}
    item["_review_status"] = "rejected_by_reviewer"
    item["_reviewed_by"] = reviewer
    item["_review_note"] = note
    item["_reviewed_at"] = _now()
    save_candidates(cands)
    _audit("reject", slot_id, item.get("id"), reviewer, note)
    return {"ok": True, "id": item.get("id")}


def approve_all_validated(reviewer: str = "ai-reviewer-v2.3") -> dict:
    """批量通过所有校验 pass 且仍 pending/validated 的候选（本期 AI 审校入口）。"""
    cands = load_candidates()
    texts = load_texts()
    ids = {t.get("id") for t in texts["texts"] if isinstance(t, dict)}
    added, skipped = 0, 0
    for slot, item in cands.items():
        if item.get("_review_status") not in ("pending", "validated"):
            continue
        # 只通过校验器放行的条目（无 reject_reasons）
        if item.get("_reject_reasons") or item.get("_needs_regen"):
            continue
        public = _to_public(item)
        if public["id"] in ids:
            skipped += 1
        else:
            texts["texts"].append(public)
            ids.add(public["id"])
            added += 1
        item["_review_status"] = "approved"
        item["_reviewed_by"] = reviewer
        item["_reviewed_at"] = _now()
        _audit("ai_approve", slot, public["id"], reviewer)
    if added:
        save_texts(texts)
    save_candidates(cands)
    return {"ok": True, "added": added, "skipped_existing": skipped, "reviewer": reviewer}


def veto(text_id: str, reviewer: str, note: str = "") -> dict:
    """人工否决已入库条目：从 texts.json 移除并留审计（更正通道）。"""
    texts = load_texts()
    before = len(texts["texts"])
    texts["texts"] = [t for t in texts["texts"] if not (isinstance(t, dict) and t.get("id") == text_id)]
    removed = before - len(texts["texts"])
    if removed:
        save_texts(texts)
    _audit("veto", "", text_id, reviewer, note, "removed" if removed else "not_found")
    return {"ok": bool(removed), "removed": removed}


def list_queue() -> list[dict]:
    """审校台视图：候选 + 状态 + 校验结论。"""
    cands = load_candidates()
    reports: dict[str, dict] = {}
    try:
        reports = json.loads((CACHE_DIR / "validation_reports.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    out = []
    for slot, item in cands.items():
        rep = reports.get(slot, {})
        out.append({
            "slot": slot,
            "id": item.get("id"),
            "title": item.get("title"),
            "level": item.get("cefr_level"),
            "topic": item.get("topic"),
            "status": item.get("_review_status", "pending"),
            "reviewed_by": item.get("_reviewed_by"),
            "validation_pass": rep.get("pass"),
            "errors": rep.get("errors", []),
            "warnings": rep.get("warnings", []),
            "coverage": rep.get("coverage"),
        })
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="审校入库通道")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("approve-all")
    p_ap = sub.add_parser("approve")
    p_ap.add_argument("slot")
    p_rj = sub.add_parser("reject")
    p_rj.add_argument("slot")
    p_vt = sub.add_parser("veto")
    p_vt.add_argument("text_id")
    sub.add_parser("queue")
    args = ap.parse_args()
    if args.cmd == "approve-all":
        print(json.dumps(approve_all_validated(), ensure_ascii=False, indent=2))
    elif args.cmd == "approve":
        print(json.dumps(approve(args.slot, "cli-operator"), ensure_ascii=False))
    elif args.cmd == "reject":
        print(json.dumps(reject(args.slot, "cli-operator"), ensure_ascii=False))
    elif args.cmd == "veto":
        print(json.dumps(veto(args.text_id, "cli-operator"), ensure_ascii=False))
    else:
        print(json.dumps(list_queue(), ensure_ascii=False, indent=2))
