# 呀呀法语 — 三项修复独立验收报告（QA_FIX_REPORT）

> 角色：qa（独立测试工程师）｜依据：`docs/ARCHITECTURE_V2.md` + team-lead 下发的验收清单｜原则：**不采信开发自报，以实际运行证据为准**。
> 约束遵守：全程未执行任何 git 命令；未修改 `backend/`、`frontend/`、`asr_service/` 中任何他人代码；本次仅在 `docs/` 下新建本报告一个文件。

## 一、摘要

- **总用例数：28　PASS：28　FAIL：0　BLOCK：0**
- **一句话结论**：三项修复（ASR 法语幻觉抑制、explanation 强制中文、前端修正提示与资源版本）均通过独立验收，v1 既有 HTTP 契约零回归，可交付。
- 期间发现并闭环 1 个环境问题：运行中 8010 的 ASR 进程初始为旧代码（`/health` 无新字段），经 team-lead 重启后复测通过。该问题属部署环节，非代码缺陷。

## 二、测试环境

| 项 | 值 |
|---|---|
| 测试时间 | 2026-11-17（本地时间） |
| 被测代码 | `backend/ai.py`、`asr_service/server.py`、`frontend/app.js`、`frontend/index.html` |
| Python | 系统 Python 3.13.14（backend/HTTP 测试）；`.venv-asr/Scripts/python.exe` 3.13.14（ASR 测试） |
| Node | v22.22.2（用于 `node --check`） |
| 服务 | 主服务 `http://127.0.0.1:8000`（health/chat/translate/tts/asr 代理）；ASR 服务 `http://127.0.0.1:8010`（health/transcribe/tts） |
| 方法 | monkeypatch `ai.urllib.request.urlopen` 精确模拟 OpenAI 响应与异常；`urlopen`/`curl` 打真实 HTTP；源码静态解析；`.venv-asr` 内 `import server` 直接调用纠正函数 |
| 数据隔离 | backend mock 套件 stub 掉 `ai._extract_new_words`，mock 部分无 DB 写操作；HTTP 回归按清单打真实 `/api/chat`，该端点按设计会向 `backend/data/yaya.db` 写入若干对话轮次与 XP（开发库，可接受副作用），未改动 DB 结构或种子数据 |

## 三、逐条验收结果

### 3.1 `backend/ai.py` — explanation 强制中文（7 例，全 PASS）

| 编号 | 验收项 | 预期 | 实际证据 | 结果 |
|---|---|---|---|---|
| T1 | 模拟 LLM 返回**法语** explanation → `recast()` 后变中文 | explanation 含中文且非法语 | monkeypatch `urlopen` 第 1 次返回合法 OpenAI 响应（`ai_text/recast_of/explanation=new_words`，`explanation="Le mot 'show' peut être utilisé..."`），第 2 次返回合法译文 JSON。实测 `urlopen_calls=2`，`explanation='“show”这个词可以用在很多场合。'` | **PASS** |
| T2 | 中文 explanation **不触发额外翻译请求** | `urlopen` 仅 1 次 | LLM 首次即返回中文 explanation `想礼貌点单，法国人更常说 voudrais...`，实测 `urlopen_calls=1`，explanation 原样保留 | **PASS** |
| T7 | 翻译失败时不抛 500、落温和中文占位 | explanation 为中文占位，无异常 | 第 2 次（翻译）`urlopen` 抛 `URLError`，实测 `explanation='这里有个更自然的说法，跟着呀呀读一遍就好啦～'`（`ai.py:460,488`），未抛异常 | **PASS** |
| T3 | 401 调用 **1 次**后降级 | 立即降级不重试 | stub 抛 `HTTPError(401)` ×1，`urlopen_calls=1`，降级返回本地规则结果（`ai_text='Je voudrais un thé'`，`explanation` 中文） | **PASS** |
| T4 | 429 调用 **2 次**后降级 | 重试 1 次再降级 | stub 抛 `HTTPError(429)` ×2，`urlopen_calls=2`，降级返回本地规则结果 | **PASS** |
| T5 | `ChatResult.to_dict()` 仍 4 字段 | 4 字段集合不变 | `fields=['ai_text','explanation','new_words','recast_of']`（集合等于预期） | **PASS** |
| T6 | `recast()` 出参仍是 4 字段 | 4 字段、无新增 | `keys=['ai_text','recast_of','explanation','new_words']`，长度 4 | **PASS** |

**实现核对**：`ai.py:454-490` 新增 `_CJK_RE`（覆盖假名/CJK 扩展 A/基本区/兼容汉字/韩文）、`_ensure_explanation_zh()`；`ai.py:510` 在 `recast()` 统一入口调用——非空且不含 CJK 才翻译，译文仍非中文则落中文占位；`ai.py:75,82` 的 SYSTEM_PROMPT 加入「explanation 必须是简体中文」硬约束。重试逻辑（`ai.py:287-299`，401/403 立即抛、429/5xx/URLError/timeout 重试 1 次）未被改动。

### 3.2 `asr_service/server.py` — 法语误识别修复（9 例 + 1 端到端，全 PASS）

