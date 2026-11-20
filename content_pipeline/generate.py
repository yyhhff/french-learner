"""GLM 语料生成器：消费需求队列，按 texts.json schema 严格约束生成候选。

设计：
- 复用 backend/ai.py 的 _glm_post（同一 key/base_url/重试契约），零新依赖；
- 每个 slot 生成 1 篇，few-shot 给一条现有语料（按目标等级取），约束输出纯 JSON；
- 候选落 cache/candidates.json，按 demand id 去重，已生成且 validate=pass 的跳过（断点续跑）；
- 只产出候选，绝不直接写 texts.json（入库唯一通道是审校）。
"""
from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from content_pipeline.paths import (
    CACHE_DIR,
    CANDIDATES_FILE,
    DEMAND_FILE,
    PROJECT_ROOT,
    TEXTS_FILE,
    ensure_dirs,
)

logger = logging.getLogger("yaya.content.generate")

# 把 backend 加入 sys.path 以复用 ai._glm_post（ai 顶层 import db/seed，故一并可见）
_BACKEND = PROJECT_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

SYSTEM_PROMPT = """你是一位专业的法语教学内容编写者，为中文母语零基础到 B2 的学习者编写分级短文。
你必须输出**严格的 JSON 对象**，不要输出任何解释、markdown 代码块或多余文字。

字段契约（全部必填，字符串用中文做 body_cn/cn 翻译）：
{
  "id": "gen_<level小写>_<三位序号>",
  "title": "中文标题",
  "format": "dialogue 或 monologue",
  "cefr_level": "A1/A2/B1/B2 之一（必须等于要求等级）",
  "topic": "给定主题",
  "body_fr": "法语正文，按行用 \\n 分隔；对话时每行一句、不写说话人前缀",
  "body_cn": "逐行对应的中文翻译，行数与 body_fr 完全一致，也用 \\n 分隔",
  "audio_url": null,
  "sort_order": 0,
  "lines": [
    {"seq": 1, "speaker": "A", "fr": "法语一行", "cn": "中文一行", "audio_url": null}
  ],
  "words": [
    {"word": "生词或短语", "meaning": "中文释义", "pos": "词性缩写如 n.m./v./adj.",
     "cefr_level": "该词 CEFR 级别", "example": "所在法语句", "pronunciation": "国际音标",
     "line_seq": 1}
  ]
}
硬性规则：
1. cefr_level 必须严格等于任务指定等级；对话 format=dialogue 时 speaker 只能是 A/B 且交替；独白 format=monologue 时 speaker 为 null。
2. lines 的 seq 从 1 连续递增；fr/cn 非空；body_fr/body_cn 的行数 = lines 条数，顺序一致。
3. 词汇与句型贴合指定等级：A1 只用现在时最常用的短句；A2 可含复合过去时；B1 可含条件式与复杂从句；B2 词汇更丰富。
4. words 至少 4 个、至多 10 个，必须是文中真实出现的生词/短语（不要编造不在正文的词）。
5. 主题与场景必须贴合任务要求；内容原创、积极、无敏感话题。
6. 只输出 JSON 对象本身，从 { 开始、以 } 结束。"""


def _few_shot(level: str) -> str:
    """按目标等级取一条现有语料做 few-shot（没有则该级退化为通用示例）。"""
    try:
        data = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for item in data.get("texts", []):
        if item.get("cefr_level") == level:
            # 只保留字段骨架，控制 token
            sample = {k: item.get(k) for k in ("id", "title", "format", "cefr_level", "topic",
                                               "body_fr", "body_cn", "audio_url", "sort_order",
                                               "lines", "words")}
            return "示例（严格照此结构与粒度，但内容须完全不同）：\n" + json.dumps(sample, ensure_ascii=False)
    return ""


