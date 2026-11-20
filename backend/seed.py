"""首次启动灌入原型数据（幂等）。

数据来源：demo.html 的 SCENARIOS（场景配色/起始对话/生词），
并按契约 8.3 将 role 的 bot/me 映射为正式取值 assistant/user。
仅当空库（users 无 id=1）时灌入；已灌入则直接返回。
"""
from __future__ import annotations

import db

# ---------------------------------------------------------------- 默认用户

SEED_USER = {
    "id": 1,
    "username": "YU",
    "cefr_level": "A2",
    "target_level": "B2",
    "xp": 0,
    "streak_days": 0,
}

# ---------------------------------------------------------------- 场景种子数据
# start: role 已映射为 "assistant"/"user"；示例保留 demo 原文的弯引号。
# vocab: word/meaning/pos/example/pronunciation/cefr_level。
# reply_pool: 未命中纠错规则时轮转取用的场景接话（含通用兜底句）。

SEED_SCENES = [
    {
        "id": "cafe",
        "title": "在咖啡馆点单",
        "description": "日常交流 · A2 难度",
        "emoji": "☕",
        "color": "#FBEDE5",
        "cefr_level": "A2",
        "sort_order": 1,
        "start": [
            {"role": "assistant", "fr": "Bonjour ! Qu’est-ce que vous voulez ?", "cn": "你好！您想要点什么？"},
            {"role": "user", "fr": "Je veux un café, s’il vous plaît.", "cn": "我想要一杯咖啡，谢谢。"},
            {"role": "assistant", "fr": "Très bien ! Vous le voulez chaud ou froid ?", "cn": "好的！您要热的还是冷的？"},
        ],
        "vocab": [
            {"word": "un café", "meaning": "一杯咖啡", "pos": "n.m.", "example": "Je voudrais un café, s’il vous plaît.", "pronunciation": "ka.fe", "cefr_level": "A1"},
            {"word": "voudrais", "meaning": "想要（礼貌）", "pos": "条件式", "example": "Je voudrais un thé.", "pronunciation": "vu.dʁɛ", "cefr_level": "A2"},
            {"word": "chaud / froid", "meaning": "热 / 冷", "pos": "adj.", "example": "Vous le voulez chaud ou froid ?", "pronunciation": "ʃo / fʁwa", "cefr_level": "A2"},
        ],
        "extra_vocab": [
            {"word": "un thé", "meaning": "一杯茶", "pos": "n.m.", "example": "Je voudrais un thé.", "pronunciation": "œ̃ te", "cefr_level": "A1"},
            {"word": "un croissant", "meaning": "一个可颂", "pos": "n.m.", "example": "Un croissant, s’il vous plaît.", "pronunciation": "œ̃ kʁwa.sɑ̃", "cefr_level": "A2"},
        ],
        "reply_pool": [
            "Un croissant ! Bien sûr. Vous en voulez un autre ?",
            "Très bien, je vous apporte ça tout de suite.",
            "Ah, je vois ! Raconte-moi encore un peu.",
        ],
    },
    {
        "id": "office",
        "title": "和同事聊周末",
        "description": "职场闲聊 · B1 难度",
        "emoji": "💼",
        "color": "#EAF1FB",
        "cefr_level": "B1",
        "sort_order": 2,
        "start": [
            {"role": "assistant", "fr": "Salut ! Tu as fait quelque chose de sympa ce week-end ?", "cn": "嗨！这周末做了什么好玩的事吗？"},
            {"role": "user", "fr": "Oui, je suis allé au cinéma.", "cn": "是的，我去了电影院。"},
            {"role": "assistant", "fr": "Ah, cools ! Quel film as-tu vu ?", "cn": "哦不错！看了什么电影？"},
        ],
        "vocab": [
            {"word": "allé", "meaning": "去了", "pos": "过去分词", "example": "Je suis allé au cinéma.", "pronunciation": "a.le", "cefr_level": "A2"},
            {"word": "le week-end", "meaning": "周末", "pos": "n.m.", "example": "Tu as fait quelque chose ce week-end ?", "pronunciation": "lə wik.ɛnd", "cefr_level": "A2"},
            {"word": "un film", "meaning": "电影", "pos": "n.m.", "example": "J’ai vu un film français.", "pronunciation": "œ̃ film", "cefr_level": "A1"},
        ],
        "extra_vocab": [
            {"word": "le cinéma", "meaning": "电影院", "pos": "n.m.", "example": "Je suis allé au cinéma.", "pronunciation": "lə si.ne.ma", "cefr_level": "A1"},
            {"word": "un musée", "meaning": "博物馆", "pos": "n.m.", "example": "Je suis allé au musée.", "pronunciation": "œ̃ my.ze", "cefr_level": "A2"},
        ],
        "reply_pool": [
            "Vraiment ? Lequel ? J’adore les films français !",
            "Ah, je vois ! Raconte-moi encore un peu.",
            "C’est intéressant, raconte-moi encore un peu.",
        ],
    },
    {
        "id": "street",
        "title": "问路",
        "description": "出行 · A2 难度",
        "emoji": "🗺️",
        "color": "#E6F4EE",
        "cefr_level": "A2",
        "sort_order": 3,
        "start": [
            {"role": "user", "fr": "Excusez-moi, où est la gare, s’il vous plaît ?", "cn": "打扰一下，请问火车站在哪里？"},
            {"role": "assistant", "fr": "La gare ? C’est à cinq minutes d’ici, tout droit.", "cn": "火车站？离这五分钟，一直往前走。"},
            {"role": "user", "fr": "Merci beaucoup !", "cn": "非常感谢！"},
        ],
        "vocab": [
            {"word": "la gare", "meaning": "火车站", "pos": "n.f.", "example": "Où est la gare, s’il vous plaît ?", "pronunciation": "la ɡaʁ", "cefr_level": "A1"},
            {"word": "tout droit", "meaning": "一直走", "pos": "adv.", "example": "C’est à cinq minutes d’ici, tout droit.", "pronunciation": "tu dʁwa", "cefr_level": "A2"},
            {"word": "à pied", "meaning": "步行", "pos": "loc.", "example": "Tu peux y aller à pied.", "pronunciation": "a pje", "cefr_level": "A2"},
        ],
        "extra_vocab": [
            {"word": "cinq minutes", "meaning": "五分钟", "pos": "loc.", "example": "C’est à cinq minutes d’ici.", "pronunciation": "sɛ̃k mi.nyt", "cefr_level": "A1"},
            {"word": "la tête", "meaning": "头", "pos": "n.f.", "example": "J’ai mal à la tête.", "pronunciation": "la tɛt", "cefr_level": "A1"},
        ],
        "reply_pool": [
            "Non, pas du tout ! Tu peux y aller à pied.",
            "Ah, je vois ! Raconte-moi encore un peu.",
            "D’accord, je comprends. Raconte-moi encore.",
        ],
    },
    {
        "id": "doctor",
        "title": "看医生",
        "description": "生活办事 · B1 难度",
        "emoji": "🩺",
        "color": "#FBF1DC",
        "cefr_level": "B1",
        "sort_order": 4,
        "start": [
            {"role": "assistant", "fr": "Bonjour, qu’est-ce qui ne va pas ?", "cn": "你好，哪里不舒服？"},
            {"role": "user", "fr": "J’ai mal à la tête depuis hier.", "cn": "我从昨天起就头疼。"},
            {"role": "assistant", "fr": "D’accord. Vous avez de la fièvre ?", "cn": "好的。您发烧吗？"},
        ],
        "vocab": [
            {"word": "avoir mal à", "meaning": "……疼", "pos": "loc.", "example": "J’ai mal à la tête.", "pronunciation": "a.vwaʁ mal a", "cefr_level": "A2"},
            {"word": "la fièvre", "meaning": "发烧", "pos": "n.f.", "example": "Vous avez de la fièvre ?", "pronunciation": "la fjɛvʁ", "cefr_level": "A2"},
            {"word": "la douleur", "meaning": "疼痛", "pos": "n.f.", "example": "Je vais vous donner quelque chose pour la douleur.", "pronunciation": "la du.lœʁ", "cefr_level": "B1"},
        ],
        "extra_vocab": [
            {"word": "de la fièvre", "meaning": "发烧", "pos": "loc.", "example": "J’ai de la fièvre.", "pronunciation": "də la fjɛvʁ", "cefr_level": "A2"},
            {"word": "la tête", "meaning": "头", "pos": "n.f.", "example": "J’ai mal à la tête.", "pronunciation": "la tɛt", "cefr_level": "A1"},
        ],
        "reply_pool": [
            "Bien. Je vais vous donner quelque chose pour la douleur.",
            "Ah, je vois ! Raconte-moi encore un peu.",
            "D’accord. Raconte-moi encore un peu.",
        ],
    },
]


