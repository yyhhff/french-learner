"""A/B 实验 v2：真实复现"近音误识别"条件下的上下文效果。

做法：TTS 合成目标句并拿到词边界，把目标词那段音频替换为【近音错误词】的发音
（如 froid→foudre），制造"声学证据指向错词、只有上下文能救"的两难。
再对比各上下文策略能否把结果拉回正确词。

策略：
    none   = 裸听写
    base   = 现状：固定场景提示 + 全对话词袋
    ctx1   = 前一句整句当 initial_prompt（原样喂，不强调语法）
    ctx2   = 前两句整句当 initial_prompt
    hword1 = 当前词袋思路，只抽前一句
    hword2 = 当前词袋思路，抽前两句

这样能回答用户的问题："前一句 vs 前两句，哪个对抗误识别更好，是否该强调上下文"。
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
    buf = io.BytesIO()
    bounds = []
    async for ch in comm.stream():
        if ch["type"] == "audio":
            buf.write(ch["data"])
        elif ch["type"] == "WordBoundary":
            bounds.append((ch["text"], int(ch["offset"]) / 1e7, int(ch["duration"]) / 1e7))
    return buf.getvalue(), bounds


def synth(text: str):
    """返回 (float32 音频, 词边界[(词, 起秒, 时长秒)])。"""
    import edge_tts  # noqa: F401
    mp3, bounds = asyncio.run(_tts_stream(text))
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3); p = f.name
    wavp = p + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", p,
             "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", wavp],
            check=True, capture_output=True,
        )
        with wave.open(wavp, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0, bounds
    finally:
        for x in (p, wavp):
            try: os.unlink(x)
            except OSError: pass


def replace_word(sentence: str, target_word: str, replacement_audio: np.ndarray) -> np.ndarray | None:
    """把句子里 target_word 对应的音频段替换为 replacement_audio。"""
    audio, bounds = synth(sentence)
    for w, start, dur in bounds:
        if w.strip().lower().strip(".,?!") == target_word.strip().lower():
            s = int(start * SR)
            e = int((start + dur) * SR)
            out = audio.copy()
            # 用错误词发音填充：短了就补静音，长了就截断
            rep = replacement_audio[: max(0, e - s)]
            out[s:e] = 0.0
            out[s:s + len(rep)] = rep
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
        "sentence": "Je veux froid",
        "wrong_word": "foudre",
        "target": "froid",
        "prev1": "Très bien ! Vous le voulez chaud ou froid ?",
        "prev2": "Bonjour ! Vous désirez ?",
    },
    {
        "name": "café→café音近混淆（thé）",
        "sentence": "Je veux un café",
        "wrong_word": "thé",
        "target": "café",
        "prev1": "Un café ou un thé, vous voulez quoi ?",
        "prev2": "Bonjour ! Bienvenue !",
    },
]


def run_case(model, case):
    print("\n" + "=" * 80)
    print(f"场景：{case['name']}")
    print(f"句子：{case['sentence']}   目标词：{case['target']}   注入错词：{case['wrong_word']}")
    print(f"前一句：{case['prev1']}")
    print(f"前两句：{case['prev2']}  +  {case['prev1']}")
    print("=" * 80)

    wrong_audio, _ = synth(case["wrong_word"])
    audio = replace_word(case["sentence"], case["target"].split()[-1], wrong_audio)
    if audio is None:
        print("  !! 未定位到目标词边界，跳过"); return
    # 去掉注入错词自身残留静音影响，做轻度归一化
    ctx1 = case["prev1"]
    ctx2 = case["prev2"] + " " + case["prev1"]
    strategies = [
        ("none", None, None),
        ("base", INITIAL_PROMPT, words(ctx1 + " " + ctx2)),
        ("ctx1", ctx1, None),
        ("ctx2", ctx2, None),
        ("hword1", INITIAL_PROMPT, words(ctx1)),
        ("hword2", INITIAL_PROMPT, words(ctx2)),
        ("ctx1+hw", ctx1, words(ctx1)),
        ("ctx2+hw", ctx2, words(ctx2)),
    ]
    target_norm = norm(case["target"])
    for name, ip, hw in strategies:
        segs, _ = model.transcribe(
            audio, language="fr", beam_size=BEAM_SIZE, vad_filter=True,
            condition_on_previous_text=False, initial_prompt=ip, hotwords=hw,
            temperature=0, no_speech_threshold=0.6, compression_ratio_threshold=2.4,
        )
        segs = list(segs)
        text = "".join(s.text for s in segs).strip()
        avg_lp = sum(s.avg_logprob for s in segs) / len(segs) if segs else float("-inf")
        hit = "✓" if target_norm in norm(text) else "✗"
        print(f"  {name:9s} {hit} lp={avg_lp:6.2f}  {text!r}")


def main():
    from faster_whisper import WhisperModel
    print(f"加载模型 {MODEL_SIZE}/{DEVICE}/{COMPUTE_TYPE} ...", flush=True)
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    for case in CASES:
        run_case(model, case)


if __name__ == "__main__":
    main()
