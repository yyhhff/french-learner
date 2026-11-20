"""音频批量预生成：从 texts.json 读已入库语料，逐句走 8011 edge-tts 落盘。

- 断点续跑：audio/<text_id>/<seq>.mp3 已存在且非空则跳过；
- 多音色：由 8011 服务的 YAYA_TTS_VOICE 决定（本模块不重复配置）；
- 失败不中断：网络失败记录到进度文件，继续下一句，可重跑补齐；
- 落盘路径供 router 的 GET /api/content/audio/{text_id}/{seq} 读取。
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from content_pipeline.paths import AUDIO_DIR, PROGRESS_FILE, TEXTS_FILE, ensure_dirs

logger = logging.getLogger("yaya.content.audio")

ASR_URL = os.environ.get("YAYA_ASR_URL", "http://127.0.0.1:8011").rstrip("/")
TIMEOUT = int(os.environ.get("YAYA_TTS_BATCH_TIMEOUT", "40"))


def load_progress() -> dict:
    if not PROGRESS_FILE.is_file():
        return {"audio": {"done": [], "failed": []}}
    try:
        d = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        d.setdefault("audio", {"done": [], "failed": []})
        return d
    except (OSError, ValueError):
        return {"audio": {"done": [], "failed": []}}


def save_progress(d: dict) -> None:
    ensure_dirs()
    PROGRESS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def synth(text: str) -> bytes:
    qs = urllib.parse.urlencode({"text": text})
    with urllib.request.urlopen(ASR_URL + "/tts?" + qs, timeout=TIMEOUT) as resp:
        audio = resp.read()
    if not audio:
        raise RuntimeError("empty audio")
    return audio


def run(limit_texts: int | None = None, only_level: str | None = None, retry_failed: bool = False) -> dict:
    if not TEXTS_FILE.is_file():
        raise SystemExit("texts.json 不存在，请先审校入库")
    data = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
    progress = load_progress()
    done = set(progress["audio"]["done"])
    failed_old = set(progress["audio"]["failed"])
    stats = {"texts": 0, "clips_new": 0, "clips_skipped": 0, "clips_failed": 0}

    for item in data.get("texts", []):
        if only_level and item.get("cefr_level") != only_level:
            continue
        if limit_texts is not None and stats["texts"] >= limit_texts:
            break
        tid = item.get("id")
        if not tid:
            continue
        stats["texts"] += 1
        lines = item.get("lines") or []
        for line in lines:
            seq = line.get("seq")
            fr = line.get("fr")
            if not isinstance(seq, int) or not fr:
                continue
            out = AUDIO_DIR / str(tid) / f"{seq}.mp3"
            key = f"{tid}/{seq}"
            if out.is_file() and out.stat().st_size > 0:
                if key in failed_old:
                    failed_old.discard(key)  # 后来补齐了
                stats["clips_skipped"] += 1
                continue
            if key in failed_old and not retry_failed:
                stats["clips_skipped"] += 1
                continue
            try:
                audio = synth(fr)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(audio)
                done.add(key)
                failed_old.discard(key)
                stats["clips_new"] += 1
                save_progress({"audio": {"done": sorted(done), "failed": sorted(failed_old)}})
            except Exception as exc:  # noqa: BLE001 — 网络/服务失败记录后续跑
                failed_old.add(key)
                stats["clips_failed"] += 1
                logger.warning("音频合成失败 %s：%s", key, exc)
                save_progress({"audio": {"done": sorted(done), "failed": sorted(failed_old)}})
            time.sleep(0.05)  # 轻微节流，避免打满 8011

    save_progress({"audio": {"done": sorted(done), "failed": sorted(failed_old)}})
    return stats


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="批量预生成语料音频（8011 edge-tts，断点续跑）")
    ap.add_argument("--limit-texts", type=int, default=None)
    ap.add_argument("--level", default=None)
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(args.limit_texts, args.level, args.retry_failed), ensure_ascii=False, indent=2))
