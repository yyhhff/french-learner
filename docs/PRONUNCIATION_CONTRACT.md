# 呀呀法语 · 零基础读音规则学习 字段级冻结契约（PRONUNCIATION_CONTRACT v1.0）

> 本文是「零基础读音规则学习」功能的**后端 / 前端 / 内容 / 测试 / PM 唯一实现契约**。所有字段名、端点路径、JSON 结构、表结构必须逐字实现，不得自行改名、改值、增删字段。
> **上游约束**：`docs/PRONUNCIATION_PLAN.md` v1.0（已确认：§10 四项全部按推荐，规则 JSON schema 已在 §6.4 锁定，进度表字段已在 §5.1 锁定）。本文**只做字段与实现级细化**，上游所有【锁定】项一律不重新定义、不改动。若本文与上游冲突，以上游为准。
> **锁定项来源**：规则 JSON 字段逐字来自 §6.4；`pronunciation_progress` 六字段逐字来自 §5.1；4 端点路径/语义来自 §7.2；错误码来自 §7.2；`/ɑ̃/` 口径来自 §6.4 注。本文对这些项**只细化、不改动**；任何无法在细化层解决的歧义，写入 §7「待裁决」，不自作主张。
> 日期：2026-11-18　读者：后端工程师、前端工程师、内容工程师、测试工程师、PM。

---

## 0. 契约地位与通用约定（沿用现有工程口径）

| 项 | 约定 |
|----|------|
| 功能定位 | 融入式读音学习（**不新增第 5 个 Tab**），P0 最小闭环：词卡融入点 + 小册子索引 + 规则卡讲解/🔊 + 过渡态进度读写；跟读/P1、全域融入/P2 见 PRONUNCIATION_PLAN §8 |
| 统一响应 | 成功 `{code:0, data:..., message:"ok"}`；失败 `{code:<非0>, data:null, message:"..."}`；复用 `app.py::ok()` / `ApiError` |
| 错误码 | **仅 `0 / 40001 / 40401 / 50001`，本文不新增**。`0`=成功(200)、`40001`=参数错(400)、`40401`=规则不存在(404)、`50001`=内部(500)。**任何"规则不存在"统一 `40401`**（含详情与进度更新） |
| 命名/时间 | `snake_case`；时间 ISO8601 UTC 秒精度 + `Z`（`YYYY-MM-DDTHH:MM:SSZ`），复用 `db.now_iso()`；空值 `null`；布尔库内 INTEGER 0/1、出参转 `bool` |
| 用户口径 | 单用户过渡态：`user_id = db.DEFAULT_USER_ID`（=1）。**所有 SQL 查询必须显式带 `user_id`**，为多用户演进铺路（PRONUNCIATION_PLAN §5.1 / §7.1） |
| 零依赖 | `backend/requirements.txt` 仍仅 `fastapi`、`uvicorn` 两行（不新增任何库） |
| 隐私红线 | **不存用户音频、不存原始转写文本**；服务端只存规则级掌握状态（PRONUNCIATION_PLAN §5.1 / §7.4） |
| 音位口径 | `/ɑ̃/`（鼻化元音）为**全库统一写法**，不是笔误、**不进易混等价集**；`/ɑ/` 是另一个音位，不得混写（PRONUNCIATION_PLAN §6.4 注） |

---

## 1. 改动清单（涉及文件逐项）

| 文件 | 改动类型 | 具体内容 | 备注 |
|------|----------|----------|------|
| `backend/db.py` | 改（增量） | ① `DDL` 字符串追加 `pronunciation_progress` 建表 + 索引（§2.1）；② 追加进度 CRUD 出参/函数 | **现有表结构一字不改**；只加一张新表 + 新函数 |
| `backend/pronunciation.py` | **新增** | 规则 JSON 加载 + 进程内缓存 `load_rules()`、列表/详情查询；参考 `exam.py::load_papers()` 模式 | 逻辑集中、可单测；`app.py` 只做路由/校验 |
| `backend/app.py` | 改（增量） | ① `import pronunciation`；② `app.mount("/")` **之前**追加 4 端点（§3）；③ 启动流程末尾追加 `pronunciation.load_rules()`（幂等，try/except 包裹，文件缺失不阻断） | 现有 **21 个端点全部保留、路径/入参/出参不变** |
| `data/input/pronunciation_rules.json` | **新增** | 39 条规则（schema 见 §2.2） | 内容角色产出；与 `exam_papers.json` 同目录 |
| `frontend/*` | 改（增量，非本契约冻结范围） | 小册子索引、规则卡浮层、🔊 复用 `/api/tts`、🎙 复用 `transcribeExamAudio()` 独立链路、评分纯函数 | 详见 PRONUNCIATION_PLAN §7.3；**评分纯函数不放服务端** |
| `backend/requirements.txt` | **不改** | 仍两行 | 硬性约束 |

> 新 4 路由必须在 `app.mount("/", ...)` **之前**声明，否则被静态目录接管（沿用 `ARCHITECTURE_EXAM.md` 的零回归要求）。

---

## 2. 数据模型

### 2.1 `pronunciation_progress` 表 DDL【字段逐字来自 PRONUNCIATION_PLAN §5.1】

