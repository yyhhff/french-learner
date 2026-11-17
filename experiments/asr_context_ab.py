"""A/B 实验：ASR 上下文喂前一句 vs 前两句 vs 当前词袋，哪个对抗真人近音误识别更好。

变量设计（控制单一变量）：
- 音频：用 TTS 合成目标句，再加噪模拟"临界可错"的声学条件
  （清晰音频本来就能识别对，看不出上下文差异，必须制造模糊）。
- 上下文策略（5 组）：
    base   = 现状：固定场景 initial_prompt + 词袋 hotwords
    none   = 无 initial_prompt、无 hotwords（裸听写，对照组）
    hot1   = 前一句整句当 initial_prompt（不强调语法，原样喂）
    hot2   = 前两句整句当 initial_prompt
    hword1 = 前一句抽词当 hotwords（现状词袋思路，只喂一句）
    hword2 = 前两句抽词当 hotwords（词袋思路，喂两句）
- 目标：把 "Je veux froid" 这类被误识别成 "Je veux foudre / Je vous fous froid" 的，
  看哪组能拉回正确词。

直接加载本地 small 模型跑，不经过 HTTP，方便精确控制变量。
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import subprocess
import tempfile
import wave

import numpy as np

# 复用 ASR 服务的固定提示与模型配置
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from asr_service.server import (  # noqa: E402
    INITIAL_PROMPT, BEAM_SIZE, DEVICE, COMPUTE_TYPE, MODEL_SIZE,
)

VOICE = "fr-FR-DeniseNeural"

# 前一句/前两句：完全照真实对话，含口语、不合语法也原样保留，不纠错。
CONVERSATIONS = [
    {
        "name": "点冷饮-前一句问冷热的直接上文",
        "prev1": "Très bien ! Vous le voulez chaud ou froid ?",
        "prev2": "Vous désirez ?",
        "target": "Je veux froid",          # 用户想说（会被误识别成 foudre）
        "keywords": ["froid", "veux"],
    },
    {
        "name": "点咖啡-上文出现 cafe/the",
        "prev1": "Un café, un thé, vous voulez quoi ?",
        "prev2": "Bonjour ! Bienvenue !",
        "target": "Je veux un café",
        "keywords": ["café", "veux"],
    },
    {
        "name": "车站-上文出现 train/gare",
        "prev1": "Le train pour Paris part de la gare.",
        "prev2": "Où allez-vous ?",
        "target": "Je veux le train",
        "keywords": ["train", "veux"],
    },
]

# 加噪强度：snr 越小越难（临界可错）
NOISE_SNRS = [None, 18, 12]  # None=干净原声


def synth_fr(text: str) -> np.ndarray:
    """edge-tts 合成法语 → ffmpeg 16k mono → float32 ndarray。"""
    import edge_tts
    mp3 = asyncio.run(_tts(text))
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3)
        p = f.name
    wavp = p + ".wav"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", p,
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wavp],
            check=True, capture_output=True,
        )
        with wave.open(wavp, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
    finally:
        for x in (p, wavp):
            try:
                os.unlink(x)
            except OSError:
                pass


async def _tts(text: str) -> bytes:
    import edge_tts
    comm = edge_tts.Communicate(text, VOICE)
    buf = io.BytesIO()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    return buf.getvalue()


def add_noise(audio: np.ndarray, snr_db: float, seed: int = 42) -> np.ndarray:
    """按信噪比叠加白噪声。"""
    rng = np.random.default_rng(seed)
    sig_pow = float(np.mean(audio ** 2)) or 1e-9
    noise_pow = sig_pow / (10 ** (snr_db / 10))
    noise = rng.normal(0, np.sqrt(noise_pow), size=audio.shape).astype("float32")
    return np.clip(audio + noise, -1.0, 1.0)


def words(text: str) -> str:
    """从句子抽字母词做 hotwords（现状词袋思路），小写去重。"""
    seen, out = set(), []
    for w in re.split(r"[^\wÀ-ÿ]+", text, flags=re.UNICODE):
        w = w.lower().strip()
        if len(w) > 1 and w not in seen:
            seen.add(w)
            out.append(w)
    return " ".join(out)


def norm(s: str) -> str:
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def kwhit(text: str, keywords: list[str]) -> int:
    t = norm(text)
    return sum(1 for k in keywords if norm(k) in t)


def main():
    from faster_whisper import WhisperModel
    print(f"加载模型 {MODEL_SIZE}/{DEVICE}/{COMPUTE_TYPE} ...", flush=True)
    model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)

    strategies = ["base", "none", "hot1", "hot2", "hword1", "hword2"]

    for case in CONVERSATIONS:
        print("\n" + "=" * 78)
        print(f"场景：{case['name']}")
        print(f"目标句：{case['target']}   期望关键词：{case['keywords']}")
        print(f"前一句：{case['prev1']}")
        print(f"前两句：{case['prev2']}  +  {case['prev1']}")
        print("=" * 78)
        clean = synth_fr(case["target"])
        ctx1 = case["prev1"]
        ctx2 = case["prev2"] + " " + case["prev1"]

        for snr in NOISE_SNRS:
            audio = clean if snr is None else add_noise(clean, snr)
            label = "干净原声" if snr is None else f"SNR={snr}dB"
            print(f"\n-- {label} --")
            for strat in strategies:
                ip = None
                hw = None
                if strat == "base":
                    ip = INITIAL_PROMPT
                elif strat == "hot1":
                    ip = ctx1
                elif strat == "hot2":
                    ip = ctx2
                elif strat == "hword1":
                    ip = INITIAL_PROMPT
                    hw = words(ctx1)
                elif strat == "hword2":
                    ip = INITIAL_PROMPT
                    hw = words(ctx2)
                # none: 全部 None
                segs, _ = model.transcribe(
                    audio,
                    language="fr",
                    beam_size=BEAM_SIZE,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    initial_prompt=ip,
                    hotwords=hw,
                    temperature=0,
                    no_speech_threshold=0.6,
                    compression_ratio_threshold=2.4,
                )
                segs = list(segs)
                text = "".join(s.text for s in segs).strip()
                avg_lp = (
                    sum(s.avg_logprob for s in segs) / len(segs) if segs else float("-inf")
                )
                hit = kwhit(text, case["keywords"])
                print(f"  {strat:7s} hit={hit}/{len(case['keywords'])} "
                      f"lp={avg_lp:6.2f}  {text!r}")


if __name__ == "__main__":
    main()
