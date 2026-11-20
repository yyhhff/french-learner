"""音频批量预生成：从 texts.json 读已入库语料，逐句走 8011 edge-tts 落盘。

- 断点续跑：audio/<text_id>/<seq>.mp3 已存在且非空则跳过；
- 多音色：由 8011 服务的 YAYA_TTS_VOICE 决定（本模块不重复配置）；
- 失败不中断：网络失败记录到进度文件，继续下一句，可重跑补齐；
- 落盘路径供 router 的 GET /api/content/audio/{text_id}/{seq} 读取。

TASK-0071 v3.1 新增 run_variants()：变体音频批量（v1 男声原文 / v2 缩略形+真实语速），
进度独立存 progress.json 的 audio_variants 键，与标准音频互不影响。
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from content_pipeline.paths import AUDIO_DIR, PROGRESS_FILE, TEXTS_FILE, ensure_dirs

logger = logging.getLogger("yaya.content.audio")

ASR_URL = os.environ.get("YAYA_ASR_URL", "http://127.0.0.1:8011").rstrip("/")
TIMEOUT = int(os.environ.get("YAYA_TTS_BATCH_TIMEOUT", "40"))


def load_progress() -> dict:
    if not PROGRESS_FILE.is_file():
        return {"audio": {"done": [], "failed": []},
                "audio_variants": {"done": [], "failed": []}}
    try:
        d = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        d.setdefault("audio", {"done": [], "failed": []})
        d.setdefault("audio_variants", {"done": [], "failed": []})
        return d
    except (OSError, ValueError):
        return {"audio": {"done": [], "failed": []},
                "audio_variants": {"done": [], "failed": []}}


def save_progress(d: dict) -> None:
    ensure_dirs()
    PROGRESS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def synth(text: str, voice: str = "", rate: str = "") -> bytes:
    """合成一条音频。voice/rate 传空 = 服务端默认（Denise 原速）；rate 为 edge-tts 格式（如 +10%）。"""
    qs = urllib.parse.urlencode({"text": text, "voice": voice, "rate": rate})
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


# ---------------------------------------------------------------- 变体批量（TASK-0071 v3.1 听力强化）

VARIANT_V1_VOICE = os.environ.get("YAYA_TTS_VARIANT_VOICE", "fr-FR-HenriNeural")  # 男声变体
VARIANT_V2_RATE = os.environ.get("YAYA_TTS_VARIANT_RATE", "+10%")                 # 真实语速档


def _load_reduce_sentence():
    """按文件路径加载 backend/reductions.py（backend 非包，跨目录复用缩略形规则）。"""
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "backend" / "reductions.py"
    spec = importlib.util.spec_from_file_location("yaya_reductions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.reduce_sentence


def run_variants(limit_texts: int | None = None, only_level: str | None = None,
                 retry_failed: bool = False) -> dict:
    """变体音频批量：每句两版——v1 男声原文（多音色）/ v2 缩略形+真实语速。

    落盘 audio/<text_id>/<seq>_v1.mp3 / _v2.mp3；断点续跑进度在 progress.json
    的 audio_variants 键，与标准音频互不影响。
    注意：8011 须为带 voice/rate 参数的新版服务（TASK-0071 后重启），
    旧版会忽略参数并得到与标准版相同的音频（无害，升级后可重跑补齐）。
    """
    if not TEXTS_FILE.is_file():
        raise SystemExit("texts.json 不存在，请先审校入库")
    data = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
    progress = load_progress()
    done = set(progress["audio_variants"]["done"])
    failed = set(progress["audio_variants"]["failed"])
    reduce_sentence = _load_reduce_sentence()
    stats = {"texts": 0, "clips_new": 0, "clips_skipped": 0, "clips_failed": 0}

    def _persist() -> None:
        progress["audio_variants"] = {"done": sorted(done), "failed": sorted(failed)}
        save_progress(progress)

    for item in data.get("texts", []):
        if only_level and item.get("cefr_level") != only_level:
            continue
        if limit_texts is not None and stats["texts"] >= limit_texts:
            break
        tid = item.get("id")
        if not tid:
            continue
        stats["texts"] += 1
        for line in item.get("lines") or []:
            seq = line.get("seq")
            fr = line.get("fr")
            if not isinstance(seq, int) or not fr:
                continue
            for tag, text, voice, rate in (
                ("v1", fr, VARIANT_V1_VOICE, ""),
                ("v2", reduce_sentence(fr), "", VARIANT_V2_RATE),
            ):
                out = AUDIO_DIR / str(tid) / f"{seq}_{tag}.mp3"
                key = f"{tid}/{seq}/{tag}"
                if out.is_file() and out.stat().st_size > 0:
                    failed.discard(key)  # 后来补齐了
                    stats["clips_skipped"] += 1
                    continue
                if key in failed and not retry_failed:
                    stats["clips_skipped"] += 1
                    continue
                try:
                    audio = synth(text, voice=voice, rate=rate)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(audio)
                    done.add(key)
                    failed.discard(key)
                    stats["clips_new"] += 1
                    _persist()
                except Exception as exc:  # noqa: BLE001 — 网络/服务失败记录后续跑
                    failed.add(key)
                    stats["clips_failed"] += 1
                    logger.warning("变体音频合成失败 %s：%s", key, exc)
                    _persist()
                time.sleep(0.05)  # 轻微节流，避免打满 8011

    _persist()
    return stats


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="批量预生成语料音频（8011 edge-tts，断点续跑）")
    ap.add_argument("--limit-texts", type=int, default=None)
    ap.add_argument("--level", default=None)
    ap.add_argument("--retry-failed", action="store_true")
    ap.add_argument("--variants", action="store_true", help="生成变体音频（v1 男声 / v2 缩略形真实语速）")
    args = ap.parse_args()
    runner = run_variants if args.variants else run
    print(json.dumps(runner(args.limit_texts, args.level, args.retry_failed), ensure_ascii=False, indent=2))