**可直接执行的语句**（追加到 `db.py::DDL` 字符串，随 `init_db()` 的 `executescript` 自动建表）：

```sql
-- ===== 读音规则学习增量：规则级掌握度（旧表结构一字不改）=====
CREATE TABLE IF NOT EXISTS pronunciation_progress (
    user_id           INTEGER NOT NULL,
    rule_id           TEXT    NOT NULL,
    stage             TEXT    NOT NULL CHECK (stage IN ('seen', 'learned', 'confident')),
    practice_count    INTEGER NOT NULL DEFAULT 0,
    last_practiced_at TEXT,
    self_assessed     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, rule_id)
);

CREATE INDEX IF NOT EXISTS idx_pron_progress_user ON pronunciation_progress (user_id);
CREATE INDEX IF NOT EXISTS idx_pron_progress_user_stage ON pronunciation_progress (user_id, stage);
```

**逐字段定义（锁定六字段，类型/默认逐字）**

| 字段 | 类型 | 必填/默认 | 示例值 | 说明 |
|------|------|-----------|--------|------|
| `user_id` | INTEGER | NOT NULL，无默认 | `1` | 用户 id，取 `db.DEFAULT_USER_ID`；复合主键第一列 |
| `rule_id` | TEXT | NOT NULL，无默认 | `"ph_comb_02"` | 规则 id，须存在于规则 JSON；复合主键第二列 |
| `stage` | TEXT | NOT NULL，CHECK `('seen','learned','confident')` | `"learned"` | 掌握阶段枚举：`seen`=见过、`learned`=学过、`confident`=能自己读 |
| `practice_count` | INTEGER | NOT NULL，DEFAULT `0` | `3` | 接触/跟读次数（非负整数） |
| `last_practiced_at` | TEXT | 可空，无默认 | `"2026-11-18T09:30:00Z"` | 最近一次练习的 UTC 时间，服务端用 `db.now_iso()` 写入；不接受客户端传入 |
| `self_assessed` | INTEGER | NOT NULL，DEFAULT `0` | `1` | 用户自评标记（库内 0/1，出参转 `bool`）；语义细化见 §3.4 与 §7 |

**主键与索引说明（细化）**

- 主键 `PRIMARY KEY (user_id, rule_id)`：一条 `(用户, 规则)` 只有一行，POST 按此主键 upsert（幂等）。
- `idx_pron_progress_user`：`GET /progress` 按 `user_id` 取全部记录；复合主键最左前缀本可覆盖，显式索引使意图清晰、便于多用户演进。
- `idx_pron_progress_user_stage`：小册子按 `stage` 分组统计「已学 N/39、能自己读 M 条」，避免全表扫描。
- 两索引均为 `IF NOT EXISTS`，重复执行无害。

**隐私与粒度边界（锁定口径）**

- 本表**只有上述六列**：**不存用户音频、不存原始转写文本**。跟读音频在 ASR 服务侧写完临时文件即 `os.unlink`，转写结果只在内存供前端评分使用，绝不落库。
- 与 `word_cards.pronunciation` **数据粒度不同、互不覆盖、互不读写**：
  - `word_cards.pronunciation` 是**词级静态文本字段**（某单词自带的音标/读音展示），随生词卡产生。
  - `pronunciation_progress` 是**规则级动态掌握状态**（用户 × 规则的 seen/learned/confident）。
  - 二者不共享字段、不互相覆盖；前端小册子的进度只读本表，不读 `word_cards.pronunciation`。
- 一致性：将来并入「我的成长」时同源读取本表，不重复记录（PRONUNCIATION_PLAN §5.2）。

### 2.2 规则 JSON `data/input/pronunciation_rules.json` Schema【逐字来自 PRONUNCIATION_PLAN §6.4】

**文件**：`french-learner/data/input/pronunciation_rules.json`，UTF-8，中文/法语直接写字符（`ensure_ascii=false` 风格），顶层对象含 `rules` 数组（39 条）。**落盘文件另含可选元数据键 `version`（当前值 `1`）**：后端加载器**只读 `payload["rules"]`，不依赖 `version`**（该键为内容版本标记，不参与契约字段校验）。

> **字段名锁定**：以下字段名来自 content 实际产出并经架构师确认，**逐字照用**。绝不允许改用 `word` / `highlight` / `read_aloud` 等旧名（PRONUNCIATION_PLAN §6.4 / §9）。

**完整示例（逐字照抄 §6.4，字段名一字不改）**

```json
{
  "rules": [
    {
      "id": "ph_comb_02",
      "group": "元音字母组合",
      "title": "ai / ay 读 /ɛ/",
      "description_zh": "字母组合 ai 和 ay 通常读 /ɛ/，嘴巴张开、舌头放平，像短促的『哎』。",
      "examples": [
        { "word_fr": "maison", "meaning_zh": "房子", "note_zh": "ai 在词中读 /ɛ/", "phonetic": "/mɛ.zɔ̃/" },
        { "word_fr": "chaise", "meaning_zh": "椅子", "note_zh": "同样的 ai 音", "phonetic": "/ʃɛz/" }
      ],
      "audio_text": "maison, chaise, lait",
      "shadow_text_fr": "maison",
      "shadow_mode": "word",
      "tier": "starter",
      "tags": ["D组", "元音组合"]
    }
  ]
}
```

