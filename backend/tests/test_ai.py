"""TASK-0076 夜班 OP-06：ai.py（GLM 重述引擎）单测，降级判定表 9 条逐条覆盖。

运行（单文件）：cd tools/french-learner/backend && python -m unittest tests.test_ai -v
合并回归：cd tools/french-learner/backend && python -X utf8 -m unittest discover -s tests -t . -p "test_*.py" -v

硬约束（夜班章程）：
- urllib 全 mock（patch urllib.request.urlopen），零网络、零 GLM 计费。AiTestBase.setUp
  把 urlopen 默认 side_effect 设为 AssertionError，任何未显式编排的调用（= 真实网络企图）
  都会让用例当场失败。
- db.create_card / db.get_profile 一律 mock，测试绝不读写真实 SQLite（backend/data/yaya.db）。
- 只新增本测试文件，不改产品代码；契约偏差只记录不修。

契约对照（docs/ARCHITECTURE_V2.md §3.5 降级判定条件表，9 条 → 用例名）：
  #1 无 key 零网络        → TestDegradationTable.test_rule01_no_key_zero_network_local
  #2 URLError 重试 1 次    → ...test_rule02_urlerror_retry_once_then_local
  #3 超时重试 1 次         → ...test_rule03_socket_timeout_retry_once_then_local
  #4 HTTP 429/5xx 重试 1 次 → ...test_rule04_http_429_5xx_retry_once_then_local
  #5 HTTP 401/403/其他 4xx 不重试 → ...test_rule05_http_401_403_no_retry_then_local
  #6 响应体非法不重试       → ...test_rule06_bad_response_body_no_retry_then_local
  #7 content 格式非法不重试 → ...test_rule07_content_format_invalid_no_retry_then_local
  #8 可选字段缺失不算失败   → ...test_rule08_optional_fields_missing_not_failure
  #9 其他任意异常兜底       → ...test_rule09_other_exception_no_retry_then_local
"""
import json
import socket
import sys
import unittest
import urllib.error
from unittest import mock
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[1])
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import ai  # noqa: E402

UT_BASE = "https://mock.local/v4"
UT_MODEL = "ut-model"
CAFE_POOL = list(ai.seed_data.get_scene_seed("cafe")["reply_pool"])
ZH_PLACEHOLDER = ai._EXPLANATION_ZH_PLACEHOLDER


def glm_ok(content: str) -> mock.MagicMock:
    """构造可 with 进出的 urlopen 假响应：read() 返回包裹 content 的 OpenAI 兼容响应体。"""
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}, ensure_ascii=False
    ).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def glm_raw(body: bytes) -> mock.MagicMock:
    """同 glm_ok，但响应体原样给定（规则 6 用：响应体本身非法）。"""
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def llm_payload(ai_text, recast_of=None, explanation=None, new_words=None) -> str:
    """LLM content（本身是 JSON 字符串，§3.3 注意点）。缺省键即不传，用于规则 8。"""
    obj = {"ai_text": ai_text}
    if recast_of is not None:
        obj["recast_of"] = recast_of
    if explanation is not None:
        obj["explanation"] = explanation
    if new_words is not None:
        obj["new_words"] = new_words
    return json.dumps(obj, ensure_ascii=False)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(UT_BASE + "/chat/completions", code, "http err", None, None)


def captured_request(urlopen_mock) -> dict:
    """取第一次 urlopen 调用的 POST 请求体（payload dict）。"""
    req = urlopen_mock.call_args[0][0]
    return json.loads(req.data.decode("utf-8"))


