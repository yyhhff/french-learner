"""阶段0 CEFR 定级：题库加载、判分定级、中文解读（ARCHITECTURE_PLACEMENT.md v1.2 / v2.2 A1 四档）。

零外部依赖：解读由本地中文模板生成，不调用 GLM、不发任何网络请求。
所有阈值/文案集中在本模块，app.py 只做路由与校验。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("yaya.assessment")

# 题库与 texts.json 同目录（项目根 data/input）
INPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "input" / "assessment_questions.json"

# 常量（§4.1 / §8.3，禁止在 app.py 散落魔数）
# v2.2 四档：A1/A2/B1/B2 各 6 题（词汇/语法/理解各 2），加权满分 6*6=36。
LEVELS = ("A1", "A2", "B1", "B2")
SKILLS = ("词汇", "语法", "理解")
SKILL_ORDER = ["词汇", "语法", "理解"]
WEIGHT = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}
MAX_WEIGHTED = 36  # 6 题 * (0+1+2+3)，仅供前端进度条；判定级不用总分

# §5 中文解读模板（逐字）
INTERPRETATION_BY_LEVEL = {
    "A1": "欢迎来到法语的世界！从最基础的招呼和自我介绍开始，先把读音和高频词练熟，你就已经迈出最棒的一步啦。",
    "A2": "你已经掌握了基础法语，能应对简单日常交流；接下来可以扩充词汇量，练习过去时和简单描述，继续保持就很棒。",
    "B1": "你的法语基础扎实，能就熟悉话题展开交流；建议加强复合时态与虚拟式入门，并提升听说流利度，离进阶不远啦。",
    "B2": "你的法语水平已经相当不错，能较自如地表达观点；接下来可挑战更复杂的阅读与原声听力，向更高阶稳步前进。",
}
WEAK_HINT = "{weak_skill}是你接下来可以多花点时间的地方。"
PUBLIC_FIELDS = ("id", "level", "skill", "question", "options")

# 进程内缓存：None 表示尚未加载；加载后固定为 list（含空表 []），幂等。
_QUESTIONS_CACHE = None


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_question(q) -> bool:
    """§2.2 单题逐字段校验；非法返回 False 由调用方跳过。"""
    if not isinstance(q, dict):
        return False
    if not _nonempty_str(q.get("id")):
        return False
    if q.get("level") not in LEVELS:
        return False
    if q.get("skill") not in SKILLS:
        return False
    if not _nonempty_str(q.get("question")):
        return False
    options = q.get("options")
    if not isinstance(options, list) or len(options) != 4:
        return False
    if any(not _nonempty_str(o) for o in options):
        return False
    if len({o.strip() for o in options}) != 4:
        return False
    answer_idx = q.get("answer_idx")
    if not isinstance(answer_idx, int) or isinstance(answer_idx, bool):
        return False
    if not 0 <= answer_idx <= 3:
        return False
    if not _nonempty_str(q.get("explanation_zh")):
        return False
    return True


def load_questions() -> list:
    """加载并校验题库；进程内缓存、幂等；文件缺失/异常降级为空表不抛异常。"""
    global _QUESTIONS_CACHE
    if _QUESTIONS_CACHE is not None:
        return _QUESTIONS_CACHE

    questions: list = []
    try:
        with INPUT_FILE.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        logger.warning("定级题库文件不存在：%s，题库降级为空", INPUT_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("定级题库加载失败：%s，题库降级为空", exc)
    else:
        raw = payload.get("questions") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            logger.warning("定级题库 questions 字段非法，题库降级为空")
        else:
            seen: set = set()
            for item in raw:
                if not _valid_question(item):
                    logger.warning("跳过非法定级题：%s", item.get("id") if isinstance(item, dict) else item)
                    continue
                if item["id"] in seen:
                    logger.warning("跳过重复 id 的定级题：%s", item["id"])
                    continue
                seen.add(item["id"])
                questions.append(item)
            logger.info("定级题库加载完成：%d 题", len(questions))

    _QUESTIONS_CACHE = questions
    return questions


def public_questions(questions: list) -> list:
    """PUBLIC_FIELDS 白名单投影：绝不下发 answer_idx / explanation_zh。"""
    return [{key: q[key] for key in PUBLIC_FIELDS} for q in questions]


def level_from_counts(c_a1: int, c_a2: int, c_b1: int, c_b2: int) -> str:
    """v1.2 §4.3 四档定级：分组下限优先；最高档需本级与其下各级均 >=4，保底 A1。

    每档 6 题，门槛 4/6（约 67%）。低档未达标时不因高档答对而跳级
    （防零基础蒙对个别 B 档题却落高档）；全档未达标落 A1。
    """
    if c_b2 >= 4 and c_b1 >= 4 and c_a2 >= 4 and c_a1 >= 4:
        return "B2"
    if c_b1 >= 4 and c_a2 >= 4 and c_a1 >= 4:
        return "B1"
    if c_a2 >= 4 and c_a1 >= 4:
        return "A2"
    return "A1"


def weak_skill(flags: list) -> str:
    """§4.2：按 skill 正确率取最低；并列按 词汇 < 语法 < 理解。"""
    acc = {skill: [0, 0] for skill in SKILL_ORDER}  # [答对数, 题数]
    for flag in flags:
        pair = acc[flag["skill"]]
        pair[1] += 1
        if flag["correct"]:
            pair[0] += 1
    return min(
        SKILL_ORDER,
        key=lambda s: (acc[s][0] / acc[s][1] if acc[s][1] else 1.0, SKILL_ORDER.index(s)),
    )


def grade(answers: list, questions: list) -> dict:
    """§4.2 判分伪码：按 id 匹配（不信顺序），产出算分结果与逐题明细。"""
    index = {q["id"]: q for q in questions}
    total = len(questions)

    correct_flags = []
    for answer in answers:
        q = index[answer["id"]]
        correct = answer["answer_idx"] == q["answer_idx"]
        correct_flags.append(
            {
                "id": answer["id"],
                "level": q["level"],
                "skill": q["skill"],
                "answer_idx": answer["answer_idx"],
                "correct": bool(correct),
            }
        )

    score = sum(1 for flag in correct_flags if flag["correct"])
    counts = {level: 0 for level in LEVELS}
    for flag in correct_flags:
        if flag["correct"]:
            counts[flag["level"]] += 1
    weighted_score = sum(counts[level] * WEIGHT[level] for level in LEVELS)

    return {
        "score": score,
        "weighted_score": weighted_score,
        "level": level_from_counts(counts["A1"], counts["A2"], counts["B1"], counts["B2"]),
        "rate": round(score / total, 4) if total else 0.0,
        "weak_skill": weak_skill(correct_flags),
        "correct_flags": correct_flags,
    }


def interpretation_zh(level: str, weak_skill: str, score: int, total: int, rate: float) -> str:
    """§5：固定前缀 + 等级文案 + 薄弱维度提示，逐字拼接、温和鼓励式。"""
    rate_pct = int(round(rate * 100))
    prefix = f"本次定级共 {total} 题，答对 {score} 题，正确率 {rate_pct}%。"
    return prefix + INTERPRETATION_BY_LEVEL[level] + WEAK_HINT.format(weak_skill=weak_skill)
