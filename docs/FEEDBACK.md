# 使用反馈 · 版本优化决策

> TASK-0062。用户反馈是「下一个版本优化什么」的第一手依据，与面客建设里程图（`ROADMAP.md`）形成回路：
> **用户声音 → 汇总排序 → 定版本主题 → 做完点亮里程图**。

## 面客入口

- 位置：页脚「💌 说说想法」小按钮（与「🌱 重温引导」并排），**不做打开即弹**，用户主动才出现。
- 表单：① 选一个「最想优化哪一块」（预设方向单选）② 写具体建议（≤1000 字）③ 邮箱/微信选填（不强制）。
- 提交后给温和确认文案，不施压、不弹评分、不索要好评。

## 数据落点

- 表：`feedback`（见 `backend/db.py` DDL）。字段：`user_id` / `category` / `content` / `contact`（可选）/ `created_at`。
- 预设方向：**唯一数据源**是 `backend/db.py` 的 `FEEDBACK_CATEGORIES`（code→展示名）：
  `chat` 口语陪练 / `read` 分级阅读 / `pron` 读音规则 / `review` 复习调度 / `exam` 考级冲刺 / `other` 其他想说的。
- 改方向：只改 `FEEDBACK_CATEGORIES` 一处——前端打开浮层时通过 `GET /api/feedback/categories` 懒拉，无需改前端。

## 决策用法（规划新版本前必看）

1. 调汇总端点：`GET /api/feedback/summary`
   返回 `{total, by_category:[{category,label,count}], recent:[{id,category,label,content,created_at}]}`。
   - `by_category` 对**全部预设方向**都列出（含 count=0），已按 `count` 降序排好——排在最前、count 最高的方向，就是用户最想优化的一块。
   - `recent` 是最近 20 条原文，用来理解「为什么想优化这块」的具体诉求。
2. 定主题：取 `by_category` 前 1-2 个方向作为下一个大版本主题（如 `pron` 居首 → 下版本做「读音体验深化」）。
3. 落里程图：主题定好后写进 `backend/app.py` 的 `ROADMAP_DEFS`（见 `ROADMAP.md`），做完把 status 改 `done` 点亮。
4. 回看：版本上线后对比新周期 `by_category` 的变化，验证优化是否命中诉求。

> 例（本机实测口径）：某周期 `by_category` 为 `read:5 / pron:3 / chat:1 / 其余:0` → 下版本主题优先「分级阅读」。

## 维护与边界

- 汇总端点当前**无鉴权**（原型阶段 user_id 固定 1，仅本机自用）。若将来面客多人使用，须加管理端鉴权后再暴露 `summary`，`recent` 含用户自由文本与可选联系方式，注意隐私。
- `contact` 仅在用户愿意时留存，用于回访；汇总只读 `content`，不对外展示 `contact`。
- 反馈是**增益功能**：提交失败仅提示、不阻塞学习主流程；离线时提示「联网后寄出」，不缓存草稿。