class AiTestBase(unittest.TestCase):
    """公共夹具：网络/DB 全 mock + 模块常量固定；任何用例都零网络、零落库。"""

    def setUp(self):
        self._card_seq = 0
        # 默认无 key：即便某用例忘了控制 key，也只会走本地规则，绝不发请求。
        mock.patch.object(ai, "GLM_API_KEY", "").start()
        # fail-loud：任何未显式编排的 urlopen 调用（= 真实网络企图）直接判失败。
        self.urlopen = mock.patch("urllib.request.urlopen").start()
        self.urlopen.side_effect = AssertionError("测试禁止真实网络请求：urllib 必须全 mock")
        self.sleep = mock.patch("ai.time.sleep").start()  # MagicMock 默认 no-op 且记录调用
        self.create_card = mock.patch.object(
            ai.db, "create_card", side_effect=self._fake_card
        ).start()
        self.get_profile = mock.patch.object(
            ai.db, "get_profile",
            return_value={"cefr_level": "A2", "target_level": "B2"},
        ).start()
        mock.patch.object(ai, "GLM_BASE_URL", UT_BASE).start()
        mock.patch.object(ai, "GLM_MODEL", UT_MODEL).start()
        self.addCleanup(mock.patch.stopall)

    def _fake_card(self, user_id, word, meaning=None, pos=None, example=None,
                   pronunciation=None, cefr_level=None, source_scene_id=None):
        """替身 create_card：不落库，返回最小 WordCard dict。"""
        self._card_seq += 1
        return {"id": self._card_seq, "word": word, "meaning": meaning,
                "user_id": user_id, "source_scene_id": source_scene_id}

    def set_key(self, key="ut-key"):
        p = mock.patch.object(ai, "GLM_API_KEY", key)
        p.start()
        self.addCleanup(p.stop)

    def assert_local(self, result, scene_id="cafe", msg=""):
        """断言结果来自本地规则（话术池或通用兜底），即已降级。"""
        pool = list(ai.seed_data.get_scene_seed(scene_id)["reply_pool"])
        self.assertIn(result.ai_text, pool + [ai.GENERIC_REPLY],
                      msg or "应降级为本地规则结果")


