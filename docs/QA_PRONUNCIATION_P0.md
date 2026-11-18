# 呀呀法语 · 零基础读音规则学习 P0 独立验收报告

> 验收角色：qa-pron（第二层独立 QA，skeptical 视角：以证明代码真的能工作为目标，非确认文件存在）
> 日期：2026-11-18　范围：commit `7d118b7`/`c674c0f`（契约+JSON）、`ee42eac`（后端）、`fcf99eb`（前端）
> 权威依据：`docs/PRONUNCIATION_CONTRACT.md` v1.0（§6 字段清单、§7 八项裁决、§8 12 条测试要点）、`docs/PRONUNCIATION_PLAN.md` §10 四项确认

## 0. 测试隔离方式（关键：不污染主库）

| 项 | 做法 |
|----|------|
| 主库 | `backend/data/yaya.db` 全程只读检查；验收结束复查 `pronunciation_progress` = **0 行**（未被污染） |
| 后端实例 | 临时启动器在 `import app` **之前**把 `db.DB_PATH`/`db.DATA_DIR` monkeypatch 到 `%TEMP%/qa_pron_isodb/yaya.db`，每次启动删旧库保证干净初始态 |
| 端口 | 主实例 **8012**、降级实例 **8013**（避开 8000/8011） |
| 降级测试 | 8013 在 import app 前把 `pronunciation.INPUT_FILE` 指向不存在文件，使启动缓存为 `[]` |
| B9 零 IO | 用 `try/finally` 把 `data/input/pronunciation_rules.json` 临时改名为 `.qa_bak`，测完必改回；已复核文件完好 |
| 前端 | agent-browser 命名会话 `qapron`，访问 8012 静态页；失败注入用 `agent-browser network route --abort` |
| 产品代码 | **零修改、零 commit**；所有测试脚本写在 `%TEMP%`，不在项目内 |

---

## A. 静态与契约一致性

### A1. 语法编译
```
python -m py_compile backend/db.py backend/app.py backend/pronunciation.py   → PY_COMPILE_OK
node --check frontend/app.js                                                  → NODE_CHECK_OK
```
**PASS**

### A2. §6 字段清单四方逐字核对 + 禁用别名
以 `%TEMP%/qa_pron_static.py` 递归遍历 JSON 键（**非全文字符串搜索**，避免把 `"shadow_mode":"word"` 的合法值误判为禁用键），并对后端源码常量做集合相等比对。结果 **31/31 PASS**，关键证据：

| 检查 | 结果 |
|------|------|
| 规则单条字段严格 = `RULE_FIELDS`(10) | `mismatch=[]` |
| `ExampleItem` 字段严格 = 4 | `mismatch=[]` |
| `RuleSummary` 摘要仅 4 字段 | 后端 `SUMMARY_FIELDS={id,group,title,tier}` |
| `ProgressItem` / `ProgressView` 出参 | 后端 `row_to_*` / app 组装逐字段一致 |
| `pronunciation_progress` 表 6 字段 | `cols=[user_id,rule_id,stage,practice_count,last_practiced_at,self_assessed]` |
| **禁用别名 `word`/`highlight`/`read_aloud` 作为键名命中** | **0**（`hits=[]`） |
| 后端 RULE/SUMMARY/EXAMPLE 三常量 = 契约 | 全部集合相等 |

> 过程说明：脚本初版 4 项 FAIL 经人工复核均为**脚本误报**（naive 字符串匹配命中 docstring/注释中的 `practice_count` 与 `P0 无 🎙 跟读`），修正为"剥离注释后按代码语义判断"后全 PASS。这不是产品缺陷。

**PASS**

### A3. §7 八项裁决落实

