# 阶段0 CEFR 定级 · 独立 QA 验收报告

| 项 | 内容 |
|----|------|
| 任务 | 波一 · TASK-0022「阶段0 CEFR定级」独立验收 |
| 角色 | qa（独立验证，不采信开发者自检结论） |
| 日期 | 2026-11-18（UTC 时间约 05:04–05:08，对应北京时间 13:04–13:08） |
| 事实源 | `docs/ARCHITECTURE_PLACEMENT.md`（PLACEMENT v1.1 冻结契约）、`docs/PLACEMENT_CHARTER.md`（产品契约 §4.3 / §6 / §7.2） |
| 验收对象 | `backend/assessment.py`、`backend/db.py`、`backend/app.py`、`frontend/{index.html,app.js,styles.css}`、`data/input/assessment_questions.json` |
| 方法 | 静态逐字对照 + 独立算分复现（自写参考实现，不调用 `assessment.grade()` 推期望）+ HTTP 真实请求 + 隔离 DB 写库验证 + 边界/错误路径主动构造 + 零回归抽样 |
| 环境 | Python 3.13.12（`C:\Users\Karen\.workbuddy\binaries\python\versions\3.13.12\python.exe`）、Node（app.js 语法检查）、FastAPI 0.163.1 / Uvicorn 0.54.0 |
| **结论** | **16 / 16 验收项 PASS，0 FAIL；波一可交付** |

## 环境与隔离说明（重要）

- 验收开始时 8000 / 8010 端口**均无监听进程**（`Get-NetTCPConnection -State Listen` 确认），并非任务背景中描述的“8000 正在跑旧代码”。
- 为避免污染主库 `backend/data/yaya.db`，采用**环境变量隔离启动器**（临时文件 `D:\tmp\qa_placement\launch_qa.py`，位于项目外）：启动前覆盖 `db.DB_PATH` / `assessment.INPUT_FILE`，再 import `app` 触发 `init_db()` 与题库加载。
  - 8000：隔离测试库 `D:\tmp\qa_placement\yaya_test.db`（主库的逐字节副本），加载真实题库 → 用于 HTTP 主流程验收。
  - 8001：隔离测试库 + 指向不存在的题库文件 → 用于“题库空降级”验收。
- 主库全程**只读**：所有写库测试均发生在上述隔离副本中。
- 验收结束：8001 实例已停止；**8000 保持运行**（`http://127.0.0.1:8000/api/health` 返回 `version=1.0.0`），其数据是**已重置到验收前基线的隔离副本**（cefr_level=A2、attempts=0）。如需面向真实数据的服务，请由后端/总指挥按正常命令另行启动（注意正常启动会触发 `seed_input.load_input_corpus()` 写库）。

---

## 逐项验收清单

### A. 静态 / 契约层

**A1. 语法编译检查 — PASS**
```
$ python -m py_compile backend/assessment.py backend/db.py backend/app.py   -> 无输出，退出码 0
$ node --check frontend/app.js                                             -> 无输出，退出码 0
```
证据：两个命令退出码均为 0，无语法错误输出。

**A2. 题库 JSON 结构 — PASS**
```
n=12, level_counts={A2:4, B1:4, B2:4}
skills_per_level_ok=True   （每级 4 题覆盖 词汇/语法/理解 ≥3 类）
options_ok=True            （每题 4 项、trim 后非空且互不重复）
answer_idx_ok=True         （全部 int、非 bool、0..3）
explanation_zh 禁用词命中=0
id_unique=12, id_format_ok=True（逐题匹配 ^asm_(a2|b1|b2)_\d{3}$ 且后缀等级与 level 一致）
```
实际 id 序列：`asm_a2_001..004, asm_b1_001..004, asm_b2_001..004`（每级内三位序号，符合 §2.2）。