class TestDegradationTable(AiTestBase):
    """契约 §3.5 降级判定表 9 条逐条覆盖，判定依据写入各断言消息。"""

    def test_rule01_no_key_zero_network_local(self):
        """规则1『ZHIPU/GLM/LLM_API_KEY 均为空 → 直接本地规则，零网络请求』。"""
        result = ai.recast("cafe", "Je veux un thé.", [])
        self.urlopen.assert_not_called()
        self.assertEqual(result.ai_text, "Je voudrais un thé.",
                         "规则1：无 key 必须走本地规则表（je veux → Je voudrais）")
        self.assertEqual(result.recast_of, "Je veux un thé.",
                         "本地纠错的 recast_of 以用户输入为唯一权威")
        self.assertTrue(result.explanation, "规则1：本地纠错应带讲解")

    def test_rule02_urlerror_retry_once_then_local(self):
        """规则2『URLError 非 HTTP（DNS 失败/连接拒绝/不可达）→ 重试 1 次 → 本地规则』。"""
        self.set_key()
        self.urlopen.side_effect = [
            urllib.error.URLError("conn refused"),
            urllib.error.URLError("conn refused"),
        ]
        with self.assertLogs("yaya.ai", level="WARNING") as cm:
            result = ai.recast("cafe", "Je veux un café.", [])
        self.assertEqual(self.urlopen.call_count, 2,
                         "规则2：URLError 可重试，恰好 1 次（共 2 次）")
        self.assertEqual(self.sleep.call_count, 1, "规则2：重试间隔 0.3s 只 sleep 1 次")
        self.assertEqual(result.ai_text, "Je voudrais un café.",
                         "规则2：重试仍失败必须降级本地规则")
        self.assertTrue(any("回退本地规则" in line for line in cm.output),
                        "契约：任一降级都写 warning『LLM 重述失败，回退本地规则』")

    def test_rule03_socket_timeout_retry_once_then_local(self):
        """规则3『单次请求超时（socket.timeout/TimeoutError）→ 重试 1 次 → 本地规则』。"""
        self.set_key()
        self.urlopen.side_effect = [socket.timeout("timed out"), socket.timeout("timed out")]
        result = ai.recast("cafe", "Je veux un café.", [])
        self.assertEqual(self.urlopen.call_count, 2, "规则3：超时可重试，恰好 1 次")
        self.assertEqual(self.sleep.call_count, 1, "规则3：重试间隔只 sleep 1 次")
        self.assertEqual(result.ai_text, "Je voudrais un café.",
                         "规则3：重试仍超时必须降级本地规则")

    def test_rule04_http_429_5xx_retry_once_then_local(self):
        """规则4『HTTP 429（限流）或 5xx → 重试 1 次 → 仍失败降级本地』。"""
        self.set_key()
        for code in (429, 500, 503):
            with self.subTest(code=code):
                self.urlopen.reset_mock()
                self.sleep.reset_mock()
                self.urlopen.side_effect = [http_error(code), http_error(code)]
                with self.assertLogs("yaya.ai", level="WARNING"):
                    result = ai.recast("cafe", "Bonjour Madame.", [])
                self.assertEqual(self.urlopen.call_count, 2,
                                 f"规则4：HTTP {code} 可重试，恰好 1 次")
                self.assertEqual(self.sleep.call_count, 1, f"规则4：HTTP {code} 重试前 sleep")
                self.assert_local(result, msg=f"规则4：HTTP {code} 重试仍失败必须降级本地规则")

    def test_rule05_http_401_403_no_retry_then_local(self):
        """规则5『HTTP 401/403（key 无效）及其他 4xx → 不重试，立即本地规则』。"""
        self.set_key()
        for code in (400, 401, 403):
            with self.subTest(code=code):
                self.urlopen.reset_mock()
                self.sleep.reset_mock()
                self.urlopen.side_effect = [http_error(code)]
                with self.assertLogs("yaya.ai", level="WARNING"):
                    result = ai.recast("cafe", "Bonjour Madame.", [])
                self.assertEqual(self.urlopen.call_count, 1,
                                 f"规则5：HTTP {code} 不可重试，立即降级")
                self.assertEqual(self.sleep.call_count, 0,
                                 f"规则5：HTTP {code} 不应 sleep")
                self.assert_local(result, msg=f"规则5：HTTP {code} 必须立即本地规则")

    def test_rule06_bad_response_body_no_retry_then_local(self):
        """规则6『响应体非合法 JSON / choices 为空 / message.content 缺失 → 不重试 → 本地』。"""
        self.set_key()
        bodies = [
            ("非 JSON 响应体", b"this is not json"),
            ("choices 键缺失", json.dumps({}).encode("utf-8")),
            ("choices 空数组", json.dumps({"choices": []}).encode("utf-8")),
            ("message.content 缺失", json.dumps({"choices": [{"message": {}}]}).encode("utf-8")),
        ]
        for name, body in bodies:
            with self.subTest(body=name):
                self.urlopen.reset_mock()
                self.urlopen.side_effect = [glm_raw(body)]
                with self.assertLogs("yaya.ai", level="WARNING"):
                    result = ai.recast("cafe", "Bonjour Madame.", [])
                self.assertEqual(self.urlopen.call_count, 1,
                                 f"规则6[{name}]：响应体格式异常不重试")
                self.assert_local(result, msg=f"规则6[{name}]：必须降级本地规则")

    def test_rule07_content_format_invalid_no_retry_then_local(self):
        """规则7『content 非合法 JSON 对象 / ai_text 非字符串或空 → 不重试 → 本地规则』。"""
        self.set_key()
        contents = [
            ("纯文本非 JSON", "plain text, not json"),
            ("ai_text 空白", llm_payload("   ")),
            ("ai_text 非字符串", llm_payload(123)),
            ("缺 ai_text 键", '{"foo": "bar"}'),
        ]
        for name, content in contents:
            with self.subTest(content=name):
                self.urlopen.reset_mock()
                self.urlopen.side_effect = [glm_ok(content)]
                with self.assertLogs("yaya.ai", level="WARNING"):
                    result = ai.recast("cafe", "Bonjour Madame.", [])
                self.assertEqual(self.urlopen.call_count, 1,
                                 f"规则7[{name}]：content 格式异常不重试")
                self.assert_local(result, msg=f"规则7[{name}]：必须降级本地规则")

    def test_rule08_optional_fields_missing_not_failure(self):
        """规则8『recast_of/explanation 缺失或 new_words 非法 → 不算失败，补全后照常返回』。"""
        self.set_key()
        llm_text = "Voilà votre commande ut-rule08."
        self.urlopen.side_effect = [glm_ok(llm_payload(llm_text, new_words="oops"))]
        result = ai.recast("cafe", "Bonjour Madame.", [])
        self.assertEqual(result.ai_text, llm_text,
                         "规则8：解析成功必须采用 LLM 结果，而非降级话术池")
        self.assertNotIn(result.ai_text, CAFE_POOL + [ai.GENERIC_REPLY],
                         "规则8：可选字段缺失不算失败，不得降级")
        self.assertIsNone(result.recast_of, "规则8：recast_of 缺失补全为 None")
        self.assertIsNone(result.explanation, "规则8：explanation 缺失补全为 None")
        self.assertEqual(result.llm_new_words, [], "规则8：new_words 非法补全为 []")
        self.assertEqual(result.new_words, [], "规则8：ai_text 未命中场景词表时无建卡")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_rule09_other_exception_no_retry_then_local(self):
        """规则9『urllib 抛出其他任意异常 → recast() 兜底 except Exception → 本地规则』。"""
        self.set_key()
        self.urlopen.side_effect = [RuntimeError("boom")]
        with self.assertLogs("yaya.ai", level="WARNING"):
            result = ai.recast("cafe", "Bonjour Madame.", [])
        self.assertEqual(self.urlopen.call_count, 1, "规则9：非可重试异常不重试")
        self.assert_local(result, msg="规则9：任意异常兜底必须降级本地规则，不抛 500")


