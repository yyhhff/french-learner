"""零基础读音规则学习：规则 JSON 加载/校验/进程内缓存与查询。

契约 PRONUNCIATION_CONTRACT.md v1.0（唯一技术输入）逐字实现；
照 exam.py::load_papers() 模式：模块级缓存、幂等、单条非法跳过、文件缺失降级为空；
零新增依赖；app.py 只做路由/校验，运行时零文件 IO。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("yaya.pronunciation")

# 与 exam_papers.json / texts.json 同目录（项目根 data/input）
INPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "input"
INPUT_FILE = INPUT_DIR / "pronunciation_rules.json"

# 契约 §2.2 枚举（8 个纯分组名 / 2 个难度 / 3 个跟读单元）
GROUPS = (
    "字母表与读音概念",
    "基础元音",
    "基础辅音",
    "元音字母组合",
    "辅音字母组合",
    "鼻化元音",
    "词末辅音规则",
    "高频例外与易错",
)
TIERS = ("starter", "core")
SHADOW_MODES = ("syllable", "word", "phrase")

# 契约 §6 出参字段集（逐字；详情 10 字段、摘要 4 字段、例词 4 字段）
RULE_FIELDS = (
    "id", "group", "title", "description_zh", "examples",
    "audio_text", "shadow_text_fr", "shadow_mode", "tier", "tags",
)
SUMMARY_FIELDS = ("id", "group", "title", "tier")
EXAMPLE_FIELDS = ("word_fr", "meaning_zh", "note_zh", "phonetic")

# 进程内缓存：None 表示尚未加载；加载后固定为 list（含空表 []），幂等。
_RULES_CACHE = None


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_rule(rule, seen_ids: set) -> str | None:
    """单条规则逐字段校验；合法返回 None，非法返回跳过原因（契约 §2.2 / §4.2）。"""
    if not isinstance(rule, dict):
        return "不是对象"
    rule_id = rule.get("id")
    if not _nonempty_str(rule_id):
        return "缺少合法 id"
    if rule_id in seen_ids:
        return f"id 重复：{rule_id}"
    if rule.get("group") not in GROUPS:
        return "group 非法"
    if rule.get("tier") not in TIERS:
        return "tier 非法"
    if rule.get("shadow_mode") not in SHADOW_MODES:
        return "shadow_mode 非法"
    for field in ("title", "description_zh", "audio_text", "shadow_text_fr"):
        if not _nonempty_str(rule.get(field)):
            return f"{field} 非法"
    examples = rule.get("examples")
    if not isinstance(examples, list) or len(examples) != 4:  # ★裁决①：恰好 4 条
        return "examples 必须恰好 4 条"
    for ex in examples:
        if not isinstance(ex, dict):
            return "examples 元素不是对象"
        for field in EXAMPLE_FIELDS:
            if not _nonempty_str(ex.get(field)):
                return f"examples.{field} 非法"
    tags = rule.get("tags")
    if not isinstance(tags, list) or any(not _nonempty_str(tag) for tag in tags):
        return "tags 非法"
    return None


def load_rules() -> list:
    """加载并校验规则 JSON；进程内缓存、幂等；文件缺失/异常降级为空表不抛异常。

    ★裁决⑦：顶层可能含 version 元信息键，只读 payload["rules"]，忽略 version。
    单条非法只跳过该条 + warning，不影响其余规则与服务启动（契约 §4.2）。
    """
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE

    rules: list = []
    try:
        with INPUT_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        logger.warning("读音规则文件不存在：%s，规则降级为空", INPUT_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("读音规则加载失败：%s，规则降级为空", exc)
    else:
        raw = payload.get("rules") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            logger.warning("读音规则 rules 字段非法，规则降级为空")
        else:
            seen_ids: set = set()
            for index, rule in enumerate(raw):
                reason = _validate_rule(rule, seen_ids)
                if reason is not None:
                    logger.warning("跳过第 %d 条非法读音规则：%s", index + 1, reason)
                    continue
                seen_ids.add(rule["id"])
                # 严格投影：详情 10 字段（按契约 §6 顺序）、例词 4 字段，绝不多下发任何字段
                detail = {}
                for key in RULE_FIELDS:
                    if key == "examples":
                        detail["examples"] = [
                            {field: ex[field] for field in EXAMPLE_FIELDS}
                            for ex in rule["examples"]
                        ]
                    else:
                        detail[key] = rule[key]
                rules.append(detail)
            logger.info("读音规则加载完成：%d 条", len(rules))

    _RULES_CACHE = rules
    return rules


def list_rules(group: str | None = None) -> list:
    """RuleSummary[]：id/group/title/tier 四字段，按文件顺序；group 精确匹配。"""
    rules = load_rules()
    if group:
        rules = [r for r in rules if r["group"] == group]
    return [{key: rule[key] for key in SUMMARY_FIELDS} for rule in rules]


def get_rule(rule_id: str) -> dict | None:
    """从缓存按 id 查找，返回 RuleDetail（完整 10 字段）或 None。"""
    for rule in load_rules():
        if rule["id"] == rule_id:
            return rule
    return None