def get_scene_seed(scene_id: str):
    """给 ai.py 用：取场景种子（词表 / 接话池 / 元数据）。"""
    for s in SEED_SCENES:
        if s["id"] == scene_id:
            return s
    return None


def seed_if_empty() -> None:
    """空库灌入；按 users.id=1 判存在，重复调用不重复插入。"""
    conn = db.get_conn()
    try:
        existing = conn.execute("SELECT 1 FROM users WHERE id = 1").fetchone()
        if existing:
            return

        today = db.today_str()
        conn.execute(
            "INSERT INTO users (id, username, cefr_level, target_level, xp, streak_days, "
            "last_active_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                SEED_USER["id"],
                SEED_USER["username"],
                SEED_USER["cefr_level"],
                SEED_USER["target_level"],
                SEED_USER["xp"],
                SEED_USER["streak_days"],
                today,
                db.now_iso(),
            ),
        )

        for scene in SEED_SCENES:
            conn.execute(
                "INSERT OR IGNORE INTO scenes "
                "(id, title, description, emoji, color, cefr_level, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    scene["id"],
                    scene["title"],
                    scene["description"],
                    scene["emoji"],
                    scene["color"],
                    scene["cefr_level"],
                    scene["sort_order"],
                ),
            )
            # 起始对话：created_at IS NULL 作为「预置」标记
            for turn in scene["start"]:
                conn.execute(
                    "INSERT INTO dialogue_turns "
                    "(user_id, scene_id, role, fr, cn, recast_of, explanation, "
                    "is_correction, created_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, NULL)",
                    (
                        SEED_USER["id"],
                        scene["id"],
                        turn["role"],
                        turn["fr"],
                        turn["cn"],
                    ),
                )
        conn.commit()
    finally:
        conn.close()

    # 生词卡 + 初始 review_logs 走 db.create_card（内部含查重，幂等）
    for scene in SEED_SCENES:
        for v in scene["vocab"]:
            db.create_card(
                user_id=SEED_USER["id"],
                word=v["word"],
                meaning=v.get("meaning"),
                pos=v.get("pos"),
                example=v.get("example"),
                pronunciation=v.get("pronunciation"),
                cefr_level=v.get("cefr_level"),
                source_scene_id=scene["id"],
            )
