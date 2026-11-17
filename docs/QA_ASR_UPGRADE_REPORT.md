# 呀呀法语 — ASR 升级（tiny→small + 置信度门控）独立验收报告（QA_ASR_UPGRADE_REPORT）

- 测试人：qa（独立测试工程师，team: yaya-asr-upgrade）
- 结论：**全部检查通过**。门控 12/12 PASS、回归 9/9 PASS、A/B 完成。无功能性缺陷。
- 重要口径：**A/B 仅使用 edge-tts 合成清晰语音，不能外推到真人中文口音**；本次 small 的收益主要来自门控 + 重录兜底，而非合成语音上的 WER 提升（详见第一、七节）。

## 一、摘要

| 维度 | 结果 |
|---|---|
| tiny vs small A/B（15 句合成语音） | 平均 WER 0.048 → 0.008，绝对改善 4.0 个百分点，相对改善 82.8%（基数小，须并列看绝对值）；幻觉率两者均 0/15 |
| 延迟实测（CPU int8） | tiny 平均 0.77s/句，small 平均 3.20s/句（约 4.2×）；交互可接受但需留意 |
| 门控参数与低置信计算 | 12/12 PASS |
| HTTP + 前端回归 | 9/9 PASS |
| 功能性缺陷 | 0（口径差异与残余误识见第六节，非缺陷） |

**核心判断**：在干净合成语音上，tiny 已达近满分（WER 0.048、幻觉 0/15），用户报障的 Show!/Chef Onti 英文误识别**不复现**（beam=5 + initial_prompt 已压制）。small 相对 tiny 在此测试集上把 3 句法语近音词错误（Où→Ou、un thé→Inté、thé→ndé）修正为正确，收益真实但绝对幅度小。因此本轮升级的真正价值在于**门控 + 低置信重录兜底**，合成语音 A/B 不足以证明在真人中文口音上的收益。

## 二、测试环境

| 项 | 值 |
|---|---|
| 项目 | `D:\code\tool_box\tools\french-learner` |
| ASR venv | `.venv-asr/Scripts/python.exe`（Python 3.13.14；faster-whisper 1.2.1 / edge-tts / numpy 2.5.5）|
| 主后端 | `http://127.0.0.1:8000`（新代码已重启） |
| ASR 服务 | `http://127.0.0.1:8010`（新代码已重启；model_size=small，beam_size=5，懒加载）|
| ffmpeg | 4.1 |
| TTS 语音 | `fr-FR-DeniseNeural`（edge-tts） |
| 测试音频 | 15 句法语短句，edge-tts 合成，存于仓库外临时目录 `d:/code/tool_box/.qa_asr_work/audio/`（未进项目仓库）|
| 解码参数（A/B 与生产一致） | CPU / int8 / beam_size=5 / language=fr / vad_filter=True / condition_on_previous_text=False / temperature=0 / no_speech_threshold=0.6 / compression_ratio_threshold=2.4 / 统一 initial_prompt |
| small 模型 | HF 缓存 `models--Systran--faster-whisper-small`，snapshot `536b066…`，已预下载并加载验证通过 |

## 三、A/B：tiny vs small（合成语音 / 清晰发音）

> ⚠️ 本节结论**仅适用于 edge-tts 合成的标准巴黎口音、清晰发音**，不可外推到真实麦克风的中文口音、房间混响、连读吞音、背景噪声等场景。

测试集覆盖用户关注的易错词：`chaud`、`un thé`、`café`、`gare`、`Je voudrais`、`s'il vous plaît`、`bien chaud`，以及报障词对应的正确句——Show! ← `C'est chaud !`（s04）、Chef Onti ← `Je voudrais un thé.`（s03）。

### 3.1 逐句结果

| id | 参考文本 | tiny 转写 | tiny WER | small 转写 | small WER | 幻觉 t/s |
|---|---|---|---|---|---|---|
| s01 | Bonjour, je voudrais un café. | Bonjour, je voudrais un café. | 0.000 | 同 | 0.000 | n/n |
| s02 | Un thé bien chaud, s'il vous plaît. | Un thé bien chaud, s'il vous plaît. | 0.000 | 同 | 0.000 | n/n |
| s03 | Je voudrais un thé. | Je voudrais un thé. | 0.000 | 同 | 0.000 | n/n |
| s04 | C'est chaud ! | C'est chaud ! | 0.000 | 同 | 0.000 | n/n |
| s05 | Où est la gare, s'il vous plaît ? | **Ou** est la gare… | 0.125 | Où est la gare… | **0.000** | n/n |
| s06 | Le train arrive en gare. | Le train arrive en gare. | 0.000 | 同 | 0.000 | n/n |
| s07 | Un café, s'il vous plaît. | Un café, s'il vous plaît. | 0.000 | 同 | 0.000 | n/n |
| s08 | Je voudrais un café bien chaud. | Je voudrais un café bien chaud. | 0.000 | 同 | 0.000 | n/n |
| s09 | La gare est à cinq minutes d'ici. | La gare est à **5** minutes d'ici. | 0.125 | La gare est à **5** minutes d'ici. | 0.125 | n/n |
| s10 | Vous désirez ? | Vous désirez ? | 0.000 | 同 | 0.000 | n/n |
| s11 | Un thé, s'il vous plaît. | **Inté**, s'il vous plaît. | 0.333 | Un thé, s'il vous plaît. | **0.000** | n/n |
| s12 | Je voudrais un café et un thé. | …et un **ndé**. | 0.143 | …et un thé. | **0.000** | n/n |
| s13 | Il fait chaud aujourd'hui. | Il fait chaud aujourd'hui. | 0.000 | 同 | 0.000 | n/n |
| s14 | Attendez le train en gare. | Attendez le train en gare. | 0.000 | 同 | 0.000 | n/n |
| s15 | S'il vous plaît, un café bien chaud. | S'il vous plaît, un café bien chaud. | 0.000 | 同 | 0.000 | n/n |

