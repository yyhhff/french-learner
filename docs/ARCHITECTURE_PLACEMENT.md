# 呀呀法语 · 阶段0 CEFR 定级 技术契约（PLACEMENT v1.1）

> 本文是阶段0「CEFR 定级」的**后端 / 前端 / 内容 / 测试 / PM 唯一技术输入**。所有字段名、端点路径、JSON 结构、算分阈值必须逐字实现，不得自行改名、改值、增删字段。
> 本文是 `ARCHITECTURE.md`（v1）与 `ARCHITECTURE_V2.md`（v2）的**增量扩展**：v1 的 7 个业务端点 + 3 个 ASR/TTS 代理、v2 的 5 个输入流端点（合计 **15 个现有端点**）的结构与契约**全部保持不变**；本次只新增 **1 张表（attempts）+ 2 个端点（/api/assessment/*）+ 1 个题库 JSON 文件**。
> **v1.1 修订说明**：按总指挥裁决，产品语义（等级范围 / 题数 / 算分 / 阈值 / skill / 文案口径）**以 PM 的 `docs/PLACEMENT_CHARTER.md` 为准**，技术实现细节（表结构 / 字段名 / 端点 / 校验 / 幂等）保留。全文已对齐，详见 §10。
> 日期：2026-11-18　读者：后端工程师、前端工程师、内容工程师、测试工程师、PM。

---

## 0. 约定沿用（不重复 v1/v2 已定义的全局规则）

| 项 | 约定 |
|----|------|
| 命名 | `snake_case`；时间 ISO8601 `YYYY-MM-DDTHH:MM:SSZ`（UTC，复用 `db.now_iso()`）；纯日期 `YYYY-MM-DD` |
| 空值 | 库内 `NULL` → JSON `null`；布尔库内 INTEGER 0/1 → 出参 `bool` |
| 统一响应 | 成功 `{code:0, data:..., message:"ok"}`；失败 `{code:<非0>, data:null, message:"..."}` |
| 错误码集合 | **仅 `0 / 40001 / 40401 / 50001`，本文不新增错误码**。含义：`40001`=参数错误(HTTP 400)、`40401`=不存在(HTTP 404)、`50001`=服务内部错误(HTTP 500) |
| 零依赖 | `backend/requirements.txt` 保持且仅保持 `fastapi`、`uvicorn` 两行；不得引入任何新包 |
| 编码 | 题库 JSON 为 UTF-8，`ensure_ascii=false` 风格（中文/法语直接写字符），与 `data/input/texts.json` 一致 |
| 降级哲学 | 除入参非法外，外部能力失败不向前端抛 500；定级解读**不依赖任何外部能力**（见 §1.3） |
| 产品口径 | 等级只评 **A2 / B1 / B2** 三级（保底 A2，不设 A1/C1/C2）；结果称「**参考等级**」，可重测；文案用温和鼓励式，禁「官方/认证/权威/证书」等词 |

---

## 1. 改动清单（涉及文件逐项）

| 文件 | 改动类型 | 具体内容 | 备注 |
|------|----------|----------|------|
| `backend/db.py` | 改 | ① `DDL` 字符串追加 `attempts` 表 + 索引（幂等 `IF NOT EXISTS`）；② 新增 4 个方法：`add_attempt` / `get_latest_attempt` / `count_attempts` / `set_user_cefr_level` | 现有 8 张表结构**一字不改**；`users` 表只 UPDATE `cefr_level`，不加列 |
| `backend/app.py` | 改 | ① 路由区（静态 mount 之前）新增 2 端点：`GET /api/assessment/questions`、`POST /api/assessment/submit`；② 启动流程末尾追加题库加载调用（幂等）；③ 入参照 §3 §6 校验 | 新路由必须声明在 `app.mount("/", ...)` **之前**，否则被静态接管 |
| `backend/assessment.py` | **新增（建议）** | 承载：题库加载 `load_questions()`、判分 `compute_score()`、定级 `level_from_counts()`、薄弱维度 `weak_skill()`、中文解读 `interpretation_zh()`、阈值常量 | 让 `app.py` 只做路由/校验，逻辑可单测；如不新增文件也可内联至 `app.py`，但契约不变 |
| `backend/ai.py` | **不改（明确不用 GLM）** | 解读由本地中文模板生成，**不调用 GLM、不发任何网络请求** | 详见 §1.3 |
| `frontend/app.js` | 改 | 新增定级入口：调 `GET /api/assessment/questions` 拉取 12 题渲染答题 UI；提交调 `POST /api/assessment/submit`；按 `level` 更新本地 profile 展示；「推荐预览」入口根据 `level` 调既有 `/api/input/recommend`；按钮防连点 | 复用现有 `apiRequest()`；沿用离线 fallback 风格 |
| `frontend/index.html` | 改 | 新增「CEFR 定级」入口按钮/弹层容器 | 不改现有 15 端点相关 DOM |
| `frontend/styles.css` | 改 | 定级卡片/选项/结果页样式 | 追加样式，不改现有类名语义 |
| `data/input/assessment_questions.json` | **新增** | 12 道定级题题库（A2/B1/B2 各 4），结构见 §2.2 | 内容角色产出；与 `data/input/texts.json` **同目录** |
| `backend/requirements.txt` | **不改** | 仍两行 | 硬性约束 |

### 1.3 关于 `ai.py` 是否用 GLM 生成解读：**不用**（本地中文模板，零依赖）

| 维度 | 结论 |
|------|------|
| 决策 | 解读 `interpretation_zh` 由**固定 3 档本地中文模板 + 薄弱维度提示**（§5）生成，位置在 `assessment.py`（或 `app.py`）内；`ai.py` 不改动、不新增网络调用 |
| 理由 1 | 解读只有 3 个等级分支，是确定性文案，LLM 会带来随机性、延迟、Key 依赖与 500 风险，与「定级必须稳定可复现」冲突 |
| 理由 2 | 零依赖原则：绝不因为解读而新增 SDK 或触发 GLM 网络请求（v2 §2 依赖锁死） |
| 理由 3 | 可测试：模板逐字定义，测试可直接断言 A2/B1/B2 三段文案及薄弱维度拼接结果 |
| 降级 | 无 Key / 无网络 / GLM 故障均与本功能无关；定级主流程**永不因此失败** |

---

## 2. 数据模型

### 2.1 `attempts` 表（第 9 张表，`kind` 为波二预留）

**字段定义（共 6 列，逐字）**

| 字段 | 类型 | 可空 | 说明 |
|------|------|:---:|------|
| id | INTEGER | 否 | 自增主键 |
| user_id | INTEGER | 否 | 用户 id，当前固定 `db.DEFAULT_USER_ID = 1` |
| kind | TEXT | 否 | 尝试类型：`placement`（本次定级）/ `exam`（**波二考级预留，本次不写入、不接受该入参**） |
| score | INTEGER | 否 | 答对题数，范围 `0..total`（`total=12`，存于 `detail_json.total`） |
| detail_json | TEXT | 否 | 明细 JSON 字符串（`json.dumps(detail, ensure_ascii=False)`），结构见下方 `AttemptDetail` |
| created_at | TEXT | 否 | ISO8601 UTC，由 `db.now_iso()` 生成 |

**`AttemptDetail`（`detail_json` 反序列化后的对象，前后端对照）**

| 字段 | 类型 | 说明 |
|------|------|------|
| total | int | 本次题目总数，固定 `12` |
| level | string | 判定等级，取值 `A2`/`B1`/`B2`（保底 A2） |
| rate | float | 正确率 `score/12`（答对题数/总题数），保留 4 位小数（如 `0.5`）；**审计用，不参与定级** |
| weighted_score | int | 加权总分 `S`，范围 `0..24`（定级依据，见 §4） |
| weak_skill | string | 薄弱维度，取值 `词汇`/`语法`/`理解`（见 §5） |
| interpretation_zh | string | 本次返回的中文解读全文（与 submit 响应一致，便于审计） |
| answers | array | 逐题明细 `[{id, answer_idx, correct}]`：`correct` 为 bool |

**DDL（追加到 `db.py::DDL` 字符串末尾；幂等，老库可直接升级）**

```sql
-- ===== 阶段0 增量：定级/考级尝试表（旧 8 表结构一字不改）=====
CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    kind         TEXT    NOT NULL CHECK (kind IN ('placement', 'exam')),
    score        INTEGER NOT NULL,
    detail_json  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);

-- 索引建议：支持「查某用户某类型最近一次」与「按类型统计」
CREATE INDEX IF NOT EXISTS idx_attempts_user_kind ON attempts (user_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_kind ON attempts (kind);
```

> `kind` 的 `CHECK` 约束把值锁死为 `placement`/`exam`，写入任何其他值由 SQLite 拒绝；波二只需复用同表写 `kind='exam'`，**本阶段前端/API 一律只写 `placement`**。

**`db.py` 新增方法契约**

| 方法 | 签名 | 行为 |
|------|------|------|
| `add_attempt` | `add_attempt(user_id:int, kind:str, score:int, detail:dict) -> dict` | 插入一行；`detail_json=json.dumps(detail, ensure_ascii=False)`、`created_at=now_iso()`；返回出参 `row_to_attempt()` |
| `get_latest_attempt` | `get_latest_attempt(user_id:int, kind:str) -> dict\|None` | `WHERE user_id=? AND kind=? ORDER BY id DESC LIMIT 1`；无记录返回 `None`（防重复写库判定用） |
| `count_attempts` | `count_attempts(user_id:int, kind:str) -> int` | `SELECT COUNT(*)`；供统计/测试 |
| `set_user_cefr_level` | `set_user_cefr_level(user_id:int, level:str) -> None` | `UPDATE users SET cefr_level=? WHERE id=?`；**只改 cefr_level，target_level/xp/streak_days 一律不动** |

**出参转换 `row_to_attempt(row)`**：`{id, user_id, kind, score, detail_json}` 原样返回，`detail_json` **保持 JSON 字符串**（与库内一致）；需要对象时由调用方 `json.loads`。`created_at` 同样出参。本阶段两个端点**不直接暴露 attempts 记录**（无查询端点），该方法供内部/测试使用。

### 2.2 题库 `assessment_questions.json` Schema（内容角色照此产出）

**文件**：`french-learner/data/input/assessment_questions.json`，UTF-8（与 `data/input/texts.json` **同目录**）。

**完整示例（节选 2 题；正式文件须 12 题，A2/B1/B2 各 4，分布见 §4.1）**

```json
{
  "questions": [
    {
      "id": "asm_a2_001",
      "level": "A2",
      "skill": "词汇",
      "question": "« la gare » signifie :",
      "options": ["火车站", "图书馆", "超市", "医院"],
      "answer_idx": 0,
      "explanation_zh": "la gare 是阴性名词，意思是『火车站』。"
    },
    {
      "id": "asm_b2_001",
      "level": "B2",
      "skill": "语法",
      "question": "« Bien que pleuve, nous sortons. » Cette phrase exprime :",
      "options": ["因为下雨我们出门", "尽管下雨我们仍出门", "下雨前我们出门", "我们等雨停再出门"],
      "answer_idx": 1,
      "explanation_zh": "bien que + 虚拟式表示让步，意为『尽管/虽然』。"
    }
  ]
}
```

**字段约束（内容角色必读，逐字段）**

| 路径 | 必填 | 类型/取值 | 说明 |
|------|:---:|-----------|------|
| `questions` | 是 | array，长度**恰好 12** | 定级题数组；A2/B1/B2 各 4 题 |
| `questions[].id` | 是 | string，全文件唯一 | 格式 `asm_<level>_<三位序号>`，如 `asm_a2_001`；level 小写 |
| `questions[].level` | 是 | `A2`/`B1`/`B2` | 严格三选一（**不含 A1/C1/C2**）；其他值整条跳过；各等级恰好 4 题 |
| `questions[].skill` | 是 | `词汇`/`语法`/`理解` | 考查技能；用于技能覆盖验收与薄弱维度提示 |
| `questions[].question` | 是 | string | **法语题干**（prompt_fr 语义由此字段承载），必要时可含简短法语情境句 |
| `questions[].options` | 是 | string[4]，**恰好 4 项** | 元素 trim 后非空且互不重复；1 正确 + 3 干扰 |
| `questions[].answer_idx` | 是 | int，`0..3` | 正确选项下标（物理名保留 `answer_idx`，语义等同 PM 的 `correct_index`）；**仅服务端可见** |
| `questions[].explanation_zh` | 是 | string，简体中文 | 温和鼓励式解析文案；**仅存在于源文件，绝不通过任何端点下发前端** |

**加载规则（后端）**：新增模块 `assessment.py` 暴露 `load_questions() -> list[dict]`（返回题目列表；进程内缓存，幂等）。
1. 启动流程末尾调用一次（在 `seed_input.load_input_corpus()` 之后）；文件不存在 → 记录 warning，缓存为空 `[]`，**不阻断启动**（其余 15 端点正常）。
2. 逐条按上表校验；单条非法（level 非法、skill 非法、options 非 4 项、answer_idx 越界等）→ 跳过该条 + warning，不影响其他条。
3. 校验通过后缓存；`GET /api/assessment/questions` 与 `POST /api/assessment/submit` 共用同一份缓存。**题库固定 12 题（A2/B1/B2 各 4）、全量返回、不抽样不随机**，故重复取卷恒得到完全相同的 12 题，按 `id` 判分必然可复现。

---

## 3. 端点契约（前后端唯一输入，字段名/类型/示例逐字定义）

Base URL 与既有相同：`http://localhost:8000`，前缀 `/api`，统一 `{code,data,message}` 包裹。

### 3.0 新增端点总览

| # | 方法 | 路径 | 请求体 / Query | 成功响应 `data` | 错误码 |
|---|------|------|----------------|------------------|--------|
| 16 | GET | `/api/assessment/questions` | 无 | `AssessmentQuestionsResult` | 40001(400)、50001(500) |
| 17 | POST | `/api/assessment/submit` | Body `{answers: AnswerItem[]}` | `PlacementResult` | 40001(400)、50001(500) |

> 现有 15 个端点状态：**全部保留，路径/入参/出参 data 不变**（见 §7）。

### 3.1 `GET /api/assessment/questions` — 取卷

- **请求**：无参数（Query / Body 均无）。
- **行为**：从题库缓存返回 12 题（A2/B1/B2 各 4）的**公开视图**。
- **隐藏答案**：**是**。本端点返回的每道题**只含 `id`/`level`/`skill`/`question`/`options` 五个字段**，**绝不包含 `answer_idx`、`explanation_zh`**，防止客户端直接读答案作弊。解释文案只在服务端判分时使用，不下发。
- **响应 `data`：`AssessmentQuestionsResult`**

| 字段 | 类型 | 说明 |
|------|------|------|
| questions | `PublicQuestion[]` | 12 道题，顺序与题库文件一致（不随机打乱，保证判分按 id 对应） |
| total | int | 题目数量，固定 `12` |

**`PublicQuestion`（题目公开视图，逐字段）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 题目 id，如 `asm_a2_001` |
| level | string | `A2`/`B1`/`B2`（仅作前端分组展示，不透露答案） |
| skill | string | `词汇`/`语法`/`理解`（前端可展示题型维度） |
| question | string | **法语题干**，可含简短法语情境句 |
| options | string[4] | 四个候选项，顺序与题库一致 |

**成功示例**（完整响应中 questions 为 12 题，此处节选 1 题示意）

```json
{
  "code": 0,
  "data": {
    "questions": [
      {
        "id": "asm_a2_001",
        "level": "A2",
        "skill": "词汇",
        "question": "« la gare » signifie :",
        "options": ["火车站", "图书馆", "超市", "医院"]
      }
    ],
    "total": 12
  },
  "message": "ok"
}
```

**降级**：题库缓存为空（文件缺失/全部非法）时，返回 `{code:0, data:{questions:[], total:0}, message:"ok"}`，前端据此提示「题库暂不可用」——**不抛 500**，与 v2 语料降级口径一致。
**错误码**：除题库为空的降级外，仅在读取缓存发生内部异常时返回 `50001`（正常路径不会触发）。

### 3.2 `POST /api/assessment/submit` — 交卷判分

- **请求体 `AnswerSubmitBody`（逐字段）**

| 字段 | 类型 | 必填 | 说明 |
|------|------|:---:|------|
| answers | `AnswerItem[]` | 是 | 答案数组，长度**恰好 12**（对应题库全部题目） |

**`AnswerItem`（逐字段）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 题目 id，须与题库中某题 id 完全一致 |
| answer_idx | int | 所选选项下标，`0..3`（非 bool） |

**请求示例**（12 项，此处节选 2 项示意）

```json
{
  "answers": [
    { "id": "asm_a2_001", "answer_idx": 0 },
    { "id": "asm_a2_002", "answer_idx": 2 }
  ]
}
```

- **行为步骤**：① 校验请求体（§6）→ ② 用 `id` 从题库缓存取标准答案逐题判分（**不信任客户端顺序，按 id 匹配**），同时记录每题 `level`/`skill`/`correct` → ③ 按 §4 分组加权算分并定级 → ④ 按 skill 统计薄弱维度、生成中文解读（§5）→ ⑤ 判定是否写库（§6.4）→ ⑥ 返回 `PlacementResult`。

- **响应 `data`：`PlacementResult`（逐字段）**

| 字段 | 类型 | 说明 |
|------|------|------|
| score | int | 答对题数，范围 `0..12`（前端展示「答对 X 题」） |
| total | int | 题目总数，固定 `12` |
| weighted_score | int | 加权总分 `S`，范围 `0..24`（定级依据与进度感展示，见 §4） |
| level | string | 参考等级，取值 `A2`/`B1`/`B2`（保底 A2） |
| interpretation_zh | string | 面向中文用户的等级解读 + 薄弱维度提示（§5 模板生成） |
| persisted | bool | 本次是否**实际写入 `attempts` 并更新 `users.cefr_level`**；重复提交为 `false`（见 §6.4） |

**成功示例**

```json
{
  "code": 0,
  "data": {
    "score": 9,
    "total": 12,
    "weighted_score": 17,
    "level": "B1",
    "interpretation_zh": "本次定级共 12 题，答对 9 题，正确率 75%。你的法语基础扎实，能就熟悉话题展开交流；建议加强复合时态与虚拟式入门，并提升听说流利度。理解是你接下来可以多花点时间的地方。",
    "persisted": true
  },
  "message": "ok"
}
```

**错误码表**

| 场景 | code | HTTP | 说明 |
|------|:---:|:---:|------|
| 题库缓存为空 / 加载内部异常 | 50001 | 500 | 无法判分，服务端资源不可用 |
| `answers` 非数组 / 空 / 长度不为 12 | 40001 | 400 | 见 §6.1 |
| `AnswerItem` 字段非法 / id 不存在 / 重复 / answer_idx 越界 / 集合不一致 | 40001 | 400 | 见 §6.2 §6.3 |
| 请求体非 JSON 对象 | 40001 | 400 | 复用 `json_body()`，与现有端点一致 |

> 本端点**不返回逐题答案或解析**（`interpretation_zh` 仅为整体等级解读 + 薄弱维度提示），避免题库答案泄露，保证定级可重复测试。

---

## 4. 算分算法（可测试伪码 + 阈值 + 边界，对齐 PM §4）

### 4.1 题库常量（与 §2.2 对齐）

- 题目总数 **N = 12**，**A2 / B1 / B2 各 4 题**。
- 单题权重：**A2=1 分、B1=2 分、B2=3 分**；答错 0 分。
- 加权总分 `S = c_A2×1 + c_B1×2 + c_B2×3`，范围 **0–24**（`c_*` 为各组答对题数，各 0–4）。
- 全部常量（权重表、阈值、等级顺序）集中定义于 `assessment.py` 模块级，**禁止在 `app.py` 散落魔数**。

### 4.2 判分与定级伪码（输入：answers + 题库缓存 → 输出：score/S/level/rate/weak_skill）

```python
# 输入：
#   answers: AnswerItem[]        # 前端提交，已经过 §6 校验
#   questions: list[dict]        # 题库缓存，每题含 answer_idx/level/skill
# 输出：score, weighted_score(S), level, rate, weak_skill, correct_flags

Q = {q["id"]: q for q in questions}              # 按 id 建索引，不依赖顺序
total = len(questions)                           # 12

correct_flags = []
for ans in answers:                              # 每项形如 {"id":"...", "answer_idx":0}
    q = Q[ans["id"]]                             # 校验阶段已保证 id 存在
    correct = (ans["answer_idx"] == q["answer_idx"])
    correct_flags.append({
        "id": ans["id"],
        "level": q["level"],
        "skill": q["skill"],
        "answer_idx": ans["answer_idx"],
        "correct": bool(correct),
    })

score = sum(1 for f in correct_flags if f["correct"])        # 答对题数 0..12

WEIGHT = {"A2": 1, "B1": 2, "B2": 3}
c = {"A2": 0, "B1": 0, "B2": 0}
for f in correct_flags:
    if f["correct"]:
        c[f["level"]] += 1
weighted_score = sum(c[l] * WEIGHT[l] for l in ("A2", "B1", "B2"))   # S, 0..24

def level_from_counts(c_a2: int, c_b1: int, c_b2: int) -> str:
    S = c_a2 * 1 + c_b1 * 2 + c_b2 * 3
    # 取「满足的最高等级」；分组下限优先于总分
    if S >= 20 and c_a2 >= 3 and c_b1 >= 3 and c_b2 >= 3:
        return "B2"
    if S >= 10 and c_a2 >= 3 and c_b1 >= 3:
        return "B1"
    return "A2"                                   # 保底

level = level_from_counts(c["A2"], c["B1"], c["B2"])
rate = round(score / total, 4)                    # 答对题数/12，审计用，不参与定级

def weak_skill(flags) -> str:
    # 按 skill 统计正确率，取最低者；并列时按固定顺序 词汇 < 语法 < 理解
    order = ["词汇", "语法", "理解"]
    acc = {s: [0, 0] for s in order}              # [答对数, 题数]
    for f in flags:
        acc[f["skill"]][1] += 1
        if f["correct"]:
            acc[f["skill"]][0] += 1
    return min(order, key=lambda s: (acc[s][0] / acc[s][1] if acc[s][1] else 1.0,
                                     order.index(s)))
```

### 4.3 定级阈值表（逐字对齐 PM §4.2，**分组下限优先于总分**）

取**满足的最高等级**；若两级门槛均不满足，则**保底 A2**（与产品下限/现状一致）。

| 判定等级 | 必要条件（须**全部**满足） | 边界含义 |
|:--------:|---------------------------|----------|
| **B2** | `S ≥ 20` **且** `c_A2 ≥ 3` **且** `c_B1 ≥ 3` **且** `c_B2 ≥ 3` | 总分够高，且三级均无明显漏洞 |
| **B1** | `S ≥ 10` **且** `c_A2 ≥ 3` **且** `c_B1 ≥ 3` | 中级达标，且 A2 基础扎实 |
| **A2** | 其他一切情况（含 `c_A2 < 3`） | 保底，避免给初学者过高起点 |

> **分组下限的作用**：防止「只蒙对几道 B2 难题就升级」——判定高级别必须建立在低级题也达标的前提上。即使 `S` 很高，只要基础组未达标也不能越过。

### 4.4 边界用例对照（逐字沿用 PM §4.3 的 TC1–TC8，测试直接断言）

| 用例 | (c_A2, c_B1, c_B2) | 加权总分 S | 期望等级 | 说明 |
|------|:---:|:---:|:---:|------|
| TC1 全对 | (4,4,4) | 24 | **B2** | 上限边界 |
| TC2 B2 临界达标 | (3,4,3) | 20 | **B2** | B2 阈值下边界（=20） |
| TC3 B2 总分够但 B2 组不足 | (4,4,2) | 18 | **B1** | c_B2=2<3，被分组下限挡住 |
| TC4 B1 临界达标 | (4,3,0) | 10 | **B1** | B1 阈值下边界（=10） |
| TC5 B1 总分不足 | (3,2,0) | 7 | **A2** | S<10 降级 |
| TC6 B2 蒙对但基础差 | (0,0,4) | 12 | **A2** | c_A2=0<3，保底 |
| TC7 全错 | (0,0,0) | 0 | **A2** | 下限边界 |
| TC8 总分高但基础组不足 | (2,4,4) | 22 | **A2** | c_A2=2<3，不满足 B1/B2 分组下限 → 保底 A2 |

> **TC8 是刻意设计的反直觉用例**：`S=22` 已超过 B2 的 20 分门槛，但因 `c_A2=2<3` 触发分组下限，仍判 **A2**。它验证「分组下限压过总分」，是判分实现的必测点。
> 定级范围锁定 **A2/B1/B2** 三级：语料仅有 A2/B1/B2，若判出 A1 则 `/api/input/recommend` 无推荐可读，会断掉「定级→i+1 推荐」衔接，故不设 A1/C1/C2。

---

## 5. 中文解读模板（零依赖，逐字，温和鼓励式）

`interpretation_zh` 由 **「固定前缀 + 等级文案 + 薄弱维度提示」** 拼接（逐字使用，不调用 GLM）。**禁用「官方 / 认证 / 权威 / 证书 / 不合格 / 排名」等词**；结果一律表述为「参考等级」。

**固定前缀（逐字）**：
```
本次定级共 12 题，答对 {score} 题，正确率 {rate_pct}%。
```
- `{score}`=`score`（答对题数 0–12）、`{rate_pct}`=`int(round(rate*100))`（如 0.75 → `75`）。
- `total` 固定为 `12`，前缀后**直接拼接**等级文案与薄弱维度提示，无换行/空格。

**等级文案（3 段，逐字）**

| level | 文案 |
|:---:|------|
| A2 | `你已经掌握了基础法语，能应对简单日常交流；接下来可以扩充词汇量，练习过去时和简单描述，继续保持就很棒。` |
| B1 | `你的法语基础扎实，能就熟悉话题展开交流；建议加强复合时态与虚拟式入门，并提升听说流利度，离进阶不远啦。` |
| B2 | `你的法语水平已经相当不错，能较自如地表达观点；接下来可挑战更复杂的阅读与原声听力，向更高阶稳步前进。` |

**薄弱维度提示（逐字模板）**
```
{weak_skill}是你接下来可以多花点时间的地方。
```
- `{weak_skill}` 取 §4.2 `weak_skill()` 的结果（`词汇`/`语法`/`理解`）。
- 定位为「可提升项」而非「弱点」，保持鼓励式。

**完整示例**（score=9, rate=0.75, level=B1, weak_skill=理解）：
```
本次定级共 12 题，答对 9 题，正确率 75%。你的法语基础扎实，能就熟悉话题展开交流；建议加强复合时态与虚拟式入门，并提升听说流利度，离进阶不远啦。理解是你接下来可以多花点时间的地方。
```

**文案码（内部实现概念，不单独作为 API 字段）**：模板以 `interpretation_code = "<level>_<weak_skill>"`（如 `B1_理解`）作稳定标识，便于测试断言与审计；API 只下发拼装后的 `interpretation_zh` 全文，`interpretation_code` 不单独下发。该全文同时写入 `attempts.detail_json.interpretation_zh`，保证响应与审计记录一致。学习建议已含在等级文案内；「推荐预览」由前端按 `level` 调既有 `/api/input/recommend` 获得，后端无需返回额外字段。

---

## 6. 安全与校验（提交时必做）

### 6.1 答案数量校验

1. `answers` 必须是 `list` 且非空；否则 `40001`（「answers 必须是非空数组」）。
2. `len(answers)` 必须 **恰好等于 12**（题库题数）；**11 或 13 均报 `40001`**（「答案数量与题目数量不一致」）。
3. 题库缓存为空时：**先判题库**（§3.2 错误码表），返回 `50001`，避免把「题库不可用」误报成「答案数量错」。

### 6.2 单项索引范围与类型校验（每项逐一）

| 校验 | 失败处理 |
|------|----------|
| 元素是 `dict` | `40001` |
| 含 `id` 且为非空 `str`（trim 后非空） | `40001` |
| 含 `answer_idx` 且为 `int`、**不是 `bool`**（`isinstance(x,bool)` 需排除） | `40001` |
| `0 <= answer_idx <= 3` | `40001`（「答案索引超出范围」） |

### 6.3 集合一致性校验（防缺题/多题/伪造/重放）

1. 所有 `id` 必须存在于题库 `Q`；任一不存在 → `40001`。
2. `answers` 中的 `id` **不得重复**；重复 → `40001`。
3. `answers` 的 `id` 集合必须**恰好等于**题库 id 集合（不多不少）；不一致 → `40001`。
4. 判分**始终以题库 `answer_idx` 为准**，客户端只提供选项下标，无法注入正确答案。

### 6.4 防重复提交策略

| 层 | 策略 |
|----|------|
| 服务端（权威） | `POST /submit` 写库前先查 `db.get_latest_attempt(DEFAULT_USER_ID, "placement")`：**已有记录则本次不写库、不更新 `users.cefr_level`**，仍按本次答案返回算分结果，但 `persisted=false`。→ 天然幂等，重复提交不会污染档案/产生多条记录 |
| 服务端（并发兜底） | `add_attempt` 用单连接事务插入；即使并发双击，以「先查后写 + 已有则跳过」为准；如出现双写，以 `id` 最大者对应的等级为当前值（可由测试覆盖） |
| 前端 | 点击「提交」后立即禁用按钮；`localStorage` 记录 `placement_done=1`，刷新后若已定级则展示结果入口而非答题表单（用户仍可主动「重新测评」，此时服务端以 `persisted=false` 响应） |
| 不暴露 | 不提供「删除 attempts」「重置等级」端点；重测不覆盖历史记录，保护数据可追溯 |

### 6.5 其他

- 请求体解析复用 `app.py::json_body()`：非 JSON / 非对象 → `40001`，与现有端点一致。
- 所有校验失败均返回 `40001` + HTTP 400 + 明确中文 `message`，**不抛 500**。
- 不修改 `users.target_level`、`xp`、`streak_days`、`last_active_date`；定级不赠送 XP（与 `/api/chat` 的 +10/轮机制隔离）。
- **写回时机**：仅在校验通过、判分成功且判定写库（§6.4）后调用 `set_user_cefr_level()`；判分/写回失败一律**不更新** `cefr_level`，前端保留答卷并提示重试。写回生效后，`/api/input/recommend` 按新 `level` 自然做 i+1，**推荐算法无需改动**。

---

## 7. 零回归约束（现有 15 端点不得破坏的点，测试据此回归）

1. **统一响应**：所有现有端点仍返回 `{code,data,message}`；成功 `code=0/message="ok"`，失败 `code∈{40001,40401,50001}/data=null`。
2. **错误码集合**：不新增错误码；新端点只用既有三码。
3. **CORS 参数**：`allow_origins=["*"]`、`allow_credentials=False`、`allow_methods=["GET","POST","OPTIONS"]`、`allow_headers=["*"]` 逐字不变。
4. **`GET /api/health`**：`version` 仍为 `"1.0.0"`，结构与取值不变。
5. **v1 七个业务端点**路径/入参/出参 data 一字不改：`GET /api/scenes`、`GET /api/scenes/{scene_id}`、`POST /api/chat`（`data` 仍且仅是 `{ai_text,recast_of,explanation,new_words}`，`new_words` 仍是完整 WordCard）、`GET /api/cards`、`POST /api/cards/{id}/review`、`GET /api/profile`、`GET /api/health`。
6. **3 个代理端点**不变：`GET /api/asr/status`、`POST /api/asr/transcribe`（含手写 multipart 解析）、`GET /api/tts`。
7. **v2 五个输入流端点**不变：`GET /api/input/levels`、`GET /api/input/texts`、`GET /api/input/texts/{id}`、`POST /api/input/texts/{id}/collect`、`GET /api/input/recommend`；i+1 逻辑（`cefr_level` 驱动）不受定级更新影响——定级只是**合法地更新 `users.cefr_level`**，推荐仍读同一字段，算法不改。
8. **现有 8 张表结构不改**：`attempts` 用 `CREATE TABLE IF NOT EXISTS` 追加，为第 9 张表；`users` 表不增列。
9. **静态托管顺序**：新 2 路由必须在 `app.mount("/", StaticFiles(...))` **之前**声明，否则 `/api/assessment/*` 被静态接管。
10. **启动流程**：保留 `db.init_db()` → `seed.seed_if_empty()` → `seed_input.load_input_corpus()`；追加题库加载且**幂等、文件缺失不阻断启动**。
11. **依赖锁死**：`backend/requirements.txt` 仍仅 `fastapi`、`uvicorn` 两行；`ai.py` 不改，GLM 相关环境变量与降级逻辑不受影响。
12. **前端离线 fallback**：`FALLBACK_*`、`fallbackChat`、`RECAST_RULES` 及现有 15 端点调用不受影响；定级 UI 为**追加**，不复用/改写现有函数名导致冲突。

---

## 8. 字段一致性清单（四方逐字核对）

### 8.1 新表字段

| 表 | 字段（逐字） |
|----|--------------|
| `attempts` | `id`, `user_id`, `kind`, `score`, `detail_json`, `created_at` |

### 8.2 新增 API Schema 字段

| Schema | 字段 |
|--------|------|
| `PublicQuestion` | `id`, `level`, `skill`, `question`, `options` |
| `AssessmentQuestionsResult` | `questions`, `total` |
| `AnswerItem`（请求） | `id`, `answer_idx` |
| `AnswerSubmitBody`（请求） | `answers` |
| `PlacementResult` | `score`, `total`, `weighted_score`, `level`, `interpretation_zh`, `persisted` |
| `AttemptDetail`（detail_json） | `total`, `level`, `rate`, `weighted_score`, `weak_skill`, `interpretation_zh`, `answers` |
| 题库单题（源文件） | `id`, `level`, `skill`, `question`, `options`, `answer_idx`, `explanation_zh` |

### 8.3 不变量

| 概念 | 全文统一名称/取值 |
|------|-------------------|
| 统一响应 | `{code,data,message}`，code=0/message="ok" |
| 错误码 | `40001` 参数错 / `40401` 不存在 / `50001` 内部 |
| `kind` 枚举 | `placement`（本阶段）/ `exam`（波二预留，本阶段不写入） |
| `level` 枚举（定级结果） | `A2` / `B1` / `B2`（保底 A2，不含 A1/C1/C2） |
| `skill` 枚举 | `词汇` / `语法` / `理解` |
| 题数 / 权重 | 12 题（各 4）；A2=1 / B1=2 / B2=3；S 范围 0–24 |
| 掌握度口径 | 沿用 `review_logs.repetitions >= 5`（本功能不改动） |
| 定级规则 | `S≥20` 且三级各≥3→B2；`S≥10` 且 c_A2≥3、c_B1≥3→B1；否则保底 A2（分组下限优先总分） |

---

## 9. 测试要点（边界必覆盖）

| # | 场景 | 预期 |
|---|------|------|
| 1 | 题库文件缺失 / 全部非法 | 服务正常启动；`GET questions` 返回 `{questions:[],total:0},code=0`；`submit` 返回 `50001` |
| 2 | `GET questions` 返回题目 | 12 题（各 4）；每题**仅** 5 字段（含 `skill`），无 `answer_idx`/`explanation_zh` |
| 3 | 提交 11 题 / 13 题 | `40001`（数量不符，须恰好 12） |
| 4 | `answers` 非数组 / 空数组 / 元素非对象 | `40001` |
| 5 | `answer_idx` 为 `true`/字符串/`-1`/`4` | `40001`（类型 bool 排除、越界） |
| 6 | `id` 不存在 / 重复 / 集合缺题 | `40001` |
| 7 | **TC1** (4,4,4) S=24 | `score=12, weighted_score=24, level=B2, persisted=true` |
| 8 | **TC2** (3,4,3) S=20 | `level=B2`（B2 阈值下边界 =20） |
| 9 | **TC3** (4,4,2) S=18 | `level=B1`（B2 组不足被挡） |
| 10 | **TC4** (4,3,0) S=10 | `level=B1`（B1 阈值下边界 =10） |
| 11 | **TC5** (3,2,0) S=7 | `level=A2`（S<10 降级） |
| 12 | **TC6** (0,0,4) S=12 | `level=A2`（c_A2<3 保底） |
| 13 | **TC7** (0,0,0) S=0 | `level=A2`（下限边界） |
| 14 | **TC8** (2,4,4) S=22 | `level=A2`（分组下限压过总分，必测） |
| 15 | 重复取卷一致性 | 两次取卷返回 12 题 id 与顺序完全一致（服务端固定缓存，按 id 判分） |
| 16 | 重复提交同一答卷第二次 | `code=0`，`persisted=false`，`attempts` 仍只有 1 行，`users.cefr_level` 不被二次改写，等级与首次一致 |
| 17 | 写库后 `GET /api/profile` | `cefr_level` 已更新为定级结果；`target_level`/`xp`/`streak_days` 不变 |
| 18 | 写回后调 `/api/input/recommend` | `target_level` 按新 `level` i+1 变化，推荐算法无需改动 |
| 19 | 文案口径 | 三段解读 + 薄弱维度提示；无「官方/认证/权威/证书」等词 |
| 20 | 字段一致性：§2 表字段 ↔ §3 Schema ↔ §8 清单 | 逐字一致 |
| 21 | **15 端点回归**：逐条请求 | 路径/入参/出参 data 与 v1/v2 完全一致；`health.version="1.0.0"` |

---

## 10. 与 PM 文档对齐状态（**已对齐**，逐项标注最终值）

> 裁决依据：总指挥 2026-11-18 裁决——**产品语义以 PM 的 `docs/PLACEMENT_CHARTER.md` 为准，技术实现细节保留**。下表逐项标注最终落地值，供后端/前端/内容/测试直接执行。

| # | 对齐项 | 最终值（本文 = PM 契约） |
|---|--------|--------------------------|
| 1 | 等级范围 | **A2 / B1 / B2 三级**，保底 A2，不含 A1/C1/C2；删除原 A1 全部痕迹（题库 level、枚举、解读、阈值、§8） |
| 2 | 题数分布 | **12 题，A2/B1/B2 各 4 题**；校验数量 11/13 报错；`total=12` |
| 3 | 算分 | **分组加权** S=c_A2×1+c_B1×2+c_B2×3（0–24）；答对题数 `score` 另记为 0–12 |
| 4 | 定级阈值 | B2: S≥20 且三级各≥3；B1: S≥10 且 c_A2≥3、c_B1≥3；否则保底 A2；**分组下限优先总分**（TC1–TC8 已入 §4.4/§9） |
| 5 | 结果字段 | `PlacementResult` = `score`(答对题数) + `total`(12) + `weighted_score`(S,0–24) + `level` + `interpretation_zh` + `persisted` |
| 6 | 单题字段 | 物理名保留 `question`/`answer_idx`（语义 = PM 的 `prompt_fr`/`correct_index`）；**新增 `skill`**（词汇/语法/理解）必填；题干法语；题库与 `PublicQuestion` 同步 |
| 7 | 题库路径 | **`data/input/assessment_questions.json`**（与 `texts.json` 同目录），非 `data/assessment/` |
| 8 | 题组版本 | **不引入 `version`**（ponytail：零价值冗余字段）；以服务端进程内固定题库缓存（12 题各 4、全量返回、不抽样不随机）+ 按 `id` 判分保证复现，等效满足 PM 幂等/复现诉求（见 §2.2 加载规则） |
| 9 | 解读文案 | 3 段温和鼓励式 + 按 skill 薄弱维度提示；禁「官方/认证/权威/证书」；前缀 total=12；「文案码」为内部标识不单独下发 |
| 10 | 写库 / i+1 | 判分成功且需写库才更新 `cefr_level`；失败不写；幂等 `persisted=false`；写回后 `/api/input/recommend` 自然 i+1，算法不改 |
| 11 | 审计字段 | `detail_json` 保留 `rate`(float=答对题数/12)、`level`(三值)，另含 `total`/`weighted_score`/`weak_skill`/`interpretation_zh`/`answers` |
| 12 | 零回归 / 其他 | attempts DDL、kind 波二预留、4 方法、§6 校验与防重复、§7 零回归 12 条、新路由静态 mount 前声明——**全部保留** |

---

> 任何契约变更必须**先改本文件**、再同步后端/前端/内容/测试/PM，禁止口头约定。本文与 `ARCHITECTURE_V2.md` 冲突时，v2 既有部分以 v2 为准，本文只约束阶段0 定级增量；产品语义层与 `PLACEMENT_CHARTER.md` 冲突时以 PM 契约为准。
