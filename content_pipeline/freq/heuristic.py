"""已知词覆盖率启发式（降级方案，非官方词频表）。

背景：MASTER_PLAN v2.3 要求 CC 许可法语词频表计算 i+1 生词覆盖率；本环境无合规词频
表、且不能引入不可信来源。按风险 2 降级为「内置高频功能词 + 现有语料生词表」基线：

- 内置词表：法语最高频的功能词/常见实词（这是一个教学用的近似集合，非词频排名），
  license=CC0（本人整理，允许商用）；
- 动态词表：从 data/input/texts.json 的 input_words 抽取已标注生词（属本项目语料，
  随语料增长而扩充，形成正反馈）；
- coverage = 命中基线的词元数 / 正文词元总数（不去重，按出现计），用于粗判 i+1 难度；
  目标区间按 MASTER_PLAN 的 95–98% 设计，但**此数值是启发式近似，非词频学精确值**，
  文档已标注，不得作为语言学精确承诺。

对外：build_known_words() -> set[str]；coverage(body_fr, known) -> float | None。
"""
from __future__ import annotations

import json
import re

from content_pipeline.paths import TEXTS_FILE

# 内置高频词（教学近似，CC0）。含冠词/代词/介词/连词/助动词/高频实词/常见屈折形。
# 说明：这是"识别得出算已知"的下限集合，宁可保守。
CORE_WORDS = """
le la les un une des de du au aux et ou mais oui non ne pas plus très bien tout tous toute toutes
je tu il elle nous vous ils elles on ce cet cette ces mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs
me te se nous vous lui leur y en que qui quoi dont où quand comment pourquoi est-ce c est c est
être etre est suis es sommes êtes sont étais était étions étiez étaient serai sera seront
avoir ai as avons avez ont eu avait avaient aurai aura auront
aller vais vas va allons allez vont allé allée allais allait
faire fais fait faisons faites font fait
pouvoir peux peut pouvons pouvez peuvent pourra
vouloir veux veut voulons voulez veulent voudrais voudriez
devoir dois doit devons devez doivent
savoir sais sait savons savez savent
voir vois voit voyons voyez voient vu
dire dis dit disons dites disent
prendre prends prend prenons prenez prennent pris
donner donne donnons donnez donné
venir viens vient venons venez viennent venu
aller chez pour dans sur sous avec sans par vers entre devant derrière près loin
ici là maintenant toujours souvent jamais encore déjà aussi seulement vraiment beaucoup peu trop assez
bien mal vite lent doucement
bon bonne bonnes bons beau belle belles beaux gentil gentille joli jolie
petit petite petits petites grand grande grands grandes gros grosse
nouveau nouvelle nouveaux nouvelles vieux vieille vieilles
aujourd hui demain hier matin midi soir nuit jour jours semaine mois année ans
mais parce que comme si donc alors ensuite puis enfin
combien quel quelle quels quelles lequel laquelle
s il vous plaît merci pardon bonjour bonsoir au revoir salut excusez excuse moi
oui non d accord peut être peut-etre peut-être
je vais je veux je voudrais j ai j ai il y a il y avait
c est c est il est elle est ce sont
la le les du de des un une
jeune homme femme enfant ami amie gens monsieur madame mademoiselle
maison école travail bureau ville rue pays France français française
manger boire dormir parler écrire lire ouvrir fermer attendre chercher trouver
nouveau aujourd hui
un une deux trois quatre cinq six sept huit neuf dix
premier première dernier dernière
""".split()

# 归一化：小写、去重音、仅保留字母（法语连字符/撇号按空格处理）
def normalize(token: str) -> str:
    token = token.lower().strip()
    token = re.sub(r"[àâäáãå]", "a", token)
    token = re.sub(r"[éèêë]", "e", token)
    token = re.sub(r"[îïíì]", "i", token)
    token = re.sub(r"[ôöòóõ]", "o", token)
    token = re.sub(r"[ûùúü]", "u", token)
    token = re.sub(r"[ç]", "c", token)
    token = re.sub(r"[œ]", "oe", token)
    return token


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿœŒ]+(?:['’][A-Za-zÀ-ÿ]+)?")


def build_known_words() -> set[str]:
    known = {normalize(w) for w in CORE_WORDS if w.strip()}
    if TEXTS_FILE.is_file():
        try:
            data = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
            for item in data.get("texts", []):
                for w in item.get("words", []):
                    word = w.get("word") if isinstance(w, dict) else None
                    if isinstance(word, str) and word.strip():
                        # 生词短语按词拆开（"une baguette" -> une / baguette）
                        for tok in TOKEN_RE.findall(word):
                            known.add(normalize(tok))
        except (OSError, ValueError):
            pass
    return known


def coverage(body_fr: str, known: set[str]) -> float | None:
    tokens = TOKEN_RE.findall(body_fr or "")
    if not tokens:
        return None
    hits = sum(1 for t in tokens if normalize(t) in known)
    return round(hits / len(tokens), 4)


if __name__ == "__main__":
    k = build_known_words()
    print(f"已知词基线 {len(k)} 个")
    if TEXTS_FILE.is_file():
        data = json.loads(TEXTS_FILE.read_text(encoding="utf-8"))
        for item in data.get("texts", [])[:3]:
            print(item["id"], coverage(item["body_fr"], k))
