"""重述引擎：智谱 GLM 主适配（OpenAI 兼容端点）+ 本地规则降级，统一入口 recast()。

契约 ARCHITECTURE_V2.md §3：
- 环境变量优先级：ZHIPU_API_KEY（用户现有 env）> GLM_* > LLM_*；三者 key 都为空 → 零网络请求走本地规则。
- 网络调用只用标准库 urllib.request / json / re / time / socket，零新依赖。
- 严格 JSON 模式：content 非合法 JSON 对象或 ai_text 非非空字符串 → 降级。
- 降级判定表 9 条逐条覆盖；除入参非法外，永不向前端抛 500。

对外仅暴露 recast(scene_id, user_text, history) -> ChatResult，
签名与 ChatResult.to_dict() 的 4 字段与 v1 完全一致。
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import db
import seed as seed_data

logger = logging.getLogger("yaya.ai")

# ---------------------------------------------------------------- §3.1 环境变量与优先级
# key 按 ZHIPU_API_KEY -> GLM_API_KEY -> LLM_API_KEY 取第一个非空值（or 的空串语义）；
# base_url / model 仍按 GLM_* -> LLM_* -> 默认 取第一个非空值。
# ZHIPU_API_KEY 是用户机器上已有的智谱 key 变量名，优先级最高，开箱即用。

GLM_API_KEY = (
    os.environ.get("ZHIPU_API_KEY", "").strip()
    or os.environ.get("GLM_API_KEY", "").strip()
    or os.environ.get("LLM_API_KEY", "").strip()
)
GLM_BASE_URL = (
    os.environ.get("GLM_BASE_URL", "").strip()
    or os.environ.get("LLM_BASE_URL", "").strip()
    or "https://open.bigmodel.cn/api/paas/v4"
).rstrip("/")
GLM_MODEL = (
    os.environ.get("GLM_MODEL", "").strip()
    or os.environ.get("LLM_MODEL", "").strip()
    or "glm-4-flash"
)

# §3.6 模块级固定常量（不是环境变量，不写入 .env.example）。
GLM_TIMEOUT_SECONDS = 8
MAX_ATTEMPTS = 2
RETRY_INTERVAL_SECONDS = 0.3

DEFAULT_USER_ID = db.DEFAULT_USER_ID

# ---------------------------------------------------------------- §3.7 SYSTEM_PROMPT（逐字）

SYSTEM_PROMPT = """你是「呀呀（YaYa）」，一位温柔、耐心的法语口语陪练。你的说话对象是一位正在学习法语的中文母语者。

核心任务：
1. 顺着用户上一句话自然接话，让对话像真人聊天一样继续下去。回应要简短、口语化，可以是一句陈述或一句追问。
2. 如果用户说的法语有语法、用词或搭配错误，绝对不要说「你错了」，不要打红叉，不要罗列语法规则，不要给出冷冰冰的批改。
   正确做法是「自然重述（recast）」：先用一句自然的回应接住对方的意思，再把正确的说法自然地嵌进你的法语回应里，让用户在理解上下文时顺便吸收正确形式。
   例如用户说「Je veux un thé.」，你可以回应「Bien sûr ! Je vous apporte un thé tout de suite. Vous le voulez chaud ?」——在自然服务对话里示范了礼貌表达，而不是纠错。
3. 法语输出要控制在对方水平可理解的范围内：多用常用词、句子宜短。

输出要求（最重要，必须严格遵守）：
- 只输出一个 JSON 对象，不要输出任何解释文字，不要使用 markdown 代码围栏。
- JSON 必须且只能包含以下四个键：
  {
    "ai_text": "string，你用法语说的回应；若发生纠错，正确说法要自然嵌在这里",
    "recast_of": "string 或 null，被纠错的『用户原句』；未纠错时必须为 null",
    "explanation": "string 或 null，面向中文用户的温和一句讲解；必须是简体中文一句话，绝对不能出现法语或英语；未纠错时必须为 null",
    "new_words": "array，你在回应中用到的、用户可能不认识的法语词，0~5 个"
  }
- new_words 数组每个元素形如：
  {"word": "法语词或短语", "meaning": "中文释义", "pos": "词性缩写", "cefr_level": "A2"}
  其中 pos 可用 n.m./n.f./adj./adv./loc./v./cond. 等；cefr_level 取 A1/A2/B1/B2/C1/C2，不确定时为 null。
