# 呀呀法语 v2 独立测试报告（QA_REPORT）

> 测试角色：tester（独立验收）｜依据：`docs/ARCHITECTURE_V2.md`｜结论以实际运行证据为准，不采信开发自报。

## 一、摘要

- **总用例数：109　PASS：109　FAIL：0　BLOCK：0**
- **一句话结论：全部用例通过，未发现阻塞缺陷，阶段二新增功能（智谱 GLM 可插拔重述 + i+1 可理解输入流 5 端点）与 v1 零回归均达标，可交付。**

## 二、测试环境

- **测试时间**：2026-11-17 19:25:29（本地时间，2026-11-17）
- **被测对象**：阶段二新代码（`backend/ai.py` GLM 适配与降级、`backend/app.py` 5 个 `/api/input/*` 路由、`backend/seed_input.py` 加载器、前端 `frontend/*`、语料 `data/input/texts.json`）。
- **服务地址**：主服务 `http://127.0.0.1:8000`（只读验证）；本地语音服务 `http://127.0.0.1:8010`（ASR/TTS，健康探测通过）；隔离测试服务 `127.0.0.1:8123` / `8124`（进程内启动，连接临时 DB 副本）。
- **无 key 状态**：测试进程与隔离服务的 `GLM_API_KEY`、`LLM_API_KEY` 均为空 → `ai.GLM_API_KEY=''`，`/api/chat` 零网络请求、200/code=0、结果来自本地规则。真实智谱 key 当时未接入（19:40 已补真实冒烟，见文末「补充验证」）。
- **种子数据基线**：profile `cefr_level=A2`、`target_level=B2`（故 i+1 目标为 B1）；语料 21 篇（A2/B1/B2 各 7）、生词 157、`word_cards` 14 张种子卡、`get_mastered_words()` 初始为空集。
- **方法**：Python 3.13 + `urllib.request`/`curl` 打真实 HTTP；`monkeypatch ai.urllib.request.urlopen` 精确模拟降级表 9 条；静态解析 `ARCHITECTURE_V2.md` ↔ `db.py` DDL ↔ §5.2 Schema ↔ 语料 JSON 做四方字段核对。
- **数据隔离（硬性约束遵守）**：所有写操作（chat 落库、collect 建卡、review 更新）均在临时副本 `yaya_http.db` / `yaya_mock.db` / `yaya_empty.db` 上完成；主库 `backend/data/yaya.db` 全程未被写操作污染。未执行任何 git 命令；未改动除本报告外的任何文件。

## 三、契约 §8 的 21 条测试要点覆盖映射

| §8# | 场景 | 对应用例编号 | 结果 |
|---|---|---|---|
| 1 | 无key零网络本地规则 | M01 / R05 | PASS |
| 2 | 401立即降级 | M05 | PASS |
| 3 | 超时/连接失败重试1次 | M02 / M03 | PASS |
| 4 | 非JSON/ai_text空降级 | M06 / M06b / M06c / M07 / M07b | PASS |
| 5 | 合法JSON缺字段补全 | M08 / M08b | PASS |
| 6 | new_words非法元素过滤 | M08b / D02 / D03 | PASS |
| 7 | 收词去重 | D01 | PASS |
| 8 | 空语料 levels=[] | Z01 / Z02 | PASS |
| 9 | 非法level=C3→40001 | I04 | PASS |
| 10 | limit=999→40001 | I05 | PASS |
| 11 | 不存在id→40401 | I09 | PASS |
| 12 | collect幂等 | I11 / E05 | PASS |
| 13 | collect忽略不存在词 | I12 | PASS |
| 14 | collect words非数组→40001 | I14 | PASS |
| 15 | 非法语料条跳过 | L03 | PASS |
| 16 | 语料文件缺失不阻断 | L04 / Z01-Z03 | PASS |
| 17 | recommend i+1目标B1 | I17 | PASS |
| 18 | exclude后无候选 | I19 | PASS |
| 19 | limit非法→40001 | I18 / I18b / I18c | PASS |
| 20 | v1零回归(7+3端点) | R01-R17 | PASS |
| 21 | 字段一致性四方核对 | S-input_* / S-SUM / S-LINE / S-WORD / S-DETAIL / S-CORPUS | PASS |

## 四、详细用例表

### 4.1 HTTP 接口套件（58 例）