| # | 裁决 | 证据 | 结果 |
|---|------|------|------|
| ① | examples 恰好 4 条 | 39 条全部 `len(examples)==4`，156 IPA 槽位全配 | PASS |
| ② | group 8 纯组名 + tags[0] 档位 | 分布 `4/6/7/6/5/4/4/3` 与裁决一致 | PASS |
| ③ | self_assessed 只增不减 | `db.py:979` `final_self = 1 if (row["self_assessed"] or self_assessed) else 0`；HTTP 实测 1→0 仍 true | PASS |
| ④ | practice_count 服务端 +1、忽略客户端传值 | `db.py:982` SQL `practice_count = practice_count + 1`；upsert 签名无该参数；app POST 不读 `body['practice_count']`；前端 POST body 无该字段 | PASS |
| ⑤ | 已学 N = learned + confident 排除 seen | `db.py:939`、`app.js:1926` 均为二者相加；实测 learned_total=1/2 正确 | PASS |
| ⑥ | 摘要四字段 | 实测 `keys=['group','id','tier','title']` | PASS |
| ⑦ | version 键忽略 | `pronunciation.py:101` 只读 `payload.get("rules")`，无 `["version"]` 读取 | PASS |
| ⑧ | id 段名 alpha/except 等 8 英文段名 | `segs_used=['alpha','ccomb','comb','cons','except','final','nasal','vowel']`，39 条唯一，无 A–H 段名 | PASS |

**PASS**

---

## B. 后端 HTTP 真实测试（8012，隔离 DB）

### B4. 现有端点零回归
```
health:  http=200 code=0 version=1.0.0
scenes:  http=200 code=0 data_size=4
input/levels:      http=200 code=0 data_size=3
exam/papers:       http=200 code=0 data_size=2
assessment/questions: http=200 code=0 data_size=2
requirements.txt:  ['fastapi','uvicorn']（两行）
4  pronunciation 路由索引 24177 < static mount 26828（先于 mount 声明）
```
**PASS**

### B5. GET /api/pronunciation/rules
| 场景 | 实测 | 结果 |
|------|------|------|
| 默认 | `http=200 code=0 len=39`，首项 `keys=['group','id','tier','title']` | PASS |
| `group=元音字母组合` | `len=6`，`groups=['元音字母组合']`（精确） | PASS |
| 非法 group | `http=400 code=40001 msg=非法分组：非法分组` | PASS |
| 缓存空降级（8013） | `/rules → http=200 code=0 data=[]`；`/rules/ph_alpha_01 → 40401`；`/progress total_rules=0`；启动日志 `WARNING yaya.pronunciation: 读音规则文件不存在…规则降级为空` | PASS |

**PASS**

### B6. GET /api/pronunciation/rules/{id}
```
ph_alpha_01: http=200 keys=['audio_text','description_zh','examples','group','id',
  'shadow_mode','shadow_text_fr','tags','tier','title']  (10 字段)
examples: len=4, first_keys=['meaning_zh','note_zh','phonetic','word_fr']
听/跟读分离: audio_text='Paris, été, si, oui'  shadow_text_fr='si'
不存在 ph_NOT_EXIST: http=404 code=40401 msg=读音规则不存在：ph_NOT_EXIST
```
**PASS**

### B7. GET /api/pronunciation/progress（空库）
```
http=200 data={"user_id":1,"total_rules":39,"seen_count":0,"learned_count":0,
  "confident_count":0,"learned_total":0,"items":[]}
有记录后读回 self_assessed 类型: ['bool']
```
**PASS**

### B8. POST /api/pronunciation/progress
| 场景 | 实测 | 结果 |
|------|------|------|
| 同一 rule_id 连发 2 次（第 2 次传 practice_count=999） | `1st=1 2nd=2`（999 被忽略） | PASS |
| last_practiced_at | `2026-11-18T09:39:25Z`（now_iso 格式） | PASS |
| self_assessed 1 后传 0 | `after1=True after0=True` | PASS |
| 幂等 | `rows_for_ph_alpha_01=1 total_items=1` | PASS |
| 未知字段 audio/transcript | `http=200`，响应仅 5 个 ProgressItem 字段，未落库 | PASS |
| 不存在 rule_id | `http=404 code=40401` | PASS |
| 非法 stage / 非对象体 / 缺 rule_id / 空白 rule_id / 非法 self_assessed | 均 `40001` | PASS |

