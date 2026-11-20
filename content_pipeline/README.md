# 内容工厂 content_pipeline（v2.3 读不完的书）

把语料从「手写 21 篇」升级为「量产 200+ 篇」的离线管线：需求矩阵 → GLM 生成 → 校验 → 审校入库 → 音频批量。
零新依赖（复用 `backend/ai.py` 的 GLM 客户端 + 8011 edge-tts）。**完整契约见 `docs/PIPELINE.md`**。

## 快速开始

```bash
cd tools/french-learner
python -m content_pipeline.cli build                  # 200 槽位（A1/A2/B1/B2 各 50）
python -m content_pipeline.cli gen --limit 10          # 生成候选（断点续跑）
python -m content_pipeline.cli check                  # 校验
python -m content_pipeline.cli retry                  # 清除被拒候选以便重生成
python -m content_pipeline.cli approve-all            # AI 审校批量入库（唯一写 texts.json）
python -m content_pipeline.cli audio                  # 音频批量（断点续跑）
python -m content_pipeline.cli status                 # 统计
```

启动主后端后访问 `/review.html`：逐条通过/否决、批量通过、人工否决已入库条目（均留审计）。

## 模块

| 文件 | 职责 |
|------|------|
| `demand.py` | 主题×场景×等级矩阵 → 需求队列（200 槽位） |
| `generate.py` | GLM 生成候选（专属 45s 超时，不面客；严格 JSON schema） |
| `validate.py` | schema + 覆盖率启发式 + 句长 + 等级漂移 + 打回标记 |
| `freq/heuristic.py` | 无 CC 词频表时的降级已知词基线（CC0 内置 + 语料生词） |
| `review_store.py` | 审校入库唯一通道 + 审计日志 + 人工否决 |
| `audio_batch.py` | 8011 批量逐句音频 + 断点续跑 |
| `cli.py` / `paths.py` | 编排入口 / 路径常量 |

## 红线

- 生成/校验只写 `data/cache/`；**只有审校能写 `data/input/texts.json`**；
- 审校动作全部留审计（含 AI 审核者身份，不伪装真人）；人工否决通道常开；
- 音频落 `data/cache/`，不入 git；`seed_input.py` 启动时自动填充 `audio_url`。

## 依赖与环境

- `ZHIPU_API_KEY`（已有）：GLM 生成；`YAYA_GEN_TIMEOUT`（默认 45s）、`YAYA_GEN_MODEL`（可选）。
- 8011 语音服务（start.bat 自动拉起）：`YAYA_TTS_VOICE` 多音色。
- 词频表合规说明与升级路径见 `docs/PIPELINE.md` §3。