**逐字段定义（内容角色与后端加载器必读）**

| 路径 | 必填 | 类型/取值 | 示例值 | 说明 |
|------|:---:|-----------|--------|------|
| `rules` | 是 | array，长度目标 **39** | — | 顶层数组；加载器校验后缓存 |
| `rules[].id` | 是 | string，`ph_<段名>_<nn>`，全库唯一 | `"ph_comb_02"` | 规则 id；★裁决⑧：`<段名>` 为 8 个英文段名 `alpha/vowel/cons/comb/ccomb/nasal/final/except` 之一（**非 A–H 字母**），`<nn>` 两位序号 |
| `rules[].group` | 是 | string，8 个分组名之一 | `"元音字母组合"` | 分组纯组名，取值见下 |
| `rules[].title` | 是 | string | `"ai / ay 读 /ɛ/"` | 规则标题 |
| `rules[].description_zh` | 是 | string | 见示例 | 中文规则讲解 |
| `rules[].examples` | 是 | array，**锁定恰好 4 条** | 见示例 | 例词列表；★总指挥裁决①：全库每条 4 例词 = 156 IPA 槽位全配（原「2–4 弹性」作废） |
| `rules[].examples[].word_fr` | 是 | string | `"maison"` | 法语例词 |
| `rules[].examples[].meaning_zh` | 是 | string | `"房子"` | 中文释义 |
| `rules[].examples[].note_zh` | 是 | string | `"ai 在词中读 /ɛ/"` | 规则体现说明 |
| `rules[].examples[].phonetic` | 是（实际全量） | string，宽式 IPA，斜杠包裹、音节用 `.` 分隔 | `"/mɛ.zɔ̃/"` | schema 标可选但已全量配齐；前端内存建 `word_fr → IPA` Map |
| `rules[].audio_text` | 是 | string | `"maison, chaise, lait"` | **只喂 TTS 作"听"的示范，不作比对目标** |
| `rules[].shadow_text_fr` | 是 | string | `"maison"` | **跟读比对目标** |
| `rules[].shadow_mode` | 是 | string，`syllable` / `word` / `phrase` | `"word"` | 跟读单元：单音→词→词组 |
| `rules[].tier` | 是 | string，`starter` / `core` | `"starter"` | 难度层级；starter 19 + core 20 = 39 |
| `rules[].tags` | 是 | string[] | `["D组","元音组合"]` | 标签；字母分档 A–H 放此处（如 `"D组"`） |

**`group` 取值（8 个纯分组名，细化自 §6.1 表格的 A–H 组）**

`字母表与读音概念`（A） / `基础元音`（B） / `基础辅音`（C） / `元音字母组合`（D） / `辅音字母组合`（E） / `鼻化元音`（F） / `词末辅音规则`（G） / `高频例外与易错`（H）。

> 字母前缀 A–H 仅作分组编号，写入 `tags[0]`（如 `"D组"`）；`group` 字段本身用上表纯组名（与 §6.4 示例 `"元音字母组合"` 一致）。该取值口径待 content/总指挥确认，见 §7。

**`id` 段名映射（细化，依据 §6.4 锁定示例）**：`id` 格式 `ph_<group>_<nn>` 中的 `<group>` 取**英文段名**——依据是 §6.4 锁定示例 `ph_comb_02` 中的 `comb` 即英文段名，而非字母档。A–H 字母档只进 `tags[0]`。**content 已确认采用英文段名**，文件生产者须照此，不得改用 A–H：

| 分组 | `tags[0]` | `group` 字段值 | `id` 段名 | 示例 |
|:---:|:---:|---|---|---|
| A | `A组` | `字母表与读音概念` | `alpha` | `ph_alpha_01` |
| B | `B组` | `基础元音` | `vowel` | `ph_vowel_01` |
| C | `C组` | `基础辅音` | `cons` | `ph_cons_01` |
| D | `D组` | `元音字母组合` | `comb` | `ph_comb_02` |
| E | `E组` | `辅音字母组合` | `ccomb` | `ph_ccomb_01` |
| F | `F组` | `鼻化元音` | `nasal` | `ph_nasal_01` |
| G | `G组` | `词末辅音规则` | `final` | `ph_final_01` |
| H | `H组` | `高频例外与易错` | `except` | `ph_except_01` |

> ★总指挥终裁（2026-11-18）：A/H 两组段名锁定为 `alpha` / `except`，以**落盘 JSON 实测**为准（`alpha` 4 条 + `except` 3 条）。已逐条核对 `data/input/pronunciation_rules.json` 39 条 id 段名，8 组一一对应无串组、全库唯一、格式全合法。`<nn>` 为两位组内序号（如 `01`、`02`）。中途曾出现 `abc/special` 误写，已作废；此映射为唯一权威，禁止再改。

**听/跟读分离（锁定）**：`audio_text` 只作示范（喂 `/api/tts`），**不作比对目标**；比对目标取 `shadow_text_fr`，比对单元由 `shadow_mode` 决定（PRONUNCIATION_PLAN §4.3 / §6.4）。