**A3. 前端静态检查 — PASS**
- 版本号已刷新：`index.html` 由 `styles.css?v=8` → `?v=10`、`app.js?v=9` → `?v=11`（git diff 确认，旧值已不存在）。
- 新增函数存在：`initAssessment`、`startAssessment`、`renderAssessmentQuestion`、`submitAssessment`、`renderAssessmentResult`（均 `function X` 命中）。
- 现有函数未破坏：`renderVocab`、`renderLedger`、`renderScenes`、`renderTop` 均保留。
- 新增定级文案扫描禁用词（官方/认证/权威/证书/考试/不合格/排名）命中 0。
  - 附注：`app.js:612` 注释含“权威”二字，但属 ASR 置信度代码注释（他人 D1/D2 修复内容），非定级新增用户可见文案，不计违规。

**A4. §8 四方字段一致性 — PASS**
- `attempts` 表 6 列逐字：`id, user_id, kind, score, detail_json, created_at`（`db.py:165-172` DDL 与索引一致）。
- `PublicQuestion` 5 字段逐字（运行时响应核对见 C8）：`id, level, skill, question, options`。
- `PlacementResult` 6 字段逐字（运行时响应核对见 C9）：`score, total, weighted_score, level, interpretation_zh, persisted`。
- `AttemptDetail` 7 字段逐字（运行时 DB 核对见 C9）：`total, level, rate, weighted_score, weak_skill, interpretation_zh, answers`。
- 错误码仅用 `0 / 40001 / 50001`，未新增（见 C11 / C12）。

### B. 算分层（独立实现复验）

独立复验脚本 `D:\tmp\qa_placement\verify_scoring.py`：先用契约 §4.2 伪码自写 `ref_level/ref_grade/ref_weak`（**不 import `assessment.grade` 推导期望值**），再用真实题库构造答卷，调用 `assessment.grade()` 比对。

**B5. TC1–TC8 全部一致 — PASS（8/8）**
```
TC1 (4,4,4) S=24 -> exp B2 / got B2  score 12 weak 词汇  PASS
TC2 (3,4,3) S=20 -> exp B2 / got B2  score 10 weak 理解  PASS
TC3 (4,4,2) S=18 -> exp B1 / got B1  score 10 weak 理解  PASS
TC4 (4,3,0) S=10 -> exp B1 / got B1  score  7 weak 理解  PASS
TC5 (3,2,0) S= 7 -> exp A2 / got A2  score  5 weak 理解  PASS
TC6 (0,0,4) S=12 -> exp A2 / got A2  score  4 weak 词汇  PASS
TC7 (0,0,0) S= 0 -> exp A2 / got A2  score  0 weak 词汇  PASS
TC8 (2,4,4) S=22 -> exp A2 / got A2  score 10 weak 语法  PASS   ← 分组下限压过总分，必测点通过
```
比对字段：`score / weighted_score / level / rate / weak_skill`，8 例 5 字段全部一致。

**B6. weak_skill 并列顺序 — PASS**
构造 词汇=2/4、语法=2/4（并列最低）、理解=4/4 → `assessment.grade()` 返回 `weak_skill=词汇`，符合“并列时 词汇 < 语法 < 理解”。

**B7. interpretation_zh 逐字模板 — PASS（A2/B1/B2 + 弱项提示）**
```
A2: 本次定级共 12 题，答对 9 题，正确率 75%。你已经掌握了基础法语，能应对简单日常交流；接下来可以扩充词汇量，练习过去时和简单描述，继续保持就很棒。理解是你接下来可以多花点时间的地方。  [逐字一致]
B1: 本次定级共 12 题，答对 9 题，正确率 75%。你的法语基础扎实，能就熟悉话题展开交流；建议加强复合时态与虚拟式入门，并提升听说流利度，离进阶不远啦。理解是你接下来可以多花点时间的地方。  [逐字一致]
B2: 本次定级共 12 题，答对 9 题，正确率 75%。你的法语水平已经相当不错，能较自如地表达观点；接下来可挑战更复杂的阅读与原声听力，向更高阶稳步前进。理解是你接下来可以多花点时间的地方。  [逐字一致]
```
前缀中 `total=12`、`rate_pct=int(round(rate*100))=75` 正确；三段文案与弱项提示与 §5 逐字比对一致。

