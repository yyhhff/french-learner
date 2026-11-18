# 呀呀法语（YaYa French）

> 像婴儿一样，自然地学会法语。Web 形态，终点 B2（外派可用）。

## 产品理念

体验层走"婴儿式"——可理解输入、先听后说、情境化内容、**重述式纠错（recast）**、低情感过滤；
引擎层走"成人式"——CEFR 定位、SM-2/FSRS 复习、AI 诊断、B2 考级专项。

核心差异化：用户说错时不给红叉，而是由 AI 顺着语义自然接话，把正确说法"重述"回去。**协议层保证"说错话"永远返回 HTTP 200，只有 `recast_of != null` 时才渲染重述卡。**

## 当前状态：阶段二完成（GLM 可插拔重述 + i+1 输入流，独立 QA 109/109 通过）

本目录是**独立 Git 仓库**，提交历史：
- `280e9d7` 前端原型 Demo　`b1fd04f` 章程+契约 v1　`2e13369` 全栈版本
- `0687252` 本地 Whisper 根治 network　`768e776` edge-tts 神经语音　`2a0cf63` Chrome 音频修复
- `b22b549` 阶段二章程 + 架构契约 v2　`5acf5ba` 阶段二 A+B 实现　`c0b1f5e` 独立 QA 报告

阶段二新增两条主线：**A 智谱 GLM 可插拔重述**（无 key 自动降级本地规则）、**B i+1 可理解输入流**（A2/B1/B2 三级各 7 篇、共 21 篇 / 157 生词）。详见 `docs/PHASE2_CHARTER.md`、`docs/ARCHITECTURE_V2.md`、`docs/QA_REPORT.md`。

### 目录结构

```
french-learner/
├── docs/
│   ├── ARCHITECTURE.md       # 契约 v1：7 API + 5 表 + 字段一致性清单
│   ├── ARCHITECTURE_V2.md    # 契约 v2：GLM 适配 + 输入流 5 端点 + 语料 schema（四方唯一输入）
│   ├── PROJECT_CHARTER.md    # 阶段一章程
│   ├── PHASE2_CHARTER.md     # 阶段二章程：双主线目标/WBS/RACI/10 项风险
│   └── QA_REPORT.md          # 独立 QA：109 用例全通过、零阻塞缺陷
├── backend/                  # FastAPI 服务
│   ├── app.py                # v1 7 端点 + v2 输入流 5 端点 + ASR/TTS 代理 + 批量翻译 + 静态托管
│   ├── db.py                 # sqlite3 建表/CRUD（标准库，无 ORM），含 3 张输入流表
│   ├── srs.py                # SM-2 调度，接口可无痛换 FSRS
│   ├── ai.py                 # 重述引擎：智谱 GLM（可插拔）+ 严格容错降级 + 合并收词
│   ├── seed.py               # 种子数据：1 用户 + 4 场景 + 起始对话 + 生词卡
│   ├── seed_input.py         # 语料加载器：幂等同步 data/input/texts.json，单条非法跳过
│   ├── .env.example          # ZHIPU_API_KEY / GLM_API_KEY / BASE_URL / MODEL 模板（不含真实 key）
│   ├── requirements.txt      # 仅 fastapi、uvicorn（阶段二零新依赖）
│   └── data/yaya.db          # 运行时生成，不入 git，删库重启自动重建
├── frontend/                 # 原生 HTML/CSS/JS，零构建
│   ├── index.html            # 「对话陪练 / 分级阅读」双视图 + 生词本 + 记忆账本
│   ├── styles.css            # 暖色圆润、无红色打击性反馈
│   └── app.js                # fetch 调全部端点 + ASR/TTS + 翻译回填 + 输入流交互 + 离线降级
├── data/input/               # 内容角色产出的分级语料（入 git）
│   ├── texts.json            # 21 篇 A2/B1/B2 对话与短文 + 157 生词标注
│   └── README.md             # 语料来源/许可/音频兜底说明
├── asr_service/              # 本地语音识别+合成服务（端口 8010）
├── demo.html                 # 历史单文件原型（保留供对照）
└── .gitignore
```

### 启动

**一键启动（推荐）**：双击仓库根目录 `start.bat`（或命令行运行）。脚本自动完成 5 项启动前自检（后端解释器 / 语音环境 / API key / 端口占用 / 前端与语料文件）→ 拉起语音服务(8010)与后端(8000) → 健康检查 → 自动打开学习页。服务已在运行时会询问「重启 / 复用 / 退出」；缺 API key 时以 ⚠ 提示降级模式但不阻塞。可选环境变量见脚本头部注释（如 `YAYA_PYTHON` 指定后端解释器、`YAYA_ASR_MODEL=tiny` 回退轻量模型）。

