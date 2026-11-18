# 阶段 4 考级冲刺 · 不可变决策基线（EXAM_BASELINE v1.0）

> 本文由总指挥（team-lead）冻结，是 PM / 架构师 / 内容 / 后端 / 前端 / QA 的**唯一共同输入**。
> 波一教训：两份契约各自"先定阈值"导致核心语义分裂。本文中标注【锁定】的项**任何角色不得改动**；
> 如需变更必须 SendMessage 报总指挥，由总指挥改本文并通知全员，禁止口头约定。
> 产品章程只写"产品语义与验收"，技术契约只写"字段与实现"，**均不得重新定义锁定项**。

## 1. 定位与边界【锁定】

- 功能名：「🏆 考级冲刺」。定位：**原创模拟卷，练题型与思路**，不是真题、不是官方认证、不预测真实考分。
- 免责声明必须写进 README 与前端结果页：「本卷为原创模拟练习，非 DELF/TCF 官方真题，成绩仅供练习参考」。
- 理念延续「像婴儿一样自然轻松」：温和鼓励式反馈，不打红叉、不排名、不"未达标"。
- 免责与文案口径由 PM 在章程细化，但禁用词【锁定】：`官方认证 / 权威 / 证书 / 保过 / 真题`（"官方真题"仅允许出现在免责声明的否定句里）。

## 2. 复用优先（零新增依赖）【锁定】

| 已有能力 | 波二怎么用 |
|---|---|
| `attempts` 表（波一建，CHECK 含 `'exam'`） | 直接写 `kind='exam'`，**不改表结构、不加表** |
| `db.add_attempt()` / `db.now_iso()` / `row_to_attempt()` | 复用 |
| `ai.py::_glm_post(messages, max_tokens, temperature)` | 主观题评分复用；**不新增 GLM 客户端、不新增 SDK、不改 requirements.txt**（仍 fastapi+uvicorn 两行） |
| `/api/tts`（8000 代理 → 8010 edge-tts） | 听力题 `audio_text` 与口语题 `prompt_fr` 由前端朗读 |
| `/api/asr/transcribe` + 前端麦克风 | 口语题转写成文本后提交 |
| 统一响应 `ok()` / `{code,data,message}` | 沿用 |
| 错误码 | **只用** `0 / 40001 / 40401 / 50001`，不新增 |

## 3. 试卷与题型【锁定】

- **2 套原创卷**：`id="delf_b2_01"`（exam_type=`DELF B2`）、`id="tcf_b2_01"`（exam_type=`TCF B2`）。
- **每套 8 题**：6 道 `choice` 客观题 + 1 道 `writing` + 1 道 `speaking`。
  - `choice` 分布：阅读理解×2、词汇语法×2、听力理解×1（带 `audio_text`）、观点逻辑×1。
  - 听力题不存音频文件——`audio_text` 是法语文本，前端调 `/api/tts` 朗读。
- **分值【锁定】**：`choice` 每题 10 分（6×10=60）；`writing` 20 分；`speaking` 20 分；**满分 100**。
- 题型 `type` 枚举【锁定】：`choice` / `writing` / `speaking`。
- 等级参考区间【锁定】（仅鼓励性表述，非 CEFR 判定）：`>=80` 很稳 / `60-79` 接近目标 / `40-59` 继续加油 / `<40` 多练几次就好。PM 负责温和文案，不得改成"达标/未达标"。

## 4. 判分与降级【锁定】

- `choice`：服务端按 `answer_idx` 判分，答对得 `points`，答错 0。
- `writing` / `speaking`：**GLM 按 rubric 评分**，严格 JSON 输出 `{score:int 0..points, feedback_zh:string(简体中文)}`；评分函数放新模块 `backend/exam.py`，复用 `ai._glm_post`，解析失败按降级处理。
- **降级（关键）**：无 key / 401 / 超时 / 5xx / JSON 解析失败 → 该题 `{scored:false, score:0, feedback_zh:"这道题先不打分，多练几次会更顺～"}`，**绝不向前端抛 500**，客观题照常出分。
- 成绩报告必须显式给 `unscored_items`（未评分题 id 列表）与 `unscored_count`；总分只累加**已评分**题目的得分，并在报告里温和说明「本次有 N 题暂未评分，分数只作参考」，不得把 0 分静默算进总分后给用户一个虚低总分。
- 主观题评分是**练习反馈**，不得写成"官方评分"。

## 5. 试卷 JSON Schema【锁定】（内容角色逐字照此产出）

文件：`data/input/exam_papers.json`（UTF-8，中文/法语直接写字符）。

