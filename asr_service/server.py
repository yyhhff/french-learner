"""呀呀法语 — 本地语音识别（ASR）服务。

独立于主后端运行，避免把 faster-whisper 的重量级依赖塞进主 API。
- 接收浏览器 MediaRecorder 录制的音频（webm/ogg/wav/mp3）
- 用 faster-whisper（CPU、small 模型）转写为法语文本
- 模型懒加载：首次请求才下载/加载，服务启动秒开（模型已预下载则更快）

启动（用独立 venv）：
    cd tools/french-learner
    .venv-asr/Scripts/python.exe asr_service/server.py
默认端口 8011（原 8010 与 WorkBuddy multi-account 服务冲突，TASK-0056），仅监听 127.0.0.1。
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("yaya.asr")

app = FastAPI(title="呀呀法语 ASR", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 模型配置：默认 small（法语近音词识别显著优于 tiny），可用环境变量切换。
# 回退到旧的轻量模型只需设置 YAYA_ASR_MODEL=tiny。
MODEL_SIZE = os.environ.get("YAYA_ASR_MODEL", "small")
DEVICE = os.environ.get("YAYA_ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("YAYA_ASR_COMPUTE", "int8")

# 低置信门控阈值：与 faster-whisper 解码阈值保持一致，避免解码与门控判定漂移。
LOG_PROB_THRESHOLD = -1.0            # avg_logprob 低于此值视为低置信（faster-whisper 默认 log_prob_threshold）
NO_SPEECH_THRESHOLD = 0.6            # no_speech_prob 高于此值视为疑似静音/非语音
COMPRESSION_RATIO_THRESHOLD = 2.4    # compression_ratio 高于此值视为重复/幻觉

# 解码配置：beam_size=1 贪心解码虽快，但 tiny 模型容易把法语近音词锁死成英文
# （chaud→"show"、un thé→"onti"）。提到 5 让解码器有机会在多个候选里选更
# 贴合法语语境的那条；CPU+tiny+短句（<=15s）通常仍在 1-3 秒量级。
# 如需极致低延迟可用 YAYA_ASR_BEAM_SIZE=1 回退。
BEAM_SIZE = max(1, int(os.environ.get("YAYA_ASR_BEAM_SIZE", "5")))

# 场景热词偏置：用一段自然法语给解码器提示本对话高频词（咖啡馆/车站点单），
# 显著降低 tiny 模型把 chaud/the/cafe/gare 误识别成英文的概率。
# 可用 YAYA_ASR_INITIAL_PROMPT 覆盖；置为空字符串可关闭偏置。
INITIAL_PROMPT = os.environ.get(
    "YAYA_ASR_INITIAL_PROMPT",
    "Conversation en français dans un café ou à la gare. "
    "Je voudrais un café, un thé bien chaud, s'il vous plaît. "
    "Le train arrive en gare. Bonjour, vous désirez ?",
)

_model = None


def get_model():
    """懒加载模型：首次调用才初始化，避免拖慢服务启动。"""
    global _model
    if _model is None:
        logger.info("首次加载 Whisper 模型：%s / %s / %s", MODEL_SIZE, DEVICE, COMPUTE_TYPE)
        from faster_whisper import WhisperModel

        t0 = time.time()
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
        logger.info("模型加载完成，耗时 %.1fs", time.time() - t0)
    return _model


def compute_confidence(segments) -> dict:
    """从 faster-whisper 的 segments 计算转写置信度与低置信标记。

    对每个 segment 取 avg_logprob / no_speech_prob / compression_ratio 的均值
    （无 segment 即未识别出任何语音时，视为低置信：confidence=0.0）。

    confidence 采用 avg_logprob 的线性映射并裁剪到 [0, 1]：
        confidence = max(0.0, min(1.0, (avg_logprob + 1.0) / 1.0))
    即 avg_logprob >= 0.0 → 1.0（识别很确定），avg_logprob <= -1.0 → 0.0（很不确定）。

    low_confidence 采用三路信号的 OR 门控，任一命中即为低置信：
        avg_logprob <= -1.0         （对数概率过低；含等号，与 confidence=0 一致）
        no_speech_prob > 0.6        （疑似静音/非语音）
        compression_ratio > 2.4     （重复/幻觉）

    返回 dict 供 /transcribe 响应使用；不修改任何现有字段语义。
    """
    segs = list(segments)
    if not segs:
        return {
            "confidence": 0.0,
            "low_confidence": True,
            "avg_logprob": None,
            "no_speech_prob": None,
            "compression_ratio": None,
        }

    n = len(segs)
    avg_logprob = sum(s.avg_logprob for s in segs) / n
    no_speech_prob = sum(s.no_speech_prob for s in segs) / n
    compression_ratio = sum(s.compression_ratio for s in segs) / n

    confidence = max(0.0, min(1.0, (avg_logprob + 1.0) / 1.0))
    low_confidence = (
        avg_logprob <= LOG_PROB_THRESHOLD
        or no_speech_prob > NO_SPEECH_THRESHOLD
        or compression_ratio > COMPRESSION_RATIO_THRESHOLD
    )
    return {
        "confidence": round(confidence, 3),
        "low_confidence": bool(low_confidence),
        "avg_logprob": round(avg_logprob, 3),
        "no_speech_prob": round(no_speech_prob, 3),
        "compression_ratio": round(compression_ratio, 3),
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "model_size": MODEL_SIZE,
        "device": DEVICE,
        "beam_size": BEAM_SIZE,
        "initial_prompt_enabled": bool(INITIAL_PROMPT),
        "gate_thresholds": {
            "log_prob": LOG_PROB_THRESHOLD,
            "no_speech_prob": NO_SPEECH_THRESHOLD,
            "compression_ratio": COMPRESSION_RATIO_THRESHOLD,
        },
    }


def _extract_audio(body: bytes, content_type: str) -> tuple[bytes, str]:
    """从 multipart body 提取音频字节与文件名（仅用标准库）。"""
    m = re.search(r'boundary=(?:"([^"]+)"|([^;\s]+))', content_type)
    if not m:
        raise ValueError("缺少 multipart boundary")
    boundary = (m.group(1) or m.group(2)).encode("utf-8")
    for part in body.split(b"--" + boundary):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header_blob, _, payload = part.partition(b"\r\n\r\n")
        header = header_blob.decode("utf-8", "ignore")
        fn = re.search(r'filename="([^"]*)"', header)
        return payload.rstrip(b"\r\n"), (fn.group(1) if fn else "audio.webm")
    raise ValueError("multipart 中没有找到音频文件字段")


def decode_with_ffmpeg(src_path: str) -> np.ndarray:
    """用 ffmpeg 把任意音频转成 16kHz 单声道 PCM，读成 float32 ndarray。

    绕开 PyAV 19 与 faster-whisper 1.2.1 的 metadata_errors 不兼容问题：
    faster-whisper 接受 ndarray 输入，走这条路径时完全不调用 av.open。
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as wav_tmp:
        wav_path = wav_tmp.name
    try:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", src_path,
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
            wav_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        with wave.open(wav_path, "rb") as wf:
            raw = wf.readframes(wf.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
        return audio
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


# ---------------------------------------------------------------- 保守发音纠正
# 只处理「明确的英文误识别词」——它们是 tiny 模型在法语输入上最典型的幻觉，
# 且几乎不可能作为正常法语出现。正常法语句子（含合法词 chef）一律原样返回。
# 注意：show / chef 单独出现时可能是合法英文/法文，因此仅做近音词映射，
# 不改写句子结构；"chef onti" 这类固定误识别短语才整体还原为 "un thé"。
_PHRASE_RULES = [
    # 吞掉可能被一起误识别的前置冠词，避免出现 "un un thé"
    (re.compile(r"\b(?:un\s+)?chef\s+(?:onti|onty|onte)\b", re.IGNORECASE), "un thé"),
    (re.compile(r"\bun\s+(?:onti|onty|onte)\b", re.IGNORECASE), "un thé"),
]
_WORD_MAP = {
    "show": "chaud",   # /ʃoʊ/ ← chaud /ʃo/
    "sho": "chaud",
    "onti": "un thé",  # /ɔ̃ti/ ← un thé /œ̃ te/
    "onty": "un thé",
    "onte": "un thé",
}
_WORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _WORD_MAP) + r")\b", re.IGNORECASE
)