手动启动（分步）：

```bash
cd tools/french-learner/backend
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000/
```

后端同时托管前端静态文件，无需另起前端服务。

**启用真实 AI 重述（可选）**：默认无 key，重述走本地规则（覆盖典型错误、离线可用）。本机已在用户环境变量 `ZHIPU_API_KEY` 中存有智谱 key，后端会**自动读取该变量（最高优先级）**，无需改任何配置；只要启动后端的进程能读到它即可。Windows PowerShell 新开终端会自动继承用户环境变量，直接启动即可：
```powershell
cd tools/french-learner/backend
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```
若你的终端读不到（例如进程在 key 设置前就已启动），可显式导出：
```powershell
$env:ZHIPU_API_KEY = [Environment]::GetEnvironmentVariable('ZHIPU_API_KEY','User')
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```
Git Bash 用户可用 `.env`：`cd tools/french-learner/backend && cp .env.example .env`，填入 `ZHIPU_API_KEY=你的key` 后 `set -a; . ./.env; set +a` 再启动（`.env` 已 gitignore，不入库）。key 优先级：`ZHIPU_API_KEY` > `GLM_API_KEY` > `LLM_API_KEY`；默认端点 `https://open.bigmodel.cn/api/paas/v4`，默认模型 `glm-4-flash`。无 key / key 无效 / 超时 / 返回格式异常一律自动降级本地规则，永不 500。

也可以**不启动后端**，直接双击 `frontend/index.html`：此时自动进入"离线演示模式"，用内嵌场景数据与重述规则完整演示核心体验（UI 有低调标签提示）。

### API 一览（Base: http://localhost:8000）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/scenes | 场景列表 |
| GET | /api/scenes/{scene_id} | 场景详情 + 起始对话 |
| POST | /api/chat | 重述式对话（核心，纠错永远 200） |
| POST | /api/translate | 批量法语→中文（每次最多 10 条，给对话气泡配中文小字） |
| GET | /api/cards | 生词卡列表 |
| POST | /api/cards/{id}/review | 提交复习评分（1~4） |
| GET | /api/profile | 用户档案与统计 |
| GET | /api/health | 健康检查 |
| GET | /api/asr/status | 本地语音服务是否可用（前端探测） |
| POST | /api/asr/transcribe | 上传音频转写法语（转发到本地 Whisper） |
| GET | /api/tts?text=... | 文本转高质量法语朗读 mp3（转发到 edge-tts，失败前端回退浏览器） |
| GET | /api/input/levels | 输入流可用等级与各等级篇数 |
| GET | /api/input/texts?level=&limit=&offset= | 分级文本列表 |
| GET | /api/input/texts/{id} | 文本详情（逐句 + 生词） |
| POST | /api/input/texts/{id}/collect | 生词收卡入库（幂等） |
| GET | /api/input/recommend?exclude_ids=&limit= | i+1 难度自适应推荐 |

统一响应包裹 `{code, data, message}`，成功 `code=0`。`/api/tts` 例外：直接返回音频流 `audio/mpeg`。新增 5 个输入流端点详见 `docs/ARCHITECTURE_V2.md` §5。

### 分级阅读（i+1 可理解输入，阶段二主线 B）

前端顶部「📖 分级阅读」Tab：按 A2/B1/B2 浏览 21 篇语料，逐句对照中文、点句朗读、一键收生词卡；「推荐下一篇」按 i+1 规则（当前 A2 → 目标 B1，结合生词覆盖率 coverage）选篇，读过的自动排除。语料为原创教学示例，音频暂缺由 edge-tts / 浏览器 TTS 兜底朗读。

### 语音交互（本地 Whisper，离线可用）

浏览器自带的语音识别依赖境外（Google）服务，国内网络会报 `network`。因此法语识别改为**本地 Whisper**：浏览器录音 → 上传 → 本地 AI 转写，完全不依赖境外服务、不花钱、音频不出本机。