**`/ɑ̃/` 与 `/ɑ/` 口径（锁定）**：`/ɑ̃/` 是全库统一写法（鼻化元音 an/en/am 等），**不是笔误、不进易混等价集**；`/ɑ/`（如 `pâte` 的 â）是另一个音位，两者不得混写（PRONUNCIATION_PLAN §6.4 注 / §9）。

**加载规则（后端 `pronunciation.py`，参考 `exam.py::load_papers()`）**

1. 路径常量：`INPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "input"`，文件 `INPUT_DIR / "pronunciation_rules.json"`。
2. 模块级 `_RULES_CACHE = None`；`load_rules() -> list` **进程内缓存、幂等**（缓存固定为 list，含空表 `[]`）。
3. 启动流程末尾调用一次（在 `exam.load_papers()` 之后）；文件不存在 → `logger.warning`，缓存为 `[]`，**不阻断启动**。
4. 逐条按 §2.2 字段表校验：`id` 唯一、`group`/`tier`/`shadow_mode` 枚举合法、必填字段齐全；**单条非法只跳过该条 + warning**，不影响其余规则与服务启动。
5. **39 条规则 JSON 启动缓存，运行时零文件 IO**：4 个端点只读缓存，不在请求路径中 `open()` 文件（PRONUNCIATION_PLAN §7.4）。

---

## 3. 端点契约（4 个端点，前后端唯一输入；字段名/类型/必填/示例/错误码逐字定义）

Base URL `http://localhost:8000`，前缀 `/api`，统一 `{code,data,message}` 包裹。端点编号沿用 PRONUNCIATION_PLAN §7.2。

### 3.0 新增端点总览

| # | 方法 | 路径 | 请求 | 成功响应 `data` | 错误码 |
|---|------|------|------|------------------|--------|
| 22 | GET | `/api/pronunciation/rules` | 查询参数 `group`（可选） | `RuleSummary[]` | 40001、50001 |
| 23 | GET | `/api/pronunciation/rules/{rule_id}` | 路径参数 `rule_id` | `RuleDetail` | 40401、50001 |
| 24 | GET | `/api/pronunciation/progress` | 无 | `ProgressView` | 50001 |
| 25 | POST | `/api/pronunciation/progress` | Body `ProgressUpdateBody` | `ProgressItem` | 40001、40401、50001 |

> 现有 **21 个端点全部保留**：`GET /api/health`、`GET /api/scenes`、`GET /api/scenes/{scene_id}`、`POST /api/chat`、`POST /api/translate`、`GET /api/cards`、`POST /api/cards/{id}/review`、`GET /api/profile`、`GET /api/asr/status`、`POST /api/asr/transcribe`、`GET /api/tts`、`GET /api/input/levels`、`GET /api/input/texts`、`GET /api/input/texts/{text_id}`、`POST /api/input/texts/{text_id}/collect`、`GET /api/input/recommend`、`GET /api/assessment/questions`、`POST /api/assessment/submit`、`GET /api/exam/papers`、`GET /api/exam/papers/{paper_id}`、`POST /api/exam/submit`。

### 3.1 `GET /api/pronunciation/rules` — 规则摘要列表

- **请求（查询参数，逐字段）**

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|------|------|:---:|--------|------|
| `group` | string | 否 | `元音字母组合` | 分组过滤；省略/空 = 不过滤；非空须为 §2.2 的 8 个合法组名之一，否则 `40001` |

- **行为**：返回规则摘要列表（小册子索引用），**不含** `description_zh`/`examples`/`audio_text`/`shadow_text_fr`/`shadow_mode`/`tags`。按规则 JSON 文件中出现顺序返回。缓存为空 → 返回 `[]` + `code=0`（降级，不抛 500）。
- **响应 `data`：`RuleSummary[]`**（数组本身即 data）

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `id` | string | `"ph_comb_02"` | 规则 id |
| `group` | string | `"元音字母组合"` | 分组纯组名 |
| `title` | string | `"ai / ay 读 /ɛ/"` | 规则标题 |
| `tier` | string | `"starter"` | `starter` / `core` |

- **成功示例**

```json
{
  "code": 0,
  "data": [
    { "id": "ph_comb_02", "group": "元音字母组合", "title": "ai / ay 读 /ɛ/", "tier": "starter" },
    { "id": "ph_vowel_01", "group": "基础元音", "title": "元音 a 与 â：/a/ 和 /ɑ/", "tier": "starter" }
  ],
  "message": "ok"
}
```

- **错误码**：`group` 非空且非合法组名 → `40001` / 400；读取缓存内部异常 → `50001`。

### 3.2 `GET /api/pronunciation/rules/{rule_id}` — 规则详情

- **请求（路径参数）**

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|------|------|:---:|--------|------|
| `rule_id` | string | 是 | `ph_comb_02` | 规则 id，须存在于加载的规则集 |