```json
{
  "papers": [
    {
      "id": "delf_b2_01",
      "exam_type": "DELF B2",
      "title": "DELF B2 风格模拟卷 · 第 1 套",
      "description_zh": "原创模拟练习，覆盖阅读、词汇语法、听力、写作与口语。",
      "questions": [
        {
          "id": "delf_b2_01_q1",
          "type": "choice",
          "section": "阅读理解",
          "prompt_fr": "<法语短文或题干>",
          "audio_text": null,
          "options": ["<A>", "<B>", "<C>", "<D>"],
          "answer_idx": 0,
          "points": 10,
          "explanation_zh": "<中文解析，服务端保留>"
        },
        {
          "id": "delf_b2_01_q7",
          "type": "writing",
          "section": "书面表达",
          "prompt_zh": "<中文题目说明>",
          "min_words": 80,
          "points": 20,
          "rubric_zh": "<评分要点，服务端用，不下发>",
          "model_answer_fr": "<参考范文，服务端用，不下发>"
        },
        {
          "id": "delf_b2_01_q8",
          "type": "speaking",
          "section": "口语表达",
          "prompt_zh": "<中文情境说明>",
          "prompt_fr": "<法语题目，前端 TTS 朗读>",
          "points": 20,
          "rubric_zh": "<评分要点，服务端用，不下发>"
        }
      ]
    }
  ]
}
```

**字段约束【锁定】**：`papers` 恰好 2 套；每套 `questions` 恰好 8 题（6 choice + 1 writing + 1 speaking）；`id` 全库唯一；`choice` 必有 `options[4]` 且 `answer_idx∈0..3`；听力题 `audio_text` 非空、其余 `audio_text=null`；`points` 按第 3 节固定；`rubric_zh`/`model_answer_fr`/`answer_idx`/`explanation_zh` **服务端专用，GET 端点一律不下发**。

## 6. 端点契约骨架【锁定】（架构师细化字段，不得改路径/语义）

| # | 方法 | 路径 | 语义 |
|---|---|---|---|
| 18 | GET | `/api/exam/papers` | 试卷列表（id/exam_type/title/description_zh/question_count/total_points），**不含题目** |
| 19 | GET | `/api/exam/papers/{paper_id}` | 试卷详情（题目公开视图，**零答案泄露**），不存在 → `40401` |
| 20 | POST | `/api/exam/submit` | 交卷 → 判分 → 写 `attempts(kind='exam')` → 返回成绩报告 |

- `POST` 请求体【锁定】：`{paper_id:string, answers:[{id:string, answer_idx?:int(0..3), text?:string}]}`。
  - `choice` 用 `answer_idx`；`writing`/`speaking` 用 `text`（口语题由前端 ASR 转写后提交）。
  - 校验：paper_id 存在、id 集合与试卷题目集合一致不重复、类型/范围合法；非法 → `40001`。
- 试卷数据缺失时：`GET papers` 返回空列表 `code=0`（不 500，参考波一题库降级）；`GET papers/{id}` → `40401`。
- 3 个新路由必须声明在 `app.mount("/", StaticFiles(...))` **之前**。
- 幂等【锁定】：**允许重复交卷**，每次都写一条新的 `attempts(kind='exam')`（练习可反复做），不做波一那种"只写一次"限制。

## 7. 前端【锁定】

- 新增第 4 个 Tab「🏆 考级冲刺」，追加函数（不改写现有函数名），资源版本 `css v10→v11`、`js v11→v12`。
- 流程：选卷 → 答题（choice 单选 / writing 文本框 / speaking 复用麦克风 ASR）→ 交卷 → 成绩报告（总分、各项得分、中文反馈、薄弱建议、免责声明、再做一次）。
- 听力/口语题提供 🔊 按钮调 `/api/tts`；口语题提供 🎙 按钮走现有 `transcribeAudio()` 链路取文本。
- 全程温和文案、无倒计时、无红叉；API 失败给温和重试提示。

## 8. 零回归【锁定】

现有 17 个端点（v1 七业务 + 3 代理 + v2 五输入流 + 波一 2 定级）路径/入参/出参不变；`health.version="1.0.0"`；`users` 表不增列；`ai.py` 不改动；`requirements.txt` 仍两行；前端现有 3 Tab 与所有既有函数不破坏。

## 9. 分工与验收

- PM → `docs/EXAM_CHARTER.md`（用户流程、AC 验收项、文案口径、风险），不改锁定项。
- 架构师 → `docs/ARCHITECTURE_EXAM.md`（逐字段 Schema、判分伪码、GLM rubric prompt、降级表、零回归清单），不改锁定项。
- 内容 → `data/input/exam_papers.json`（2 套卷，按 §5）。
- 后端 → `backend/exam.py`（新增）+ `backend/app.py`（3 路由）。
- 前端 → `frontend/{index.html,app.js,styles.css}`（增量）。
- QA → `docs/QA_EXAM.md`，独立验收、临时库隔离、证明可用。