**一次性安装**（本机 `.venv-asr` 已装好，可跳过）：
```bash
cd tools/french-learner
python -m venv .venv-asr
.venv-asr/Scripts/python.exe -m pip install faster-whisper fastapi uvicorn edge-tts -i https://mirrors.aliyun.com/pypi/simple
```
> 需系统装有 `ffmpeg`（本机已有）。默认模型为 **Whisper small（约 470MB）**，首次启动下载（国内请在启动前设 `HF_ENDPOINT=https://hf-mirror.com`），之后离线可用。若机器较慢，启动时设 `YAYA_ASR_MODEL=tiny` 即可回退到 tiny（约 75MB）。
> **低置信保护**：解码用 `temperature=0` + `no_speech_threshold=0.6` + `compression_ratio_threshold=2.4` 三道门控，服务返回 `confidence` / `low_confidence`；低置信时前端**只把识别文本放进输入框、不自动提交**，提示你改一下或再录一次，避免错句进入对话。阈值见 `asr_service/server.py:49-51`。
> **兼容性说明**：本机 Python 3.13 只能用 PyAV 19，而 faster-whisper 1.2.1 与 PyAV 19 的 `metadata_errors` 参数不兼容。本项目已绕开——`asr_service/server.py` 用 ffmpeg 将音频转 16kHz 单声道 PCM、以 numpy ndarray 传给 Whisper，完全不走 PyAV 解码路径，无需降级任何包。

**启动两个服务**：
```bash
# 终端 1：本地语音服务（端口 8010）
asr_service/start_asr.bat

# 终端 2：主后端（端口 8000）
cd backend && python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

**使用**：点麦克风说话 → 说完再点一次（或等 2 秒）→ 本地转写为法语 → 自动进入对话。首次需允许麦克风权限，建议 Chrome / Edge。

**三级降级**：① 本地 ASR 服务可用 → 用它；② 未启动且浏览器识别碰巧可用 → 浏览器兜底；③ 都不行 → 清晰提示打字，输入框自动聚焦，对话主流程不受影响。

**法语误识别修正**：tiny 模型在法语近音词上偶发听成英文（`chaud`→`Show !`、`un thé`→`Chef Onti`）。现默认 `beam_size=5` + 法语场景 `initial_prompt` 偏置，并加保守白名单纠正（`Show !`→`Chaud !`、`Chef Onti`→`Un thé`，正常法语句子不误伤）。`/transcribe` 同时返回 `raw_text`/`corrected`，前端会显示「🎧 原声识别：… → 已按法语修正」的温和小字。可用 `YAYA_ASR_BEAM_SIZE`、`YAYA_ASR_INITIAL_PROMPT` 调整（置空关闭偏置）。

**发音朗读（本地神经语音，优先）**：点气泡旁发音按钮，走 `GET /api/tts?text=...` → 8010 语音服务用 **edge-tts**（微软神经网络语音 `fr-FR-DeniseNeural`）合成 mp3 播放。相比浏览器自带 TTS，它能把 `le/la/les` 等功能词自然连读（浏览器缺法语 voice 时会用英语引擎把 `le` 读成字母 L/E）。合成结果按「文本+语音」内存缓存，重复点同一句秒回。需联网连微软（国内可访问、免费）；语音服务未启动或合成失败时，自动回退浏览器 SpeechSynthesis 并尽量选法语 voice——离线仍可用。可用 `YAYA_TTS_VOICE` 换音色（如 `fr-FR-HenriNeural` 男声）。

### AI 重述与降级

环境变量按 `ZHIPU_API_KEY`（最高）→ `GLM_API_KEY` → `LLM_API_KEY` 取 key，端点/模型默认智谱 `https://open.bigmodel.cn/api/paas/v4` + `glm-4-flash`（也可用 `GLM_BASE_URL` / `GLM_MODEL` 覆盖）。未设置 key 或调用失败时，自动降级为本地规则式重述（覆盖 `je veux→Je voudrais`、`je suis aller→Je suis allé`、`le gare→la gare`、`au tête→à la tête`），保证离线也能演示且永不因纠错返回 500。2026-11-17 已用本机 `ZHIPU_API_KEY` 真实调用智谱端点冒烟通过。

**讲解必为中文**：提示词已硬约束 `explanation` 只能是简体中文一句话；万一 GLM 偶发吐法语/英语，入口层会自动翻译或退化为温和中文占位，绝不把用户看不懂的外语展示出来（中文讲解零额外请求）。详见 `docs/QA_FIX_REPORT.md`（24 用例全 PASS）。

## 验收记录（2026-11-17）

端到端联调真实跑通：
- `GET /` 返回前端页面（200 text/html），`/styles.css`、`/app.js` 正常加载
- 7 端点全通，错误码（40001/40401/50001）实测正确，无 traceback 外泄
- `POST /api/chat {"user_text":"Je veux un thé."}` → `recast_of="Je veux un thé"`、`ai_text="Je voudrais un thé"`、自动建 1 张新词卡
- 前端独立核查：无 `me/bot` 残留、无红色错误样式、仅 `recast_of != null` 时渲染重述卡

