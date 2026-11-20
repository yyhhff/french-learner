"""v3.2 发音教练路由（TASK-0067）：选句 + 跟读打分。

新端点一律写独立 router（MASTER_PLAN §4 文件边界），不改公共 asr.py。
"""
import json
import re
import urllib.error
import urllib.request

from fastapi import APIRouter, Request

import db
import pron_coach
from common import ApiError, _parse_multipart, ok

router = APIRouter()

ASR_SERVICE_URL = __import__("os").environ.get("YAYA_ASR_URL", "http://127.0.0.1:8011").rstrip("/")


@router.get("/api/pron-coach/sentences")
async def proncoach_sentences(
    level: str | None = None,
    focus: str | None = None,
    exclude: str | None = None,
):
    """按等级/发音难点选一句；exclude 为逗号分隔的已练 id。

    词卡池从 db.list_cards() 运行时注入；失败降级为空列表不影响选句。
    """
    exclude_ids = [x.strip() for x in (exclude or "").split(",") if x.strip()]
    try:
        cards = db.list_cards()
    except Exception as exc:  # noqa: BLE001 - 词卡池是补充池，失败不阻断
        cards = []
    sentence = pron_coach.select_sentence(
        level=level, focus_tag=focus, exclude_ids=exclude_ids, cards=cards
    )
    return ok({
        "sentence": sentence,
        "tags_meta": {
            "y_vs_u": "/y/ 与 /u/（tu/tout）", "nasal": "鼻化元音（temps/vin）",
            "r": "小舌音 r（rue/très）", "elision": "省音（j'aime/l'école）",
            "liaison": "连诵（les amis）",
        },
    })


@router.get("/api/pron-coach/focus-tags")
async def proncoach_focus_tags():
    """返回难点标签元数据（前端筛选器用）。"""
    return ok({
        "tags": [
            {"key": "y_vs_u", "label": "u / ou 辨析"},
            {"key": "nasal", "label": "鼻化元音"},
            {"key": "r", "label": "小舌音 r"},
            {"key": "elision", "label": "省音"},
            {"key": "liaison", "label": "连诵"},
        ]
    })


@router.post("/api/pron-coach/evaluate")
async def proncoach_evaluate(request: Request):
    """跟读打分：音频 → ASR（word_ts=1 词级时间戳）→ 三维评分 → 中文反馈。

    multipart 字段：
      file          音频（必填）
      target_text   目标法语句（必填）
      sentence_id   句 id（可选，用于中文反馈）
      level/focus   句子等级/标签（可选，透传不用于评分）
    """
    content_type = request.headers.get("content-type", "")
    body = await request.body()
    audio, filename, audio_ct = _parse_multipart(body, content_type)
    if not audio:
        raise ApiError(40001, 400, "空音频文件")

    def field(name: str) -> str:
        m = re.search(
            r'name="' + re.escape(name) + r'"\r\n\r\n([^\r\n]*)',
            body.decode("utf-8", "ignore"),
        )
        return m.group(1).strip() if m else ""

    target_text = field("target_text")
    if not target_text:
        raise ApiError(40001, 400, "缺少 target_text")
    sentence_id = field("sentence_id")

    # 目标句中文：从难点库/语料池按 id 查（仅用于反馈，非评分输入）
    sentence_cn = ""
    focus_word = ""
    for s in pron_coach._load_focus_pool() + pron_coach._load_texts_pool():
        if s["id"] == sentence_id:
            sentence_cn = s.get("cn", "")
            focus_word = s.get("focus_word", "")
            break

    # 转发到 ASR 服务，强制 word_ts=1（独立链路，绝不进聊天流）
    boundary = "----yayaPronCoachBoundary"

    def part(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode("utf-8")

    forward = b"".join([
        part("language", "fr"),
        part("hints", target_text[:200]),   # 目标句作热词，提升近音识别
        part("context", ""),
        part("word_ts", "1"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {audio_ct or 'application/octet-stream'}\r\n\r\n".encode("utf-8"),
        audio,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(
        ASR_SERVICE_URL + "/transcribe",
        data=forward,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            asr = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(50001, 500, f"语音转写失败（ASR {exc.code}）")
    except Exception as exc:  # noqa: BLE001
        raise ApiError(40001, 400, "本地语音服务未启动，跟读先跳过～")

    if not asr.get("ok"):
        raise ApiError(50001, 500, asr.get("error", "转写失败"))

    score = pron_coach.score_pronunciation(
        target_text=target_text,
        words=asr.get("words") or [],
        low_confidence=bool(asr.get("low_confidence", False)),
    )
    sentence_meta = {"cn": sentence_cn, "focus_word": focus_word} if sentence_id else None
    feedback = pron_coach.build_feedback(score, sentence_meta)

    return ok({
        "band": score["band"],
        "scores": score["scores"],
        "overall": score["overall"],
        "hit_words": score["hit_words"],
        "missing_words": score["missing_words"],
        "feedback": feedback,
        "elapsed": asr.get("elapsed"),
        "low_confidence": bool(asr.get("low_confidence", False)),
    })
