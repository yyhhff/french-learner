"""A/B 实验 v3：临界可错区里，前一句 vs 前两句谁更能救回近音误识别。

模拟真人中文口音：把【正确词】与【近音错词】的发音按比例混合。
- 0% 错词 = 完全正确发音，都能识别
- 100% 错词 = 完整错词发音（v2 已验证：上下文全军覆没）
- 中间地带 = 口音模糊区，才是上下文偏置真正能发力的地方

在临界区对比：
    none / base / ctx1 / ctx2 / hword1 / hword2 / ctx1+hw / ctx2+hw
回答："喂前一句还是前两句更好"。
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from asr_service.server import (  # noqa: E402
    INITIAL_PROMPT, BEAM_SIZE, DEVICE, COMPUTE_TYPE, MODEL_SIZE,
)

VOICE = "fr-FR-DeniseNeural"
SR = 16000


async def _tts_stream(text: str):
    import edge_tts as et
    comm = et.Communicate(text, VOICE, boundary="WordBoundary")
    buf = io.BytesIO(); bounds = []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            buf.write(ch["data"])
        elif ch["type"] == "WordBoundary":
            bounds.append((ch["text"], int(ch["offset"]) / 1e7, int(ch["duration"]) / 1e7))
    return buf.getvalue(), bounds


def synth(text: str):
    mp3, bounds = asyncio.run(_tts_stream(text))
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3); p = f.name
    wavp = p + ".wav"
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", p,
                        "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", wavp],
                       check=True, capture_output=True)
        with wave.open(wavp, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0, bounds
    finally:
        for x in (p, wavp):
            try: os.unlink(x)
            except OSError: pass


def segment_of(word: str, sentence: str):
    """返回某词在其原句中的音频段。"""
    audio, bounds = synth(sentence)
    for w, start, dur in bounds:
        if w.strip().lower().strip(".,?!'’") == word.strip().lower():
            return audio[int(start * SR): int((start + dur) * SR)]
    return None


def blend_in_sentence(sentence: str, target_word: str, wrong_audio: np.ndarray, ratio: float):
    """把句子里 target_word 段换成 (1-ratio)*正确 + ratio*错词 的混合。"""
    audio, bounds = synth(sentence)
    for w, start, dur in bounds:
        if w.strip().lower().strip(".,?!'’") == target_word.strip().lower():
            s = int(start * SR); e = int((start + dur) * SR)
            correct = audio[s:e]
            n = min(len(correct), len(wrong_audio))
            mixed = (1 - ratio) * correct[:n] + ratio * wrong_audio[:n]
            out = audio.copy()
            out[s:s + n] = mixed
            # 长度差用正确词剩余部分补齐，保持时长稳定
            if len(correct) > n:
                out[s + n:e] = correct[n:]
            return out
    return None


def words(text: str) -> str:
    seen, out = set(), []
    for w in re.split(r"[^\wÀ-ÿ]+", text, flags=re.UNICODE):
        w = w.lower().strip()
        if len(w) > 1 and w not in seen:
            seen.add(w); out.append(w)
    return " ".join(out)


def norm(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


CASES = [
    {
        "name": "froid→foudre（用户实际遇到）",
        "sentence": "Je veux froid", "target_word": "froid",
        "wrong_word": "foudre", "target": "froid", "wrong_full": "foudre",
        "prev1": "Très bien ! Vous le voulez chaud ou froid ?",
        "prev2": "Bonjour ! Vous désirez ?",
    },
    {
        "name": "café→thé",
        "sentence": "Je veux un café", "target_word": "café",
        "wrong_word": "thé", "target": "café", "wrong_full": "thé",
        "prev1": "Un café ou un thé, vous voulez quoi ?",
        "prev2": "Bonjour ! Bienvenue !",
    },
]

RATIOS = [0.0, 0.25, 0.5, 0.75, 1.0]


def main():
    from faster_whisper import WhisperModel
    print(f"加载模型 {MODEL_SIZE}/{DEVICE}/{COMPUTE_TYPE} ...", flush=True)
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    strategies = [
        ("none", None, None),
        ("base", INITIAL_PROMPT, None),
        ("ctx1", lambda c: c["prev1"], None),
        ("ctx2", lambda c: c["prev2"] + " " + c["prev1"], None),
        ("hword1", INITIAL_PROMPT, lambda c: words(c["prev1"])),
        ("hword2", INITIAL_PROMPT, lambda c: words(c["prev2"] + " " + c["prev1"])),
        ("ctx1+hw", lambda c: c["prev1"], lambda c: words(c["prev1"])),
        ("ctx2+hw", lambda c: c["prev2"] + " " + c["prev1"], lambda c: words(c["prev2"] + " " + c["prev1"])),
    ]

    for case in CASES:
        print("\n" + "=" * 84)
        print(f"场景：{case['name']}  句子={case['sentence']}")
        print(f"前一句：{case['prev1']}")
        print(f"前两句：{case['prev2']}  +  {case['prev1']}")
        wrong_audio, _ = synth(case["wrong_word"])
        target_norm = norm(case["target"])
        wrong_norm = norm(case["wrong_full"])

        # 表头
        header = f"{'ratio':>6} | " + " | ".join(f"{n:>9}" for n, _, _ in strategies)
        print(header)
        print("-" * len(header))
        tally = {n: 0 for n, _, _ in strategies}
        crit_rows = []

        for ratio in RATIOS:
            audio = blend_in_sentence(case["sentence"], case["target_word"], wrong_audio, ratio)
            if audio is None:
                print(f"{ratio:>6} | !!未定位目标词"); continue
            cells = []
            hits = {}
            for name, ip_f, hw_f in strategies:
                ip = ip_f(case) if callable(ip_f) else ip_f
                hw = hw_f(case) if callable(hw_f) else hw_f
                segs, _ = model.transcribe(
                    audio, language="fr", beam_size=BEAM_SIZE, vad_filter=True,
                    condition_on_previous_text=False, initial_prompt=ip, hotwords=hw,
                    temperature=0, no_speech_threshold=0.6, compression_ratio_threshold=2.4,
                )
                segs = list(segs)
                text = "".join(s.text for s in segs).strip()
                hit = target_norm in norm(text)
                hits[name] = hit
                tally[name] += 1 if hit else 0
                mark = "✓" if hit else ("≈" if wrong_norm in norm(text) else "✗")
                cells.append(f"{mark:>9}")
            print(f"{ratio:>6} | " + " | ".join(cells))
            crit_rows.append((ratio, hits))

        print("-" * len(header))
        print("命中合计：" + " | ".join(f"{tally[n]:>9}" for n, _, _ in strategies) + f"  / {len(RATIOS)}")

        # 临界区（base 或部分策略开始出错的比例）展开文本，便于人工核对
        print("\n[临界区文本明细]")
        for ratio in (0.25, 0.5, 0.75):
            audio = blend_in_sentence(case["sentence"], case["target_word"], wrong_audio, ratio)
            if audio is None: continue
            print(f"  -- ratio={ratio} --")
            for name, ip_f, hw_f in strategies:
                if name in ("none", "base", "ctx1", "ctx2"):
                    ip = ip_f(case) if callable(ip_f) else ip_f
                    hw = hw_f(case) if callable(hw_f) else hw_f
                    segs, _ = model.transcribe(
                        audio, language="fr", beam_size=BEAM_SIZE, vad_filter=True,
                        condition_on_previous_text=False, initial_prompt=ip, hotwords=hw,
                        temperature=0, no_speech_threshold=0.6, compression_ratio_threshold=2.4,
                    )
                    segs = list(segs)
                    text = "".join(s.text for s in segs).strip()
                    print(f"     {name:9s} {text!r}")


if __name__ == "__main__":
    main()
