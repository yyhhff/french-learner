# v2.3 内容工厂管线契约（content_pipeline）

> TASK-0066 / Wave 1 车道 B。本文是管线的唯一契约：数据流、词频降级说明、审校边界、CLI 用法。
> 总纲见 `docs/MASTER_PLAN.md`；语料 schema 见 `docs/ARCHITECTURE_V2.md` §5.4。

## 1. 数据流与唯一入库通道

```
需求矩阵(demand) → 候选(candidates.json) → 校验(validation_reports.json)
                                              ↓ pass
                                    审校(review_store) ──→ texts.json（唯一入库）
                                              ↓ approved
                                    音频批量(8011) → cache/audio/<id>/<seq>.mp3
                                              ↓
                                    seed_input 启动同步 → SQLite(input_* 三表)
```

**红线**：只有 `review_store.approve/approve_all_validated` 能写 `texts.json`；生成器和校验器只写 `data/cache/`。
所有审校动作追加到 `data/cache/content_pipeline/review_audit.jsonl`（slot / id / 审核者 / 时间 / 结果）。

## 2. 各阶段契约

| 阶段 | 模块 | 输入 | 输出 | 断点续跑 |
|------|------|------|------|----------|
| 需求 | demand.py | 主题×场景×等级矩阵 | demand_queue.json（200 槽位，A1/A2/B1/B2 各 50） | 重建即覆盖 |
| 生成 | generate.py | 队列 slot | candidates.json（原文 JSON，含 `_source_demand`） | 已生成 slot 跳过，`--force` 覆盖 |
| 校验 | validate.py | 候选 | validation_reports.json + 候选 `_review_status` | 全量重算 |
| 审校 | review_store.py | 已校验候选 | texts.json（入 git）+ 审计日志 | 幂等（按 id 去重） |
| 音频 | audio_batch.py | texts.json | cache/audio/<id>/<seq>.mp3 | 文件存在即跳过 |

## 3. 词频表降级说明（MASTER_PLAN 风险 2）

- **目标**：用 CC 许可开源法语词频表计算 i+1 生词覆盖率（设计目标 95–98%）。
- **现实**：本环境无合规词频表，且不得引入来源不明的词表（合规红线）。
- **降级实现**（`content_pipeline/freq/heuristic.py`）：
  - 内置高频功能词/常见实词集合（本人整理，CC0，可商用）；
  - 动态并入现有 `texts.json` 已标注生词（本项目原创语料，随语料增长扩充）；
  - `coverage = 命中词元 / 总词元`，用于同等级相对异常检测。
- **诚实边界**：此覆盖率是**教学用启发式近似，非语言学精确值**，95–98% 仅为设计目标参照，
  不作为绝对及格线；校验器对 coverage 只做「过低告警」（<0.55），不因绝对值卡死入库。
- **升级路径**：若后续取得 CC 许可词频表（如 `lexique` 等），替换 `heuristic.build_known_words` 为词频表
  读取即可，其余模块无需改动（接口不变）。

## 4. 审校边界（AI 承担审校，本期决策）

- 用户确认本期由 AI 承担审校以解除产能瓶颈；`approve_all_validated` 逐条写审计，`_reviewed_by = "ai-reviewer-v2.3"`。
- **不伪装真人审**：审计日志与候选字段都明确标注 AI 审核者身份。
- **人工否决通道保留**：审校台（`/review.html`）与 API 提供逐条否决、批量通过、`veto(text_id)` 从 texts.json 移除已入库条目，均留审计。
- 人工复核建议：批量通过后抽审 ≥10%，发现系统性偏差可整体 `veto` 后重生成。

## 5. 音频批量（本期一并做）

- 走本地 8011 语音服务的 `/api/tts?text=`（edge-tts `fr-FR-DeniseNeural`，需联网连微软；失败自动跳过并记录，可重跑）。
- 落盘到 `data/cache/content_pipeline/audio/<text_id>/<seq>.mp3`（cache，不入 git）。
- 取音端点：`GET /api/content/audio/{text_id}/{seq}`（在 `backend/routers/content_review.py`）。
- `seed_input.py` 启动时若发现落盘音频，自动为 text/line 填充 `audio_url` 指向本地取音端点；未生成则留空，前端回退在线 TTS（零回归）。

## 6. CLI 用法

```bash
cd tools/french-learner
python -m content_pipeline.cli build                  # 200 槽位需求队列
python -m content_pipeline.cli gen --limit 10          # 生成候选（断点续跑，耗 GLM 额度）
python -m content_pipeline.cli check                  # 校验
python -m content_pipeline.cli retry                  # 清除被拒候选以便重生成
python -m content_pipeline.cli approve-all            # AI 审校批量入库（唯一写 texts.json）
python -m content_pipeline.cli audio                  # 音频批量（断点续跑）
python -m content_pipeline.cli status                 # 统计
```

审校台：启动主后端后访问 `/review.html`（通过/否决/批量通过，均留审计）。

## 7. 本期验收实况（2026-11-20）

- 需求队列 200 槽位（A1/A2/B1/B2 各 50）已生成；本期完成 **A1 全部 34 篇**（A2/B1/B2 队列留待后续批次，管线支持断点续跑）。
- 34 篇全部经校验 + AI 审校入库（31 篇自动 pass + 3 篇 `too_few_words` 软瑕疵经 AI 判断放行，留审计），`texts.json` 从 21 → 55 篇。
- 音频批量：A1 34 篇 / 117 句全部合成成功（0 失败），逐句 audio_url 已由 `seed_input` 填充。
- 全端点回归：40 端点（原 34 + 新 6）；前端首页/审校台/分级阅读冒烟通过。
- **未达目标**：200+ 篇全量入库需数小时 GLM 生成工时，本期受单次会话时长限制只产 A1；A2/B1/B2 可按 `cli gen --level` 续跑。

## 8. 与 v2.2 车道的边界

- 本期内容工厂可产 A1 语料并入库（`seed_input.py` 的 `VALID_LEVELS` 加 A1）；
- **不触碰** v2.2 的定级题库、`assessment.py`、onboarding 台阶路径、场景对话；
- 两车道都改 `seed_input.py` 的 `VALID_LEVELS`：合并时以「含 A1 的四档集合」为准，避免丢失。
