"""内容工厂一键 CLI：demand → generate → validate → review → audio 全流程编排。

用法：
  python -m content_pipeline.cli build                 # 构建 200 槽位需求队列
  python -m content_pipeline.cli gen --limit 10         # 生成候选（断点续跑）
  python -m content_pipeline.cli check                  # 校验全部候选
  python -m content_pipeline.cli retry                  # 清除被拒候选以便重生成
  python -m content_pipeline.cli approve-all            # AI 审校批量入库
  python -m content_pipeline.cli audio --limit-texts 5  # 音频批量（断点续跑）
  python -m content_pipeline.cli status                 # 查看队列/候选/入库统计
"""
from __future__ import annotations

import argparse
import json

from content_pipeline import audio_batch, demand, generate, review_store, validate
from content_pipeline.paths import (
    AUDIT_FILE,
    CACHE_DIR,
    CANDIDATES_FILE,
    DEMAND_FILE,
    REPORTS_FILE,
    TEXTS_FILE,
)


def status() -> dict:
    q = demand.load_queue()
    cands = review_store.load_candidates()
    texts = review_store.load_texts()["texts"]
    reports = validate.load_json(REPORTS_FILE, {})
    by_status: dict[str, int] = {}
    for c in cands.values():
        s = c.get("_review_status", "pending")
        by_status[s] = by_status.get(s, 0) + 1
    by_level: dict[str, int] = {}
    for t in texts:
        lv = t.get("cefr_level", "?")
        by_level[lv] = by_level.get(lv, 0) + 1
    audio_done = 0
    if (CACHE_DIR / "progress.json").is_file():
        try:
            audio_done = len(json.loads((CACHE_DIR / "progress.json").read_text(encoding="utf-8"))["audio"]["done"])
        except (OSError, ValueError, KeyError):
            pass
    return {
        "demand_slots": q["total"] if q else 0,
        "candidates": len(cands),
        "candidate_status": by_status,
        "validation_pass": sum(1 for r in reports.values() if r.get("pass")),
        "texts_in_db": len(texts),
        "texts_by_level": by_level,
        "audio_clips_done": audio_done,
        "audit_records": sum(1 for _ in AUDIT_FILE.open(encoding="utf-8")) if AUDIT_FILE.is_file() else 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="v2.3 内容工厂 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--per-level", type=int, default=50)

    p_gen = sub.add_parser("gen")
    p_gen.add_argument("--limit", type=int, default=None)
    p_gen.add_argument("--level", default=None)
    p_gen.add_argument("--force", action="store_true")

    sub.add_parser("check")
    sub.add_parser("retry")
    p_ap = sub.add_parser("approve-all")
    p_ap.add_argument("--reviewer", default="ai-reviewer-v2.3")
    sub.add_parser("approve-one")

    p_audio = sub.add_parser("audio")
    p_audio.add_argument("--limit-texts", type=int, default=None)
    p_audio.add_argument("--level", default=None)
    p_audio.add_argument("--retry-failed", action="store_true")

    p_av = sub.add_parser("audio-variants")
    p_av.add_argument("--limit-texts", type=int, default=None)
    p_av.add_argument("--level", default=None)
    p_av.add_argument("--retry-failed", action="store_true")

    sub.add_parser("status")

    args = ap.parse_args()
    if args.cmd == "build":
        q = demand.build_and_save(args.per_level)
        print(f"需求队列 {q['total']} 槽位")
    elif args.cmd == "gen":
        print(json.dumps(generate.run(args.limit, args.level, args.force), ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        print(json.dumps(validate.run(), ensure_ascii=False, indent=2))
    elif args.cmd == "retry":
        print(json.dumps(validate.retry_rejected(), ensure_ascii=False))
    elif args.cmd == "approve-all":
        print(json.dumps(review_store.approve_all_validated(args.reviewer), ensure_ascii=False, indent=2))
    elif args.cmd == "approve-one":
        slot = input("slot id: ").strip()
        print(json.dumps(review_store.approve(slot, "cli-operator"), ensure_ascii=False))
    elif args.cmd == "audio":
        print(json.dumps(audio_batch.run(args.limit_texts, args.level, args.retry_failed), ensure_ascii=False, indent=2))
    elif args.cmd == "audio-variants":
        print(json.dumps(audio_batch.run_variants(args.limit_texts, args.level, args.retry_failed), ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(json.dumps(status(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