**语音根治验收（2026-11-17，针对 `network` 错误）**：
- 浏览器原生识别报 `network`（依赖 Google 服务）→ 已改为本地 Whisper，彻底摆脱境外依赖
- 本地 ASR 服务实测：TTS 生成"Je voudrais un café, s'il vous plaît."→ Whisper 转写"Je voudrais un café, si vous plait."，语言检测 fr 置信度 1.0，纯转写 0.81s
- 主后端代理链路实测：`POST /api/asr/transcribe` → 200/code=0，经代理转写 0.7s
- 完整闭环实测：说"Je veux un thé"（错误句）→ 转写 → `POST /api/chat` → `recast_of="Je veux un thé"`、`ai_text="Je voudrais un thé"`，温柔重述触发成功
- 兼容性：Python 3.13 + PyAV 19 用 ffmpeg→ndarray 方案绕开，无需降包；faster-whisper 1.2.1 实测可用

**发音修复验收（2026-11-17，针对 `le` 读成字母）**：
- 根因：浏览器 SpeechSynthesis 缺法语 voice 时用英语引擎硬读，`le`→字母 L/E（非法语错误）
- 方案：新增 `GET /api/tts`（8000 代理）→ `/tts`（8010，edge-tts 神经语音）→ 前端优先播放合成 mp3，失败回退浏览器 TTS
- 实测：`Très bien ! Vous le voulez chaud ou froid ?` 经主后端合成返回 200/audio-mpeg/23184 bytes（1.5s），缓存命中 0s
- 发音验证：慢速回听清楚识别 `Vous le voulez`（`le` 读成单词 /lə/ 而非字母）；全速时 tiny 把 `le` 听成 `ne` 属 tiny 连读识别局限，非发音问题

**阶段二验收（2026-11-17，六角色三波 + 独立 QA）**：
- 端到端联调：v1 零回归（health 1.0.0 / 4 场景 / profile A2→B2）；输入流三级各 7 篇入库、详情正常、recommend 命中 B1（`level_and_coverage`）；chat 无 key 时 200/4 字段/本地规则重述
- 独立 QA（`docs/QA_REPORT.md`）：**109 用例 PASS 109 / FAIL 0 / BLOCK 0**——含 GLM 降级表 9 条 mock、收词幂等（含 5 并发）、recommend 三态、非法参数错误码、v1 七端点+三代理零回归、语料全量合规、字段四方一致；主库数据未被测试污染
- 语料：21 篇（A2/B1/B2 各 7）/ 157 生词，生词 100% 命中原文
- 后续补充：真实智谱 key 已用 `ZHIPU_API_KEY` 端到端冒烟通过（见 QA_REPORT §7）；对话气泡新增「双方 🔊 标准发音 + 中文翻译」，`/api/translate` 实测通过；仍未覆盖前端浏览器交互 E2E（仅验证资源与端点）
- 对话体验：你说的每一句和呀呀的每一句（含自然重述卡）都有 🔊 标准神经语音朗读与中文小字；中文由 GLM 批量翻译，失败只显示温和占位、不打断对话

## 后续规划（路线图）

| 阶段 | 内容 | 状态 |
|------|------|------|
| 0 地基 | 用户档案 + CEFR 定级 + 场景词库数据管线 | 已实现（12 题快速自评 + 加权分组算分 A2/B1/B2 + 写回驱动 i+1；QA 16/16） |
| 1 尖刀 | 重述式 AI 口语陪练（ASR + LLM + TTS） | 已实现（智谱 GLM 可插拔 + 降级 + 神经语音 TTS + 本地 ASR） |
| 2 记忆 | SM-2→FSRS 复习引擎 + 从对话自动制卡 | 已实现（SM-2，接口预留 FSRS） |
| 3 输入 | i+1 可理解输入流 | 已实现（21 篇分级语料 + 5 端点 + 阅读界面 + 难度自适应） |
| 4 达标 | DELF B2 / TCF 冲刺 + 真题 | 已实现（2 套原创模拟卷替真题规避版权：6 客观题 + 写作 + 口语，客观自动判分、主观 GLM 中文反馈 + 6 类降级；第 4 个 Tab「🏆 考级冲刺」；QA 112 PASS；TASK-0023） |

技术选型（混合策略）：骨架自研 + FastAPI/SQLite + 原生 JS + LLM 可插拔 + SM-2/FSRS + 开源词库打底（注意 CC 许可）。

## 数据与版权

正式版词库拟用开源卡组（如 `bonorca/the-only-french-deck`，约 6900 词 A1–C1）打底，
该类数据多为 CC BY-NC-SA，商业化前需换源或授权。当前种子词表仅用于演示。

**考级冲刺免责声明**：本卷为原创模拟练习，非 DELF/TCF 官方真题，成绩仅供练习参考。
练习成绩不用于任何外部用途，也不预测真实考分。阶段 0 的 CEFR 定级同为内部快速自评，可随时重测。
