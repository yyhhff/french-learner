# 呀呀法语（YaYa French）

> 像婴儿一样，自然地学会法语。Web 形态，终点 B2（外派可用）。

## 产品理念

体验层走"婴儿式"——可理解输入、先听后说、情境化内容、**重述式纠错（recast）**、低情感过滤；
引擎层走"成人式"——CEFR 定位、SM-2/FSRS 复习、AI 诊断、B2 考级专项。

核心差异化：用户说错时不给红叉，而是由 AI 顺着语义自然接话，把正确说法"重述"回去。**协议层保证"说错话"永远返回 HTTP 200，只有 `recast_of != null` 时才渲染重述卡。**

## 当前状态：全栈可运行版本（E2E 联调通过）

本目录是**独立 Git 仓库**，提交历史：
- `280e9d7` 前端原型 Demo
- `b1fd04f` 项目章程 + 架构契约
- `2e13369` 全栈版本（后端 7 端点 + 前端 Web 应用）

### 目录结构

```
french-learner/
├── docs/
│   ├── ARCHITECTURE.md       # 架构契约：7 API + 5 表 + 字段一致性清单（前后端唯一输入）
│   └── PROJECT_CHARTER.md    # 项目章程：目标/WBS/RACI/风险/汇报机制
├── backend/                  # FastAPI 服务
│   ├── app.py                # 7 端点、统一响应包裹、CORS、异常处理、静态托管
│   ├── db.py                 # sqlite3 建表/CRUD（标准库，无 ORM）
│   ├── srs.py                # SM-2 调度，接口可无痛换 FSRS
│   ├── ai.py                 # 重述引擎：LLM（可选）+ 本地规则降级
│   ├── seed.py               # 种子数据：1 用户 + 4 场景 + 起始对话 + 生词卡
│   ├── requirements.txt      # 仅 fastapi、uvicorn
│   └── data/yaya.db          # 运行时生成，不入 git，删库重启自动重建
├── frontend/                 # 原生 HTML/CSS/JS，零构建
│   ├── index.html            # 场景/对话/生词本/记忆账本
│   ├── styles.css            # 暖色圆润、无红色打击性反馈
│   └── app.js                # fetch 调 API + Web Speech ASR/TTS + 离线降级
├── demo.html                 # 历史单文件原型（保留供对照）
└── .gitignore
```

### 启动

```bash
cd tools/french-learner/backend
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
# 浏览器打开 http://localhost:8000/
```

后端同时托管前端静态文件，无需另起前端服务。

也可以**不启动后端**，直接双击 `frontend/index.html`：此时自动进入"离线演示模式"，用内嵌场景数据与重述规则完整演示核心体验（UI 有低调标签提示）。

### API 一览（Base: http://localhost:8000）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/scenes | 场景列表 |
| GET | /api/scenes/{scene_id} | 场景详情 + 起始对话 |
| POST | /api/chat | 重述式对话（核心，纠错永远 200） |
| GET | /api/cards | 生词卡列表 |
| POST | /api/cards/{id}/review | 提交复习评分（1~4） |
| GET | /api/profile | 用户档案与统计 |
| GET | /api/health | 健康检查 |

统一响应包裹 `{code, data, message}`，成功 `code=0`。

### 语音交互

- **语音输入**：点麦克风，用浏览器 Web Speech API 识别法语（`fr-FR`），需允许麦克风权限；Chrome/Edge 支持最好，Firefox 不支持时给友好提示并可用打字替代。
- **发音朗读**：点气泡旁发音按钮，用浏览器 SpeechSynthesis 朗读（`fr-FR`）。

### AI 重述与降级

设置环境变量 `LLM_API_KEY` / `LLM_BASE_URL`（默认 OpenAI）/ `LLM_MODEL`（默认 gpt-3.5-turbo）即启用真实 LLM 重述。
未设置 key 或调用失败时，自动降级为本地规则式重述（覆盖 `je veux→Je voudrais`、`je suis aller→Je suis allé`、`le gare→la gare`、`au tête→à la tête`），保证离线也能演示且永不因纠错返回 500。

## 验收记录（2026-11-17）

端到端联调真实跑通：
- `GET /` 返回前端页面（200 text/html），`/styles.css`、`/app.js` 正常加载
- 7 端点全通，错误码（40001/40401/50001）实测正确，无 traceback 外泄
- `POST /api/chat {"user_text":"Je veux un thé."}` → `recast_of="Je veux un thé"`、`ai_text="Je voudrais un thé"`、自动建 1 张新词卡
- 前端独立核查：无 `me/bot` 残留、无红色错误样式、仅 `recast_of != null` 时渲染重述卡

## 后续规划（路线图）

| 阶段 | 内容 | 状态 |
|------|------|------|
| 0 地基 | 用户档案 + CEFR 定级 + 场景词库数据管线 | 部分（种子数据已就绪，定级待做） |
| 1 尖刀 | 重述式 AI 口语陪练（ASR + LLM + TTS） | 已实现（LLM 可插拔 + 降级） |
| 2 记忆 | SM-2→FSRS 复习引擎 + 从对话自动制卡 | 已实现（SM-2，接口预留 FSRS） |
| 3 输入 | i+1 可理解输入流（场景短视频） | 未开始 |
| 4 达标 | DELF B2 / TCF 冲刺 + 真题 | 未开始 |

技术选型（混合策略）：骨架自研 + FastAPI/SQLite + 原生 JS + LLM 可插拔 + SM-2/FSRS + 开源词库打底（注意 CC 许可）。

## 数据与版权

正式版词库拟用开源卡组（如 `bonorca/the-only-french-deck`，约 6900 词 A1–C1）打底，
该类数据多为 CC BY-NC-SA，商业化前需换源或授权。当前种子词表仅用于演示。
