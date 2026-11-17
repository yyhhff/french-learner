# ASR 上下文对照实验报告：前一句 vs 前两句

日期：2026-11-17　模型：faster-whisper small / cpu / int8 / beam=5
实验脚本：`experiments/asr_context_ab.py`（声学加噪）、`asr_context_ab2.py`（错词替换）、`asr_context_ab3.py`（临界混合）
复现：`HF_HUB_OFFLINE=1 .venv-asr/Scripts/python.exe experiments/asr_context_ab3.py`

## 一、为什么要做这个实验

用户反馈真人说 `Je veux froid` 被识别成 `Je veux foudre` / `Je vous fous froid`。
当前实现用「词袋 hotwords」偏置（从上文抽词）。用户要求对比「喂前一句 vs 前两句」整句上下文，
并强调「用户会说不合语法的句子，不用强调语法，着重上下文」。

## 二、实验方法（关键：必须制造临界条件）

| 实验 | 做法 | 结果 |
|---|---|---|
| v1 加噪 | TTS 标准发音 + 白噪声 SNR18/12 | 所有策略全对，**看不出差异**（标准发音太干净） |
| v2 错词替换 | 把 froid 音频段换成标准 foudre 发音 | 所有策略全错（声学证据是完整错词，软偏置救不回） |
| v3 临界混合 | 正确词与错词发音按比例 0/0.25/0.5/0.75/1 混合 | **临界区出现分化，实验有效** |

v3 才是有效对照：模拟真人中文口音「介于两个音之间」的模糊状态。

## 三、结果（v3 命中数，满分 5/5）

### 场景 A：froid → foudre
| ratio（错词占比） | none | base(现状) | ctx1(前1句) | ctx2(前2句) | hword1 | hword2 | ctx1+hw | ctx2+hw |
|---|---|---|---|---|---|---|---|---|
| 0.0 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| 0.5 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **0.75（临界）** | ✗ | ✗ | **✓** | **✓** | **✓** | **✓** | **✓** | **✓** |
| 1.0 | ✗ | ≈ | ≈ | ≈ | ≈ | ≈ | ≈ | ≈ |
| **合计** | 3 | 3 | **4** | **4** | **4** | **4** | **4** | **4** |

临界区明细：none/base → `Je veux foudre.`；ctx1/ctx2/hword1/hword2 → `Je veux froid !`

### 场景 B：café → thé
| ratio | none | base | ctx1 | ctx2 | hword1 | hword2 | ctx1+hw | ctx2+hw |
|---|---|---|---|---|---|---|---|---|
| **0.75（临界）** | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **合计** | 3 | 4 | **4** | **4** | **4** | **4** | **4** | **4** |

临界区明细：none → `Je veux enquêter.`；其余 → `Je veux un café.`

## 四、结论

1. **上下文有效**：临界模糊时，带上下文的策略比裸听写/现状多救回 1 例，且把 `foudre`→`froid`、`enquêter`→`café`。
2. **前一句 vs 前两句：打平**（4/5 vs 4/5，临界区都救回）。多加一句没有收益 → **用前一句即可**（更省 token、更少稀释）。
3. **整句 prompt vs 词袋 hotwords：也打平**（ctx1 vs hword1 都是 4/5）。
4. **边界**：错词占比到 100%（声学就是完整错词）时，任何上下文都救不回——这是 Whisper 软偏置的物理上限，只能靠用户重录或人工改。
5. **符合用户偏好**：用户要「重上下文、轻语法」。词袋 hword 只保留上文词汇、丢掉语法结构，正是这一思路，且与现有链路零改动兼容。

## 五、建议的最小改动

现状 `buildAsrHints()` 已经从最近 6 轮 + 前 40 张卡抽词做 hotwords，**本实验证明它已在有效策略之列**。
真正缺的是：把「前一句」也作为一个**整句 initial_prompt** 喂进去，形成双保险（ctx1+hw，实验里同样 4/5 且置信度 lp 最高 -0.28）。

最小改法（前端加 2 行 + 后端透传 1 个字段 + ASR 拼 1 行）：
- 前端 `buildAsrHints()` 同时返回 `context` = 最近一条 assistant 的法语整句；
- 后端 `/api/asr/transcribe` 透传 `context`；
- ASR `/transcribe` 把 `context` 拼到 `initial_prompt` 末尾。

风险：整句 prompt 长度需截断（如 200 字符），避免长句稀释偏置；中文/非法语字符要过滤。
