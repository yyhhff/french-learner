"""v2.3 内容工厂（content factory）：需求矩阵 → GLM 生成 → 校验 → 审校入库 → 音频批量。

纯 CLI/离线管线，零新依赖（复用 backend/ai.py 的 GLM 客户端与 8011 语音服务）。
设计契约见 docs/PIPELINE.md。数据落点：
- data/cache/content_pipeline/：需求队列、候选、校验报告、审计日志、音频（不入 git）
- data/input/texts.json：审校通过的入库语料（入 git，人审是唯一入库通道）
"""
