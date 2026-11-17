"""重述引擎：OpenAI 兼容 LLM（可选）+ 本地规则降级，统一入口 recast()。

对外仅暴露 recast(scene_id, user_text, history) -> ChatResult。
- 环境变量：LLM_API_KEY / LLM_BASE_URL(默认 https://api.openai.com/v1) / LLM_MODEL(默认 gpt-3.5-turbo)
- key 未设置 → 不发网络请求，直接用 LocalRecaster；
- key 存在但调用失败（网络/超时/额度/格式）→ 记录日志并回退本地规则，绝不向前端抛 500。
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Optional

import db
import seed as seed_data

logger = logging.getLogger("yaya.ai")

LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-3.5-turbo")

DEFAULT_USER_ID = db.DEFAULT_USER_ID


@dataclass
class ChatResult:
    """契约 4.4：{ai_text, recast_of, explanation, new_words}。"""

    ai_text: str
    recast_of: Optional[str] = None
    explanation: Optional[str] = None
    new_words: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- 本地规则表（契约 7.1）

# (小写触发片段列表, 修正输出, 中文讲解)；顺序即优先级。
RULES = [
    (["je veux"], "Je voudrais", "礼貌点单用条件式 voudrais 更自然（你也完全能被懂）。"),
    (
        ["je suis aller"],
        "Je suis allé",
        "复合过去时 être 后用过去分词 allé。",
    ),
    (["le gare"], "la gare", "gare 是阴性名词，用 la。"),
    (
        ["au tête", "à le tête"],
        "à la tête",
        "「身体部位疼」用 à + 定冠词，tête 阴性→ à la tête。",
    ),
]

GENERIC_REPLY = "Ah, je vois ! Raconte-moi encore un peu."

# 场景接话池轮转游标（每个场景独立）
_reply_cursor: dict[str, int] = {}


def _next_reply(scene_id: str) -> str:
    scene = seed_data.get_scene_seed(scene_id)
    pool = list(scene["reply_pool"]) if scene else []
    if not pool:
        return GENERIC_REPLY
    i = _reply_cursor.get(scene_id, 0)
    reply = pool[i % len(pool)]
    _reply_cursor[scene_id] = i + 1
    return reply


def recast_local(scene_id: str, user_text: str) -> ChatResult:
    """规则式重述：小写归一化后子串匹配，未命中则场景话术池接话。"""
    lower = user_text.lower()
    for triggers, fixed, explanation in RULES:
        for trigger in triggers:
            if trigger in lower:
                # 在原文上做一次大小写不敏感替换，保留句子的其余部分
                ai_text = re.sub(
                    re.escape(trigger),
                    lambda _m: fixed,
                    user_text,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()
                return ChatResult(
                    ai_text=ai_text or fixed,
                    recast_of=user_text,
                    explanation=explanation,
                )
    return ChatResult(ai_text=_next_reply(scene_id), recast_of=None, explanation=None)


# ---------------------------------------------------------------- LLM 分支

def _build_llm_messages(scene_id: str, user_text: str, history: list) -> list:
    scene = seed_data.get_scene_seed(scene_id) or {}
    context = {
        "scene": {
            "id": scene_id,
            "title": scene.get("title"),
            "cefr_level": scene.get("cefr_level"),
        },
        "recent_history": history[-10:],
        "user_text": user_text,
    }
    system = (
        "你是温柔的法语陪练「呀呀」。请顺着用户的话自然接话，"
        "如果用户说法有错，不要打红叉、不要解释语法规则，"
        "直接把正确说法自然地嵌在一句法语回应里。"
        "只输出 JSON：{\"ai_text\": 法语回应, \"recast_of\": 被纠正的原句或null, "
        "\"explanation\": 中文温和讲解或null}。未纠错时 recast_of 与 explanation 均为 null。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def _parse_llm_content(content: str) -> ChatResult:
    """解析 LLM 文本：优先 JSON；非 JSON 时整段当作 ai_text（视为未纠错）。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        obj = None
    if isinstance(obj, dict):
        ai_text = obj.get("ai_text")
        if isinstance(ai_text, str) and ai_text.strip():
            return ChatResult(
                ai_text=ai_text.strip(),
                recast_of=obj.get("recast_of") or None,
                explanation=obj.get("explanation") or None,
            )
    if text:
        return ChatResult(ai_text=text, recast_of=None, explanation=None)
    raise ValueError("LLM 返回空内容")


def recast_llm(scene_id: str, user_text: str, history: list) -> ChatResult:
    """调用 OpenAI 兼容 /chat/completions；任何异常由 recast() 统一降级。"""
    url = f"{LLM_BASE_URL}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": _build_llm_messages(scene_id, user_text, history),
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"]
    return _parse_llm_content(content)


# ---------------------------------------------------------------- 新词卡抽取

def _extract_new_words(scene_id: str, ai_text: str) -> list:
    """用场景词表（seed 生词 + 扩展词）匹配 ai_text，命中且未建过则建卡。"""
    scene = seed_data.get_scene_seed(scene_id)
    if not scene:
        return []
    vocab = list(scene.get("vocab", [])) + list(scene.get("extra_vocab", []))
    lower = ai_text.lower()
    created = []
    for v in vocab:
        word = v["word"]
        if word.lower() in lower and not db.card_exists(DEFAULT_USER_ID, word):
            created.append(
                db.create_card(
                    user_id=DEFAULT_USER_ID,
                    word=word,
                    meaning=v.get("meaning"),
                    pos=v.get("pos"),
                    example=v.get("example"),
                    pronunciation=v.get("pronunciation"),
                    cefr_level=v.get("cefr_level"),
                    source_scene_id=scene_id,
                )
            )
    return created


# ---------------------------------------------------------------- 统一入口

def recast(scene_id: str, user_text: str, history: list) -> ChatResult:
    """契约唯一对外入口。history 内部只取最后 10 轮。"""
    history = history[-10:] if isinstance(history, list) else []

    if LLM_API_KEY:
        try:
            result = recast_llm(scene_id, user_text, history)
        except Exception as exc:  # 网络/超时/额度/格式错一律降级，不抛 500
            logger.warning("LLM 重述失败，回退本地规则：%s", exc)
            result = recast_local(scene_id, user_text)
    else:
        result = recast_local(scene_id, user_text)

    result.new_words = _extract_new_words(scene_id, result.ai_text)
    return result