def _with_case(replacement: str, matched: str) -> str:
    """让替换词继承被替换片段的大小写风格（Show→Chaud、SHOW→CHAUD）。"""
    if matched.isupper():
        return replacement.upper()
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def correct_french_pronunciation(raw_text: str) -> dict:
    """保守地把英文误识别词还原成法语近音词。

    返回 ``{"text": 修正后, "raw_text": 原文, "corrected": 是否改动}``，
    便于上游/前端在确实发生修正时给出低调提示，而不是误伤正常法语。
    """
    raw = (raw_text or "").strip()
    text = raw
    for pattern, replacement in _PHRASE_RULES:
        text = pattern.sub(lambda m: _with_case(replacement, m.group(0)), text)
    text = _WORD_RE.sub(
        lambda m: _with_case(_WORD_MAP[m.group(1).lower()], m.group(1)), text
    )
    return {"text": text, "raw_text": raw, "corrected": text != raw}


@app.post("/transcribe")
async def transcribe(request: Request):
    """接收音频文件，返回法语转写文本（含保守发音修正标记）。"""
    try:
        content_type = request.headers.get("content-type", "")
        body = await request.body()
        data, filename = _extract_audio(body, content_type)
        if not data:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "空音频文件"},
            )
        lang_m = re.search(r'name="language"\r\n\r\n([^\r\n]+)', body.decode("latin-1", "ignore"))
        language = (lang_m.group(1).strip() if lang_m else "fr") or "fr"
        # 上下文热词（含法语重音，按 UTF-8 解码）：让解码器偏向用户上文出现过的词
        hints_m = re.search(r'name="hints"\r\n\r\n([^\r\n]*)', body.decode("utf-8", "ignore"))
        hotwords = (hints_m.group(1).strip()[:1000] if hints_m else "") or None
        # 前一句对话整句作为上下文：拼到 initial_prompt 末尾，让解码器按对话续写
        ctx_m = re.search(r'name="context"\r\n\r\n([^\r\n]*)', body.decode("utf-8", "ignore"))
        context = (ctx_m.group(1).strip()[:200] if ctx_m else "")
        initial_prompt = " ".join(x for x in (INITIAL_PROMPT, context) if x) or None

        # faster-whisper 通过 PyAV 解码；写临时文件更稳
        suffix = Path(filename).suffix or ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            model = get_model()
            t0 = time.time()
            audio_array = decode_with_ffmpeg(tmp_path)
            segments, info = model.transcribe(
                audio_array,
                language=language,
                beam_size=BEAM_SIZE,     # 5 路束搜索，兼顾准确率与 CPU 延迟
                vad_filter=True,         # 过滤静音，减少幻觉
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,           # 场景提示 + 前一句对话上下文
                hotwords=hotwords,                        # 本次对话上下文词偏置（可覆盖近音误识）
                temperature=0,                            # 贪心解码，结果确定可复现
                no_speech_threshold=NO_SPEECH_THRESHOLD,
                compression_ratio_threshold=COMPRESSION_RATIO_THRESHOLD,
            )
            # segments 是惰性迭代器，先物化一次，再用同一批结果算文本与置信度
            segs = list(segments)
            raw_text = "".join(seg.text for seg in segs).strip()
            conf = compute_confidence(segs)
            result = correct_french_pronunciation(raw_text)
            text = result["text"]
            elapsed = time.time() - t0
            logger.info(
                "转写完成：lang=%s %.1fs corrected=%s conf=%.3f low=%s text=%r raw=%r",
                info.language,
                elapsed,
                result["corrected"],
                conf["confidence"],
                conf["low_confidence"],
                text,
                raw_text,
            )
            return {
                "ok": True,
                "text": text,                     # 修正后文本（供主流程使用）
                "raw_text": result["raw_text"],   # 原始转写（供前端提示/排查）
                "corrected": result["corrected"], # 是否发生保守修正
                "language": info.language,
                "language_probability": round(info.language_probability, 3),
                "elapsed": round(elapsed, 2),
                "confidence": conf["confidence"],       # 0-1 转写置信度
                "low_confidence": conf["low_confidence"],  # 低置信标记（供前端触发重录）
            }
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:  # noqa: BLE001 - 服务边界兜底
        logger.exception("转写失败")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"转写失败：{exc}"},
        )