- **行为**：返回单条规则完整详情，字段集 = §2.2 全部字段（含 `examples`、`audio_text`、`shadow_text_fr`、`shadow_mode`）。
- **响应 `data`：`RuleDetail`**

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `id` | string | `"ph_comb_02"` | 规则 id |
| `group` | string | `"元音字母组合"` | 分组纯组名 |
| `title` | string | `"ai / ay 读 /ɛ/"` | 规则标题 |
| `description_zh` | string | 见 §2.2 示例 | 中文讲解 |
| `examples` | `ExampleItem[]` | 见下 | ★裁决①：恰好 4 条例词（全库 156 槽位全配） |
| `audio_text` | string | `"maison, chaise, lait"` | TTS 示范文本（只听不比对） |
| `shadow_text_fr` | string | `"maison"` | 跟读比对目标 |
| `shadow_mode` | string | `"word"` | `syllable`/`word`/`phrase` |
| `tier` | string | `"starter"` | `starter`/`core` |
| `tags` | string[] | `["D组","元音组合"]` | 标签 |

**`ExampleItem`（`examples[]` 元素，逐字段）**

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `word_fr` | string | `"maison"` | 法语例词 |
| `meaning_zh` | string | `"房子"` | 中文释义 |
| `note_zh` | string | `"ai 在词中读 /ɛ/"` | 规则体现说明 |
| `phonetic` | string | `"/mɛ.zɔ̃/"` | 宽式 IPA，斜杠包裹、音节用 `.` 分隔 |

- **成功示例**（同 §2.2 的单条规则 JSON，外层包 `{code:0, ..., message:"ok"}`）。
- **错误码**：`rule_id` 不存在（含规则缓存为空）→ `40401` / 404，`message` 如 `"读音规则不存在：ph_bad"`；读取缓存内部异常 → `50001`。

### 3.3 `GET /api/pronunciation/progress` — 当前用户掌握度

- **请求**：无参数。`user_id` 固定取 `db.DEFAULT_USER_ID`（不接受客户端传 `user_id`）。
- **行为**：读 `pronunciation_progress` 中当前用户全部记录，汇总统计 + 明细返回。小册子据此显示「已学 N/39、能自己读 M 条」及每条规则的掌握微标。
- **响应 `data`：`ProgressView`**

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `user_id` | int | `1` | 当前用户 id |
| `total_rules` | int | `39` | 已加载规则总数（动态取 `len(load_rules())`，当前 39；不硬编码） |
| `seen_count` | int | `5` | `stage=seen` 的规则数 |
| `learned_count` | int | `3` | `stage=learned` 的规则数 |
| `confident_count` | int | `1` | `stage=confident` 的规则数（"能自己读 M 条"的 M） |
| `learned_total` | int | `4` | `learned + confident`（"已学 N/39"的 N，口径见 §7） |
| `items` | `ProgressItem[]` | 见下 | **仅含已有记录**的规则；无记录则 `[]` |

**`ProgressItem`（进度明细，逐字段）**

| 字段 | 类型 | 示例值 | 说明 |
|------|------|--------|------|
| `rule_id` | string | `"ph_comb_02"` | 规则 id |
| `stage` | string | `"learned"` | `seen`/`learned`/`confident` |
| `practice_count` | int | `3` | 练习次数 |
| `last_practiced_at` | string\|null | `"2026-11-18T09:30:00Z"` | 最近练习时间（ISO8601 UTC Z）；无则 `null` |
| `self_assessed` | bool | `true` | 库内 `self_assessed` 0/1 转 `bool` |

- **成功示例**

```json
{
  "code": 0,
  "data": {
    "user_id": 1,
    "total_rules": 39,
    "seen_count": 5,
    "learned_count": 3,
    "confident_count": 1,
    "learned_total": 4,
    "items": [
      { "rule_id": "ph_comb_02", "stage": "learned", "practice_count": 3, "last_practiced_at": "2026-11-18T09:30:00Z", "self_assessed": true }
    ]
  },
  "message": "ok"
}
```

- **错误码**：DB 查询内部异常 → `50001` / 500；无参数校验错误。

### 3.4 `POST /api/pronunciation/progress` — 更新某规则掌握状态（幂等 upsert）

- **请求体 `ProgressUpdateBody`（逐字段）**

| 字段 | 类型 | 必填 | 示例值 | 说明 |
|------|------|:---:|--------|------|
| `rule_id` | string | 是 | `"ph_comb_02"` | 规则 id，须存在于规则集，否则 `40401` |
| `stage` | string | 否 | `"learned"` | 枚举 `seen`/`learned`/`confident`；缺省时新记录用 `seen`、已有记录保留旧值 |
| `practice_count` | int | 否 | `3` | ★裁决④：**不接受客户端传该字段**；服务端对已有记录 `+1` 累加（新记录从 `1` 起）；若客户端误传，忽略该字段不报错 |
| `self_assessed` | int \| bool | 否 | `1` | `0/1` 或 `bool`；覆盖语义但**只增不减**（已有为 1 时传 0 仍保留 1）；缺省时新记录用 `0`、已有保留旧值 |

> **不接受**客户端传 `user_id`（固定 `db.DEFAULT_USER_ID`）、`last_practiced_at`（服务端每次写 `db.now_iso()`）、`practice_count`（★裁决④：服务端累加，防多端/重复提交丢计数）。前端每次 POST 只需带 `rule_id` +（可选）`stage`/`self_assessed`。