class TestRecastMainPath(AiTestBase):
    """recast 主路径：GLM 正常返回 → 重述结果；prompt 组装与回填契约固化。"""

    def test_llm_normal_returns_recast_with_words(self):
        """主路径：GLM 正常返回合法 JSON → 采纳 LLM 重述；中文讲解零额外请求。"""
        self.set_key()
        content = llm_payload(
            "Bien sûr ! Je vous apporte un thé tout de suite.",
            recast_of="Je veux un thé.",
            explanation="想礼貌点单，法国人更常说 'voudrais'，不过你这样说也完全能懂。",
            new_words=[{"word": "tout de suite", "meaning": "马上",
                        "pos": "loc.", "cefr_level": "A2"}],
        )
        self.urlopen.side_effect = [glm_ok(content)]
        result = ai.recast("cafe", "Je veux un thé.", [])
        self.assertEqual(result.ai_text, "Bien sûr ! Je vous apporte un thé tout de suite.",
                         "主路径：GLM 正常返回时必须采纳 LLM 的 ai_text")
        self.assertEqual(result.explanation,
                         "想礼貌点单，法国人更常说 'voudrais'，不过你这样说也完全能懂。",
                         "中文讲解应原样保留（_ensure_explanation_zh 不动含 CJK 的讲解）")
        self.assertEqual(result.recast_of, "Je veux un thé.",
                         "recast_of 以用户输入为唯一权威回填（验收缺陷 D2 保险）")
        self.assertEqual([w["word"] for w in result.new_words],
                         ["tout de suite", "un thé"],
                         "收词=来源A(LLM 命中 ai_text)+来源B(本地场景词表)，按序合并")
        self.assertEqual(self.urlopen.call_count, 1,
                         "讲解含 CJK 时零额外翻译请求（中文化兜底契约）")

    def test_recast_of_overwritten_with_user_text(self):
        """固化：GLM 回传的 recast_of 被截断/漂移时，以用户原句逐字覆盖回填。"""
        self.set_key()
        content = llm_payload(
            "Bien sûr ! Je vous apporte un thé tout de suite.",
            recast_of="Je veux un",
            explanation="想礼貌点单，法国人更常说 'voudrais'。",
        )
        self.urlopen.side_effect = [glm_ok(content)]
        result = ai.recast("cafe", "Je veux un thé.", [])
        self.assertEqual(result.recast_of, "Je veux un thé.",
                         "recast_of 必须逐字等于用户原句，防 GLM 回填截断/漂移")
        self.assertNotEqual(result.recast_of, "Je veux un")

    def test_pseudo_recast_degraded_in_full_chain(self):
        """固化 D2：recast_of 与 ai_text 无词汇锚的伪重述 → 降级为普通回应。"""
        self.set_key()
        content = llm_payload(
            "Le temps passe très vite.",
            recast_of="Je veux un thé.",
            explanation="讲解一下",
        )
        self.urlopen.side_effect = [glm_ok(content)]
        result = ai.recast("cafe", "Je veux un thé.", [])
        self.assertEqual(result.ai_text, "Le temps passe très vite.",
                         "伪重述兜底：保留 ai_text，宁可不纠错")
        self.assertIsNone(result.recast_of,
                          "伪重述兜底：无词汇锚时 recast_of 必须清空")
        self.assertIsNone(result.explanation, "伪重述兜底：explanation 一并清空")

    def test_retry_then_success_llm_result(self):
        """主路径：首次 429 → 重试成功 → 采纳 LLM 结果（重试不白做）。"""
        self.set_key()
        self.urlopen.side_effect = [
            http_error(429),
            glm_ok(llm_payload("Voilà votre ut-retry.")),
        ]
        result = ai.recast("cafe", "Bonjour Madame.", [])
        self.assertEqual(result.ai_text, "Voilà votre ut-retry.",
                         "重试成功必须采纳 LLM 结果而非本地池")
        self.assertEqual(self.urlopen.call_count, 2, "首次 429 后应恰好重试 1 次")
        self.assertEqual(self.sleep.call_count, 1)

    def test_no_key_local_pool_generic_reply(self):
        """主路径：无 key 且未命中规则表 → 场景话术池接话。"""
        result = ai.recast("cafe", "Bonjour Madame.", [])
        self.urlopen.assert_not_called()
        self.assertIn(result.ai_text, CAFE_POOL,
                      "未命中规则表时必须用场景话术池（cafe）接话")
        self.assertIsNone(result.recast_of, "非纠错轮 recast_of 为 None")
        self.assertIsNone(result.explanation, "非纠错轮 explanation 为 None")

    def test_history_truncated_to_last_10(self):
        """固化 §3.3：recent_history 只取最后 10 轮，且仅映射 {role, fr}。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok(llm_payload("Voilà votre ut-hist."))]
        history = [{"role": "user", "fr": f"turn {i}", "cn": f"第{i}句"} for i in range(15)]
        ai.recast("cafe", "Bonjour Madame.", history)
        payload = captured_request(self.urlopen)
        context = json.loads(payload["messages"][1]["content"])
        recent = context["recent_history"]
        self.assertEqual(len(recent), 10, "history 超过 10 轮必须截到最后 10 轮")
        self.assertEqual([t["fr"] for t in recent], [f"turn {i}" for i in range(5, 15)],
                         "必须保留最后 10 轮（turn 5~14）")
        for t in recent:
            self.assertEqual(set(t), {"role", "fr"},
                             "recent_history 每项只含 role/fr，cn 等额外字段被剥离")

    def test_prompt_system_user_context_and_endpoint(self):
        """固化 §3.2/§3.3/§3.7：端点、鉴权、超时、请求体与 messages 结构逐项核对。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok(llm_payload("Voilà votre ut-prompt."))]
        history = [
            {"role": "user", "fr": "Bonjour"},
            {"role": "user", "fr": "Salut !", "extra": "x"},
            None,
        ]
        ai.recast("cafe", "Je veux un thé.", history)
        req = self.urlopen.call_args[0][0]
        self.assertEqual(req.full_url, UT_BASE + "/chat/completions",
                         "§3.2：URL = base_url(去尾斜杠) + /chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer ut-key",
                         "§3.2：鉴权头 Bearer {key}")
        self.assertEqual(self.urlopen.call_args[1].get("timeout"), 8,
                         "§3.6：单次超时 GLM_TIMEOUT_SECONDS=8")
        payload = captured_request(self.urlopen)
        self.assertEqual(payload["model"], UT_MODEL, "§3.3：model 取配置值")
        self.assertEqual(payload["temperature"], 0.7, "§3.3：对话默认 temperature=0.7")
        self.assertEqual(payload["max_tokens"], 512, "§3.3：默认 max_tokens=512")
        msgs = payload["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[0]["content"], ai.SYSTEM_PROMPT,
                         "§3.7：system 消息逐字使用 ai.SYSTEM_PROMPT")
        self.assertEqual(msgs[1]["role"], "user")
        context = json.loads(msgs[1]["content"])
        self.assertEqual(context["scene"],
                         {"id": "cafe", "title": "在咖啡馆点单", "cefr_level": "A2"},
                         "§3.3：scene 上下文取自 seed 场景")
        self.assertEqual(context["learner"],
                         {"cefr_level": "A2", "target_level": "B2"},
                         "§3.3：learner 上下文取自 db.get_profile()（此处为 mock 值）")
        self.assertEqual(context["recent_history"],
                         [{"role": "user", "fr": "Bonjour"}, {"role": "user", "fr": "Salut !"}],
                         "history 逐项只映射 role/fr；非 dict 项被过滤")
        self.assertEqual(context["user_text"], "Je veux un thé.",
                         "user_text 必须逐字为用户原句")

    def test_new_words_merge_dedup(self):
        """固化 §3.8：来源 A（LLM）+ 来源 B（本地词表）合并、按 word 去重、过滤非法项。"""
        self.set_key()
        content = llm_payload(
            "Un croissant ! Bien sûr. Vous en voulez un autre ?",
            new_words=[
                {"word": "un croissant", "meaning": "可颂（LLM）", "pos": "n.m.", "cefr_level": "A2"},
                {"word": "bien sûr", "meaning": ""},          # meaning 空 → 剔除
                {"word": "un autre", "meaning": "另一个"},     # 命中 ai_text → 收
            ],
        )
        self.urlopen.side_effect = [glm_ok(content)]
        result = ai.recast("cafe", "Bonjour Madame.", [])
        self.assertEqual(self.create_card.call_count, 2,
                         "本地词表的重复词（un croissant）必须被去重，不再建第二张卡")
        words = [c.kwargs["word"] for c in self.create_card.call_args_list]
        self.assertEqual(words, ["un croissant", "un autre"],
                         "来源 A 先于来源 B，重复词以来源 A 为准")
        first = self.create_card.call_args_list[0].kwargs
        self.assertEqual(first["meaning"], "可颂（LLM）")
        self.assertEqual(first["cefr_level"], "A2")
        self.assertEqual(first["source_scene_id"], "cafe")
        self.assertEqual(first["user_id"], ai.DEFAULT_USER_ID, "建卡固定 user_id=1")
        self.assertEqual([w["word"] for w in result.new_words], ["un croissant", "un autre"],
                         "result.new_words 即 create_card 返回序列")

    def test_to_dict_only_4_fields(self):
        """固化 §3.8：ChatResult.to_dict() 仅输出 v1 四字段，llm_new_words 不进 JSON。"""
        r = ai.ChatResult("a", "b", "c", [{"w": 1}], llm_new_words=[{"x": 2}])
        d = r.to_dict()
        self.assertEqual(set(d), {"ai_text", "recast_of", "explanation", "new_words"},
                         "契约 §3.8：to_dict 仅 v1 四字段，前端无感")
        self.assertNotIn("llm_new_words", d)