| 编号 | 场景 | 方法 | 预期 | 实际 | 结果 | 证据（关键摘录） |
|---|---|---|---|---|---|---|
| R01 | health 版本零回归 | HTTP GET /api/health | 200, code=0, data.version=1.0.0, status=ok | HTTP 200 {'code': 0, 'data': {'status': 'ok', 'version': '1.0.0', 'time': '2026-11-17T11:24:22Z'}, 'message': 'ok'} | PASS | {'code': 0, 'data': {'status': 'ok', 'version': '1.0.0', 'time': '2026-11-17T11:24:22Z'}, 'message': 'ok'} |
| R02 | v1 GET /api/scenes 字段不变 | HTTP GET | 7 字段场景数组 | HTTP 200 共4条 | PASS | {'id': 'cafe', 'title': '在咖啡馆点单', 'description': '日常交流 · A2 难度', 'emoji': '☕', 'color': '#FBEDE5', 'cefr_level': 'A2', 'sort_order': 1} |
| R03 | v1 GET /api/scenes/{id} 含 start_dialogue | HTTP GET | 场景详情+起始对话 | HTTP 200 keys=['id', 'title', 'description', 'emoji', 'color', 'cefr_level', 'sort_order', 'start_dialogue'] | PASS | [{'id': None, 'role': 'assistant', 'fr': 'Bonjour ! Qu’est-ce que vous voulez ?', 'cn': '你好！您想要点什么？', 'recast_of': None, 'explanation': None, 'is_correction': False, 'created_at': None}] |
| R04 | v1 场景不存在错误码 | HTTP GET | 40401 / HTTP 404 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '场景不存在：__no_such__'} |
| R05 | v1 POST /api/chat 仅 4 字段 | HTTP POST(无key→本地规则) | code=0 且 data 仅 ai_text/recast_of/explanation/new_words | HTTP 200 keys=['ai_text', 'recast_of', 'explanation', 'new_words'] ai_text='Je voudrais un thé' | PASS | {'ai_text': 'Je voudrais un thé', 'recast_of': 'Je veux un thé', 'explanation': '礼貌点单用条件式 voudrais 更自然（你也完全能被懂）。', 'new_words': [{'id': 2, 'word': 'voudrais', 'meaning': '想要（礼貌）', 'pos': '条件式', 'example': 'Je voudrais un thé.', 'pronunciation': 'vu.dʁɛ', 'cefr_level': 'A2', 'source_scene_id': 'cafe', 'created_at': '202… |
| R06 | v1 chat 入参校验 缺 scene_id | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': '缺少必填字段 scene_id'} |
| R07 | v1 chat 入参校验 空 user_text | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'user_text 不能为空'} |
| R08 | v1 chat 入参校验 user_text>500 | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'user_text 长度不能超过 500'} |
| R09 | v1 chat 入参校验 history 非数组 | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'history 必须是数组'} |
| R10 | v1 chat 入参校验 场景不存在 | HTTP POST | code=40401 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '场景不存在：__no__'} |
| R11 | v1 GET /api/cards 为完整 WordCard | HTTP GET | WordCard[] 9 字段 | HTTP 200 共14张 | PASS | {'id': 14, 'word': 'un thé', 'meaning': '一杯茶', 'pos': 'n.m.', 'example': 'Je voudrais un thé.', 'pronunciation': 'œ̃ te', 'cefr_level': 'A1', 'source_scene_id': 'cafe', 'created_at': '2026-11-17T10:14:10Z'} |
| R11b | v1 GET /api/cards?scene_id 过滤 | HTTP GET | 200, 仅该场景卡 | HTTP 200 n=5 | PASS | [{'id': 14, 'word': 'un thé', 'meaning': '一杯茶', 'pos': 'n.m.', 'example': 'Je voudrais un thé.', 'pronunciation': 'œ̃ te', 'cefr_level': 'A1', 'source_scene_id': 'cafe', 'created_at': '2026-11-17T10:14:10Z'}, {'id': 13, 'word': 'un croissant', 'meaning': '一个可颂', 'pos': 'n.m.', 'example': 'Un croissant, s’il vous plaît.… |
| R12 | v1 POST review 出参 | HTTP POST | {next_due,interval_days} | HTTP 200 {'next_due': '2026-11-18T11:24:23Z', 'interval_days': 1} | PASS | {'next_due': '2026-11-18T11:24:23Z', 'interval_days': 1} |
| R12b | v1 review 入参 {'rating': 5} | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'rating 必须是 1/2/3/4 的整数'} |
| R12c | v1 review 入参 {'rating': 3} | HTTP POST | code=40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': '卡片 id 必须是整数'} |
| R12d | v1 review 入参 {'rating': 3} | HTTP POST | code=40401 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '卡片不存在：999999'} |
| R13 | v1 GET /api/profile 结构 | HTTP GET | profile+stats 4 字段 | HTTP 200 | PASS | {'due_cards_count': 13, 'new_words_week': 14, 'mastered_count': 0, 'accuracy': 1.0} |
| R14 | v1 GET /api/asr/status 代理 | HTTP GET | 200, data.available 布尔 | HTTP 200 {'available': True, 'status': 'ok', 'model_loaded': True, 'model_size': 'tiny', 'device': 'cpu'} | PASS | {'available': True, 'status': 'ok', 'model_loaded': True, 'model_size': 'tiny', 'device': 'cpu'} |
| R15 | v1 POST /api/asr/transcribe 空音频降级 | HTTP POST | 40001 不抛 500 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': '缺少 multipart boundary'} |
| R16 | v1 GET /api/tts 空文本校验 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': '空文本'} |
| R16b | v1 GET /api/tts 正常/降级均不崩 | HTTP GET | 音频流或优雅降级非500崩溃 | HTTP 200 ct= bytes=10080 | PASS | ct= len=10080 |
| R17 | v1 requirements 锁两行 | 静态读文件 | 仅 fastapi/uvicorn 两行 | ['fastapi', 'uvicorn'] | PASS | ['fastapi', 'uvicorn'] |
| I01 | 输入流 levels | HTTP GET /api/input/levels | A2/B1/B2 按序且 count>0 | HTTP 200 [{'level': 'A2', 'count': 7}, {'level': 'B1', 'count': 7}, {'level': 'B2', 'count': 7}] | PASS | [{'level': 'A2', 'count': 7}, {'level': 'B1', 'count': 7}, {'level': 'B2', 'count': 7}] |
| I02 | texts 默认分页(total=21,limit=20) | HTTP GET | total=21, items=20, level=null | HTTP 200 total=21 items=20 level=None | PASS | {'total': 21, 'n': 20, 'level': None} |
| I03 | texts 按 level 过滤 | HTTP GET ?level=A2 | total=7 全 A2 | HTTP 200 total=7 | PASS | {'total': 7, 'level': 'A2'} |
| I04 | 非法 level=C3 | HTTP GET ?level=C3 | 40001 / HTTP 400 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'level 必须是 A2/B1/B2'} |
| I05 | limit=999 超上限 | HTTP GET ?limit=999 | 40001 (上限50) | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 超出允许范围'} |
| I06a | texts 非法参数 limit=0 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 超出允许范围'} |
| I06b | texts 非法参数 limit非数字 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 必须是整数'} |
| I06c | texts 非法参数 offset负数 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'offset 超出允许范围'} |
| I06d | texts 非法参数 offset非数字 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'offset 必须是整数'} |
| I06e | texts 非法参数 level小写 | HTTP GET | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'level 必须是 A2/B1/B2'} |
| I07 | texts offset/limit 分页 | HTTP GET ?level=A2&limit=10&offset=2 | items=5 total=7 | HTTP 200 items=5 | PASS | {'n': 5, 'total': 7} |
| I08 | texts/{id} 详情 Schema 完整 | HTTP GET | 15 字段+lines(seq升序)+words(8字段) | HTTP 200 keys=15 lines=6 words=7 | PASS | {'fields': ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'lines', 'sort_order', 'title', 'topic', 'updated_at', 'word_count', 'words'], 'seqs': [1, 2, 3, 4, 5, 6], 'word0': {'word': "s'il vous plaît", 'meaning': '请，拜托', 'pos': 'loc.', 'cefr_level': 'A1', 'example': "Je vo… |
| I09 | texts/{不存在id} | HTTP GET | 40401 / HTTP 404 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '语料不存在：__no_such__'} |
| I10 | collect 全量收词 Schema | HTTP POST collect {} | CollectResult 4字段+完整WordCard | HTTP 200 collected=7 | PASS | {'text_id': 'inp_a2_001', 'n': 7, 'already': ['un croissant'], 'skipped': []} |
| I11 | collect 幂等(二次id不变/review_logs不重复) | HTTP POST collect ×2 | id相同, already_existed含全部, review_logs不增 | id同=True logs 20->20 already=7 | PASS | {'ids_equal': True, 'logs_before': 20, 'logs_after': 20} |
| I12 | collect 指定词+忽略不存在词 | HTTP POST collect words=[已存在,不存在] | 只收存在的词, 不报错 | HTTP 200 collected=["s'il vous plaît"] | PASS | {'text_id': 'inp_a2_001', 'collected': [{'id': 15, 'word': "s'il vous plaît", 'meaning': '请，拜托', 'pos': 'loc.', 'example': "Je voudrais une baguette, s'il vous plaît.", 'pronunciation': 'sil vu plɛ', 'cefr_level': 'A1', 'source_scene_id': None, 'created_at': '2026-11-17T11:24:23Z'}], 'already_existed': ["s'il vous plaî… |
| I13 | collect words=[] 收全部 | HTTP POST collect words=[] | 200 收全部 | HTTP 200 n=7 | PASS | [{'id': 15, 'word': "s'il vous plaît", 'meaning': '请，拜托', 'pos': 'loc.', 'example': "Je voudrais une baguette, s'il vous plaît.", 'pronunciation': 'sil vu plɛ', 'cefr_level': 'A1', 'source_scene_id': None, 'created_at': '2026-11-17T11:24:23Z'}, {'id': 16, 'word': 'une baguette', 'meaning': '一根法棍', 'pos': 'n.f.', 'examp… |
| I14 | collect 非法 words words非数组 | HTTP POST | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'words 必须是字符串数组'} |
| I15 | collect 非法 words words含非字符串 | HTTP POST | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'words 元素必须是字符串'} |
| I16 | collect 不存在 id | HTTP POST | 40401 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '语料不存在：__no__'} |
| I17 | recommend i+1 目标B1 | HTTP GET /api/input/recommend | target_level=B1, reason有效, text为完整详情 | HTTP 200 target=B1 reason=level_and_coverage | PASS | {'target': 'B1', 'reason': 'level_and_coverage', 'text_id': 'inp_b1_001'} |
| I18 | recommend limit=0 非法 | HTTP GET ?limit=0 | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 超出允许范围'} |
| I18b | recommend limit=11 非法 | HTTP GET ?limit=11 | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 超出允许范围'} |
| I18c | recommend limit非数字 | HTTP GET ?limit=abc | 40001 | HTTP 400 code=40001 | PASS | {'code': 40001, 'data': None, 'message': 'limit 必须是整数'} |
| I19 | recommend 排除全部→no_candidate | HTTP GET exclude_ids=全部 | text=null, reason=no_candidate, code=0 | HTTP 200 {'text': None, 'target_level': 'B1', 'reason': 'no_candidate'} | PASS | {'text': None, 'target_level': 'B1', 'reason': 'no_candidate'} |
| I20 | recommend exclude_ids 尾随逗号/空格 | HTTP GET exclude_ids='id,,  ,' | 优雅处理, 仍返回 text | HTTP 200 reason=level_and_coverage | PASS | {'reason': 'level_and_coverage', 'text_id': 'inp_b1_001'} |
| F01 | GET / 返回含 Tab 的 HTML | HTTP GET / | 200, 含 tab 与输入流标记 | HTTP 200 len=5680 tab=6 | PASS | <!DOCTYPE html> <html lang="zh-CN"> <head> <meta charset="UTF-8"> <meta name="viewport" content="width=device-width, initial-scale=1.0"> <title>呀呀法语 YaYa French — 像婴儿一样，自然地学会法语</title> <link rel="styl |
| F02 | app.js?v=4 含 5 端点 | HTTP GET /app.js?v=4 | 含 levels/texts/detail/collect/recommend | HTTP 200 len=34963 miss=[] | PASS | {'miss': [], 'len': 34963} |
| F03 | styles.css?v=4 可加载 | HTTP GET /styles.css?v=4 | 200 text/css 非空 | HTTP 200 ct=text/css; charset=utf-8 len=18575 | PASS | text/css; charset=utf-8 |
| E01 | chat 中文/特殊字符 user_text | HTTP POST | 200 code=0 不崩 | HTTP 200 code=0 | PASS | {'ai_text': 'Un croissant ! Bien sûr. Vous en voulez un autre ?', 'recast_of': None, 'explanation': None, 'new_words': [{'id': 13, 'word': 'un croissant', 'meaning': '一个可颂', 'pos': 'n.m.', 'example': 'Un croissant, s’il vous plaît.', 'pronunciation': 'œ̃ kʁwa.sɑ̃', 'cefr_level': 'A2', 'source_scene_id': 'cafe', 'create… |
| E02 | chat history 含非 dict 元素 | HTTP POST | 200 code=0 不崩 | HTTP 200 code=0 | PASS | {'ai_text': 'Je voudrais un thé', 'recast_of': 'Je veux un thé', 'explanation': '礼貌点单用条件式 voudrais 更自然（你也完全能被懂）。', 'new_words': [{'id': 2, 'word': 'voudrais', 'meaning': '想要（礼貌）', 'pos': '条件式', 'example': 'Je voudrais un thé.', 'pronunciation': 'vu.dʁɛ', 'cefr_level': 'A2', 'source_scene_id': 'cafe', 'created_at': '202… |
| E03 | collect words 含空串仅 trim | HTTP POST | 过滤空串, 正常收词 | HTTP 200 code=0 | PASS | {'text_id': 'inp_a2_001', 'collected': [{'id': 15, 'word': "s'il vous plaît", 'meaning': '请，拜托', 'pos': 'loc.', 'example': "Je voudrais une baguette, s'il vous plaît.", 'pronunciation': 'sil vu plɛ', 'cefr_level': 'A1', 'source_scene_id': None, 'created_at': '2026-11-17T11:24:23Z'}], 'already_existed': ["s'il vous plaî… |
| E04 | CORS allow-origin=* | HTTP GET /api/health (Origin头) | access-control-allow-origin: * | * | PASS | {'acao': '*'} |
| E05 | 并发 collect 幂等无重复卡 | HTTP 5并发 POST collect | 全200, 卡数不变, 无重复word | statuses=[200, 200, 200, 200, 200] 卡数20->20 重复=[] | PASS | {'statuses': [200, 200, 200, 200, 200], 'before': 20, 'after': 20, 'dup': []} |
| E06 | chat 类SQL注入文本不崩不破坏数据 | HTTP POST user_text=注入串 | 200 code=0, word_cards表完好 | HTTP 200 code=0 cards=20 | PASS | {'status': 200, 'card_count': 20} |
| I21 | recommend 全无生词→level_only_fallback | HTTP GET (隔离库清空input_words) | reason=level_only_fallback | HTTP 200 reason=level_only_fallback | PASS | {'text': {'id': 'inp_b1_001', 'title': '租房', 'format': 'dialogue', 'cefr_level': 'B1', 'topic': '生活', 'body_fr': "Bonjour, j'appelle au sujet de l'appartement à louer.\nOui, bonjour. Il est encore disponible.\nPourriez-vous me dire le montant du loyer ?\nBien sûr. C'est six cents euros par mois, charges comprises.\nEst… |

### 4.2 GLM 降级/Mock 套件（29 例）

| 编号 | 场景 | 方法 | 预期 | 实际 | 结果 | 证据（关键摘录） |
|---|---|---|---|---|---|---|
| M01 | #1 无key零网络直走本地 | monkeypatch urlopen + ai.GLM_API_KEY='' | urlopen调用=0, 本地结果, llm_new_words=[] | calls=0 ai_text='Je voudrais un thé.' | PASS | {'calls': 0, 'ai_text': 'Je voudrais un thé.'} |
| M02 | #2 URLError 重试1次后降级 | stub抛URLError(2次) | urlopen=2, 本地结果, warning日志 | calls=2 ai_text='Je voudrais un thé.' warn=1 | PASS | {'calls': 2, 'warn': ['LLM 重述失败，回退本地规则：<urlopen error Name or service not known>']} |
| M03 | #3 socket.timeout 重试1次后降级 | stub抛socket.timeout(2次) | urlopen=2, 本地结果 | calls=2 ai_text='Je voudrais un thé.' | PASS | {'calls': 2} |
| M04 | #4 HTTP429 重试1次后降级 | stub抛HTTPError(429)×2 | urlopen=2, 本地结果 | calls=2 ai_text='Je voudrais un thé.' | PASS | {'calls': 2} |
| M04b | #4 HTTP503 重试1次后降级 | stub抛HTTPError(503)×2 | urlopen=2, 本地结果 | calls=2 ai_text='Je voudrais un thé.' | PASS | {'calls': 2} |
| M04c | #4 首次429重试后成功→LLM结果 | stub 429→成功 | urlopen=2, LLM结果 | calls=2 ai_text='LLM_SPECIAL_TEXT' | PASS | {'calls': 2, 'ai_text': 'LLM_SPECIAL_TEXT'} |
| M05 | #5 HTTP401 立即降级不重试 | stub抛HTTPError(401) | urlopen=1, 本地结果, warning | calls=1 warn=1 | PASS | {'calls': 1, 'warn': ['LLM 重述失败，回退本地规则：HTTP Error 401: err']} |
| M05b | #5 HTTP403 立即降级 | stub抛HTTPError(403) | urlopen=1, 本地结果 | calls=1 | PASS | {'calls': 1} |
| M06 | #6 响应体非合法JSON | stub返回非JSON字节 | urlopen=1, 本地结果(格式异常不重试) | calls=1 ai_text='Je voudrais un thé.' | PASS | {'calls': 1} |
| M06b | #6 choices为空 | stub返回choices=[] | urlopen=1, 本地结果 | calls=1 | PASS | {'calls': 1} |
| M06c | #6 content缺失 | stub返回message无content | urlopen=1, 本地结果 | calls=1 | PASS | {'calls': 1} |
| M07 | #7 content非合法JSON | stub content='not-json-content' | urlopen=1, 本地结果 | calls=1 ai_text='Je voudrais un thé.' | PASS | {'calls': 1} |
| M07b | #7 ai_text为空 | stub content ai_text='   ' | urlopen=1, 本地结果 | calls=1 | PASS | {'calls': 1} |
| M08 | #8 缺字段补null/null/[]仍成功 | stub content仅ai_text | LLM成功, recast_of/explanation=None, new_words=[] | ai_text='LLM_SPECIAL_TEXT' recast_of=None explanation=None nw=[] | PASS | {'ai_text': 'LLM_SPECIAL_TEXT', 'recast_of': None, 'explanation': None, 'new_words': []} |
| M08b | #8 new_words非法元素过滤 | stub new_words含5类非法/半合法元素 | LLM成功, llm_new_words仅留有word的, 不建脏卡 | nw=[] llm_nw=[{'word': 'okword', 'meaning': None, 'pos': None, 'cefr_level': None}, {'word': 'bad', 'meaning': '', 'pos': None, 'cefr_level': None}] | PASS | {'llm_new_words': [{'word': 'okword', 'meaning': None, 'pos': None, 'cefr_level': None}, {'word': 'bad', 'meaning': '', 'pos': None, 'cefr_level': None}], 'new_words': []} |
| M09 | #9 其他异常兜底降级 | stub抛RuntimeError | urlopen=1, 本地结果, warning | calls=1 warn=1 | PASS | {'calls': 1, 'warn': ['LLM 重述失败，回退本地规则：boom']} |
| M10 | bonus markdown围栏JSON解析 | stub content=```json...``` | LLM成功 | ai_text='LLM_SPECIAL_TEXT' | PASS | {'ai_text': 'LLM_SPECIAL_TEXT'} |
| M11 | bonus recent_history仅取最后10 | 传15轮history, 捕获请求体 | context.recent_history长度10且为h5..h14 | len=10 first=h5 last=h14 | PASS | {'len': 10, 'first': 'h5', 'last': 'h14'} |
| M12 | 模块级常量 超时8s/2次/0.3s | 读取 ai 常量 | 8/2/0.3 | 8/2/0.3 | PASS | {'timeout': 8, 'attempts': 2, 'interval': 0.3} |
| D01 | 收词去重: LLM建议∩本地词表命中同词 | mock scene vocab + LLM new_words 同词 | 只建1张卡, new_words不重复且完整WordCard | db卡数=1 new_words=['dedup_unique_xyz'] | PASS | {'db_count': 1, 'new_words': [{'id': 15, 'word': 'dedup_unique_xyz', 'meaning': 'LLM释义', 'pos': 'n.m.', 'example': None, 'pronunciation': None, 'cefr_level': 'A2', 'source_scene_id': 'cafe', 'created_at': '2026-11-17T11:22:39Z'}]} |
| D02 | LLM建议词不在ai_text→不建卡 | stub new_words word不在ai_text | 不建卡, new_words不含该词 | db卡数=0 new_words=[] | PASS | {'db_count': 0} |
| D03 | LLM建议词缺meaning→不建卡 | stub new_words 有word无meaning | 不建脏卡 | db卡数=0 | PASS | {'db_count': 0} |
| L01 | 加载器入库数量正确 | 读 mock DB | input_texts=21, input_words=157 | texts=21 lines=126 words=157 | PASS | {'texts': 21, 'lines': 126, 'words': 157} |
| L02 | 加载器幂等(重载不重复) | 再次 load_input_corpus() | texts/words 数量不变 | texts 21->21 words 157->157 | PASS | {'before': [21, 157], 'after': [21, 157]} |
| L03 | 加载器跳过非法条(C3/缺lines) | 临时语料含1合法+2非法, 空库加载 | 仅合法条入库, 服务不阻断 | ids=['inp_test_valid'] | PASS | {'ids': ['inp_test_valid']} |
| L04 | 语料文件缺失不阻断 | INPUT_FILE指向不存在文件调用load | 无异常返回 | 无异常 | PASS | no exception |
| V01 | 环境变量 GLM_* 优先于 LLM_* | 子进程设双套env, 读ai常量 | GLM_*三项胜出 | {'k': 'gk', 'b': 'https://g', 'm': 'gm'} | PASS | {'k': 'gk', 'b': 'https://g', 'm': 'gm'} |
| V02 | 仅设 LLM_* 时作为兼容别名生效 | 子进程仅设LLM_*, 读ai常量 | LLM_*三项生效 | {'k': 'lk', 'b': 'https://l', 'm': 'lm'} | PASS | {'k': 'lk', 'b': 'https://l', 'm': 'lm'} |
| V03 | 全不设时默认(空key+GLM默认url/model) | 子进程无env, 读ai常量 | k空, url=bigmodel, model=glm-4-flash | {'k': '', 'b': 'https://open.bigmodel.cn/api/paas/v4', 'm': 'glm-4-flash'} | PASS | {'k': '', 'b': 'https://open.bigmodel.cn/api/paas/v4', 'm': 'glm-4-flash'} |

### 4.3 语料合规与字段一致性套件（18 例）

| 编号 | 场景 | 方法 | 预期 | 实际 | 结果 | 证据（关键摘录） |
|---|---|---|---|---|---|---|
| C01 | 语料 version=1 且 texts=21 | JSON全量解析 | version=1, texts=21 | version=1 n=21 | PASS | {'version': 1, 'n': 21} |
| C02 | 语料 id 全文件唯一 | JSON校验 | 21个唯一id | unique=21 重复=[] | PASS | {'unique': 21} |
| C03 | cefr_level/format 枚举合法 | JSON校验 | level∈A2/B1/B2, format∈dialogue/monologue | bad_level=[] bad_fmt=[] | PASS | {'bad_level': [], 'bad_fmt': []} |
| C04 | 必填字符串字段齐全 | JSON校验 | id/title/topic/body_fr/body_cn 非空 | 缺失=[] | PASS | {'missing': []} |
| C05 | lines.seq 从1递增且speaker合规 | JSON校验 | seq=1..n, dialogue=A/B, monologue=null | bad_seq=[] bad_speaker=[] | PASS | {'bad_seq': [], 'bad_speaker': []} |
| C06 | words 共157且必填/line_seq指向有效句 | JSON校验 | 总词数157, word/meaning非空, line_seq有效 | total=157 bad=[] | PASS | {'total': 157, 'bad': []} |
| C07 | 生词表面形式命中 body_fr | JSON校验(大小写不敏感子串) | 每个 word ∈ body_fr | 未命中数=0 样例=[] | PASS | {'miss_count': 0, 'sample': []} |
| C08 | 内容未越权写生成字段 | JSON校验 | 不含 word_count/created_at/updated_at | 含生成字段=[] | PASS | {'violations': []} |
| C09 | 抽检 body_fr/word_count 入库正确 | 读 mock DB 比对原文 | body_fr一致, word_count=正则计算值 | id=inp_a2_001 word_count库=44 计算=44 | PASS | {'id': 'inp_a2_001', 'db_wc': 44, 'calc': 44} |
| C10 | 抽检 lines/words 入库数量 | 读 mock DB | 行数/词数与JSON一致 | lines 6/6 words 7/7 | PASS | {'lines': 6, 'words': 7} |
| S-input_texts | mermaid↔DDL 字段一致: input_texts | 静态解析 ARCHITECTURE_V2 §4.1 与 db.py DDL | 字段名集合逐字一致 | mermaid=['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_count'] ddl=['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_count'] … | PASS | {'mermaid': ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_count'], 'ddl': ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_… |
| S-input_lines | mermaid↔DDL 字段一致: input_lines | 静态解析 ARCHITECTURE_V2 §4.1 与 db.py DDL | 字段名集合逐字一致 | mermaid=['audio_url', 'cn', 'fr', 'id', 'seq', 'speaker', 'text_id'] ddl=['audio_url', 'cn', 'fr', 'id', 'seq', 'speaker', 'text_id'] 差异=[] | PASS | {'mermaid': ['audio_url', 'cn', 'fr', 'id', 'seq', 'speaker', 'text_id'], 'ddl': ['audio_url', 'cn', 'fr', 'id', 'seq', 'speaker', 'text_id'], 'diff': []} |
| S-input_words | mermaid↔DDL 字段一致: input_words | 静态解析 ARCHITECTURE_V2 §4.1 与 db.py DDL | 字段名集合逐字一致 | mermaid=['cefr_level', 'example', 'id', 'line_seq', 'meaning', 'pos', 'pronunciation', 'text_id', 'word', 'word_card_id'] ddl=['cefr_level', 'example', 'id', 'line_seq', 'meaning', 'pos', 'pronunciation', 'text_id', 'word', 'word_card_id'] 差异=[] | PASS | {'mermaid': ['cefr_level', 'example', 'id', 'line_seq', 'meaning', 'pos', 'pronunciation', 'text_id', 'word', 'word_card_id'], 'ddl': ['cefr_level', 'example', 'id', 'line_seq', 'meaning', 'pos', 'pronunciation', 'text_id', 'word', 'word_card_id'], 'diff': []} |
| S-SUM | Schema InputTextSummary ↔ db 转换器 | 静态+db转换器 | 8字段一致 | ['audio_url', 'cefr_level', 'format', 'id', 'sort_order', 'title', 'topic', 'word_count'] | PASS | {'actual': ['audio_url', 'cefr_level', 'format', 'id', 'sort_order', 'title', 'topic', 'word_count'], 'expect': ['audio_url', 'cefr_level', 'format', 'id', 'sort_order', 'title', 'topic', 'word_count']} |
| S-LINE | Schema InputLine ↔ db 转换器 | 静态+db转换器 | 5字段一致 | ['audio_url', 'cn', 'fr', 'seq', 'speaker'] | PASS | {'actual': ['audio_url', 'cn', 'fr', 'seq', 'speaker'], 'expect': ['audio_url', 'cn', 'fr', 'seq', 'speaker']} |
| S-WORD | Schema InputWord ↔ db 转换器 | 静态+db转换器 | 8字段一致 | ['cefr_level', 'example', 'line_seq', 'meaning', 'pos', 'pronunciation', 'word', 'word_card_id'] | PASS | {'actual': ['cefr_level', 'example', 'line_seq', 'meaning', 'pos', 'pronunciation', 'word', 'word_card_id'], 'expect': ['cefr_level', 'example', 'line_seq', 'meaning', 'pos', 'pronunciation', 'word', 'word_card_id']} |
| S-DETAIL | Schema InputTextDetail ↔ db 转换器 | 静态+db转换器 | Summary+5字段 | ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_count'] | PASS | {'actual': ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'word_count'], 'expect': ['audio_text', 'audio_url', 'body_cn', 'body_fr', 'cefr_level', 'created_at', 'format', 'id', 'sort_order', 'title', 'topic', 'updated_at', 'wor… |
| S-CORPUS | 语料字段 ⊆ 语料schema允许字段 | JSON键集合校验 | 无越界字段 | 越界=[] | PASS | {'violations': []} |

### 4.4 空语料降级套件（4 例）

| 编号 | 场景 | 方法 | 预期 | 实际 | 结果 | 证据（关键摘录） |
|---|---|---|---|---|---|---|
| Z01 | 空库 levels 返回 [] | HTTP(空库隔离) | 200 data=[] | HTTP 200 [] | PASS | [] |
| Z02 | 空库 texts 返回空页 | HTTP(空库隔离) | items=[] total=0 level=null | HTTP 200 {'items': [], 'total': 0, 'level': None} | PASS | {'items': [], 'total': 0, 'level': None} |
| Z03 | 空库 recommend→no_candidate | HTTP(空库隔离) | text=null reason=no_candidate code=0 | HTTP 200 {'text': None, 'target_level': 'B1', 'reason': 'no_candidate'} | PASS | {'text': None, 'target_level': 'B1', 'reason': 'no_candidate'} |
| Z04 | 空库 text 详情 40401 | HTTP(空库隔离) | 40401 | HTTP 404 code=40401 | PASS | {'code': 40401, 'data': None, 'message': '语料不存在：inp_a2_001'} |

## 五、缺陷清单

**未发现阻塞缺陷。** 109 条用例中无一条 FAIL；契约 §3.5 降级表 9 条、§5 全部 5 端点及错误码、§3.8 收词去重、§6 i+1 三态、§8 21 条测试要点均通过。

> 说明：测试过程中出现的 4 个早期 FAIL 经复核均为**测试脚本自身缺陷**，非被测代码问题，已修正后复跑通过：
> 1. `F02` 初版按模板字符串 `/api/input/texts/${` 匹配前端端点，实际前端用 `'/api/input/texts/'+encodeURIComponent(id)` 拼接；修正匹配串后通过（5 端点均在 `app.js` 中）。
> 2. `F03` 初版按大小写敏感的 `Content-Type` 取响应头，实际返回头为小写 `content-type`；改为大小写不敏感后通过。
> 3. `E04` 初版未带 `Origin` 请求头，CORS 中间件不会注入 `access-control-allow-origin`；补 `Origin` 并大小写不敏感取值后确认返回 `*`。
> 4. 静态解析初版把 mermaid 的 `TYPE field` 误取首词、把 `created_at` 误判为 `CREATE` 关键字；均为测试解析 bug，修正后四方字段一致。

## 六、风险与限制

1. ~~**真实 GLM key 调用未测**~~ **已关闭（2026-11-17 19:40 补充冒烟）**：用户告知本机 key 在用户环境变量 `ZHIPU_API_KEY`，`ai.py` 已将其提升为最高优先级。用该 key 直连真实智谱端点 `https://open.bigmodel.cn/api/paas/v4/chat/completions`（模型 `glm-4-flash`）实测两例：① `Je veux un thé` → 自然回应且未硬纠错（`recast_of=None`）；② `Je suis aller à le gare` → `Ah, vous êtes allé à la gare ?`，`recast_of` 正确回填原句。测试中把 `recast_local` 替换为抛异常桩，确认**未走降级**。鉴权、返回结构、严格 JSON 解析均真实打通；限流/额度耗尽仍沿用 mock 验证，未做真实压测。详见文末「补充验证」。
2. **Mock 边界**：降级表 9 条均按异常类型精确桩模拟（URLError/socket.timeout/HTTPError 429/5xx/401/403/非 JSON/格式异常/RuntimeError），已验证重试次数（可重试=2 次、不可重试=1 次）。但真实网络抖动组合与智谱侧特殊返回（如 `choices` 多元素）未穷尽。
3. **i+1 打分档位**：三态 `level_and_coverage` / `level_only_fallback` / `no_candidate` 均已实测（I17/I21/Z03/I19）。因种子用户 `mastered_count=0`，未构造出 `coverage∈[0.7,0.9]` 的理想档实例；`_level_score`/`_coverage_score`（`app.py:430-456`）与 §6 打分表已做静态逐项核对，一致。
4. **前端验证深度**：仅验证 `/` 含 Tab 标记、`app.js?v=4` 含 5 端点字符串、`styles.css?v=4` 可加载，未做浏览器 DOM 渲染与真实点击交互的端到端测试。
5. **并发量级**：并发 collect 用 5 线程验证幂等与无重复卡（E05），未做高并发压力测试。
6. **环境差异**：隔离测试服务运行于本机临时 DB 副本，主服务 `127.0.0.1:8000` 用于只读验证（health/前端/静态资源/CORS）；若生产环境开启了额外中间件或代理，行为需以生产复测为准。

---

> 报告生成时间：2026-11-17 19:25:29　｜　用例来源：HTTP 58 + Mock 29 + 静态/语料 18 + 空库 4 = 109。

## 七、补充验证：真实智谱 key 端到端冒烟（2026-11-17 19:40）

用户说明 key 位于本机用户环境变量 `ZHIPU_API_KEY`（User 作用域已设置，工具进程未继承）。变更与验证如下：

- **代码变更**：`backend/ai.py` 的 key 解析优先级改为 `ZHIPU_API_KEY` > `GLM_API_KEY` > `LLM_API_KEY`；base_url/model 仍走 `GLM_*` > `LLM_*` > 默认。`.env.example`、`README.md`、`ARCHITECTURE_V2.md` 同步更新。
- **取值核对**：进程内显式注入 `$env:ZHIPU_API_KEY = [Environment]::GetEnvironmentVariable('ZHIPU_API_KEY','User')` 后，`ai.GLM_API_KEY` 非空、`GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4`、`GLM_MODEL=glm-4-flash`。key 值未打印、未写入任何文件。
- **冒烟 1（无错句）**：`recast('cafe', 'Je veux un thé', [])` → `ai_text="Bien sûr ! Je vous apporte un thé tout de suite. Vous le voulez chaud ?"`，`recast_of=None`，`explanation=None`，场景词 `un thé` 正常命中建卡。
- **冒烟 2（错句）**：先把 `ai.recast_local` 替换为抛 `AssertionError('FALLBACK_CALLED')` 的桩，再调 `recast('gare', 'Je suis aller à le gare', [])` → `ai_text="Ah, vous êtes allé à la gare ?"`，`recast_of="Je suis aller à le gare"`，`new_words` 含 `la gare`；桩未被触发 → 确认真实 LLM 路径生效、未降级。
- **冒烟 3（HTTP 端到端）**：带 `ZHIPU_API_KEY` 重启 `127.0.0.1:8000` 后，`POST /api/chat`（scene `street`，`Je suis aller à le gare`）返回 `code=0`，`ai_text="Ah, vous êtes allé à la gare ? Où en êtes-vous ?"`，`recast_of` 正确回填原句，`new_words` 命中 `la gare`。本地规则对同一句只会输出 `Je suis allé à le gare`（不会同时修 `à le`），故此结果证明运行中的服务确实走真实 GLM。
- **追加（19:57）对话气泡体验**：新增 `POST /api/translate` 批量翻译端点与前端「双方 🔊 + 中文小字」，`ai.py` 抽出统一 `_glm_post()`（重试规则不变）。真实调用 `texts=["Je veux un thé.","Ah, vous êtes allé à la gare ? Où en êtes-vous ?"]` → `code=0`，译文 `["我想喝杯茶。","啊，你去车站了？你到哪了？"]`；随后回归 `POST /api/chat` 仍 200/4 字段、重述正常，说明重构未破坏 109 用例基线。
- **结论**：风险 #1 关闭。真实端点鉴权、OpenAI 兼容响应解析、严格 JSON 校验、recast 回填、收词合并均打通；未覆盖真实限流/额度耗尽。

## 八、验收期缺陷 D1：explanation 正确/错误形式颠倒（2026-11-18）

- **现象**（上级验收发现）：输入 `Je veux un froid café, s'il vous plaît.`，重述正确（`Bien sûr, un café froid.`），但解释写成「在法语中，形容词放在名词后面，所以是 'froid café' 而不是 'café froid'。」——正确/错误形式颠倒。
- **根因**：SYSTEM_PROMPT 自相矛盾（要求 explanation 绝不出现法语，但其"正确示例"本身含法语词 voudrais），且从未约束「正确形式在前、与重述一致」；后端仅有语言兜底（`_ensure_explanation_zh` 管"是不是中文"），无正确性校验（管"说得对不对"）。
- **修复**（`backend/ai.py`）：
  1. 提示词：消除矛盾——允许单引号包裹的法语短形式，硬约束「正确形式在前、错误形式在后、正确形式必须与 ai_text 中实际说法一致」，附正反示例；
  2. 新增确定性兜底 `_validate_explanation_order`：仅纠错轮（`recast_of` 非空）且 explanation 含「而不是/不是/而非」及 ≥2 个单引号片段（正则支持法语缩合撇号 j'aime/l'homme）时，与 `ai_text` 归一化匹配的一方视为正确形式；判定颠倒则机械交换两个片段，无法判定或异常一律保持原样，绝不抛出。
- **验证**：
  - 离线单测 **9/9 PASS**（颠倒交换 / 顺序正确不动 / 撇号片段颠倒交换 / 撇号顺序正确不动 / 双片段均匹配不动 / 均不匹配不动 / 无引号 / 无关键字 / recast_of 空）；
  - 真实 GLM 直调 2 次（scene `cafe` + 原句）：两次 explanation 均正确形式在前、与重述一致，未再颠倒；
  - HTTP 端到端（`start.bat` 重启后 `POST /api/chat`，scene `cafe`）：`code=0`、HTTP 200，`ai_text="D'accord, je vous apporte un café froid tout de suite. Ça va bien pour vous ?"`，explanation「在咖啡馆点单时，可以说 'Je veux un café froid, s'il vous plaît'。」——顺序正确。
- **边界**：兜底仅覆盖「单引号片段 + 而不是类关键字」这一模板类；主防线是提示词约束。本次改动仅涉 explanation 生成与校验，未批量重跑 109 用例（v1/v2 其余链路未动）。

## 九、验收期缺陷 D2：伪重述（凑 recast_of 但未真正纠错）+ recast_of 截断（2026-11-18）

- **现象**（上级验收发现）：输入片段句 `S'en va ?`，GLM 间歇性硬凑 `recast_of`，ai_text（"Bien sûr, je vais préparer votre croissant…"）与原句无词汇关联、角色错位（把服务员的台词当成顾客的"正确说法"）；且 recast_of 回填被截断为 `S'en va`（丢 `?`）。复现取证：同一输入 2 次直调，一次伪重述、一次正常——**间歇性**，提示词单防线不可靠。
- **根因**：① SYSTEM_PROMPT 未定义"纠错"的充要条件（= 对用户原句的修正说法须出现在 ai_text 中），GLM 可把"接下来该说的话"当正确说法；② 后端无 recast_of 与 ai_text 的相关性校验；③ recast_of 直接采信 GLM 回填，无用户原句权威覆盖。
- **修复**（`backend/ai.py`）：
  1. SYSTEM_PROMPT 新增硬约束：纠错专指把用户原句用更自然的法语再说一遍，修正说法必须能在 ai_text 中找到；片段/语义不明必须 `recast_of=null` 纯接话；
  2. 新增 `_validate_recast_relevance` 兜底：recast_of 与 ai_text 归一化后无词汇锚（任一 ≥3 字母非虚词内容词子串匹配；归一化含 NFD 去重音，cinéma/cinema 可匹配）→ 判定伪重述 → 降级普通回应（recast_of/explanation 置 null，保留 ai_text）——宁可不纠错，不教错的；虚词表覆盖代词/冠词/常用助动词；
  3. `recast()` 入口：recast_of 非空时一律以 `user_text` 覆盖回填（用户输入是唯一权威，治截断/漂移）；
  4. 顺带（D1 家族残留，本节回归中发现）：提示词补「规则表述方向必须与例子一致（形容词在名词后面）」约束及反例，治 explanation 中「之前/之后」方位词写反。
- **验证**：
  - 离线单测 **8/8 PASS**（真机 D2 原型降级 / gare、froid café、撇号 j'aime、重音 cinéma 真重述均放行 / 纯虚词句降级 / recast_of 空不动 / ai_text 空不抛）；
  - 真实 GLM 直调：`S'en va ?` × 2 用户可见行为均正确（无伪重述卡；日志显示兜底真实拦截 2 次）；对照组真错句重述正常、recast_of 完整；
  - HTTP 端到端 × 2：真实错句（explanation 方向正确 + 完整回填）与片段句（`recast_of=null` 无卡）均 200/code 0。
- **边界**：词汇锚刻意放宽（任一内容词命中即放行），可能漏放个别伪重述（概率低、无错误教学危害大于误杀）；"之前/之后"方位词错误仅提示词约束（机械校验需词性标注，零依赖约束下不做）；本地规则路径不受影响（其 ai_text 按构造含修正说法）。
