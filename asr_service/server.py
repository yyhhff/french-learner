"""呀呀法语 — 本地语音识别（ASR）服务。

独立于主后端运行，避免把 faster-whisper 的重量级依赖塞进主 API。
- 接收浏览器 MediaRecorder 录制的音频（webm/ogg/wav/mp3）
- 用 faster-whisper（CPU、tiny 模型）转写为法语文本
- 模型懒加载：首次请求才下载/加载，服务启动秒开

启动（用独立 venv）：
    cd tools/french-learner
    .venv-asr/Scripts/python.exe asr_service/server.py
默认端口 8010，仅监听 127.0.0.1。
"""
from __future__ import annotations

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
from fastapi.responses import JSONResponse

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

# 模型配置：tiny 最快（CPU 上约 1-2 秒），可用环境变量切换
MODEL_SIZE = os.environ.get("YAYA_ASR_MODEL", "tiny")
DEVICE = os.environ.get("YAYA_ASR_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("YAYA_ASR_COMPUTE", "int8")

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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "model_size": MODEL_SIZE,
        "device": DEVICE,
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


@app.post("/transcribe")
async def transcribe(request: Request):
    """接收音频文件，返回法语转写文本。"""
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
                beam_size=1,          # 贪心解码，最快
                vad_filter=True,      # 过滤静音，减少幻觉
                condition_on_previous_text=False,
            )
            text = "".join(seg.text for seg in segments).strip()
            elapsed = time.time() - t0
            logger.info("转写完成：lang=%s %.1fs text=%r", info.language, elapsed, text)
            return {
                "ok": True,
                "text": text,
                "language": info.language,
                "language_probability": round(info.language_probability, 3),
                "elapsed": round(elapsed, 2),
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8010)