class TestParseLlmContent(unittest.TestCase):
    """_parse_llm_content 严格解析（§3.4 步骤 1~6）：纯函数，无需网络/DB 夹具。"""

    def test_markdown_fence_stripped(self):
        """§3.4 步骤 2：``` 开头先去 markdown 围栏（带或不带 json 标记）。"""
        for content in ('```json\n{"ai_text": "Salut !"}\n```',
                        '```\n{"ai_text": "Salut !"}\n```'):
            with self.subTest(content=content):
                r = ai._parse_llm_content(content)
                self.assertEqual(r.ai_text, "Salut !", "围栏剥离后应正常解析")

    def test_non_dict_json_raises(self):
        """§3.4 步骤 3~4：JSON 非对象（数组/字符串/数字/空串）→ ValueError 降级。"""
        for content in ('[1, 2]', '"just a string"', "123", ""):
            with self.subTest(content=content):
                with self.assertRaises(ValueError, msg="非 dict 一律 ValueError"):
                    ai._parse_llm_content(content)

    def test_ai_text_invalid_raises(self):
        """§3.4 步骤 4：ai_text 缺失/非字符串/空白 → ValueError（严格模式，不回退 v1 整段当 ai_text）。"""
        for obj in ({}, {"ai_text": "   "}, {"ai_text": 123}, {"ai_text": None}):
            with self.subTest(obj=obj):
                with self.assertRaises(ValueError):
                    ai._parse_llm_content(json.dumps(obj, ensure_ascii=False))

    def test_optional_fields_normalized_to_none(self):
        """§3.4 步骤 5：recast_of/explanation 空白补 None；new_words 非 list 补 []。"""
        r = ai._parse_llm_content(
            '{"ai_text": "ok", "recast_of": "  ", "explanation": "", "new_words": "oops"}'
        )
        self.assertEqual(r.ai_text, "ok")
        self.assertIsNone(r.recast_of, "空白 recast_of 补 None")
        self.assertIsNone(r.explanation, "空白 explanation 补 None")
        self.assertEqual(r.llm_new_words, [], "非 list 的 new_words 补 []")

    def test_new_words_filtered(self):
        """§3.4 步骤 5：new_words 逐元素过滤，仅保留含非空字符串 word 的 dict。"""
        content = json.dumps(
            {"ai_text": "ok", "new_words": [
                "junk", {"word": ""}, {"meaning": "无词"}, 42,
                {"word": " café ", "meaning": "咖啡", "pos": "n.m.", "cefr_level": "A1"},
            ]},
            ensure_ascii=False,
        )
        r = ai._parse_llm_content(content)
        self.assertEqual(r.llm_new_words,
                         [{"word": "café", "meaning": "咖啡", "pos": "n.m.", "cefr_level": "A1"}],
                         "仅合法 dict 元素保留，word 去首尾空白")