def build_messages(slot: dict, few_shot: str) -> list[dict]:
    lo, hi = slot["target_sentences"]
    user = (
        f"请编写一篇法语分级短文，任务单如下：\n"
        f"- 等级：{slot['level']}（必须严格等于该值）\n"
        f"- 主题：{slot['topic']}\n"
        f"- 场景：{slot['scene']}\n"
        f"- 体裁：{slot['format']}\n"
        f"- 句数：{lo}–{hi} 句\n"
        f"- id 用：gen_{slot['level'].lower()}_{slot['id'].split('_')[-1]}\n"
        f"{few_shot}\n"
        f"现在输出 JSON："
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# 生成场景专属 GLM POST：与 ai.py 同 key/base_url/model，但超时放宽到 45s、
# 重试 2 次。不修改 ai.py（其 8s/1 次重试是面客聊天的低延迟契约，不能动）。
GEN_TIMEOUT = int(os.environ.get("YAYA_GEN_TIMEOUT", "60"))
GEN_ATTEMPTS = 2
# 实测完整一篇（含 5-10 个 words）约 1800-2200 tokens；1600 会截断尾部导致 JSON 解析失败
GEN_MAX_TOKENS = int(os.environ.get("YAYA_GEN_MAX_TOKENS", "2600"))


def glm_post_gen(messages: list, max_tokens: int = GEN_MAX_TOKENS, temperature: float = 0.65) -> str:
    import ai  # 延迟导入，复用其 key/base_url/model 常量

    payload = json.dumps(
        {
            "model": ai.GLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    url = ai.GLM_BASE_URL + "/chat/completions"
    last_exc: Exception | None = None
    for attempt in range(GEN_ATTEMPTS):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {ai.GLM_API_KEY}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=GEN_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                last_exc = exc
                if attempt < GEN_ATTEMPTS - 1:
                    time.sleep(1.0)
                    continue
            raise
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            last_exc = exc
            if attempt < GEN_ATTEMPTS - 1:
                time.sleep(1.0)
                continue
            raise
    raise RuntimeError(f"GLM 生成失败：{last_exc}")


def _parse_json(content: str) -> dict | None:
    """从模型输出里稳健提取 JSON 对象（容忍 markdown 代码围栏）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0:
        return None
    body = text[start:end + 1] if end > start else text[start:]
    try:
        obj = json.loads(body)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        pass
    # 兜底：max_tokens 截断导致尾部缺闭合（常见于 words 数组最后一个对象处）
    repaired = _repair_truncated(body)
    if repaired:
        try:
            obj = json.loads(repaired)
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None
    return None


def _repair_truncated(text: str) -> str | None:
    """补全被截断 JSON 的尾部闭合括号。

    策略：扫描出未闭合的括号栈（忽略字符串内字符）；若截断落在字符串中间，
    先补引号；再按栈逆序补闭合符。仅当结构明显"只差闭合"时补全，绝不改写内容。
    """
    s = text.rstrip()
    if not s.startswith("{"):
        return None
    stack: list[str] = []  # 期望的闭合符，如 '}' 或 ']'
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
            else:
                return None  # 括号不匹配，非单纯截断，不修
    if not stack:
        return None
    out = s
    if in_str:
        out += '"'          # 截断在字符串中间
    out += "".join(reversed(stack))  # 按栈逆序闭合
    return out


def load_candidates() -> dict[str, dict]:
    if not CANDIDATES_FILE.is_file():
        return {}
    try:
        data = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_candidates(cands: dict[str, dict]) -> None:
    ensure_dirs()
    CANDIDATES_FILE.write_text(
        json.dumps(cands, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def generate_one(slot: dict, glm_post) -> tuple[dict | None, str]:
    """生成单条候选。返回 (item, error)；error 为空表示成功。"""
    few_shot = _few_shot(slot["level"])
    try:
        content = glm_post(build_messages(slot, few_shot), max_tokens=2200, temperature=0.65)
    except Exception as exc:  # noqa: BLE001 — 网络/限流交给上层记录并续跑
        return None, f"glm_call_failed: {exc}"
    item = _parse_json(content)
    if item is None:
        return None, "json_parse_failed"
    _normalize_body(item)  # 用 lines 重建 body，消除 line_count_mismatch 高频瑕疵
    item["_source_demand"] = slot["id"]
    item["_review_status"] = "pending"
    return item, ""


def _normalize_body(item: dict) -> None:
    """用 lines 的 fr/cn 序列重建 body_fr/body_cn，保证三者行数一致。

    GLM 常把 body 多写/少写一行或与 lines 不一致；lines 是结构化权威源，
    以它为准重建 body 属于无损规整，不改动任何句子内容。
    """
    lines = item.get("lines")
    if not isinstance(lines, list) or not lines:
        return
    fr_parts, cn_parts = [], []
    for line in lines:
        if not isinstance(line, dict):
            continue
        fr = line.get("fr")
        cn = line.get("cn")
        if isinstance(fr, str) and fr.strip():
            fr_parts.append(fr.strip())
        if isinstance(cn, str) and cn.strip():
            cn_parts.append(cn.strip())
    if fr_parts:
        item["body_fr"] = "\n".join(fr_parts)
    if cn_parts:
        item["body_cn"] = "\n".join(cn_parts)


def run(limit: int | None = None, only_level: str | None = None, force: bool = False) -> dict:
    """批量生成：跳过已有候选（force=True 覆盖）；返回统计。"""
    if not DEMAND_FILE.is_file():
        raise SystemExit("需求队列不存在，请先运行 python -m content_pipeline.demand")
    queue = json.loads(DEMAND_FILE.read_text(encoding="utf-8"))
    cands = load_candidates()
    stats = {"processed": 0, "generated": 0, "skipped": 0, "failed": 0, "errors": {}}

    for slot in queue["slots"]:
        if only_level and slot["level"] != only_level:
            continue
        key = slot["id"]
        if key in cands and not force:
            stats["skipped"] += 1
            continue
        if limit is not None and stats["processed"] >= limit:
            break
        item, err = generate_one(slot, glm_post_gen)
        stats["processed"] += 1
        if err:
            stats["failed"] += 1
            stats["errors"][err.split(":")[0]] = stats["errors"].get(err.split(":")[0], 0) + 1
            logger.warning("slot %s 生成失败：%s", key, err)
            continue
        cands[key] = item
        stats["generated"] += 1
        save_candidates(cands)  # 每条即时落盘，保证断点续跑
        logger.info("slot %s 生成成功：%s", key, item.get("id"))

    return stats


if __name__ == "__main__":
    import argparse
    import logging as _lg

    _lg.basicConfig(level=_lg.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="GLM 批量生成语料候选")
    ap.add_argument("--limit", type=int, default=None, help="本次最多处理的新 slot 数")
    ap.add_argument("--level", default=None, help="仅生成某等级 A1/A2/B1/B2")
    ap.add_argument("--force", action="store_true", help="覆盖已生成候选")
    args = ap.parse_args()
    result = run(args.limit, args.level, args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