**PASS**

### B9. 零运行时 IO
```
[B9] 已临时改名 pronunciation_rules.json -> pronunciation_rules.json.qa_bak (server 保持运行)
PASS 改名后 /rules 仍 39 条 code0
PASS 改名后 /rules/{id} 仍返回详情 (keys=10)
PASS 改名后 /progress 仍正常 (total_rules=39)
PASS 改名后 POST /progress 仍成功
[B9] 已恢复 pronunciation_rules.json; exists=True bak_exists=False
```
**PASS**

### 补充：建表幂等与 schema
```
init_db(); init_db()  → OK
PRAGMA table_info 字段/类型/NOTNULL/默认/主键 = MATCH（5 列 NOT NULL，last_practiced_at 可空）
CHECK (stage IN ('seen','learned','confident')) = True
PRIMARY KEY (user_id, rule_id) = True
索引: idx_pron_progress_user / idx_pron_progress_user_stage / sqlite_autoindex
```
**PASS**

---

## C. 前端浏览器真实测试（8012，agent-browser）

### C10. 词卡融入点 + 规则卡
```
命中词🎵入口数 = 1
未命中词卡: chaud / froid → entry=false, voudrais → entry=false, un café → entry=true
规则卡: title="字母 c 的软硬两种读法", kicker="🎵 字母表与读音概念入门", desc_len=83
listenBtns=2 (🔊 先听一遍 / ↻ 再听一次)
examples=[{word:café, ipa:/ka.fe/, spk:true},{cinq,/sɛ̃k/,true},{cent,/sɑ̃/,true},{cadeau,/ka.do/,true}]
stages=[👀 见过, 🌱 学会了, ✨ 能自己读]
```
字段齐全、有 IPA、每条例词有 🔊。**PASS**

### C11. 进度读写 + 服务端持久化
```
点击前小册子: 📖 读音小册子 · 已学 0/39
点 ✨ 能自己读后: toast="记下啦，这条你越来越熟了～", badge="能自己读", 小册子=1/39
服务端 GET /progress: {"confident_count":1,"learned_total":1,
  "items":[{"rule_id":"ph_alpha_03","stage":"confident","practice_count":1,"self_assessed":true}]}
刷新页面后小册子 = 1/39
localStorage 键 = []（无任何进度键；"能自己读"进度来自服务端而非 localStorage 假象）
```
**PASS**

### C13. 首次提示气泡（先于 C12 执行，避免 localStorage 干扰）
```
首次 hidden=false（弹出）
点 × 后 hidden=true
localStorage 键 = ["pron_tip_shown"]
刷新后 hidden=true（不再弹）
```
**PASS**

### C12. 小册子
```
8 组: 字母表与读音概念:4, 基础元音:6, 基础辅音:7, 元音字母组合:6,
      辅音字母组合:5, 鼻化元音:4, 词末辅音规则:4, 高频例外与易错:3
条目总数 = 39
微标分布 = {"未见过":38, "能自己读":1}
点条目 → 复用规则卡，标题="字母有名字，也有读音"
```
**PASS**

### C14. 回归（4 Tab + 对话 + 考级）
```
Tab 按钮 = ["💬 对话陪练","📖 分级阅读","🎯 定级","🏆 考级冲刺"]
逐个点击 tabRead / tabAssessment / tabExam → view 均 "visible"
对话发送: 输入 "Bonjour test" → 点发送 → chat 尾部出现 "我 / Bonjour test / 🔊 / 翻译中…"
```
**PASS**（翻译小字停留在"翻译中…"是因为测试环境未配置翻译/AI 上游，属既有依赖，不影响"发送"主流程；用户气泡正常渲染）

### C15. P0 范围红线
```
Tab 总数 = 4（无第 5 个）
发音浮层内 🎙 按钮数 = 0（无跟读入口）
打开规则卡前后 chat 气泡数 3 → 3（读音动作不注入对话流消息）
规则卡为独立 #pronOverlay 浮层，非 chat 气泡
```
**PASS**