- 如果用户的表达没有错误，recast_of 与 explanation 都必须为 null，不要为了纠错而纠错。
- 【硬约束】explanation 必须且只能是【简体中文】的一句话：它是给用户看的讲解，用户不懂法语/英语。严禁写成法语或英语句子，严禁把用户的法语原句整段照抄进来。例如正确写法：「想礼貌点单，法国人更常说 voudrais，不过你这样说也完全能懂」；错误写法：「Le mot 'show' peut être utilisé pour exprimer...」。如果 explanation 不是简体中文，就视为输出格式错误，必须改写成上面这样的简体中文后再输出。
- 确保输出是合法 JSON：字符串内的引号要正确转义。"""

# ---------------------------------------------------------------- 法语→中文翻译（给对话气泡配中文）

TRANSLATE_SYSTEM_PROMPT = """你是「呀呀法语」的翻译小助手，把法语口语翻译成自然、简洁的简体中文。

要求：
- 只输出一个 JSON 对象，不要解释、不要 markdown 代码围栏：{"translations":["译文1","译文2",...]}
- translations 数组长度和顺序必须与用户给出的 texts 完全一致；每条都是字符串。
- 译文要口语化、符合中文表达习惯，不要逐词硬翻；保留语气（问候、礼貌、疑问等）。
- 如果某条不是法语或无法翻译，对应位置输出空字符串。
- 字符串内的引号要正确转义，确保整个输出是合法 JSON。"""


@dataclass
class ChatResult:
    """契约 4.4 / v2 §3.8：仅 4 字段进 JSON；llm_new_words 为内部字段。"""

    ai_text: str
    recast_of: Optional[str] = None
    explanation: Optional[str] = None
    new_words: list = field(default_factory=list)
    llm_new_words: list = field(default_factory=list)  # 内部：LLM 建议候选词，不进 to_dict

    def to_dict(self) -> dict:
        return {
            "ai_text": self.ai_text,
            "recast_of": self.recast_of,
            "explanation": self.explanation,
            "new_words": self.new_words,
        }


# ---------------------------------------------------------------- 本地规则表（沿用 v1）

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


# ---------------------------------------------------------------- §3.3 LLM 请求体

def _build_llm_messages(scene_id: str, user_text: str, history: list) -> list:
    scene = seed_data.get_scene_seed(scene_id) or {}
    profile = db.get_profile() or {}
    context = {
        "scene": {
            "id": scene_id,
            "title": scene.get("title"),
            "cefr_level": scene.get("cefr_level"),
        },
        "learner": {
            "cefr_level": profile.get("cefr_level"),
            "target_level": profile.get("target_level"),
        },
        "recent_history": [
            {"role": t.get("role"), "fr": t.get("fr")} for t in history[-10:]
            if isinstance(t, dict)
        ],
        "user_text": user_text,
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


# ---------------------------------------------------------------- §3.4 严格 JSON 解析

def _parse_llm_content(content: str) -> ChatResult:
    """严格模式：非合法 JSON 对象 / ai_text 非非空字符串 → 抛 ValueError 降级。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("LLM 返回格式异常") from exc
    if not isinstance(obj, dict):
        raise ValueError("LLM 返回格式异常")

    ai_text = obj.get("ai_text")
    if not (isinstance(ai_text, str) and ai_text.strip()):
        raise ValueError("LLM 返回格式异常")

    recast_of = obj.get("recast_of")
    recast_of = (
        recast_of.strip()
        if isinstance(recast_of, str) and recast_of.strip()
        else None
    )
    explanation = obj.get("explanation")
    explanation = (
        explanation.strip()
        if isinstance(explanation, str) and explanation.strip()
        else None
    )

    # 仅保留含非空字符串 word 的 dict 元素；字段缺失/非 list → []（§3.4 步骤 5）。
    llm_new_words: list = []
    raw_words = obj.get("new_words")
    if isinstance(raw_words, list):
        for item in raw_words:
            if (
                isinstance(item, dict)
                and isinstance(item.get("word"), str)
                and item["word"].strip()
            ):
                llm_new_words.append(
                    {
                        "word": item["word"].strip(),
                        "meaning": item.get("meaning"),
                        "pos": item.get("pos"),
                        "cefr_level": item.get("cefr_level"),
                    }
                )

    return ChatResult(
        ai_text=ai_text.strip(),
        recast_of=recast_of,
        explanation=explanation,
        llm_new_words=llm_new_words,
    )


