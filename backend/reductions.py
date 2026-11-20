"""TASK-0071 v3.1 听力强化：法语口语缩略形（réductions colloquiales）纯函数库。

把书面法语转成口语缩略形，供「真实语速」变体音频的合成文本（content_pipeline/audio_batch）
与精听对照展示（routers/listen.py）使用。只收教科书公认的高频规则，宁缺勿错；
缩略形仅用于展示/合成，不改语料本体（texts.json / DB 全只读）。

零依赖、零副作用：audio_batch.py 用 importlib 按文件路径加载本模块
（backend 无 __init__.py，不作包导入），因此这里不得 import 其他后端模块。
"""
from __future__ import annotations

import re

# (pattern, replacement)：按序应用——先长短语后单条省音，避免被提前截断。
# 仅收高频、公认规则；\b 保证不误伤词内字母（如 nouvelle 不含独立 ne）。
_RULES: list[tuple[str, str]] = [
    # je ne V → j'V（口语吞 ne，"je ne sais pas"→"j'sais pas"）
    (r"\bje\s+ne\s+(?=\w)", "j'"),
    (r"\bil y en a\b", "y'en a"),
    (r"\bil y a\b", "y'a"),
    (r"\bparce que\b", "parc'que"),
    (r"\bce que\b", "c'que"),
    (r"\bce qui\b", "c'qui"),
    (r"\btu\s+es\b", "t'es"),
    (r"\btu\s+as\b", "t'as"),
    # tu/je + 辅音开头词 → t'/j'（元音前本就是标准省音，不在此列）
    (r"\btu\s+(?=[bcdfghjklmnpqrstvwxz])", "t'"),
    (r"\bje\s+(?=[bcdfghjklmnpqrstvwxz])", "j'"),
    # me/te/se + 辅音 → m'/t'/s'（"me trompe"→"m'trompe"）
    (r"\b([mts])e\s+(?=[bcdfghjklmnpqrstvwxz])", r"\1'"),
    # 其余否定 ne 吞掉（…pas 保留："tu ne sais pas"→"tu sais pas"）
    (r"\bne\s+(?=\w)", ""),
]

# 仅匹配被替换片段本身的首字母大小写（句首 Je → J'）
_LOWER_FIRST = re.compile(r"^[A-ZÀ-ÖØ-Þ]")


def _apply(match: "re.Match[str]", repl: str) -> str:
    out = match.expand(repl)
    if out and _LOWER_FIRST.match(match.group(0)) and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def reduce_sentence(text: str) -> str:
    """书面法语 → 口语缩略形。幂等（对已缩略文本重复调用不再变化）。"""
    if not text:
        return ""
    out = text
    for pattern, repl in _RULES:
        out = re.sub(pattern, lambda m: _apply(m, repl), out, flags=re.IGNORECASE)
    return re.sub(r"\s{2,}", " ", out).strip()