---

## D. 边界与陷阱（主动找茬）

### D16. 规则数据加载失败优雅降级
用 `agent-browser network route "**/api/pronunciation/*" --abort` 后 reload：
```
🎵 入口数 = 0（降级：不显示读音入口）
小册子文案 = 📖 读音小册子 · 已学 0/39（回退 total 39）
核心功能仍在: tabs=4, scenes=4, cards=4, 输入框存在
agent-browser errors → 无页面错误
```
原有功能完全不受影响。**PASS**

### D17. 多次快速点击
```
10 并发 POST 返回 practice_count 序列 = [1,5,3,10,7,4,6,9,8,2]（各不重复）
最终库内 practice_count=10，行数=1（幂等，无丢计数）
浏览器同步连点 5 次"学会了": ph_alpha_03 practice_count 1→6（+5），learned_total=2
```
服务端严格累加，符合裁决④预期。**PASS**

### D18. practice_count 覆盖语义
```
起始=10 → 传 999 → 11；传 -5 → 12；传 0 → 13；最终库内=13
```
任意客户端值（含负数）均被忽略，服务端恒 +1；静态亦确认全链路无覆盖实现。**PASS**

### 补充：音位口径与评分位置（§8 要点 4/11）
```
/ɑ̃/ 例词 11 处（cent/grand/champagne/manger…），/ɑ/ 仅 2 处：
  pâte /pɑt/、âne /ɑn/，均在 ph_vowel_01（基础元音组），与鼻化组不混写。
服务端 grep pronunciation/(score|assess)|band|评分|score\( → 无命中（无评分端点）。
```
**PASS**

---

## 总结

| 项 | 结果 |
|----|------|
| 逐项验收（题目 1–18） | **18 PASS / 0 FAIL** |
| 静态契约子检查 | **31 PASS / 0 FAIL** |
| 后端 HTTP 子检查 | **35 PASS / 0 FAIL** |
| 浏览器观察 | **19 PASS / 0 FAIL** |
| 边界/补充子检查 | **6 PASS / 0 FAIL** |

### 阻塞性缺陷
**无。** 未发现任何阻塞性、功能性或契约违背缺陷。

### 非阻塞观察项（不建议因此拒收）
1. **首次提示文案涉及 P1 功能**：`frontend/index.html:86` 文案为"生词旁有个小喇叭，点一下能听标准读音、**还能跟着读**～"。P0 按 §10 不做跟读（🎙 入口实测为 0），该文案可能让用户期待一个尚不存在的功能。**文件/行号**：`frontend/index.html:86`。**建议**：后续版本改为"点一下能听标准读音、看看怎么读～"，或随 P1 跟读上线再对齐。此为文案问题，非功能缺陷。
2. **连点 UI 一致性**：快速连点时服务端计数严格正确（D17 已证），但前端采用"等 POST 返回再局部更新"策略，极端并发下各次响应可能乱序，理论上短暂显示旧计数；刷新后从服务端读取即正确。未观察到实际错值，且不影响契约要求（服务端累加）。仅作风险提示。

### 验收建议
**建议通过验收。** 实现在字段一致性、8 项裁决、4 端点错误码、零运行时 IO、前端融入式交互、服务端持久化、P0 范围红线、边界降级等方面均有真实证据支撑，主库未被测试污染，产品代码零修改。

---

## 附：证据可复现方式
- 静态脚本：`python %TEMP%/qa_pron_static.py`（31/31）
- 后端 HTTP：`python %TEMP%/qa_pron_http.py`（26/26，8012）
- 零 IO：`python %TEMP%/qa_pron_b9.py`（4/4，自带 finally 恢复）
- 降级实例：`python %TEMP%/qa_pron_launch2.py` + curl 8013（3/3）
- 浏览器：agent-browser 会话 `qapron`，`network route --abort` 注入失败
- 所有测试脚本仅位于 `%TEMP%`，未写入项目仓库