WER 口径：标准词错误率 `(S+D+I)/N`，文本经小写化、重音保留、标点剥离后按词对齐；`cinq→5` 归一化为数字差异计入错误（见第六节说明）。

### 3.2 汇总

| 指标 | tiny | small | 改善 |
|---|---|---|---|
| 平均 WER | 0.048 | 0.008 | 绝对 **−0.040（4.0 个百分点）**；相对 **+82.8%** |
| 幻觉句数 / 幻觉率 | 0 / 15（0%） | 0 / 15（0%） | 0（两者均未复现 Show!/Chef Onti） |
| small 改善句 | — | — | s05、s11、s12（3 句） |
| small 回退句 | — | — | 无 |
| 平均置信度 | 0.676 | 0.784 | +0.108 |
| 低置信句数（重录触发） | 0 / 15 | 0 / 15 | 干净语音下均为 0 |

> 相对 82.8% 建立在 0.048 的小基数上，**请勿单独引用相对值**；应并列陈述「绝对改善 4.0 个百分点、15 句中修正 3 句」。

### 3.3 延迟实测（CPU int8，纯 model.transcribe 计时，15 句均值）

| 模型 | 平均 | 最小 | 最大 | 说明 |
|---|---|---|---|---|
| tiny | 0.77s | 0.50s | 1.50s | 当前默认前的值 |
| small | 3.20s | 2.78s | 3.62s | 默认模型，约 4.2× tiny |

交互判断：small 单句约 3.2s，较 tiny 慢约 4 倍，属于「点按后短等待」量级，交互可接受；但实时性敏感场景需知悉这一成本。此前 tiny 全量端到端（含 ffmpeg 解码）12.6s/15 句，small 55.0s/15 句，结论一致。

### 3.4 失败样例

- **s05**：tiny「Ou est la gare…」漏 `ù` 重音 → small「Où est la gare…」修正。
- **s11**：tiny「Inté, s'il vous plaît.」把 `un thé` 整体误识为 `Inté` → small 修正。
- **s12**：tiny「…et un ndé.」把 `thé` 误识为 `ndé` → small 修正。
- **s09**（两模型共同残余）：`cinq` → `5`。属数字书写格式差异，非声学误识；不影响语义，故未列为缺陷。

## 四、门控参数与低置信计算验证

脚本：`verify_gating.py`（直接 import 模块，不依赖服务重启）。**12/12 PASS**。

### 4.1 三个阈值常量

| 常量 | 期望 | 实测 | 结果 |
|---|---|---|---|
| LOG_PROB_THRESHOLD | -1.0 | -1.0 | PASS |
| NO_SPEECH_THRESHOLD | 0.6 | 0.6 | PASS |
| COMPRESSION_RATIO_THRESHOLD | 2.4 | 2.4 | PASS |

### 4.2 transcribe 调用参数（源码静态核对）

`temperature=0`、`no_speech_threshold=NO_SPEECH_THRESHOLD`、`compression_ratio_threshold=COMPRESSION_RATIO_THRESHOLD` 三项均在 `asr_service/server.py` 的 `model.transcribe(...)` 调用中显式出现 → 3/3 PASS。

### 4.3 compute_confidence + mock segments（按代码实际行为）

| 用例 | 输入 (avg_logprob/nsp/cr) | 期望 low_conf | 实测 | confidence | 结果 |
|---|---|---|---|---|---|
| 高置信 | -0.2 / 0.1 / 1.5 | False | False | 0.8 | PASS |
| 低 logprob | -1.5 / 0.1 / 1.5 | True | True | 0.0 | PASS |
| 仅 nsp 超阈 | 0.3 / 0.9 / 1.5 | True | True | 1.0 | PASS |
| 仅 cr 超阈 | 0.3 / 0.1 / 3.0 | True | True | 1.0 | PASS |
| 边界 avg_logprob=-1.0 | -1.0 / 0.1 / 1.5 | True（`<=`） | True | 0.0 | PASS |
| 空 segments | [] | True | True | 0.0 | PASS |