| 编号 | 验收项 | 预期 | 实际证据 | 结果 |
|---|---|---|---|---|
| S1 | 转写传入法语 `initial_prompt` | 定义并传给 `model.transcribe` | 源码含 `INITIAL_PROMPT = os.environ.get(...)`（`server.py:56`）与 `initial_prompt=INITIAL_PROMPT or None`（`server.py:212`） | **PASS** |
| S2 | `beam_size` 提升 | 默认 >1 且传入 | `YAYA_ASR_BEAM_SIZE` 默认 `5`（`server.py:51`），`beam_size=BEAM_SIZE`（`server.py:209`） | **PASS** |
| S3 | `/transcribe` 响应含 `raw_text`/`corrected` | 两字段均在响应体 | 源码 `server.py:229-230` 含 `"raw_text": result["raw_text"]`、`"corrected": result["corrected"]` | **PASS** |
| S4.1 | 纠正函数 `"Show !"` | `"Chaud !"`, corrected=True | `{'text':'Chaud !','raw_text':'Show !','corrected':True}` | **PASS** |
| S4.2 | 纠正函数 `"Chef Onti"` | `"Un thé"`, corrected=True | `{'text':'Un thé','raw_text':'Chef Onti','corrected':True}`（首字母大写按设计继承） | **PASS** |
| S4.3 | 纠正函数 `"chef onti"` | `"un thé"`, corrected=True | `{'text':'un thé','raw_text':'chef onti','corrected':True}` | **PASS** |
| S4.4 | 纠正函数 `"SHOW !"` | `"CHAUD !"`, corrected=True | `{'text':'CHAUD !','raw_text':'SHOW !','corrected':True}` | **PASS** |
| S4.5 | 正常法语句不被误伤 | 原样返回, corrected=False | `"un thé bien chaud, s'il vous plaît."` → 原样，`corrected=False` | **PASS** |
| S5 | 运行中 ASR `/health` 暴露新字段 | `beam_size=5`、`initial_prompt_enabled=true` | 重启后 `{'status':'ok','model_loaded':true,'model_size':'tiny','device':'cpu','beam_size':5,'initial_prompt_enabled':true}` | **PASS** |
| E2E | 端到端转写响应字段 | 200/code=0 且含 text/raw_text/corrected | TTS 生成法语 `"un thé bien chaud, s'il vous plaît"`（16272 bytes）→ `POST /api/asr/transcribe` → `{'code':0,'data':{'text':"Un thé bien chaud, s'il vous plaît.",'language':'fr','raw_text':"Un thé bien chaud, s'il vous plaît.",'corrected':False}}`，5.0s | **PASS** |

> S4 采用「直接 import `server.correct_french_pronunciation` 传字符串」的方式，绕开真实音频，精确验证近音词映射（`/ʃoʊ/←chaud`、`/ɔ̃ti/←un thé`）与短语还原（`chef onti→un thé`）。`Show !→Chaud !` 为用户原始报障样例，已复现并验证修复。
> 另核对主后端代理 `backend/app.py:334-338` 已将 `raw_text`/`corrected` 透传到 `/api/asr/transcribe` 响应，E2E 结果证实两字段确实到达前端。

### 3.3 `frontend/app.js` / `index.html` / `styles.css`（7 例，全 PASS）

| 编号 | 验收项 | 预期 | 实际证据 | 结果 |
|---|---|---|---|---|
| F1 | `node --check app.js` | 退出码 0 | `rc=0, stderr=''` | **PASS** |
| F2 | `index.html` 资源版本 | `app.js?v=6`、`styles.css?v=6`，无 `?v=5` 残留 | `index.html:7/153` 均为 `?v=6`；`grep -rn '?v=5' frontend/` 无输出 | **PASS** |
| F3 | `transcribeAudio` 解析 `corrected`/`raw_text` | 均能解析并温和提示 | `app.js:573-579`：读取 `data.data.raw_text` 与 `data.data.corrected`，仅在 `corrected && rawText && rawText!==text` 时 `setMicStatus('已按法语发音把识别结果修正为：…')` 并 `submitUserText(text, rawText)` | **PASS** |
| F4 | 修正信息贯通 user turn 并在气泡显示 | `asr_raw` 挂到 user turn，气泡追加 🎧 小字 | `normalizeTurn`（`app.js:150`）、`userTurn(fr,rawText)`（`app.js:159`，仅当有 raw 且 !=fr 时挂 `asr_raw`）、`messageHTML`（`app.js:226`，`m.asr_raw` 时渲染 `<span class="asr-note">🎧 原声识别：… → 已按法语修正</span>`） | **PASS** |
| F5 | 🎧 小字样式非红色、低调 | 浅白半透明、虚线上边框、italic | `styles.css:82-83`：`.asr-note{color:rgba(255,255,255,.72);border-top:1px dashed rgba(255,255,255,.28);font-style:italic;font-size:10.5px}` | **PASS** |
| F6 | 打字/点击/浏览器兜底路径不误伤 | 单参调用，不出现 🎧 行 | `submitUserText(text)` 在 `sendTyped`（`app.js:431`）、`tryIt`（`app.js:437`）、`browserRecognizeFallback`（`app.js:604`）均为单参 → `asr_raw` 为空 → 无 🎧 行 | **PASS** |
| F7 | `corrected=false` 或无 `raw_text` 时走原流程 | 「识别到：xxx」，无 🎧 行 | `app.js:577` 条件不满足时走 `app.js:582` `submitUserText(text)` 单参；recast 卡片渲染逻辑（`app.js:224-236`）未改动 | **PASS** |