# ---------------------------------------------------------------- §3.5 / §3.6 LLM 调用 + 重试

def _glm_post(messages: list, max_tokens: int = 512, temperature: float = 0.7) -> str:
    """智谱 OpenAI 兼容 /chat/completions 的统一 POST；返回 message.content 原文。

    重试规则与 v2 契约一致：仅 #2 网络、#3 超时、#4 429/5xx 重试 1 次；
    #5 401/403 等其他 4xx 立即抛出。格式异常留给调用方严格解析。
    """
    url = GLM_BASE_URL + "/chat/completions"
    payload = {
        "model": GLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    for attempt in range(MAX_ATTEMPTS):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {GLM_API_KEY}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=GLM_TIMEOUT_SECONDS) as resp:
                raw = resp.read().decode("utf-8")
            body = json.loads(raw)
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            # #4 429/5xx 可重试；#5 401/403/其他 4xx 立即降级。
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_INTERVAL_SECONDS)
                continue
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            # #2 DNS/连接/网络不可达、#3 超时 → 可重试 1 次。
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_INTERVAL_SECONDS)
                continue
            raise
        # #6/#7 格式异常、#9 其他异常都不在此捕获，交由调用方兜底降级。

    raise RuntimeError("LLM 调用失败")  # 逻辑不可达，防御性兜底


def recast_llm(scene_id: str, user_text: str, history: list) -> ChatResult:
    """调用智谱 OpenAI 兼容 /chat/completions；可重试异常仅 #2/#3/#4。"""
    content = _glm_post(_build_llm_messages(scene_id, user_text, history))
    return _parse_llm_content(content)


# ---------------------------------------------------------------- §3.8 收词合并去重

def _extract_new_words(
    scene_id: str, ai_text: str, llm_new_words: list | None
) -> list:
    """来源 A（LLM 建议）+ 来源 B（本地场景词表）合并按 word 去重后建卡。"""
    lower = ai_text.lower()
    seen: set[str] = set()
    candidates: list[dict] = []

    def add(word, meaning, pos, example, pronunciation, cefr_level) -> None:
        if not (isinstance(word, str) and word.strip()):
            return
        word = word.strip()
        key = word.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "word": word,
                "meaning": meaning,
                "pos": pos,
                "example": example,
                "pronunciation": pronunciation,
                "cefr_level": cefr_level,
            }
        )

    # 来源 A：LLM 建议，仅当 word + meaning 齐全且 word 命中 ai_text。
    for item in llm_new_words or []:
        if not isinstance(item, dict):
            continue
        word = item.get("word")
        meaning = item.get("meaning")
        if not (
            isinstance(word, str)
            and word.strip()
            and isinstance(meaning, str)
            and meaning.strip()
        ):
            continue
        if word.strip().lower() in lower:
            add(
                word.strip(),
                meaning.strip(),
                item.get("pos"),
                None,
                None,
                item.get("cefr_level"),
            )

    # 来源 B：本地场景词表（v1 逻辑）。
    scene = seed_data.get_scene_seed(scene_id)
    if scene:
        vocab = list(scene.get("vocab", [])) + list(scene.get("extra_vocab", []))
        for v in vocab:
            if not isinstance(v, dict):
                continue
            word = v.get("word")
            if isinstance(word, str) and word.strip() and word.strip().lower() in lower:
                add(
                    word,
                    v.get("meaning"),
                    v.get("pos"),
                    v.get("example"),
                    v.get("pronunciation"),
                    v.get("cefr_level"),
                )

    created = []
    for c in candidates:
        # create_card 内部按 (user_id, word) 查重；重复词/重复调用都天然幂等。
        created.append(
            db.create_card(
                user_id=DEFAULT_USER_ID,
                word=c["word"],
                meaning=c["meaning"],
                pos=c["pos"],
                example=c["example"],
                pronunciation=c["pronunciation"],
                cefr_level=c["cefr_level"],
                source_scene_id=scene_id,
            )
        )
    return created