### C. HTTP 层（隔离实例真实请求）

**C8. GET /api/assessment/questions — PASS（安全红线通过）**
```
http=200 code=0 total=12 n=12 leaked_ids=[] fields_ok=True
```
- 逐题审计 12/12：每题字段集合**恰好**为 `{id, level, skill, question, options}`，零 `answer_idx`、零 `explanation_zh`（这是防作弊安全红线）。
- 附带验证“重复取卷一致性”（契约 §9 测试 15）：两次取卷 12 个 id 与顺序完全相同，`ids_identical=True`。

**C9. POST /api/assessment/submit 正常路径 — PASS**
用题库真实 `answer_idx` 构造全对答卷：
```
http=200 code=0 data={"score":12,"total":12,"weighted_score":24,"level":"B2",
  "interpretation_zh":"...词汇是你接下来可以多花点时间的地方。","persisted":true}
隔离库: cefr_level A2->B2, attempts 0->1, kind=placement
GET /api/profile: cefr_level=B2；target_level/xp/streak_days 与提交前一致（未被动）
detail_json 反序列化: keys=[answers,interpretation_zh,level,rate,total,weak_skill,weighted_score]，
  answers 12 项、每项 {id,level,skill,answer_idx,correct}，correct 为 bool，rate=1.0
```

**C10. 幂等 — PASS**
同一答卷第二次提交：`persisted=false`、`level=B2`、`weighted_score=24` 与首次一致、`attempts` 仍为 1、`cefr_level` 未被二次改写。
额外主动探测**并发双提交**（2 线程同时提交）：`[(200,True),(200,False)]`，`attempts=1`、`cefr=B2` —— 并发下亦未双写。

**C11. 错误路径 14 种 — PASS（14/14）**
全部返回 `HTTP 400 + code 40001 + data:null + 中文 message`：
```
answers非数组(dict/string) -> "answers 必须是非空数组"
answers空数组              -> "answers 必须是非空数组"
长度11 / 长度13            -> "答案数量与题目数量不一致"
元素非dict                 -> "answers 元素必须是对象"
id不存在                   -> "题目不存在：asm_zzz_999"
id重复                     -> "题目 id 重复：asm_a2_001"
id集合不一致               -> "题目 id 重复：..."（集合一致性由“长度12+id存在+不重复”联合保证）
answer_idx=true(_bool)     -> "answer_idx 必须是整数"
answer_idx=-1 / 4           -> "答案索引超出范围"
answer_idx="1"(字符串)      -> "answer_idx 必须是整数"
请求体为 JSON 数组          -> "请求体必须是 JSON 对象"
```
> 过程说明：初测出现 1 个 FAIL，经排查为**测试脚本自身缺陷**（“id重复”用例实际构造了一份合法答卷），修正用例后 14/14 通过；非产品代码问题。

**C12. 题库空降级 — PASS（8001 隔离实例，题库路径指向不存在文件）**
```
启动日志: WARNING yaya.assessment:定级题库文件不存在 ... 题库降级为空  （服务正常启动，未阻断）
GET  /api/assessment/questions -> http=200 code=0 data={"questions":[],"total":0}  （不抛 500）
GET  /api/health               -> http=200 code=0 version=1.0.0
POST /api/assessment/submit    -> http=500 code=50001 data=null message="定级题库暂不可用，无法判分"
```
符合 §3.1 降级与 §6.1.3「先判题库」要求。

### D. 零回归层

**D13. 现有端点抽样回归 — PASS（6/6，无 500）**
```
GET  /api/health            -> 200 code0 version="1.0.0"
GET  /api/scenes            -> 200 code0 data=list
GET  /api/profile           -> 200 code0 data=dict
GET  /api/input/levels      -> 200 code0 data=list
GET  /api/input/recommend   -> 200 code0 data=dict
POST /api/chat（无 key）     -> 200 code0 keys={ai_text,recast_of,explanation,new_words}
```
统一 `{code,data,message}` 包裹、错误码集合、CORS 配置（源码核对 `app.py:36-42` 逐字）、静态路由顺序（`app.py:547/554` 新路由在 `app.mount("/",...)` 之前）均保持不变。