- **行为**：① `json_body()` 解析（非 JSON 对象 → `40001`）→ ② 字段校验（见错误码）→ ③ 校验 `rule_id` 存在于规则集（不存在 → `40401`）→ ④ 按主键 `(user_id, rule_id)` **幂等 upsert**：不存在则插入（`practice_count=1`）；存在则 `practice_count = practice_count + 1`（★裁决④累加），`stage`/`self_assessed` 按提供值更新（`self_assessed` 只增不减），`last_practiced_at` 每次置 `now_iso()` → ⑤ 回读该行 → ⑥ 出参转 `bool` 返回 `ProgressItem`。
- **响应 `data`：`ProgressItem`**（字段同 §3.3，为更新后的完整记录）

```json
{
  "code": 0,
  "data": {
    "rule_id": "ph_comb_02",
    "stage": "learned",
    "practice_count": 3,
    "last_practiced_at": "2026-11-18T09:30:00Z",
    "self_assessed": true
  },
  "message": "ok"
}
```

- **错误码表**

| 场景 | code | HTTP | 说明 |
|------|:---:|:---:|------|
| `rule_id` 缺失 / 非 string / 空白 | 40001 | 400 | 必填校验 |
| `rule_id` 不在规则集 | 40401 | 404 | **"规则不存在"统一 40401**（PRONUNCIATION_PLAN §7.2） |
| `stage` 非 `seen`/`learned`/`confident` | 40001 | 400 | 枚举校验 |
| `practice_count` 由客户端传入 | — | — | ★裁决④：字段被忽略（不报错），服务端 +1 累加 |
| `self_assessed` 非 `0/1` / 非 bool | 40001 | 400 | 布尔校验 |
| 请求体非 JSON 对象 | 40001 | 400 | 复用 `json_body()` |
| DB 写入/回读异常 | 50001 | 500 | 内部错误 |

> **幂等口径（★裁决④，已终裁）**：`upsert` 保证同一 `(user_id, rule_id)` 只有一行，重复请求不产生重复行；`practice_count` **由服务端 +1 累加、不接受客户端传目标值**（防多端/重复提交丢计数，新记录从 1 起），`stage`/`self_assessed` 按提供值更新（`self_assessed` 只增不减）。此口径与 §3.4 请求体表、行为步骤、§6、§8 完全一致。

### 3.5 错误码统一口径（全 4 端点）

| code | HTTP | 触发 |
|:---:|:---:|------|
| `0` | 200 | 成功；含降级空列表（`/rules` 缓存空 → `[]`） |
| `40001` | 400 | 参数错：`group` 非法、请求体非对象、`rule_id` 缺失/空白、`stage`/`self_assessed` 非法（`practice_count` 客户端传入一律忽略，不报错） |
| `40401` | 404 | **规则不存在**：`GET /rules/{rule_id}` 或 `POST /progress` 的 `rule_id` 不在规则集 |
| `50001` | 500 | 服务端内部异常（DB/缓存读取异常） |

> 所有失败响应均为 `{code:<非0>, data:null, message:"<中文说明>"}`，复用 `app.py::ApiError` 处理器，禁止返回 traceback。

---

## 4. 规则数据加载与缓存（后端 `pronunciation.py`，参考 `exam.py`）

### 4.1 模块职责

- `load_rules() -> list`：加载并校验 `pronunciation_rules.json`，进程内缓存、幂等、降级不抛异常；缓存元素为完整规则 dict（`RuleDetail` 字段集）。
- `list_rules(group: str | None) -> list`：返回 `RuleSummary[]`（投影 §3.1 四字段），按文件顺序；`group` 精确匹配。
- `get_rule(rule_id: str) -> dict | None`：从缓存按 `id` 查找，返回 `RuleDetail` 或 `None`。
- 进度相关数据库操作放 `db.py`（`get_progress()` / `upsert_progress()`），`app.py` 只做路由/校验。

### 4.2 加载与降级规则

1. 缓存 `_RULES_CACHE = None`；首次调用加载，之后直接返回（幂等）。
2. 文件缺失/解析失败 → `logger.warning`，缓存 `[]`，不阻断启动；`GET /rules` 返回 `[]`，`GET /rules/{id}` 返回 `40401`。
3. 单条规则字段非法（缺字段/枚举错/id 重复）→ 跳过该条 + warning，保留其余规则（降级哲学，同 `exam.py`）。
4. **运行时零文件 IO**：仅启动阶段读一次文件；端点只读内存缓存。

---

## 5. 一致性约束与零回归（锁定）

