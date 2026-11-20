"""输入语料加载器：启动时把 data/input/texts.json 同步入 SQLite（幂等）。

契约 ARCHITECTURE_V2.md §5.4 / §5.5：
- 文件不存在 → info 日志跳过，不阻断启动；
- 单条非法 → warning 日志跳过该条，不影响其余条与服务启动；
- 合法条用 INSERT ... ON CONFLICT(id) DO UPDATE，行表先删后插；
- word_count 由 body_fr 正则计算；audio_text 为空时用 body_fr 填充；
- created_at 首次生成、更新时保留；updated_at 每次刷新；
- 全程复用 db.get_conn()，不新开连接方式。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import db

logger = logging.getLogger("yaya.seed_input")

INPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "input"
INPUT_FILE = INPUT_DIR / "texts.json"

# v2.3：语料量产覆盖 A1–B2 四档（A1 语料由内容工厂产出；定级逻辑属 v2.2 车道，与本加载器无关）
VALID_LEVELS = {"A1", "A2", "B1", "B2"}
VALID_FORMATS = {"dialogue", "monologue"}

# v2.3 音频批量预生成的落盘目录（cache，不入 git）；存在则用本地取音端点填充 audio_url
_AUDIO_CACHE = INPUT_DIR.parent / "cache" / "content_pipeline" / "audio"


def _audio_url(text_id: str, seq: int | None = None) -> str | None:
    """若批量音频已落盘，返回本地取音端点 URL；否则 None（前端回退在线 TTS）。"""
    rel = f"/api/content/audio/{text_id}/{seq}" if seq is not None else None
    if seq is not None:
        p = _AUDIO_CACHE / str(text_id) / f"{seq}.mp3"
        return rel if p.is_file() and p.stat().st_size > 0 else None
    # 整篇 audio_url：任意一句有音频即指向第 1 句（前端逐句用 line.audio_url）
    first = _AUDIO_CACHE / str(text_id) / "1.mp3"
    return f"/api/content/audio/{text_id}/1" if first.is_file() and first.stat().st_size > 0 else None



def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_text(item) -> bool:
    """§5.4 必填字段校验；单条不满足返回 False（由调用方跳过）。"""
    if not isinstance(item, dict):
        return False
    required_str = ("id", "title", "topic", "body_fr", "body_cn")
    if any(not _nonempty_str(item.get(k)) for k in required_str):
        return False
    if item.get("format") not in VALID_FORMATS:
        return False
    if item.get("cefr_level") not in VALID_LEVELS:
        return False
    lines = item.get("lines")
    if not isinstance(lines, list) or len(lines) < 1:
        return False
    for line in lines:
        if not isinstance(line, dict):
            return False
        seq = line.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            return False
        if not isinstance(line.get("fr"), str) or not isinstance(line.get("cn"), str):
            return False
    return True


def _upsert_one(conn, item: dict) -> None:
    """写入单条合法语料（调用方已开 SAVEPOINT，异常时整体回滚该条）。"""
    text_id = item["id"]
    now = db.now_iso()
    body_fr = item["body_fr"]

    word_count = len(re.findall(r"[A-Za-zÀ-ÿ]+", body_fr))
    audio_text = item.get("audio_text")
    if not _nonempty_str(audio_text):
        audio_text = body_fr
    audio_url = item.get("audio_url")
    if not _nonempty_str(audio_url):
        audio_url = _audio_url(text_id)  # v2.3：批量音频已落盘则自动填充
    sort_order = item.get("sort_order", 0)
    if not isinstance(sort_order, int) or isinstance(sort_order, bool):
        sort_order = 0

    existing = conn.execute(
        "SELECT created_at FROM input_texts WHERE id = ?", (text_id,)
    ).fetchone()
    created_at = existing["created_at"] if existing else now

    conn.execute(
        """
        INSERT INTO input_texts
            (id, title, format, cefr_level, topic, body_fr, body_cn,
             audio_url, audio_text, word_count, sort_order, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title,
            format=excluded.format,
            cefr_level=excluded.cefr_level,
            topic=excluded.topic,
            body_fr=excluded.body_fr,
            body_cn=excluded.body_cn,
            audio_url=excluded.audio_url,
            audio_text=excluded.audio_text,
            word_count=excluded.word_count,
            sort_order=excluded.sort_order,
            created_at=input_texts.created_at,
            updated_at=excluded.updated_at
        """,
        (
            text_id,
            item["title"],
            item["format"],
            item["cefr_level"],
            item["topic"],
            body_fr,
            item["body_cn"],
            audio_url if isinstance(audio_url, str) and audio_url else None,
            audio_text,
            word_count,
            sort_order,
            created_at,
            now,
        ),
    )

    # 语料改版同步：行表先按 text_id 删除旧行再插入。
    conn.execute("DELETE FROM input_lines WHERE text_id = ?", (text_id,))
    conn.execute("DELETE FROM input_words WHERE text_id = ?", (text_id,))

    valid_seqs = {line["seq"] for line in item["lines"]}
    for line in item["lines"]:
        speaker = line.get("speaker")
        if item["format"] == "dialogue" and speaker not in ("A", "B"):
            speaker = None
        elif item["format"] == "monologue":
            speaker = None
        line_audio = line.get("audio_url")
        if not _nonempty_str(line_audio):
            line_audio = _audio_url(text_id, line["seq"])  # v2.3：逐句批量音频
        conn.execute(
            "INSERT INTO input_lines "
            "(text_id, seq, speaker, fr, cn, audio_url) VALUES (?, ?, ?, ?, ?, ?)",
            (
                text_id,
                line["seq"],
                speaker,
                line["fr"],
                line["cn"],
                line_audio if isinstance(line_audio, str) and line_audio else None,
            ),
        )

    raw_words = item.get("words")
    if not isinstance(raw_words, list):
        raw_words = []
    for word_item in raw_words:
        if not isinstance(word_item, dict):
            continue
        word, meaning = word_item.get("word"), word_item.get("meaning")
        if not (_nonempty_str(word) and _nonempty_str(meaning)):
            logger.warning("语料 %s 跳过非法生词条目：%r", text_id, word_item)
            continue
        line_seq = word_item.get("line_seq")
        if not isinstance(line_seq, int) or isinstance(line_seq, bool):
            line_seq = None
        elif line_seq not in valid_seqs:
            line_seq = None

        def clean_str(value):
            return value.strip() if isinstance(value, str) and value.strip() else None

        conn.execute(
            "INSERT INTO input_words "
            "(text_id, line_seq, word, meaning, pos, cefr_level, example, "
            "pronunciation, word_card_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                text_id,
                line_seq,
                word.strip(),
                meaning.strip(),
                clean_str(word_item.get("pos")),
                clean_str(word_item.get("cefr_level")),
                clean_str(word_item.get("example")),
                clean_str(word_item.get("pronunciation")),
            ),
        )


def load_input_corpus() -> None:
    """加载全部语料；幂等，可重复调用。任何异常都不阻断服务启动。"""
    if not INPUT_FILE.is_file():
        logger.info("输入语料文件不存在（%s），跳过输入流加载。", INPUT_FILE)
        return

    try:
        data = json.loads(INPUT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("输入语料文件读取/解析失败，跳过加载：%s", exc)
        return

    if not isinstance(data, dict) or not isinstance(data.get("texts"), list):
        logger.warning("输入语料顶层结构非法（应为 {version, texts:[]}），跳过加载。")
        return

    conn = db.get_conn()
    loaded = 0
    try:
        for index, item in enumerate(data["texts"]):
            if not _validate_text(item):
                logger.warning(
                    "跳过非法语料条目 #%d：id=%r",
                    index,
                    item.get("id") if isinstance(item, dict) else None,
                )
                continue
            conn.execute("SAVEPOINT sp_input_item")
            try:
                _upsert_one(conn, item)
                conn.execute("RELEASE sp_input_item")
                loaded += 1
            except Exception as exc:  # 单条写失败只回滚该条，不阻断其余语料
                conn.execute("ROLLBACK TO sp_input_item")
                conn.execute("RELEASE sp_input_item")
                logger.warning("语料 %s 写入失败，跳过该条：%s", item.get("id"), exc)
        conn.commit()
    finally:
        conn.close()

    logger.info("输入语料加载完成：成功 %d 篇。", loaded)