**D14. i+1 推荐联动 — PASS**
`cefr_level` 写回 B2 后，`GET /api/input/recommend` 返回 `target_level="C1"`（CEFR_ORDER 中 B2 的 i+1），`reason=level_and_coverage`。链路打通，推荐算法未改动。

**D15. 文案合规 — PASS**
对 submit 响应 `interpretation_zh` 全文禁用词扫描：`hits=[]`（官方/认证/权威/证书/考试/不合格/排名 命中 0）。前端新增定级文案扫描同样命中 0（见 A3）。

### E. 数据完整性

**E16. 主库未被污染 — PASS**
```
基线: sha256=58734bfab967ecc983f28fa138e32070df6d56bf08efea62579243d95b47a41c, cefr=A2, attempts=0
终态: sha256=58734bfab967ecc983f28fa138e32070df6d56bf08efea62579243d95b47a41c, cefr=A2, attempts=0
```
主库哈希与验收前**逐字节一致**；说明开发者自检确实未污染主库，且本次 QA 写库测试全部在隔离副本完成。

---

## 发现的问题

### 功能性缺陷
**无。** 16 项验收全部通过，未发现 FAIL 级别问题。

### 观察项（非缺陷，不阻断交付）

1. **[低 / 文档一致性]** `docs/ARCHITECTURE_PLACEMENT.md` §2.1 的 `AttemptDetail.answers` 描述为 `[{id, answer_idx, correct}]`，而 §4.2 伪码的 `correct_flags` 含额外 `level`/`skill`；实现 `assessment.py:142-150` 遵循 §4.2 伪码，写入的 answers 元素为 5 键（含 level/skill）。§8.2 的**顶层字段清单逐字一致**，不影响判分与响应；建议后续文档统一口径，明确 answers 元素是否允许携带 level/skill（当前为超集，无兼容问题）。

2. **[低 / 冗余字段]** `data/input/assessment_questions.json` 顶层存在 `"version": 1` 字段。契约 §10 第 8 项裁决“不引入 version”，且 `load_questions()` 仅读取 `questions` 数组、该字段不进入任何 API 响应，故不构成验收失败；建议内容角色按裁决移除以保持契约纯净。

### 验收过程中的自查修正（如实记录）
- 初测 A2、C11 各出现 1 个 FAIL，均定位为**验收脚本 bug**而非产品缺陷：
  - A2：脚本误把 id 序号当作全局 001–012；契约 §2.2 明确为**每级内**三位序号，修正断言后通过。
  - C11：“id重复”用例误写成合法答卷；修正后 14/14 通过。
- 这两处修正未掩盖任何产品问题；所有断言均保留可复现证据。

---

## 结论

**波一阶段0 CEFR 定级：可交付。**

- 16 / 16 验收项 PASS，0 FAIL；TC1–TC8（含反直觉用例 TC8）、14 种非法入参、答案保密红线、幂等与并发、题库空降级、i+1 联动、零回归抽样、主库零污染均实证通过。
- 唯一待办为**文档层口径统一**（观察项 1/2），不影响功能与数据，不构成交付阻断。

## 主库清理声明

- 验收前已备份主库至 `C:\Users\Karen\AppData\Local\Temp\qa_placement\yaya.db.orig`（未用于恢复，因主库从未被写）。
- 主库 `backend/data/yaya.db` 的 `cefr_level` **保持验收前原值 A2**，`attempts` 表 **保持 0 行**，sha256 与基线逐字节一致。**无需恢复、无残留。**
- 所有写库测试均在隔离副本 `D:\tmp\qa_placement\yaya_test.db` / `yaya_degrade.db` 中完成；当前 8000 服务连接的是已重置为基线的 `yaya_test.db`（非主库）。