**口径差异记录**：speech 口述称边界 `avg_logprob=-1.0` 时 `low_confidence=False`（严格 `<`），但落地代码为 `<= LOG_PROB_THRESHOLD`（-1.0 判 True），docstring 亦写明「含等号」。team-lead 确认系其主动改为 `<=` 以拦截零置信句。本报告按代码实际行为判定，无缺陷。

### 4.4 temperature=0 对重录率的影响

干净合成语音 15 句在 `temperature=0` 下 low_confidence 命中 **0/15（tiny 与 small 均然）**，说明关闭多温度回退**未在清晰语音上抬高重录率**。真实中文口音下的重录率未量化（见第七节限制）——这是 temperature=0 副作用仍需真人场景观察的点。

## 五、回归验收（HTTP + 前端）

脚本：`regression.py`。**9/9 PASS**。数据：`regression_results.json`。

| # | 用例 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | GET /api/health 200 & code=0 | PASS | status=200, code=0 |
| 2 | POST /api/chat (cafe, "Je veux un thé") 200 & code=0 & 4 字段 | PASS | missing=[]；ai_text/recast_of/explanation/new_words 齐全 |
| 3 | POST /api/translate 200 | PASS | status=200, code=0 |
| 4 | GET /api/asr/status available=true | PASS | available=True |
| 5 | POST /api/asr/transcribe 200 & 新旧字段齐全 | PASS | status=200，data 含 text/raw_text/corrected/language + confidence(0.731)/low_confidence(False)，miss_new=[], miss_old=[] |
| 6 | GET :8010/health 门控参数 | PASS | model_size=small, beam_size=5, gate_thresholds={log_prob:-1.0, no_speech_prob:0.6, compression_ratio:2.4} |
| 7 | node --check frontend/app.js | PASS | 退出码 0 |
| 8 | index.html 仅 ?v=7 | PASS | versions=['7','7']（styles.css 与 app.js） |
| 9 | 低置信分支不自动提交（静态） | PASS | `if(lowConfidence){…}` 块内 has_return=True、auto_submit_in_block=False |

补充静态核对：`app.js:594-599` 低置信分支逻辑为「填入输入框 + 温和提示 + 聚焦 + return」，确实不触发 `submitUserText`；业务错误（code≠0）以服务端 message 提示后 return，不再误导致命提示。

## 六、缺陷清单

无功能性缺陷（0 项）。以下为如实记录的边界情况，均非阻断：

1. **口径差异（已澄清）**：speech 口述 `<` 与代码 `<=` 不一致，team-lead 确认为主动改为 `<=`，代码与 docstring 自洽；报告按实测 `<=` 判定。
2. **s09 `cinq→5`**：tiny 与 small 均输出阿拉伯数字，属数字书写格式差异，非声学误识，不影响语义。
3. **small 延迟成本**：3.20s/句 vs tiny 0.77s/句（约 4.2×），交互可接受但属本轮升级的性能权衡，需知悉。

## 七、未覆盖项与限制

1. **真实麦克风口音未量化（最重要）**：本次 A/B 全部使用 edge-tts 合成语音（标准巴黎口音、清晰发音、无噪声）。真实用户经浏览器 MediaRecorder 录音，存在中文口音、房间混响、远端采样率、连读吞音等差异，**本报告 WER/幻觉率不能外推到该场景**。合成语音上 tiny 已近满分、报障词不复现，正是这一局限的体现。
2. **temperature=0 的真实重录率未量化**：干净语音下 low_confidence=0/15；真实口音下的重录率、是否因关闭多温度回退而上升，需真人场景观察。
3. **浏览器 DOM 交互未验证**：低置信「不自动提交」仅做静态代码检查（node --check + 分支结构），未用浏览器自动化跑真实点击/录音链路。
4. **幻觉率口径较窄**：按「出现已知英文近音误识别词（show/onti/chef 等）」统计，未覆盖语义级幻觉（凭空生成无关法语句）。
5. **401/429 等 GLM 降级路径未重复注入**：沿用 v2 既有实现，详见既有 `QA_REPORT.md`，本次未重复构造上游错误注入。
6. **门控阈值的听感副作用**（如过度过滤吞字）未做真人场景人工 A/B 听辨，仅验证参数生效与计算逻辑。

## 八、结论

本轮 ASR 升级的验收**全部通过**：门控参数（temperature=0、no_speech_threshold、compression_ratio_threshold）确实生效，`compute_confidence` 的低置信判定在六类用例（含空段与边界 -1.0）下均符合代码预期；HTTP 与前端回归 9/9 全绿，`/api/asr/transcribe` 响应新旧字段齐全、低置信分支不自动提交；A/B 显示 small 在合成清晰语音上把平均 WER 从 0.048 降至 0.008（绝对改善 4.0 个百分点），修正了 tiny 的 3 句法语近音词错误，无回退，但幻觉率两者均为 0。

**须强调**：合成语音 A/B 无法外推到真人中文口音，且该测试集上 tiny 已近满分、用户报障的 Show!/Chef Onti 并不复现，因此 small 的绝对收益有限；本轮真正价值在于门控 + 低置信重录兜底，其真人场景收益仍需后续实测确认。small 带来约 4.2× 的延迟成本，属可接受的交互权衡。