1. **零新增依赖**：`backend/requirements.txt` 仍仅 `fastapi`、`uvicorn` 两行；不引入任何新库（PRONUNCIATION_PLAN §7.4）。
2. **不动现有 21 端点**：路径/入参/出参 data 一字不改（清单见 §3.0）；`GET /api/health` 的 `version` 仍为 `"1.0.0"`；统一响应 `{code,data,message}`、`ok()`/`ApiError`、CORS 参数不变；错误码只用既有四码。
3. **39 条规则 JSON 启动缓存、无运行时 IO**：规则是静态教学数据，放 JSON 不建内容表；启动加载一次进程内缓存，4 端点只读缓存（§4）。
4. **跟读评分是前端纯函数**：服务端**只提供 ASR 转写能力**（复用 `POST /api/asr/transcribe`），**不提供评分端点、不存 ASR 结果**。比对函数签名 `score(target=shadow_text_fr, asr结果, IPA Map) -> {band, 反馈话术}`，无网络、无状态、可单测（PRONUNCIATION_PLAN §4.3 / §7.3 / §9）。
5. **不建内容表、不改现有表**：只新增 `pronunciation_progress` 一张表；`users`/`word_cards`/`review_logs`/`attempts`/输入流三表结构一字不改；不写 XP/CEFR。
6. **隐私**：不存用户音频（ASR 端已 unlink）、不存原始转写文本。
7. **融入式无新 Tab**：P0 只做词卡单一融入点；阅读②/对话气泡③留 P2；不新增第 5 Tab（PRONUNCIATION_PLAN §10）。
8. **路由声明顺序**：4 个 `/api/pronunciation/*` 路由必须在 `app.mount("/", ...)` 之前声明。
9. **启动流程**：保留 `db.init_db()` → `seed.seed_if_empty()` → `seed_input.load_input_corpus()` → `assessment.load_questions()` → `exam.load_papers()`；追加 `pronunciation.load_rules()` 且幂等、文件缺失不阻断启动。
10. **并入「我的成长」时同源读取** `pronunciation_progress`，不重复记录。

---

## 6. 字段一致性清单（四方逐字核对）

| Schema | 字段（逐字） |
|--------|--------------|
| `pronunciation_progress`（表） | `user_id`, `rule_id`, `stage`, `practice_count`, `last_practiced_at`, `self_assessed` |
| `RuleSummary` | `id`, `group`, `title`, `tier` |
| `ExampleItem` | `word_fr`, `meaning_zh`, `note_zh`, `phonetic` |
| `RuleDetail` | `id`, `group`, `title`, `description_zh`, `examples`, `audio_text`, `shadow_text_fr`, `shadow_mode`, `tier`, `tags` |
| `ProgressItem` | `rule_id`, `stage`, `practice_count`, `last_practiced_at`, `self_assessed` |
| `ProgressView` | `user_id`, `total_rules`, `seen_count`, `learned_count`, `confident_count`, `learned_total`, `items` |
| `ProgressUpdateBody` | `rule_id`, `stage`?, `self_assessed`?（★裁决④：不含 `practice_count`，客户端传值一律忽略） |
| 规则单条（源文件 §6.4） | `id`, `group`, `title`, `description_zh`, `examples`(`word_fr`,`meaning_zh`,`note_zh`,`phonetic`), `audio_text`, `shadow_text_fr`, `shadow_mode`, `tier`, `tags` |

**禁用旧字段别名**：`word`、`highlight`、`read_aloud`（以及 §6.4 未定义的任何别名）一律不得出现在 JSON、请求/响应、表结构中。

**不变量**：错误码 `0/40001/40401/50001`；`stage ∈ {seen,learned,confident}`；`shadow_mode ∈ {syllable,word,phrase}`；`tier ∈ {starter,core}`；主键 `(user_id, rule_id)`；`/ɑ̃/` 保留且不进易混等价集、`/ɑ/` 独立。

---

## 7. 待裁决项 · 总指挥裁决结果（2026-11-18，已全部回填）

> 架构师初稿列出 7 处锁定项内部弹性点。总指挥逐项裁决如下（★=对架构师细化值的实质修改），本文正文已按裁决同步，实现以此为准。

| # | 弹性点 | 架构师细化值 | ★总指挥裁决 | 理由 |
|:--:|--------|--------------|-------------|------|
| 1 | `examples` 条数 | 2–4 条弹性、156 仅为上限 | ★**锁定每条恰好 4 例词，全库 156 槽位全配** | 音素层全量开启是 §9 已裁决项；弹性会让前端 IPA Map 不完整、比对降级。内容角色已按 39×4 产出并校验通过 |
| 2 | `group` 取值 | 8 纯组名 + tags[0] 放「D组」 | **采纳** | 与 §6.4 示例一致；内容产出已按此填 |
| 3 | `self_assessed` 语义 | 1=自评"读对了"，置 1 不回退 | **采纳**（一旦置 1 不回退） | 掌握度只增不减符合低情感过滤 |
| 4 | `practice_count` 更新语义 | 覆盖式（客户端传目标值） | ★**改为服务端 +1 累加，不接受客户端传该字段目标值** | 覆盖式在多端/重复提交下会丢计数；§5.1 语义是"接触次数"天然累加。前端 POST 只需带 rule_id/stage/self_assessed |
| 5 | `GET /progress` 统计口径 | 已学 N = learned+confident，排除 seen | **采纳** | "见过"不算"已学"，符合用户认知 |
| 6 | `GET /rules` 摘要字段集 | id/group/title/tier 四字段 | **采纳** | 小册子索引最小够用，详情才拉全字段 |
| 7 | JSON 顶层键名 | `{"rules":[...]}` | **采纳**，并额外允许 `version` 元信息键（内容产出含 `version:1`），加载器忽略 `version` | 对齐 exam_papers.json 模式，元信息键无害 |
| 8 | `id` 段名用英文还是 A–H 字母（内容角色提出） | 内容产出用英文段名（ph_alpha_01 等） | ★**锁定英文段名 `alpha/vowel/cons/comb/ccomb/nasal/final/except`，不改成 ph_A_01** | §6.4 示例本身即 ph_comb_02（英文段名），`<group>` 是占位符语义非字面字母；落盘 JSON 39 条实测按此产出、唯一校验通过，改字母段名全量返工零收益；A–H 仅进 tags[0] |