class TestTranslateToZh(AiTestBase):
    """translate_to_zh：批量法语→中文，任何失败对应位置 None，绝不抛异常。"""

    def test_no_key_no_request(self):
        """无 key → 全 None，且不发任何请求。"""
        result = ai.translate_to_zh(["Bonjour"])
        self.assertEqual(result, [None], "无 key 时对应位置全 None")
        self.urlopen.assert_not_called()

    def test_blank_inputs_short_circuit(self):
        """全空白/非字符串输入 → 全 None 短路返回，不发请求。"""
        result = ai.translate_to_zh(["", "   ", None])
        self.assertEqual(result, [None, None, None], "空白输入跳过请求并在原位置补 None")
        self.urlopen.assert_not_called()

    def test_success_mapping_and_blank_backfill(self):
        """有 key：空白输入跳过翻译并回填 None，其余按序对位。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok('{"translations": ["你好", "谢谢"]}')]
        result = ai.translate_to_zh(["Bonjour", "  ", "Merci"])
        self.assertEqual(result, ["你好", None, "谢谢"],
                         "translations 按非空白项顺序对位，空白项补 None")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_short_answer_all_none(self):
        """translations 长度不足 → ValueError → 全 None，绝不抛给调用方。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok('{"translations": ["你好"]}')]
        with self.assertLogs("yaya.ai", level="WARNING"):
            result = ai.translate_to_zh(["Bonjour", "Merci"])
        self.assertEqual(result, [None, None], "长度不符必须整体降级为全 None")

    def test_invalid_body_all_none(self):
        """响应体非合法 JSON → 全 None。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok("not json at all")]
        result = ai.translate_to_zh(["Bonjour", "Merci"])
        self.assertEqual(result, [None, None])

    def test_network_error_all_none(self):
        """网络异常（重试 1 次仍失败）→ 全 None，不阻断对话。"""
        self.set_key()
        self.urlopen.side_effect = [
            urllib.error.URLError("conn refused"),
            urllib.error.URLError("conn refused"),
        ]
        result = ai.translate_to_zh(["Bonjour", "Merci"])
        self.assertEqual(result, [None, None])
        self.assertEqual(self.urlopen.call_count, 2, "translate 走同一 _glm_post，重试 1 次")


class TestExplanationZhFallback(AiTestBase):
    """explanation 中文化兜底：非中文讲解 → 尝试翻译，失败给温和占位；中文零请求。"""

    def test_chinese_explanation_no_extra_request(self):
        """含 CJK 的讲解原样保留，零额外网络请求。"""
        r = ai.ChatResult("x", explanation="这里有个讲解。")
        ai._ensure_explanation_zh(r)
        self.assertEqual(r.explanation, "这里有个讲解。", "中文讲解不应被改动")
        self.urlopen.assert_not_called()

    def test_english_explanation_translated(self):
        """非中文讲解 → 发起一次翻译请求并用中文译文覆盖。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok('{"translations": ["这是一句中文讲解。"]}')]
        r = ai.ChatResult("x", explanation="The polite form is 'voudrais'.")
        ai._ensure_explanation_zh(r)
        self.assertEqual(r.explanation, "这是一句中文讲解。",
                         "译文含 CJK 时应替换原讲解")
        self.assertEqual(self.urlopen.call_count, 1)

    def test_translation_failure_placeholder(self):
        """翻译请求失败 → 温和中文占位，不把看不懂的外语展示给用户。"""
        self.set_key()
        self.urlopen.side_effect = [
            urllib.error.URLError("conn refused"),
            urllib.error.URLError("conn refused"),
        ]
        r = ai.ChatResult("x", explanation="Sorry, the polite form.")
        ai._ensure_explanation_zh(r)
        self.assertEqual(r.explanation, ZH_PLACEHOLDER, "翻译失败必须落到中文占位")

    def test_no_key_placeholder(self):
        """无 key（翻译直接返回 None）→ 占位，且零网络请求。"""
        r = ai.ChatResult("x", explanation="Sorry, the polite form.")
        ai._ensure_explanation_zh(r)
        self.assertEqual(r.explanation, ZH_PLACEHOLDER, "无 key 也必须兜底为中文占位")
        self.urlopen.assert_not_called()

    def test_translated_but_non_cjk_placeholder(self):
        """译文仍非中文 → 占位，不展示外语讲解。"""
        self.set_key()
        self.urlopen.side_effect = [glm_ok('{"translations": ["hallo noch immer"]}')]
        r = ai.ChatResult("x", explanation="Sorry, the polite form.")
        ai._ensure_explanation_zh(r)
        self.assertEqual(r.explanation, ZH_PLACEHOLDER, "译文不含 CJK 时必须落到占位")