# ---------------------------------------------------------------- 法语→中文（批量，供对话气泡展示）

def _parse_translation_content(content: str, expected: int) -> list[Optional[str]]:
    """严格解析翻译结果：非合法 JSON/长度不符 → 抛 ValueError；空串 → None。"""
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise ValueError("翻译返回格式异常") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("translations"), list):
        raise ValueError("翻译返回格式异常")
    raw = obj["translations"]
    if len(raw) < expected:
        raise ValueError("翻译返回格式异常")
    result: list[Optional[str]] = []
    for item in raw[:expected]:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        else:
            result.append(None)
    return result


def translate_to_zh(texts: list) -> list[Optional[str]]:
    """批量把法语译成中文；无 key 或任何失败 → 对应位置 None，绝不抛异常。"""
    items = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
    if not items:
        return [None] * len(texts)
    if not GLM_API_KEY:
        return [None] * len(texts)

    messages = [
        {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({"texts": items}, ensure_ascii=False)},
    ]
    try:
        content = _glm_post(messages, max_tokens=512, temperature=0.2)
        parsed = _parse_translation_content(content, len(items))
    except Exception as exc:  # 网络/额度/格式等任意异常 → 不阻断对话
        logger.warning("中文翻译失败：%s", exc)
        return [None] * len(texts)

    out: list[Optional[str]] = []
    cursor = 0
    for t in texts:
        if isinstance(t, str) and t.strip():
            out.append(parsed[cursor] if cursor < len(parsed) else None)
            cursor += 1
        else:
            out.append(None)
    return out


# ---------------------------------------------------------------- explanation 中文化兜底
# 真实 GLM 偶尔不遵守 SYSTEM_PROMPT，把 explanation 写成法语/英文。用户看不懂，
# 这里在入口层做最后一道保险：非空却不含中日韩字符 → 尝试翻译，失败给温和占位。

# 覆盖：日文假名、CJK 扩展 A、CJK 基本区、CJK 兼容汉字、韩文音节。
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]")
_EXPLANATION_ZH_PLACEHOLDER = "这里有个更自然的说法，跟着呀呀读一遍就好啦～"


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _ensure_explanation_zh(result: ChatResult) -> None:
    """把非中文的 explanation 兜底成中文；中文 explanation 不触发任何网络请求。

    只改 result.explanation，不动 recast_of / new_words / ai_text。translate_to_zh
    自身对所有失败都已降级返回 None；这里再包一层 try 以绝对保障不抛异常。
    """
    explanation = result.explanation
    if not (isinstance(explanation, str) and explanation.strip()):
        return
    if _has_cjk(explanation):
        return

    translated = None
    try:
        translated = translate_to_zh([explanation])[0]
    except Exception as exc:  # 防御性：translate_to_zh 契约上不抛，仍兜底
        logger.warning("explanation 中文兜底翻译异常：%s", exc)

    if isinstance(translated, str) and translated.strip() and _has_cjk(translated):
        result.explanation = translated.strip()
    else:
        # 翻译失败或译文仍非中文 → 温和中文占位，不把看不懂的外语展示给用户。
        result.explanation = _EXPLANATION_ZH_PLACEHOLDER


# ---------------------------------------------------------------- 统一入口

def recast(scene_id: str, user_text: str, history: list) -> ChatResult:
    """契约唯一对外入口。无 key 或任何 LLM 失败都降级本地规则，不抛 500。"""
    history = history[-10:] if isinstance(history, list) else []

    llm_new_words: list = []
    if GLM_API_KEY:
        try:
            result = recast_llm(scene_id, user_text, history)
            llm_new_words = result.llm_new_words
        except Exception as exc:  # 网络/超时/额度/格式/其他任意异常 → 降级（#1~#9）
            logger.warning("LLM 重述失败，回退本地规则：%s", exc)
            result = recast_local(scene_id, user_text)
    else:
        # #1 无 key：零网络请求，直接本地规则。
        result = recast_local(scene_id, user_text)

    _ensure_explanation_zh(result)  # 非中文讲解兜底翻译/占位；中文零额外请求
    result.llm_new_words = llm_new_words
    result.new_words = _extract_new_words(scene_id, result.ai_text, llm_new_words)
    return result