### 3.4 HTTP 回归（4 例，全 PASS）

| 编号 | 验收项 | 预期 | 实际证据 | 结果 |
|---|---|---|---|---|
| H1 | `GET /api/health` | 200 / code=0 | `status=200, {'code':0,'data':{'status':'ok','version':'1.0.0',...},'message':'ok'}` | **PASS** |
| H2 | `POST /api/chat`（scene=cafe, user_text="Je veux un thé"） | 200 / code=0 / 4 字段 | `code=0, keys=['ai_text','recast_of','explanation','new_words']`；实测 `recast_of='Je veux un thé'`，`explanation='想礼貌点单，法国人更常说 voudrais，不过你这样说也完全能懂'`（真实 GLM 输出，直接为中文，印证 prompt 硬约束生效） | **PASS** |
| H3 | `/api/chat` explanation 中文 | 含中文 | 见 H2，中文 explanation | **PASS** |
| H4 | `POST /api/translate` | 200 / code=0 | `status=200, {'code':0,'data':{'translations':['我想要一杯茶。']},'message':'ok'}` | **PASS** |

> 端口均可用，故按清单要求打真实 HTTP（未使用进程内替代）。8000/8010 初始与最终均监听正常。

## 四、缺陷清单

**未发现代码缺陷（28 例全 PASS）。**

过程中出现的 2 个 FAIL 经复核均非被测代码问题，已修正测试/环境后复跑通过：

1. **S4.2（首轮 FAIL → PASS）**：测试期望写成小写 `"un thé"`，但纠正函数 `_with_case()`（`server.py:156-162`）按设计继承原句首字母大小写，`"Chef Onti"` 正确输出 `"Un thé"`。属测试期望错误，已修正。
2. **S5（首轮 FAIL → PASS）**：运行中 8010 ASR 进程为旧代码（`/health` 仅 4 字段），非代码缺陷。经 team-lead 重启后 `/health` 返回 `beam_size=5, initial_prompt_enabled=true`，复测通过。

## 五、未覆盖项与限制

1. **真实音频下的误识别率未量化**：E2E 用 TTS 生成的清晰语音验证了响应字段与转写正确性，但「法语被识别成 Show !/Chef Onti」是 tiny 模型在特定发音/底噪下的概率性幻觉；本次未做批量音频统计误识别率下降幅度，`beam_size=5 + initial_prompt` 的效果属机制层面确认（参数确实生效）而非大样本 A/B。
2. **真实 GLM 偶发法语 explanation 的 HTTP 复现**：真实 key 调用下抽样的 explanation 为 `None` 或中文，未能稳定复现「LLM 返回法语 explanation」的线上场景；该路径由 **T1（mock 合法 OpenAI 响应）** 精确覆盖，属等效验证。翻译失败兜底由 **T7** 覆盖。
3. **浏览器端 DOM/真实点击未做**：F1-F3 为静态与语法层验证，未做真实浏览器麦克风授权、`MediaRecorder` 录音、识别后小字提示的可视化端到端。
4. **纠正词典覆盖面**：`_WORD_MAP`（`server.py:144-150`）仅含 show/sho/onti/onty/onte 与 chef onti 短语，其他潜在英文幻觉词未穷尽；本次按报障样例验证。
5. **不重试的 401/403 与可重试的 5xx/超时**：`401`（T3）、`429`（T4）已实测；`403`、`503`、`URLError`、`socket.timeout` 的重试次数沿用前序 QA 报告（QA_REPORT.md M02-M05）基线，本次未重复展开。

## 六、结论

三项修复均通过独立验收，各项核心诉求达成：

- ① ASR：法语 `initial_prompt` 与 `beam_size=5` 确实传入并生效；`Show !→Chaud !`、`Chef Onti→Un thé` 修正有效；`/transcribe` 返回 `raw_text`/`corrected` 且端到端 200。
- ② explanation：LLM 法语讲解经 mock 验证转为中文，中文讲解零额外请求，翻译失败有中文占位兜底，不抛 500。
- ③ 前端：`node --check` 通过、资源 `?v=6`、`transcribeAudio` 解析 `corrected`/`raw_text` 并温和提示。
- 回归：`/api/health`、`POST /api/chat`（4 字段、中文 explanation）、`POST /api/translate` 均 200/code=0。

**建议：可交付。** 后续若有真实用户音频样本，建议补一轮误识别率的量化对比（限制项 1）。

---

> 报告生成：qa（独立测试）｜用例统计：backend 7 + ASR 10 + frontend 7 + HTTP 4 = 28（全 PASS）
> 证据脚本位于系统临时目录（`C:\Users\Karen\AppData\Local\Temp\yaya_qa_*.py`），未写入项目仓库。