class TestRecastGuards(unittest.TestCase):
    """D1/D2 兜底校验器：纯函数级直测（recast 链路级已由 TestRecastMainPath 覆盖）。"""

    def test_pseudo_recast_cleared_when_no_anchor(self):
        """D2：recast_of 与 ai_text 无任何词汇锚（≥3 字母非虚词）→ 双双清空。"""
        r = ai.ChatResult(ai_text="Le temps passe très vite.",
                          recast_of="Je veux un thé.", explanation="讲解")
        ai._validate_recast_relevance(r)
        self.assertIsNone(r.recast_of, "无词汇锚的伪重述必须清空 recast_of")
        self.assertIsNone(r.explanation, "无词汇锚的伪重述必须清空 explanation")

    def test_true_recast_kept_with_anchor(self):
        """D2：话题词（thé→the）命中 ai_text → 视为真重述，放行。"""
        r = ai.ChatResult(ai_text="Bien sûr ! Je vous apporte un thé tout de suite.",
                          recast_of="Je veux un thé.", explanation="讲解")
        ai._validate_recast_relevance(r)
        self.assertEqual(r.recast_of, "Je veux un thé.", "有锚的真重述不得误杀")
        self.assertEqual(r.explanation, "讲解")

    def test_explanation_order_swapped_when_reversed(self):
        """D1：explanation 把错误形式放在「而不是」之前 → 机械交换两个片段。"""
        r = ai.ChatResult(ai_text="Voilà votre café froid.",
                          recast_of="Je veux un froid café.",
                          explanation="所以是 'froid café' 而不是 'café froid'")
        ai._validate_explanation_order(r)
        self.assertEqual(r.explanation, "所以是 'café froid' 而不是 'froid café'",
                         "与 ai_text 一致的片段才是正确形式，必须换到「而不是」之前")

    def test_explanation_order_correct_untouched(self):
        """D1：顺序正确（正确形式在「而不是」之前）→ 保持原样。"""
        original = "所以是 'café froid' 而不是 'froid café'"
        r = ai.ChatResult(ai_text="Voilà votre café froid.",
                          recast_of="Je veux un froid café.", explanation=original)
        ai._validate_explanation_order(r)
        self.assertEqual(r.explanation, original, "顺序正确时不得干预")

    def test_non_correction_round_untouched(self):
        """D1：非纠错轮（recast_of 空）不干预，即使 explanation 形似颠倒。"""
        original = "所以是 'a' 而不是 'b'"
        r = ai.ChatResult(ai_text="Bonjour !", recast_of=None, explanation=original)
        ai._validate_explanation_order(r)
        self.assertEqual(r.explanation, original, "仅纠错轮触发校验")


if __name__ == "__main__":
    unittest.main()