> **裁决①②⑦⑧已由内容产出实测确认**：39 条、8 组分布 4/6/7/6/5/4/4/3、starter 19 + core 20、每条 4 例词、156 IPA 槽位全配、133 个不同词 IPA 无冲突、`/ɑ̃/` 13 处零混写、8 段名映射一一对应无串组、id 全库唯一无重复。

> id 段名口径（已裁决⑧、非待裁决）：`ph_<段名>_<nn>` 的 `<段名>` 取**英文段名** `alpha/vowel/cons/comb/ccomb/nasal/final/except`（A=alpha、H=except，以落盘 JSON 实测为准），依据 §6.4 锁定示例 `ph_comb_02` 的 `comb` 即英文段名；A–H 字母档仅进 `tags[0]`。content 已确认，映射表见 §2.2，文件生产者已同步，不再列为分裂源。

> 另注（非阻塞，按锁定执行）：本契约对"规则不存在"统一用 `40401`（含 `POST /progress`），与 `ARCHITECTURE_EXAM.md` 中考级 `POST /submit` 传不存在 `paper_id` 用 `40001` 的口径不同——这是两个功能的独立契约，按 PRONUNCIATION_PLAN §7.2 锁定执行，不视为冲突。

> **验收口径澄清（防 QA 误判）**：QA 第 12 条"禁用别名命中=0"检查的是**字段名/键名**，不是字符串字面量。内容 JSON 中 `"shadow_mode": "word"` 含 21 处 `"word"` 字面量，这是合法枚举值，**不是**禁用字段 `word`；独立 `word` 键实测为 0。校验脚本须按 JSON 键遍历，不得用全文字符串搜索。

---

## 8. 测试要点（给 QA，逐条可验收）

| # | 场景 | 预期 |
|:--:|------|------|
| 1 | 建表幂等 | 重复 `init_db()` 不报错；`PRAGMA table_info(pronunciation_progress)` 六字段类型/默认/CHECK 与 §2.1 一致；主键 `(user_id,rule_id)`；索引存在 |
| 2 | 规则列表 | `GET /rules` 返回摘要四字段、无 `description_zh/examples/audio_text/shadow_*`；`group=元音字母组合` 只返回该组；非法 `group` → `40001`；缓存空 → `[]` + `code=0` |
| 3 | 规则详情 | `GET /rules/ph_comb_02` 含全部 10 字段、`examples[].word_fr/meaning_zh/note_zh/phonetic` 齐全、`audio_text` 与 `shadow_text_fr` 分离；不存在 → `40401` |
| 4 | 音位口径 | 全库 JSON 中 `/ɑ̃/` 写法保留、`/ɑ/` 独立，二者未混写；易混等价集不含 `/ɑ̃/` |
| 5 | 进度读取 | 空库 `GET /progress` → `total_rules=39`、各计数 0、`items=[]`；有记录时 `self_assessed` 为 `bool` |
| 6 | 进度 upsert 幂等与累加 | 同一 `(user_id,rule_id)` 连 POST 2 次仍 1 行；`practice_count` 由服务端从 1 起 +1 累加（第 2 次=2，客户端传值被忽略）；`last_practiced_at` 更新为 `now_iso()` |
| 7 | 进度校验 | 缺 `rule_id`/空白 → `40001`；不存在 `rule_id` → `40401`；`stage` 非法 / `self_assessed` 非 0-1 → `40001`；客户端传 `practice_count`（任意值）一律忽略不报错、服务端仍 +1；请求体非对象 → `40001` |
| 8 | 隐私红线 | `pronunciation_progress` 表无音频/转写列；`POST /progress` 请求体含未知字段 `audio`/`transcript` 一律忽略且不落库 |
| 9 | 零回归 | 现有 21 端点逐条请求路径/入参/出参不变；`health.version="1.0.0"`；`requirements.txt` 两行 |
| 10 | 零运行时 IO | 启动后重命名/删除 `pronunciation_rules.json`，4 端点仍从缓存正常返回（无 `open()` 请求路径） |
| 11 | 评分在前端 | 服务端无评分端点；`/api/asr/transcribe` 仍只返回转写五字段，不返回 band/分数 |
| 12 | 字段一致性 | §2 Schema ↔ §3 端点 ↔ §6 清单 ↔ 示例 JSON 逐字一致；禁用别名 `word/highlight/read_aloud` 命中=0 |

---

> 任何契约变更必须**先改本文**、再同步后端/前端/内容/测试/PM，禁止口头约定；锁定项（PRONUNCIATION_PLAN §5.1 / §6.4 / §7 / §9 / §10）变更必须先报总指挥。本文只约束「零基础读音规则学习」增量，产品语义以 `PRONUNCIATION_PLAN.md` 为准。