# ---------------------------------------------------------------- 本地 TTS 合成
# 用 edge-tts（微软神经网络语音）生成高质量法语朗读，避免浏览器 TTS 把
# le/la/les 等功能词读成单独字母。edge-tts 需联网（连微软），失败时前端回退浏览器 TTS。
TTS_VOICE = os.environ.get("YAYA_TTS_VOICE", "fr-FR-DeniseNeural")
_tts_cache: dict[tuple[str, str], bytes] = {}


@app.get("/tts")
async def tts(text: str = ""):
    """把法语文本合成为 mp3 音频流。相同文本+语音缓存，减少重复在线请求。"""
    text = (text or "").strip()
    if not text:
        return JSONResponse(status_code=400, content={"ok": False, "error": "空文本"})
    if len(text) > 500:
        return JSONResponse(status_code=400, content={"ok": False, "error": "文本过长"})
    key = (text, TTS_VOICE)
    audio = _tts_cache.get(key)
    if audio is None:
        try:
            import edge_tts

            t0 = time.time()
            communicate = edge_tts.Communicate(text, TTS_VOICE)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            audio = buf.getvalue()
            if not audio:
                raise RuntimeError("edge-tts 返回空音频")
            _tts_cache[key] = audio
            logger.info("TTS 完成：%.1fs %d bytes text=%r", time.time() - t0, len(audio), text[:40])
        except Exception as exc:  # noqa: BLE001
            logger.exception("TTS 合成失败")
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": f"TTS 合成失败：{exc}"},
            )
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/tts/status")
async def tts_status():
    """探测 TTS 能力（voice + 缓存条目数）。"""
    return {"ok": True, "voice": TTS_VOICE, "cached": len(_tts_cache)}


if __name__ == "__main__":
    import uvicorn

    # TASK-0056：默认端口 8010→8011 —— 8010 与 WorkBuddy multi-account 服务冲突
    # （其客户端会轮询 /api/accounts/list，且占用端口导致 ASR 无法启动）
    port = int(os.environ.get("YAYA_ASR_PORT", "8011"))
    uvicorn.run(app, host="127.0.0.1", port=port)
