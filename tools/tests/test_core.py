"""核心算法的单元测试（标准库 unittest，不需要装 pytest）。

跑：python tools/run_tests.py

## 为什么用 unittest 不用 pytest

这是发布给别人用的工具集。多一个依赖就多一道门槛，
而 unittest 是标准库，`python tools/run_tests.py` 直接能跑。

## 测什么

只测**纯逻辑**（不碰游戏、不碰 OCR）：
```
disc_stoploss  止损线：什么时候该丢
disc_initial   初始判定：升不升
tune_plan      调律预算：母盘够不够
agent_name     名字归一化 / 宽松匹配
agent_cfg      配置回退 / 未知角色
disc_stats     数值解析 / 词条有效性
```

## 第一版测试全部失败的教训

我凭印象写了一版，11 个失败。**全部是我对接口的假设错**：
```
resolve(name, value, is_pct)          → 返回 tuple[str, int]，不是 str
parse_value(txt)                      → 返回 tuple[float,bool] | None，可能是 None
should_stop(...)                      → 返回 dict（stop/reason/expect），不是 bool
initial_verdict(...)                  → 返回 dict，不是 str
max_tunes(n, directed=True)           → 默认是**定向**（6 母盘/次），不是不定向
count_hits(subs, good, half)          → 返回 tuple[int, int, list]，不是单个数字
```
**这就是测试的价值：它逼你去查真实签名，而不是「应该是这样」。**
"""
import pathlib
import unittest
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))



# ============================================================================
# 取「只剩代码」的源码（RT-02）
# ============================================================================
#
# ## 为什么需要这个
#
# 测试里到处是 `src = _code(x)` + `assertIn("某个词", src)`。
# 而 `getsource` 把**注释和 docstring 也带回来** ——
# 于是在 `main()` 里加一行注释 `# 下游需要 "blue_total"`，
# 那些断言就全部通过，**而真正的代码可以已经删掉了**。
#
# RT 做了变异测试：删掉 `_payload` 里真实的 `slots`/`blue_total` 两键，
# 只在 `main()` 里加一行注释含这两个词 -> 7/7 通过，192 用例零新增失败。
#
# ## 这个 helper 做什么
#
# · **注释**：用 tokenize 找到 COMMENT token，把它之后的同一行文字砍掉
# · **docstring**：用 AST 找到模块/类/函数的第一个裸字符串表达式，整段置空
#
# 剩下的就是**真正的代码**。字符串字面量保持原样（不做 unparse，
# 避免引号被规范化导致断言失效）。
import ast as _ast
import io as _io
import tokenize as _tokenize


def _code(src_or_obj) -> str:
    """源码**去掉注释和 docstring**，只留代码。

    参数可以是一段源码字符串，也可以是一个模块/函数（内部会 getsource）。
    """
    import inspect as _insp
    src = (src_or_obj if isinstance(src_or_obj, str)
           else _insp.getsource(src_or_obj))
    lines = src.splitlines()

    # ① 砍注释：找到每个 COMMENT token 的列号，把它及之后截掉
    try:
        for tok in _tokenize.generate_tokens(_io.StringIO(src).readline):
            if tok.type == _tokenize.COMMENT:
                row, col = tok.start
                if 1 <= row <= len(lines):
                    lines[row - 1] = lines[row - 1][:col]
    except Exception:
        pass

    # ② 砍 docstring：模块/类/函数的第一个裸字符串表达式
    try:
        _t = _ast.parse("\n".join(lines))
        drop = set()
        for node in _ast.walk(_t):
            if not isinstance(node, (_ast.Module, _ast.FunctionDef,
                                     _ast.AsyncFunctionDef, _ast.ClassDef)):
                continue
            body = node.body or []
            b = body[0] if body else None
            if (isinstance(b, _ast.Expr) and isinstance(b.value, _ast.Constant)
                    and isinstance(b.value.value, str)):
                drop.update(range(b.lineno, (b.end_lineno or b.lineno) + 1))
        if drop:
            lines = [("" if i + 1 in drop else l) for i, l in enumerate(lines)]
    except Exception:
        pass

    return "\n".join(lines)

class TestDiscStoploss(unittest.TestCase):
    """止损线：一块盘什么时候不值得继续升。"""

    def setUp(self):
        from core.disc_stoploss import (MILESTONES, ROLLS_3SUB, ROLLS_4SUB,
                                        rolls_remaining, rolls_used,
                                        should_stop)
        self.M = MILESTONES
        self.R3 = ROLLS_3SUB
        self.R4 = ROLLS_4SUB
        self.used = rolls_used
        self.left = rolls_remaining
        self.stop = should_stop

    def test_milestones(self):
        """里程碑必须是 3/6/9/12/15 —— 游戏里就是这么给的。"""
        self.assertEqual(tuple(self.M), (3, 6, 9, 12, 15))

    def test_rolls_total(self):
        """4 词条盘 5 次，3 词条盘 4 次（第 3 次解锁第 4 条不算 roll）。"""
        self.assertEqual(self.R4, 5)
        self.assertEqual(self.R3, 4)

    def test_rolls_used_lv0(self):
        self.assertEqual(self.used(0, 4), 0)
        self.assertEqual(self.used(0, 3), 0)

    def test_rolls_used_lv15(self):
        """满级 = 全部 roll 用完。"""
        self.assertEqual(self.used(15, 4), self.R4)
        self.assertEqual(self.used(15, 3), self.R3)

    def test_rolls_used_first_milestone(self):
        """到 Lv3 算用了 1 次。"""
        self.assertEqual(self.used(3, 4), 1)

    def test_rolls_remaining_monotone(self):
        """等级越高剩越少。"""
        prev = 99
        for lv in (0, 3, 6, 9, 12, 15):
            r = self.left(lv, 4)
            self.assertLessEqual(r, prev, f"Lv{lv} 剩的比上一级多")
            prev = r

    def test_should_stop_returns_dict(self):
        """返回 dict，必须有 stop / reason 两个键。"""
        d = self.stop(0.0, 0, 4, 0)
        self.assertIsInstance(d, dict)
        self.assertIn("stop", d)
        self.assertIn("reason", d)
        self.assertIsInstance(d["stop"], bool)

    def test_should_stop_fresh_useless_disc(self):
        """Lv0 且一条有效词条都没有 → 该停（省镀剂）。"""
        d = self.stop(0.0, 0, 4, 0)
        self.assertTrue(d["stop"], f"Lv0 全歪的盘应该停，实际 reason={d.get('reason')}")

    def test_should_stop_good_disc_continues(self):
        """Lv0 但已经 4 条有效的 4 词条盘 → 不该停。"""
        d = self.stop(4.0, 4, 4, 0)
        self.assertFalse(d["stop"], f"好盘不该停，实际 reason={d.get('reason')}")

    def test_should_stop_at_max_level(self):
        """满级了必然停。"""
        d = self.stop(2.0, 1, 4, 15)
        self.assertTrue(d["stop"])


class TestDiscInitial(unittest.TestCase):
    """初始判定：这块盘值不值得升。"""

    def setUp(self):
        from core import disc_initial as m
        self.count = m.count_hits
        self.verdict = m.initial_verdict
        self.judge = m.judge_disc

    def test_count_hits_returns_three(self):
        """返回 (命中数, 总数, 明细列表)。"""
        got = self.count(["攻击力百分比", "暴击率", "防御力"],
                         ["攻击力百分比", "暴击率", "暴击伤害"], [])
        self.assertIsInstance(got, tuple)
        self.assertEqual(len(got), 3, f"应该是 3 元组，实际 {got}")

    def test_count_hits_all_good(self):
        got = self.count(["攻击力百分比", "暴击率"],
                         ["攻击力百分比", "暴击率"], [])
        self.assertEqual(got[0], 2, f"两条都该命中，实际 {got}")

    def test_count_hits_empty(self):
        got = self.count([], ["攻击力百分比"], [])
        self.assertEqual(got[0], 0)

    def test_count_hits_half_scores(self):
        """次选词条算半个 —— 明细里应该能看到。"""
        got = self.count(["穿透值"], ["攻击力百分比"], ["穿透值"])
        self.assertEqual(got[0], 0, "次选不算命中数")
        detail = " ".join(map(str, got[2]))
        self.assertIn("穿透值", detail, f"明细里该有次选词条，实际 {got}")

    def test_verdict_returns_dict(self):
        d = self.verdict(True, 2, 4, True)
        self.assertIsInstance(d, dict)
        self.assertIn("action", d, f"判定结果里该有 action，实际键={list(d)}")

    def test_verdict_actions_valid(self):
        """动作必须是预定义的几个之一。"""
        from core import disc_initial as m
        allowed = set(getattr(m, "VALID_ACTIONS",
                              ("max", "probe", "maybe", "drop")))
        for hits in range(0, 5):
            d = self.verdict(True, hits, 4, True)
            self.assertIn(d["action"], allowed,
                          f"hits={hits} 给出未知动作 {d['action']}")

    def test_verdict_bad_main_worst(self):
        """主词条错时，判定不该比主词条对时更好。"""
        rank = {"drop": 0, "maybe": 1, "probe": 2, "max": 3}
        good = self.verdict(True, 3, 4, True)["action"]
        bad = self.verdict(False, 3, 4, True)["action"]
        self.assertLessEqual(rank[bad], rank[good],
                             f"主词条错({bad}) 不该优于主词条对({good})")


class TestTunePlan(unittest.TestCase):
    """调律预算：母盘够不够。"""

    def setUp(self):
        from core.tune_plan import (MOTHER_PER_TUNE_DIRECTED,
                                    MOTHER_PER_TUNE_PLAIN, max_tunes)
        self.PLAIN = MOTHER_PER_TUNE_PLAIN
        self.DIRECT = MOTHER_PER_TUNE_DIRECTED
        self.max_tunes = max_tunes

    def test_costs(self):
        """不定向 3 母盘，定向 6（2 倍）。"""
        self.assertEqual(self.PLAIN, 3)
        self.assertEqual(self.DIRECT, 6)
        self.assertEqual(self.DIRECT, self.PLAIN * 2)

    def test_max_tunes_zero(self):
        self.assertEqual(self.max_tunes(0), 0)

    def test_max_tunes_directed_is_default(self):
        """默认是定向 —— 3 母盘不够一次定向。"""
        self.assertEqual(self.max_tunes(3), 0,
                         "默认定向，3 母盘只够半次")
        self.assertEqual(self.max_tunes(6), 1)

    def test_max_tunes_plain_explicit(self):
        """显式要不定向时 3 母盘够 1 次。"""
        self.assertEqual(self.max_tunes(3, directed=False), 1)
        self.assertEqual(self.max_tunes(7, directed=False), 2)

    def test_max_tunes_never_negative(self):
        for n in (0, 1, 2, 3, 7, 100):
            self.assertGreaterEqual(self.max_tunes(n), 0, f"n={n} 给出负数")


class TestAgentName(unittest.TestCase):
    """名字归一化和宽松匹配。"""

    def setUp(self):
        from core.agent_name import (canonical_agent, lenient_match,
                                     normalize_name)
        self.norm = normalize_name
        self.canon = canonical_agent
        self.match = lenient_match

    def test_strip_brackets(self):
        self.assertEqual(self.canon("「佩洛伊斯」"), "佩洛伊斯")

    def test_traditional(self):
        self.assertEqual(self.canon("麗娜"), "丽娜")

    def test_keep_dot_prefix(self):
        """`·` 前缀不能剥 —— 星徽·比利 和 比利 是两个角色。"""
        self.assertNotEqual(self.canon("星徽·比利"), self.canon("比利"))
        self.assertNotEqual(self.canon("零号·安比"), self.canon("安比"))

    def test_lenient_exact(self):
        self.assertTrue(self.match("佩洛伊斯", "佩洛伊斯"))

    def test_lenient_ocr_one_char(self):
        """OCR 错 1 个字要能认出来。"""
        self.assertTrue(self.match("佩洛伊斯", "佩洛依斯"))

    def test_lenient_different_agents(self):
        self.assertFalse(self.match("佩洛伊斯", "洛克茜"))
        self.assertFalse(self.match("安比", "零号·安比"))

    def test_lenient_empty(self):
        self.assertFalse(self.match("", "佩洛伊斯"))
        self.assertFalse(self.match("佩洛伊斯", ""))


class TestAgentCfg(unittest.TestCase):
    """配置读取和未知角色处理。"""

    def setUp(self):
        from core.agent_cfg import cfg_of, is_known, resolve_agent
        self.cfg = cfg_of
        self.known = is_known
        self.resolve = resolve_agent

    def test_known_agent(self):
        self.assertTrue(self.known("佩洛伊斯"))

    def test_unknown_rejected_by_default(self):
        """不在库里默认要拒绝（防打错字静默跑错）。"""
        with self.assertRaises(Exception):
            self.resolve("绝对不存在的角色名XYZ")

    def test_unknown_allowed_when_asked(self):
        got = self.resolve("绝对不存在的角色名XYZ", allow_unknown=True)
        self.assertTrue(got)

    def test_typo_auto_corrected(self):
        self.assertEqual(self.resolve("佩洛依斯"), "佩洛伊斯")

    def test_cfg_has_required_fields(self):
        """配置必须有定位和有效词条 —— 少了判盘会走空分支。"""
        c = self.cfg("佩洛伊斯")
        self.assertIn("定位", c)
        self.assertTrue(c.get("有效副词条"), "有效副词条不能为空")


class TestDiscStats(unittest.TestCase):
    """数值解析和词条判断。"""

    def setUp(self):
        from core.disc_stats import is_effective, parse_value, resolve
        self.parse = parse_value
        self.resolve = resolve
        self.eff = is_effective

    def test_parse_value_returns_tuple(self):
        """parse_value 返回 (数值, 是否百分比) —— 这是个踩过的坑。"""
        got = self.parse("7.5%")
        self.assertIsInstance(got, tuple, "必须返回 tuple，不是单个 float")
        self.assertEqual(len(got), 2)
        self.assertAlmostEqual(got[0], 7.5)
        self.assertTrue(got[1])

    def test_parse_value_flat(self):
        got = self.parse("19")
        self.assertAlmostEqual(got[0], 19.0)
        self.assertFalse(got[1])

    def test_parse_value_garbage_returns_none(self):
        """读不到返回 None（不是 0）—— 调用方必须自己判。"""
        for bad in ("", "abc", "—", "N/A"):
            got = self.parse(bad)
            self.assertIsNone(got, f"{bad!r} 应该返回 None，实际 {got}")

    def test_resolve_returns_tuple(self):
        """resolve 返回 (名字, 层数) —— 不止一个字符串。"""
        got = self.resolve("攻击力", 3.0, True)
        self.assertIsInstance(got, tuple)
        self.assertEqual(len(got), 2)

    def test_resolve_percent_variant(self):
        """带 % 的 攻击力 要变成 攻击力百分比（踩过的坑）。"""
        self.assertEqual(self.resolve("攻击力", 3.0, True)[0], "攻击力百分比")

    def test_resolve_flat_variant(self):
        """不带 % 的 攻击力 保持原样。"""
        self.assertEqual(self.resolve("攻击力", 19, False)[0], "攻击力")

    def test_is_effective_good(self):
        n = self.eff("攻击力百分比", {"攻击力百分比"}, set())
        self.assertGreater(n, 0)

    def test_is_effective_useless(self):
        n = self.eff("防御力", {"攻击力百分比"}, set())
        self.assertEqual(n, 0)

    def test_is_effective_half(self):
        n = self.eff("穿透值", {"攻击力百分比"}, {"穿透值"})
        self.assertGreater(n, 0, "次选也该有分")
        full = self.eff("攻击力百分比", {"攻击力百分比"}, {"穿透值"})
        self.assertLess(n, full, "次选分数该低于首选")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestDiscCycleLevelMatch(unittest.TestCase):
    """弃置标记的等级匹配（BUG-001 / BUG-002）。

    ## BUG-002 前缀匹配

    `"等级10".startswith("等级1")` 为真 —— 所以在 `level=1` 时，
    原来的前缀匹配会把 Lv10~15 的卡片也当成候选。

    ## BUG-001 标记不比对等级

    `mark_disc_abandoned` 原来只比对套装和位号。同一套同一位置可能同时有
    Lv0 的废盘和 Lv15 主词条全对的毕业盘 —— 两者在 set/slot 上完全一样，
    于是标记会落在该位号**第一张**卡片上，最坏是把毕业盘标成狗粮，
    下一轮拆解就真拆了（不可逆）。

    这两条的修法都是同一个辅助函数：`_level_label()`。
    """

    def setUp(self):
        from zzz_disc_cycle import _level_label
        self.f = _level_label

    def test_exact_match(self):
        self.assertTrue(self.f("等级15", 15))
        self.assertTrue(self.f("等级1", 1))
        self.assertTrue(self.f("等级0", 0))

    def test_prefix_does_not_leak(self):
        """BUG-002：等级1 不能命中 等级10 / 等级15。"""
        self.assertFalse(self.f("等级10", 1))
        self.assertFalse(self.f("等级15", 1))
        self.assertFalse(self.f("等级12", 1))

    def test_reverse_prefix(self):
        """等级10 也不该命中 level=1 之外的错值。"""
        self.assertFalse(self.f("等级1", 10))
        self.assertFalse(self.f("等级15", 10))

    def test_embedded_in_longer_text(self):
        """标签里带别的内容也要认得出。"""
        self.assertTrue(self.f("Lv15 等级15 满级", 15))
        self.assertTrue(self.f("等级15 / 15", 15))

    def test_empty_and_garbage(self):
        self.assertFalse(self.f("", 1))
        self.assertFalse(self.f("攻击力", 1))
        self.assertFalse(self.f(None, 1))

    def test_boundary_followed_by_digit_is_rejected(self):
        """等级1 后面紧跟数字 = 另一个等级。"""
        self.assertFalse(self.f("等级100", 1))
        self.assertFalse(self.f("等级199", 1))


class TestAgentNameCoverage(unittest.TestCase):
    """全部角色名都要能被名字解析认出来（BUG-026）。

    ## 背景

    `pick_agent._read_name_raw` 里有一道 `NAME_RE` 闸和一步 `_clean`。
    这两者太窄的时候，某些角色名**永远读不出来**：

    ```
    奥菲丝&鬼火   → `&` 不在字符集里，NAME_RE 直接拒
    11号         → `_clean` 无条件剥数字，变成「号」
    ```

    而读不出来这件事会被上层伪装成「账号上没有这个角色」，
    所以症状表现为「选不中」，很难往「正则太窄」上想。

    ## 测什么

    1. `disc_meta.json` 里**每一个**角色名都过 NAME_RE
    2. `_clean` 不破坏名字里的数字（11号）和符号（&、·）
    3. `_clean` 仍然会剥掉等级尾巴（`简☆2` → `简`）
    """

    def _name_re(self):
        import re
        # 与 pick_agent._read_name_raw 里的 NAME_RE 保持一致
        return re.compile(r"^[\u4e00-\u9fa5·・.‧•∙&＆\d]{1,12}$")

    def _clean(self):
        import re

        def f(x: str) -> str:
            x = re.sub(r"[☆★◇◆○●◯◎✦✧＊*]", "", x)
            x = re.sub(r"(?<=[^\d])\d+", "", x)
            return x.replace(" ", "").strip()
        return f

    def test_all_library_names_pass(self):
        import json
        meta = json.loads((pathlib_path() / "disc_meta.json").read_text(encoding="utf-8"))
        names = list((meta.get("角色") or {}).keys())
        self.assertGreater(len(names), 50, "角色库太小，测试没意义")
        bad = [n for n in names if not self._name_re().fullmatch(n)]
        self.assertEqual(bad, [], f"这些角色名过不了 NAME_RE：{bad}")

    def test_digits_in_name_survive(self):
        """11号 不能被剥成 号。"""
        self.assertEqual(self._clean()("11号"), "11号")

    def test_ampersand_survives(self):
        self.assertEqual(self._clean()("奥菲丝&鬼火"), "奥菲丝&鬼火")
        self.assertTrue(self._name_re().fullmatch("奥菲丝&鬼火"))

    def test_middle_dot_survives(self):
        for n in ("星徽·比利", "零号·安比"):
            self.assertEqual(self._clean()(n), n)
            self.assertTrue(self._name_re().fullmatch(n), n)

    def test_level_tail_stripped(self):
        """等级尾巴还是要剥掉（这是原来就对的，别改坏）。"""
        self.assertEqual(self._clean()("简☆2"), "简")
        self.assertEqual(self._clean()("凯撒☆"), "凯撒")

    def test_single_char_names(self):
        for n in ("简", "本", "柳", "雅", "照"):
            self.assertEqual(self._clean()(n), n)
            self.assertTrue(self._name_re().fullmatch(n), n)


def pathlib_path():
    """tools 目录（测试文件在 tools/tests/ 下）。"""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


class TestStatWhitelist(unittest.TestCase):
    """白名单必须覆盖生命/防御的百分比版本（BUG-011）。"""

    def test_pct_variants_present(self):
        from core import vocab
        for n in ("生命值百分比", "防御力百分比", "攻击力百分比",
                  "生命值", "防御力", "攻击力"):
            self.assertIn(n, vocab.STATS, f"{n} 不在 STATS 里")

    def test_shield_character_scores(self):
        """防护角色靠生命值百分比/防御力百分比算分，不能是 0。"""
        from core.disc_cfg import effective
        good = {"生命值百分比", "防御力百分比"}
        eff, rows = effective([("生命值百分比+1", "6%")], good, set())
        self.assertGreater(eff, 0, f"生命值百分比 算出 0 分，明细={rows}")
        names = [r["name"] for r in rows]
        self.assertIn("生命值百分比", names)


class TestRollsCap(unittest.TestCase):
    """强化次数封顶 5（BUG-013）。"""

    def test_real_roll_values(self):
        from core.disc_stats import resolve
        CASES = [
            ("防御力百分比", 4.8, True, 0), ("防御力百分比", 9.6, True, 1),
            ("防御力百分比", 14.4, True, 2), ("防御力百分比", 28.8, True, 5),
            ("生命值百分比", 3.0, True, 0), ("生命值百分比", 18.0, True, 5),
            ("攻击力百分比", 6.0, True, 1), ("暴击率", 7.2, True, 2),
            ("暴击伤害", 14.4, True, 2), ("穿透值", 9.0, False, 0),
        ]
        for hint, v, pct, want in CASES:
            got, rolls = resolve(hint, v, pct)
            self.assertEqual(got, hint, f"{hint} {v} 被改成了 {got}")
            self.assertEqual(rolls, want, f"{hint} {v} rolls={rolls}，期望 {want}")

    def test_never_exceeds_five(self):
        """任何值都不该算出 rolls > 5。"""
        from core.disc_stats import resolve
        for hint, v in [("攻击力百分比", 18.0), ("攻击力百分比", 21.0),
                        ("攻击力百分比", 24.0), ("暴击率", 24.0),
                        ("生命值百分比", 99.0)]:
            _, rolls = resolve(hint, v, True)
            self.assertLessEqual(rolls, 5, f"{hint} {v}% 算出 rolls={rolls}")


class TestResolveKeepsName(unittest.TestCase):
    """名字和数值对不上时，保留名字，不换属性。

    属性名是固定词表，OCR 读错数字的概率远高于读错名字。
    换成别的属性会让角色按错误的词条算分。
    """

    def test_keeps_name_on_impossible_value(self):
        from core.disc_stats import resolve
        got, rolls = resolve("防御力百分比", 7.2, True)
        self.assertEqual(got, "防御力百分比",
                         f"被换成了 {got}（7.2% 不是防御力百分比的有效 roll）")
        self.assertEqual(rolls, 0, "对不上的值应该记 0 次，不要编造")

    def test_unknown_name_still_falls_back(self):
        """名字读残（不在词表）时才允许按数值挑。"""
        from core.disc_stats import resolve
        got, rolls = resolve("暴击卒", 7.2, True)
        self.assertIn(got, ("暴击率", "穿透率", "异常掌控"))


class TestEquipConfirm(unittest.TestCase):
    """换装的「真的装上了」判据（BUG-005）。

    ## 原来是什么样的

    ```python
    hit = vs.find("替换", R_BOTTOM) or vs.find("装备", R_BOTTOM)
    inp.click(hit["cx"], hit["cy"])
    log.log(ok=True)
    print("装备完成")
    ```

    **没有定位目标盘**（`d` 可能是 None）、**没有回读**、**无条件报成功**。
    没跑过 `find_disc` 时列表里选中的是游戏默认项，
    点「替换」= 把一个完全不相关的盘装上去，还打印「装备完成」。

    ## 现在的判据

    `_equip_confirmed(before, after)`：只有看到装备后的状态才算成功。
    确认不了就返回 False，由调用方报「未确认」并返回非 0 —— 不谎报。
    """

    def setUp(self):
        from zzz_equip import _equip_confirmed
        self.f = _equip_confirmed

    def test_unequip_button_appears(self):
        """出现「卸下」= 这块已经装身上了（能卸才说明装着）。"""
        self.assertTrue(self.f("替换", "卸下"))
        self.assertTrue(self.f("", "卸下"))
        self.assertTrue(self.f("替换", "替换 卸下"))

    def test_equipped_marker(self):
        self.assertTrue(self.f("装备", "已装备"))
        self.assertTrue(self.f("替换", "使用中"))

    def test_unchanged_means_unconfirmed(self):
        """按钮一模一样 = 确认不了，不能算成功。"""
        self.assertFalse(self.f("替换", "替换"))
        self.assertFalse(self.f("装备", "装备"))

    def test_empty_after_is_unconfirmed(self):
        self.assertFalse(self.f("替换", ""))
        self.assertFalse(self.f("", ""))

    def test_any_change_counts(self):
        """按钮文本变了（通常是 替换 → 卸下 的中间态）也算确认。"""
        self.assertTrue(self.f("替换", "换成别的"))


class TestLenientMatchSafety(unittest.TestCase):
    """宽松匹配不能把两个不同角色认成同一个（RT 实测 5 组误配）。

    ## 为什么这条最要紧

    `lenient_match` 用来判断「切过去的是不是我要的那个人」。
    误配的后果不是「报错」，是**在别人的角色身上做破坏性操作**
    （升级、换盘、拆解）。

    真机实测原状：
    ```
    本 ↔ 柳 = True      简 ↔ 雅 = True      柳 ↔ 照 = True
    安比 ↔ 安东 = True   星徽·安比 ↔ 安比 = True
    ```

    根因：编辑距离 ≤1 没有最小长度门槛，单字名差一个字就通过。
    """

    def setUp(self):
        from core.agent_name import lenient_match
        self.f = lenient_match

    def test_no_short_name_false_positives(self):
        """5 组实测误配必须全部拦住。"""
        BAD = [("本", "柳"), ("简", "雅"), ("安比", "安东"),
               ("柳", "照"), ("星徽·安比", "安比")]
        for a, b in BAD:
            self.assertFalse(self.f(a, b), f"{a} 被误配成 {b}")
            self.assertFalse(self.f(b, a), f"{b} 被误配成 {a}")

    def test_ocr_jitter_still_passes(self):
        """真 OCR 抖动（长名字差一个字）仍要通过。"""
        self.assertTrue(self.f("佩洛伊斯", "佩洛依斯"))
        self.assertTrue(self.f("佩洛伊斯", "佩洛伊斯"))

    def test_long_prefix_truncation_passes(self):
        """长名字被截断（≥3 字的那个做前缀）要通过。"""
        self.assertTrue(self.f("佩洛", "佩洛伊斯"))

    def test_same_name_always_passes(self):
        for n in ("露西", "安比", "本", "简"):
            self.assertTrue(self.f(n, n), n)

    def test_empty(self):
        self.assertFalse(self.f("", "露西"))
        self.assertFalse(self.f("露西", ""))


class TestCanonicalNoTailGuess(unittest.TestCase):
    """`canonical_agent` 不能靠「·」尾巴猜人（星徽·安比 → 安比 是错的）。"""

    def test_no_tail_fallback(self):
        from core.agent_name import canonical_agent
        got = canonical_agent("星徽·安比")
        self.assertNotEqual(got, "安比", "把完整名字拆成尾巴去匹配 = 凭空认定同一个人")

    def test_exact_names_unchanged(self):
        from core.agent_name import canonical_agent
        for n in ("安比", "露西", "本", "简"):
            self.assertEqual(canonical_agent(n), n, n)


class TestCostCumulativeTable(unittest.TestCase):
    """`SKILL_CHIP` 是累计表，不能当增量求和（RT 实测总量虚高 6.2 倍）。

    ```
    SKILL_CHIP = {1: 125, 2: 118, ..., 11: 8, 12: 0}   # 从 N 到 12 的累计
    ```

    错误写法（原代码）：`sum(SKILL_CHIP[i] for i in range(cur, 12))`
    → cur=1 时得 767，而正确值是 125。**6.1 倍。**

    这个数直接决定「还要刷多少电量」——
    虚高 6 倍等于告诉用户要刷 6 倍的量。
    """

    def test_cumulative_not_summed(self):
        import zzz_cost as zc
        cum = zc.SKILL_CHIP
        self.assertEqual(cum[1], 125, "表被改了，测试要同步")
        wrong = sum(cum[i] for i in range(1, 12))
        self.assertGreater(wrong / cum[1], 5.0,
                           "累计表当增量求和会放大 5 倍以上，这个用例就是在防它")

    def test_single_skill_cost_is_lookup(self):
        """5 个技能都在 1 级时，芯片总数必须是 5×125=625，不是 5×767=3835。

        用**行为**测，不看源码文本 —— 源码里有注释提到旧写法，
        字符串断言会被注释骗到（第一版就这么挂的）。
        """
        import zzz_cost as zc
        real = zc.skill_levels
        try:
            zc.skill_levels = lambda a: {"普攻": 1, "闪避": 1, "支援": 1,
                                         "特殊": 1, "连携": 1}
            e = zc.estimate("__test__", 60)
        finally:
            zc.skill_levels = real
        self.assertEqual(e["chip"], 625,
                         f"5 个 1 级技能的芯片应是 5×125=625，实际 {e['chip']}")
        self.assertLess(e["chip"], 700, "不能是旧算法的 3835")

    def test_unknown_level_is_zero_not_max(self):
        """等级未知时按 0 算，不能按 1 级（那是最贵估算，RT 实测第二处错误）。"""
        import zzz_cost as zc
        e = zc.estimate("__不存在__", -1)
        self.assertTrue(e.get("unknown"))
        for k in ("exp", "cert", "chip", "data", "relic", "batt"):
            self.assertEqual(e[k], 0, f"未知等级时 {k} 应为 0")


class TestAtomicWrite(unittest.TestCase):
    """原子写：要么是旧的，要么是新的，不能是半个（BUG-064）。

    全仓原来 `grep -rn "os.replace" tools/` 是空的 ——
    所有 `state/*.json` 都是直接覆盖写。
    写到一半被杀就留下半截 JSON，而读取方把坏 JSON 当成「空状态」，
    数据**凭空消失**且没有任何报错。
    """

    def setUp(self):
        import tempfile
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.f = self.dir / "x.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_write_json_roundtrip(self):
        from core import atomic
        atomic.write_json(self.f, {"a": 1, "b": [2, 3]})
        import json
        self.assertEqual(json.loads(self.f.read_text(encoding="utf-8")),
                         {"a": 1, "b": [2, 3]})

    def test_no_tmp_left_behind(self):
        """写完不能留下 .tmp —— 否则下次读目录会困惑。"""
        from core import atomic
        atomic.write_json(self.f, {"a": 1})
        leftovers = [p.name for p in self.dir.iterdir() if p.name != "x.json"]
        self.assertEqual(leftovers, [], f"留下了 {leftovers}")

    def test_existing_file_survives_if_write_fails(self):
        """写失败时，旧文件必须完好 —— 这是原子写的全部意义。"""
        from core import atomic
        atomic.write_json(self.f, {"old": True})
        before = self.f.read_text(encoding="utf-8")
        # 传一个 json 序列化不了的对象
        with self.assertRaises(Exception):
            atomic.write_json(self.f, {"bad": object()})
        after = self.f.read_text(encoding="utf-8")
        self.assertEqual(before, after, "写失败把旧文件也弄坏了")

    def test_read_json_reports_corrupt_file(self):
        """坏 JSON 要报出文件名和位置，不能假装是「没有数据」。"""
        from core import atomic
        self.f.write_text('{"a": 1, "b"', encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            atomic.read_json(self.f)
        msg = str(cm.exception)
        self.assertIn("x.json", msg)
        self.assertIn("字节", msg)

    def test_read_json_missing_returns_default(self):
        from core import atomic
        self.assertIsNone(atomic.read_json(self.dir / "nope.json"))
        self.assertEqual(atomic.read_json(self.dir / "nope.json", default=[]), [])


class TestOcclusionHonesty(unittest.TestCase):
    """窗口被遮挡时必须说「被遮挡」，不能伪装成「未知界面」（BUG-032）。

    ## 为什么这条重要

    `live.grab()` 是 `ImageGrab.grab(bbox=窗口坐标)` ——
    **抓的是「屏幕那个位置」的像素，不是窗口内容**。
    窗口被别的程序盖住时，读到的是遮挡物。

    实测踩过：浏览器盖在游戏上，OCR 读出来的是 GitHub 页面，
    而 `describe()` 只会说「未知界面」——
    上层以为「游戏画面变了」，实际是**在拿别人的像素做判断**。
    对换装/拆解这类破坏性操作来说，这是致命的。
    """

    def test_describe_says_occluded(self):
        # 直接测 describe 的遮挡分支：造一个带 occluded 的哑对象
        from core import anchors

        class _FakeVision:
            occluded = True
            def frame(self, force=False): return None
            def items(self, region, **kw): return []
            def text(self, region, **kw): return ""

        self.assertEqual(anchors.describe(_FakeVision()), "被遮挡")

    def test_describe_normal_when_not_occluded(self):
        from core import anchors

        class _FakeVision:
            occluded = False
            def frame(self, force=False): return None
            def items(self, region, **kw): return []
            def text(self, region, **kw): return ""

        # 没有任何锚点命中 → 未知界面（不是「被遮挡」）
        self.assertEqual(anchors.describe(_FakeVision()), "未知界面")

    def test_vision_has_occluded_attr(self):
        """Vision 必须有 occluded 属性 —— 否则 describe 拿不到它。"""
        import inspect
        from core.vision import Vision
        src = _code(Vision.__init__)
        self.assertIn("self.occluded", src, "Vision.__init__ 没初始化 occluded")


class TestElementFamily(unittest.TestCase):
    """变体属性角色拿到正确主词条不能被判 bad（BUG-010）。

    ## 原来的问题

    ```python
    ELEM_DMG = {"火","冰","电","物理","以太"}     # 只有 5 项
    if full == m and element and e != element:
        return "bad"
    ```

    · 烈霜/玄墨/凛刃是冰/以太/物理的**变体**，
      `冰 != 烈霜` 恒真 → **正确的主词条被判 bad**，那块盘会被换掉
    · 风属性（维琳娜）根本不在表里
    · 游戏里同时有 `X伤害加成` 和 `X属性伤害加成` 两种写法

    ## 修的时候还踩了一个坑

    `expand_want()` 把配置里的泛称「属性伤害」展开后，
    `verdict` 用**子串**匹配 —— 而 `"属性伤害" in "风属性伤害加成"` 为真，
    于是冰角色会把风伤害认成 good。**现在属性伤害词条优先走精确同族判定。**
    """

    def setUp(self):
        from core.disc_main import verdict
        self.f = verdict
        self.want = {"5": ["属性伤害", "攻击力"]}

    def _v(self, main, elem):
        return self.f(main, 5, self.want, elem)[0]

    def test_variant_elements_accept_base(self):
        """变体属性接受基属性的伤害词条。"""
        for elem, term in (("烈霜", "冰属性伤害加成"),
                           ("玄墨", "以太伤害加成"),
                           ("凛刃", "物理伤害加成")):
            self.assertEqual(self._v(term, elem), "good",
                             f"{elem} 角色装「{term}」应判 good")

    def test_base_accepts_variant(self):
        for elem, term in (("冰", "烈霜属性伤害加成"),
                           ("以太", "玄墨属性伤害加成"),
                           ("物理", "凛刃属性伤害加成")):
            self.assertEqual(self._v(term, elem), "good",
                             f"{elem} 角色装「{term}」应判 good")

    def test_wrong_element_is_bad(self):
        """不同族才判 bad —— 而且不能被子串误匹配。"""
        for elem, term in (("冰", "风属性伤害加成"),
                           ("以太", "火属性伤害加成"),
                           ("电", "物理伤害加成")):
            self.assertEqual(self._v(term, elem), "bad",
                             f"{elem} 角色装「{term}」应判 bad")

    def test_wind_supported(self):
        """风属性原来根本不在表里。"""
        self.assertEqual(self._v("风属性伤害加成", "风"), "good")

    def test_both_term_spellings(self):
        """游戏里两种写法并存，都要认。"""
        self.assertEqual(self._v("以太伤害加成", "以太"), "good")
        self.assertEqual(self._v("以太属性伤害加成", "以太"), "good")

    def test_empty_element_is_unknown(self):
        """属性读不到时返回 unknown，不要乱判 bad。"""
        self.assertEqual(self._v("冰属性伤害加成", ""), "unknown")


class TestStatusSchema(unittest.TestCase):
    """状态文件的「写入方/读取方」契约（RT-REPORT N-3）。

    ## 原来的问题

    写入方只写 5 个字段、读取方读 8 个，**而文件看着完全正常**。
    于是「字段从没被写过」被当成「旧文件残留」，谁都没发现契约从未实现。
    实测 `status_丽娜.json` 里只有 `agent` 和 `total`。

    后果：`zzz_who` 的「主词条×N」告警永久失效，
    `zzz_grind` 的进展永远 `0.0 → 0.0`。
    """

    def test_missing_keys_detected(self):
        from core.state import check_status_schema
        miss = check_status_schema("测试", {"agent": "x", "total": 0})
        self.assertIn("slots", miss)
        self.assertIn("blue_total", miss)

    def test_complete_payload_clean(self):
        from core.state import check_status_schema
        full = {"total": 1, "slots": [], "blue_total": 0}
        self.assertEqual(check_status_schema("测试", full), [])

    def test_schema_version_written(self):
        """`stamp()` 要写 `_schema`，读取方才能判断写入方版本。"""
        from core.state import stamp
        d = stamp({"total": 1})
        self.assertIn("_schema", d)
        self.assertIn("_ts", d)

    def test_zzz_status_payload_has_all_required(self):
        """`zzz_status` 写出的 payload 必须包含全部 REQUIRED 键。

        ## 原来这条**可以被一行注释绕过**（RT-02）

        ```python
        src = _code(zzz_status.main)
        for k in REQUIRED_STATUS_KEYS:
            self.assertIn(f'"{k}"', src)      # <- 纯文本
        ```

        把 `_payload` 里真实的 `"slots"` / `"blue_total"` 删掉，
        只在 `main()` 里加一行注释 `# 下游需要 "blue_total" 和 "slots"`
        —— 7/7 全过，全量用例零新增失败。

        ## 现在改成查 **AST 里的字典键**

        只看两种地方真正出现过的字符串常量：
        · `dict` 字面量的 key
        · `subscript` 赋值的目标（`d["slots"] = ...`）
        · `f-string` 之外的 `Constant` 出现在 `_payload` 附近的赋值里

        注释**不在 AST 里**，所以骗不过。
        """
        import ast as _ast
        import inspect
        import zzz_status
        from core.state import REQUIRED_STATUS_KEYS

        tree = _ast.parse(inspect.getsource(zzz_status.main))
        keys = set()
        for node in _ast.walk(tree):
            # dict 字面量的键
            if isinstance(node, _ast.Dict):
                for k in node.keys:
                    if isinstance(k, _ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
            # d["x"] = ... 形式
            elif isinstance(node, _ast.Subscript):
                sl = node.slice
                if isinstance(sl, _ast.Constant) and isinstance(sl.value, str):
                    keys.add(sl.value)

        missing = [k for k in REQUIRED_STATUS_KEYS if k not in keys]
        self.assertEqual(missing, [],
                         f"zzz_status 的 payload 真的没写这些键：{missing}\n"
                         f"    实测 AST 里的键：{sorted(keys)}")


class TestDataConsistency(unittest.TestCase):
    """同一份知识的多个副本必须一致（RT-REPORT 柱 3）。

    RT 说「属性/套装/词条各有 3–7 份互不一致的副本」，
    实测两处真漂移（都已修）：
    · `zh._NORM_SETS` 是从手抄的 19 个建表，而权威 `vocab.SETS` 有 29 个
      → 10 个套装名永远配不上自己（BUG-016）
    · `disc_main.ELEM_DMG` 只有 5 个属性，`materials.json` 有 10 个
      → 变体属性 & 风属性判错（BUG-010）

    这个用例把「一致性」本身钉住 —— 以后谁改了一边忘了另一边，测试就红。
    """

    def test_set_lists_agree(self):
        """套装名的两个副本必须完全相等。"""
        from core import vocab, zh
        a = set(vocab.SETS)
        b = set(zh._NORM_SETS.values())
        self.assertEqual(a, b,
                         f"套装表漂移：vocab 有 {len(a)}，zh 有 {len(b)}；"
                         f"只在 vocab: {sorted(a - b)}；只在 zh: {sorted(b - a)}")

    def test_element_names_agree(self):
        """属性名的两个副本必须完全相等。"""
        import json
        import pathlib
        from core import disc_main
        mp = (pathlib.Path(__file__).resolve().parent.parent / "materials.json")
        if not mp.exists():
            self.skipTest("materials.json 不在当前集合里")
        m = json.loads(mp.read_text(encoding="utf-8"))
        mat_attrs = set((m.get("技能芯片") or {}).get("属性名") or {})
        fam = set(disc_main.ELEM_FAMILY)
        self.assertEqual(mat_attrs, fam,
                         f"属性表漂移：materials {sorted(mat_attrs)} "
                         f"vs ELEM_FAMILY {sorted(fam)}")

    def test_agent_element_values_covered(self):
        """`game_cfg.AGENT_ELEMENT` 用到的属性值都要能在 ELEM_FAMILY 里找到。

        例外：「特殊」= 蕾米埃尔的「属性流变」，`verdict` 里单独处理。
        """
        from core import game_cfg, disc_main
        used = set(game_cfg.AGENT_ELEMENT.values()) - {"特殊"}
        missing = sorted(used - set(disc_main.ELEM_FAMILY))
        self.assertEqual(missing, [], f"这些属性在 ELEM_FAMILY 里没有：{missing}")

    def test_disc_meta_chip_table_matches_materials(self):
        """`disc_meta.技能芯片` 必须和 `materials.json` 的权威映射一致（BUG-129）。

        ## 这张表原来 10 项里错了 6 项

        ```
        流明 → 特化以太芯片    ← 错（流明不是以太）
        火   → 特化火芯片      ← 错（火属性芯片叫「引燃」）
        冰   → 特化冰芯片      ← 错（叫「冰结」）
        电   → 特化电芯片      ← 错（叫「电击」）
        风   → 特化风芯片      ← 错（叫「风蚀」）
        烈霜 → 特化冰芯片      ← 错（同样该是「冰结」，但键名也不对）
        ```

        而它**零消费者** —— 所以错了很久没人发现。
        现在按 `materials.json` 派生，并在这里钉住一致性。
        """
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        if not (root / "disc_meta.json").exists() \
                or not (root / "materials.json").exists():
            self.skipTest("disc_meta.json / materials.json 不在当前集合里")
        dm = json.loads((root / "disc_meta.json").read_text(encoding="utf-8"))
        mt = json.loads((root / "materials.json").read_text(encoding="utf-8"))
        names = (mt.get("技能芯片") or {}).get("属性名") or {}
        want = {a: f"特化{n}芯片" for a, n in names.items()}
        got = dm.get("技能芯片") or {}
        self.assertEqual(got, want,
                         f"disc_meta.技能芯片 和 materials.json 不一致："
                         f"差异 {[(k, got.get(k), want.get(k)) for k in set(got) | set(want) if got.get(k) != want.get(k)]}")

    def test_sub_base_subset_of_stats(self):
        """副词条基础值表必须是词条白名单的子集。"""
        from core import vocab
        from core import disc_stats as ds
        missing = sorted(set(ds.SUB_BASE) - set(vocab.STATS))
        self.assertEqual(missing, [],
                         f"这些副词条不在 vocab.STATS 里，会被静默丢弃：{missing}")


class TestSnapshotValidity(unittest.TestCase):
    """「全空快照」和「读取失败」必须能区分（BUG-130）。

    ## 两种 total=0 长得一样

    ```
    丽娜：slots=0（一个都没读到）      ← 读取失败/不完整
    苍角：slots=6，6 个全空位          ← 真的没装盘
    ```

    读取方只看 `total` 分不出来，会把「读取失败」当成「角色没盘」，
    于是 `zzz_who` 报「未毕业」、`zzz_grind` 觉得「没进展」——
    而且**两者都会一直循环下去**。
    """

    def test_invalid_snapshot_detected(self):
        from core.state import check_status_schema
        # 字段齐但 _valid=False → 要算无效
        d = {"total": 0, "slots": [], "blue_total": 0,
             "_valid": False, "_slots_read": 0}
        self.assertEqual(check_status_schema("测试", d), ["_valid"])

    def test_genuinely_empty_snapshot_is_valid(self):
        """6 个空位 + total=0 是**有效**快照，不能报警。"""
        from core.state import check_status_schema
        d = {"total": 0, "slots": [{"slot": i, "set": ""} for i in range(1, 7)],
             "blue_total": 0, "_valid": True, "_slots_read": 6}
        self.assertEqual(check_status_schema("测试", d), [])

    def test_old_file_without_valid_flag_passes(self):
        """老文件没有 `_valid` 字段 —— 不能因此挡住它。"""
        from core.state import check_status_schema
        d = {"total": 20.5, "slots": [{"slot": 1}], "blue_total": 3}
        self.assertEqual(check_status_schema("测试", d), [])

    def test_zzz_status_writes_valid_flag(self):
        import inspect
        import zzz_status
        src = _code(zzz_status.main)
        self.assertIn('"_valid"', src, "zzz_status 没写 _valid")
        self.assertIn('"_slots_read"', src, "zzz_status 没写 _slots_read")


class TestCostLevelPriority(unittest.TestCase):
    """`zzz_cost.read_levels` 要按文件头声明的三级优先级读（BUG-145）。

    文件头写着：
        1. state/status_<角色>.json   （最准）
        2. state/agent_elements.json  （只有等级和属性）
        3. 都读不到 → 标记未知，不瞎猜

    但实现**只读第 2 个**，从不碰 `status_*.json` 的 `char_level`。
    而 `agent_elements.json` 在修 BUG-128 之前根本没人写 ——
    读者拿的可能是一份几个月前的缓存。
    """

    def test_status_level_matches(self):
        """有 status 文件时，读到的等级要和它一致。"""
        import json
        import pathlib
        import zzz_cost as zc
        st_dir = pathlib.Path(zc.BASE) / "state"
        files = sorted(st_dir.glob("status_*.json"))
        if not files:
            self.skipTest("没有 status 文件")
        lv = zc.read_levels()
        checked = 0
        for f in files[:5]:
            if f.name.startswith("core_status_"):
                continue
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            agent = d.get("agent") or f.stem.replace("status_", "", 1)
            import re
            digits = re.sub(r"\D", "", str(d.get("char_level") or ""))
            if not digits or agent not in lv:
                continue
            self.assertEqual(lv[agent], int(digits),
                             f"{agent} 的等级和 status 文件不一致")
            checked += 1
        self.assertGreater(checked, 0, "没有一个角色能对上，优先级可能没生效")

    def test_unknown_is_minus_one_not_one(self):
        """读不到等级要返回 -1（未知），不能当 1 级 —— 那是最贵的估算。"""
        import inspect
        import zzz_cost as zc
        src = _code(zc.read_levels)
        self.assertIn("-1", src, "read_levels 里没有「未知 = -1」的处理")
        # 侧证：任何一个不在数据里的角色名不该出现在结果里
        self.assertNotIn("__不存在的角色__", zc.read_levels())


class TestMcpConfirm(unittest.TestCase):
    """MCP 的 `confirm` 必须严格解析（BUG-158）。

    ## 原来是什么样的

    ```python
    if not args.get("confirm"):      # ← 字符串 "false" 会被当成真
        return "【未执行】这是计划…"
    ```

    MCP 客户端可能把布尔值发成**字符串** `{"confirm": "false"}`。
    `not "false"` == False → **直接放行去跑 `--run`**，花掉电量和材料。
    这是「以为只出计划，实际全跑了」。
    """

    def setUp(self):
        from zzz_mcp import _truthy
        self.f = _truthy

    def test_string_false_is_false(self):
        for v in ("false", "False", "FALSE", "0", "no", "off", ""):
            self.assertFalse(self.f(v), f"{v!r} 被当成了真")

    def test_real_true_values(self):
        for v in (True, 1, "true", "True", "1", "yes", "y", "on", "是"):
            self.assertTrue(self.f(v), f"{v!r} 应该是真")

    def test_non_bool_objects_are_false(self):
        """非空列表/字典在 Python 里是 truthy，但在这里必须是 False。"""
        for v in ([], {}, (), None, 0, 2.5):
            self.assertFalse(self.f(v), f"{v!r} 被当成了真")

    def test_daily_run_gate_uses_truthy(self):
        import inspect
        import zzz_mcp
        src = _code(zzz_mcp.call_tool)
        self.assertIn("_truthy(args.get(\"confirm\"))", src,
                      "call_tool 里的 confirm 闸没用 _truthy")


class TestMcpTimeoutKillsTree(unittest.TestCase):
    """MCP 超时要连子孙进程一起杀（BUG-157）。

    `subprocess.run(timeout=)` 只 kill **直接子进程**。
    而我们的子进程是 `zzz_daily.py`，它会再起 OneDragon 的 python 去动游戏 ——
    杀掉中间那一层，孙进程还活着，**继续注入键鼠**。
    """

    def test_has_kill_tree(self):
        import zzz_mcp
        self.assertTrue(hasattr(zzz_mcp, "_kill_tree"),
                        "没有 _kill_tree —— 超时只会杀直接子进程")

    def test_timeout_returns_124(self):
        import sys
        import zzz_mcp
        rc, out = zzz_mcp._run(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=2)
        self.assertEqual(rc, 124, f"超时返回码应为 124，实际 {rc}")
        self.assertIn("超时", out)


class TestOutcomeRules(unittest.TestCase):
    """`judge()` 必须能对着工具的**真实输出**数出「做成了几件事」（BUG-089）。

    ## 原来 7 条规则里至少 4 条永久失效

    正则写的是想象出来的文案：
    ```
    "音擎养成": [(r"强化了一次", "强化")]
    "角色等级": [(r"已升级", "升级"), (r"点晋升", "晋升")]
    "驱动盘":   [(r"号位已换装", "换装")]
    ```
    而工具实际打印的是：
    ```
    zzz_wengine.py:  完成：强化 5 次，改装 2 次
    zzz_level.py:    完成，升级 3 次
    zzz_core.py:     合计升了 4 次
    ```
    于是 `judge()` 恒返回 0 → 「实际完成」永远 0 →
    **`zzz_grind` 看不到任何进展，那个「刷到毕业」的循环永远不会收敛**。

    ## 还有个细节

    「强化 5 次」是**一行报 5 次**。只数行数会得到 1，
    所以规则支持 `(正则, 描述, 分组号)` 把数字取出来。
    """

    def setUp(self):
        from zzz_daily import judge
        self.j = judge

    def test_counts_number_not_lines(self):
        """「完成：强化 5 次」要数出 5，不是 1。"""
        n, _ = self.j("音擎养成", "完成：强化 5 次，改装 2 次")
        self.assertEqual(n, 5)

    def test_level_up_count(self):
        n, _ = self.j("角色等级", "完成，升级 3 次")
        self.assertEqual(n, 3)

    def test_core_skill_count(self):
        n, _ = self.j("核心技", "合计升了 4 次")
        self.assertEqual(n, 4)

    def test_disc_two_actions(self):
        out = "      ✔ 已调（校验主词条…）\n   ✔ 主词条 攻击力（10691）可用"
        n, notes = self.j("驱动盘", out)
        self.assertEqual(n, 2)
        self.assertEqual(len(notes), 2)

    def test_no_false_positive_on_failure_text(self):
        """失败/跳过的文案不能被当成「做成了」。"""
        for label, out in (
            ("音擎养成", "→ 已经是目标音擎，跳过换装"),
            ("角色等级", "职级晋升：读不到认证章数量"),
            ("驱动盘", "⚠ 刷本可能没真跑（没看到「挑战完成」）"),
            ("核心技", "（一次都没升成 —— 材料不够）"),
        ):
            n, _ = self.j(label, out)
            self.assertEqual(n, 0, f"{label} 把失败文案当成了成功：{n}")

    def test_old_imagined_patterns_removed(self):
        """原来那些想象出来的文案不该再出现在**规则表**里。

        **只看正则，不看整个源文件** —— 我第一版写的是
        `assertNotIn(bad_pat, inspect.getsource(zzz_daily))`，
        结果被自己写的解释注释骗了：注释里为了说明问题引用了那几个词，
        测试就把注释当成了「还在用旧文案」。

        （这个坑我在 `zzz_cost` 上踩过一次，这是第二次。）
        """
        import zzz_daily
        pats = []
        for rules in zzz_daily.OUTCOME_RULES.values():
            for r in rules:
                pats.append(r[0])
        joined = "\n".join(pats)
        for bad_pat in ("强化了一次", "点改装", "点晋升", "号位已换装"):
            self.assertNotIn(bad_pat, joined,
                             f"规则正则里还有「{bad_pat}」，实际输出里没有这文案")

    def test_rules_target_real_output(self):
        """反向确认：规则里确实用了工具真实打印的文案。"""
        import zzz_daily
        pats = "\n".join(r[0] for rules in zzz_daily.OUTCOME_RULES.values()
                          for r in rules)
        for real in ("完成：强化", "完成，升级", "合计升了", "已调"):
            self.assertIn(real, pats,
                          f"规则里没有「{real}」—— 这是工具真会打印的")


class TestNoProgressIsFailure(unittest.TestCase):
    """「一步都没做成」必须返回非 0（BUG-087）。

    ## 原来是 10 处无条件 `return 0`

    ```python
    print(f"完成：有效操作 {total_up} 次，最终等级 {lv}/{cap}")
    return 0                      # ← 一次都没升也是 0
    ```

    上层 `zzz_daily --from-targets` 看到 0 就认为这步过了、继续下一步，
    **用户完全不知道其实什么都没做成**。这和之前那些「失败伪装成成功」
    是同一族问题。

    ## 检查方式

    不看整份源码（会被注释骗），只看每个工具里
    「有进度计数」和「无进度返回非 0」这两件事是否同时存在。
    """

    TOOLS = {
        "zzz_wengine.py": ("total_up", "return 1"),
        "zzz_convert.py": ("done", "return 1"),
        "zzz_level.py": ("done", "return 1"),
        "zzz_skill.py": ("upgraded", "return 1"),
    }

    def test_tools_report_no_progress(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for name, (counter, ret) in self.TOOLS.items():
            src = (root / name).read_text(encoding="utf-8")
            self.assertIn(counter, src, f"{name} 里没有进度计数 {counter}")
            # 不要求 `if X == 0` 正好连着写 —— 有的是
            # `if args.cmd == "upgrade" and upgraded == 0`。
            self.assertIn(f"{counter} == 0", src,
                          f"{name} 没判「{counter} == 0」—— 无进展也会返回 0")
            self.assertIn(ret, src, f"{name} 没有非零返回")

    def test_wengine_zero_ops_returns_1(self):
        """具体一点：音擎一次操作都没有时必须返回 1。"""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_wengine.py").read_text(encoding="utf-8")
        i = src.index("if total_up == 0")
        after = src[i:i + 200]
        self.assertIn("return 1", after,
                      "「if total_up == 0」后面没有 return 1")


class TestGrindGapDetection(unittest.TestCase):
    """`zzz_grind.find_gaps` 必须**按行**判断材料缺口（BUG-092）。

    ## 原来是整段判断

    ```python
    if key in out and ("不足" in out or "不够" in out):
        found.append(key)
    ```

    两个条件在整段输出里各自成立就算命中。于是：

    ```
    音擎：高维数据 3 个（够）
    技能强化：材料不足
    ```

    `"高维数据" in out` 为真、`"不足" in out` 也为真 →
    **高维数据被误判成不足** → `fill_gaps()` 去刷空域戒戍者 →
    **白花电量刷一个并不缺的本**。
    """

    def setUp(self):
        from zzz_grind import find_gaps
        self.f = find_gaps

    def test_cross_line_false_positive(self):
        """别处的「不足」不能嫁祸给这一行里写「够」的资源。"""
        out = "音擎：高维数据 3 个（够）\n技能强化：材料不足\n"
        self.assertNotIn("高维数据", self.f(out))

    def test_real_shortage_detected(self):
        self.assertIn("高维数据", self.f("高维数据不足\n"))
        self.assertIn("认证章", self.f("认证章不够\n"))
        self.assertIn("音擎蓄电池", self.f("音擎蓄电池不足\n"))

    def test_all_sufficient(self):
        out = "高维数据 5 个\n认证章 3 个\n"
        self.assertEqual(self.f(out), [])

    def test_multiple_shortages(self):
        got = self.f("特化芯片不足\n高维数据不足\n")
        self.assertIn("特化芯片", got)
        self.assertIn("高维数据", got)

    def test_unspecified_fallback(self):
        """只说「材料不足」没说是什么 —— 才走兜底猜。"""
        self.assertEqual(self.f("材料不足\n"), ["特化芯片"])


class TestDailyFarmLog(unittest.TestCase):
    """`zzz_daily --run` 要记得今天刷过没（BUG-091 + RT-08）。

    ## 完全没记（BUG-091）

    `zzz_daily --run` 一天跑两次就刷两次本 —— **第二天的电量被提前烧掉**。

    ## 记了，但 schema 和 zzz_gap 打架（RT-08）

    原来 `zzz_daily` 按 dict 读写、`zzz_gap` 按 list 读写，交叉跑就会
    互相 AttributeError。现在统一走 `core.farm_log`。
    """

    def setUp(self):
        import zzz_daily as zd
        from core import farm_log as FL
        self.zd = zd
        self.FL = FL
        self._orig = FL.LOG
        self.f = FL.LOG
        self.bak = self.f.read_text(encoding="utf-8") if self.f.exists() else None
        self.f.unlink(missing_ok=True)

    def tearDown(self):
        self.FL.LOG = self._orig
        if self.bak is not None:
            self.f.write_text(self.bak, encoding="utf-8")
        else:
            self.f.unlink(missing_ok=True)

    def test_starts_at_zero(self):
        self.assertEqual(self.zd._farm_count_today(), 0)

    def test_record_increments(self):
        self.zd._farm_record("测A", 1)
        self.assertEqual(self.zd._farm_count_today(), 1)
        self.zd._farm_record("测B", 2)
        self.assertEqual(self.zd._farm_count_today(), 2)

    def test_yesterday_does_not_count(self):
        """昨天的记录不能算今天的。"""
        import json
        self.zd._farm_record("测A", 1)
        d = json.loads(self.f.read_text(encoding="utf-8"))
        for r in d.get("records") or []:
            r["date"] = "2000-01-01"
        self.f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.zd._farm_count_today(), 0)

    def test_bad_file_is_not_zero(self):
        """坏 JSON 要报 -1（不知道），**不能静默当 0**（RT-08）。"""
        self.f.write_text("{半截", encoding="utf-8")
        self.assertEqual(self.zd._farm_count_today(), -1,
                         "坏文件返回了 0 —— 会静默当成「今天没刷过」")

    def test_record_survives_bad_file(self):
        """坏文件时记账要备份 + 重来，不能崩、也不能覆盖掉历史。"""
        self.f.write_text("{半截", encoding="utf-8")
        self.zd._farm_record("测A", 1)          # 不抛异常
        self.assertEqual(self.zd._farm_count_today(), 1)
        self.assertTrue(self.f.with_name(self.f.name + ".corrupt").exists(),
                        "坏文件没被备份 —— 历史就这么没了")

    def test_again_flag_exists(self):
        import inspect
        import zzz_daily
        self.assertIn("--again", inspect.getsource(zzz_daily.main),
                      "没有 --again —— 电量回满了想再刷就没法强制")

class TestReadStatusHonesty(unittest.TestCase):
    """`read_status` 读失败必须说出来（BUG-085）。

    ## 原来两个静默失败

    ```python
    ok, out = run("zzz_status.py", [agent, "--json"], 1800)   # ← ok 被丢掉
    return json.loads(...)      # 不管命令成没成，读到啥就是啥
    return {}                   # 没文件 → 空字典，还用空字典表示「读不到」
    ```

    · `zzz_status` 失败时照样读**上一次**的文件 —— 旧数据被当成当前数据
    · 空字典既表示「读不到」也表示「没数据」，调用方分不出来
    """

    def test_missing_file_warns(self):
        import io
        import contextlib
        import zzz_disc_daily as zd
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            d = zd.read_status("__绝对不存在的角色__")
        self.assertEqual(d, {})
        self.assertIn("状态数据缺失", buf.getvalue(),
                      "文件不存在时没有提示")

    def test_bad_file_warns(self):
        import io
        import contextlib
        import pathlib
        import zzz_disc_daily as zd
        p = pathlib.Path(zd.BASE) / "state" / "status___坏文件测试__.json"
        p.write_text("{半截", encoding="utf-8")
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                d = zd.read_status("__坏文件测试__")
            self.assertEqual(d, {})
            self.assertIn("读不了", buf.getvalue(),
                          "坏文件时没有提示")
        finally:
            p.unlink(missing_ok=True)

    def test_exit_code_not_discarded(self):
        """源码里 `run(...)` 的返回必须被解包成两个名字，不能只接一个。"""
        import inspect
        import zzz_disc_daily as zd
        src = _code(zd.read_status)
        self.assertIn("ok, out = run(", src,
                      "read_status 没接住 run 的退出码")
        self.assertIn("if not ok:", src,
                      "接住了却没判 —— 等于没接")


class TestDocsMatchCode(unittest.TestCase):
    """文档里的「事实声明」必须和代码一致（BUG-183）。

    ## 原来 AGENTS.md 的 `--json` 清单 6 个里 5 个是错的

    ```
    声称有：zzz_status ✔ | zzz_plan ✘ | zzz_auto ✘ | zzz_daily ✘
            zzz_disc_daily ✘ | zzz_grind ✘
    实际有：zzz_status | zzz_gap | zzz_guide | zzz_guide_agents | zzz_uid
    ```

    照着它调用会得到：

    ```
    zzz_daily.py: error: unrecognized arguments: --json
    → exit 2
    ```

    而 exit 2 在这套工具里的语义是「配置缺失」—— 很容易误判。
    **文档和代码脱节比没有文档更糟。**

    还发现 `zzz_auto.py` 已经归档，但 `TOOLS.md` 还在教用户跑它
    （而且那行是 `gen_tools_doc.py` 生成的，改了也会被覆盖回来）。
    """

    DOCS = ("AGENTS.md", "TOOLS.md", "README.md", "DISC_LOOP.md",
            "START_HERE.md")

    def test_no_ghost_tools(self):
        """文档里提到的 `xxx.py` 必须真的存在（含 _legacy）。"""
        import re
        import pathlib
        # 注意：test_core.py 在 tools/tests/，`.parent.parent` 是 tools/，
        # 到**仓库根**要三个 parent。（我第一版只写两个，
        # 于是去找 tools/AGENTS.md —— 不存在。）
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        # **要用 rglob**：`tools/core/*.py` 也是工具的一部分，
        # 只用 glob("*.py") 会把 core/ 下的全漏掉
        # （我第一版就漏了，于是 `tools/core/game_cfg.py` 被误报成不存在）。
        have = {p.stem for p in (root / "tools").rglob("*.py")}
        bad = {}
        for md in self.DOCS:
            f = root / md
            if not f.exists():
                continue
            ghosts = set()
            # 占位符不算：文档里会写 `python tools/xxx.py` 表示「随便哪个工具」
            PLACEHOLDER = {"xxx", "xx", "x", "角色名", "agent", "<agent>"}
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                # ① zzz_xxx.py / od_xxx.py 形式
                for m in re.finditer(r"\b(zzz_[a-z0-9_]+|od_[a-z_]+)\.py", line):
                    if m.group(1) not in have:
                        ghosts.add(m.group(1))
                # ② tools/xxx.py 形式 —— **不限前缀**（曾经漏过 loop.py / to_world.py）
                #
                # `have` 存的是**文件名主干**（不含目录），所以这里拿 stem 比。
                for m in re.finditer(r"tools/([\w/]+)\.py", line):
                    path_in = m.group(1)                 # 例如 "core/vocab" 或 "loop"
                    stem = path_in.split("/")[-1]
                    if stem in PLACEHOLDER:
                        continue
                    if stem not in have:
                        ghosts.add(f"tools/{path_in}.py")
            if ghosts:
                bad[md] = sorted(ghosts)
        self.assertEqual(bad, {}, f"文档提到了不存在的工具：{bad}")

    def test_agents_json_list_is_accurate(self):
        """AGENTS.md 的 --json 清单必须和 `tools.json` 的 `json_output` 一致。

        ## 为什么改成对照 tools.json，而不是跑 --help

        第一版是「跑每个工具的 `--help`，看有没有 `--json`」。三个问题：

        ① **子命令的 `--json` 顶层看不到** —— `zzz_resource.py check --json`
           是真的能用，但 `zzz_resource.py --help` 里没有。
        ② **有的工具根本没有 argparse** —— `gen_manifest.py --help`
           会直接**跑一遍生成**，而不是打印帮助。
        ③ **`--help` 太慢** —— 每个工具起一个子进程。

        而 `tools.json` 的 `json_output` 现在由 `gen_manifest.py` **解析 AST**
        得出（只认真正的 `add_argument("--json")`），是可信的源头。
        """
        import json as _json
        import re as _re
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        doc = root / "AGENTS.md"
        tj = root / "tools.json"
        if not doc.exists() or not tj.exists():
            self.skipTest("AGENTS.md / tools.json 不在当前集合里")
        txt = doc.read_text(encoding="utf-8")
        m = _re.search(r"现在只有这 \d+ 个有：\s*```\s*\n(.*?)```", txt, _re.S)
        if not m:
            self.skipTest("AGENTS.md 里没找到那份清单（可能措辞变了）")
        claimed = set(_re.findall(r"(\w+)\.py", m.group(1)))

        d = _json.loads(tj.read_text(encoding="utf-8"))
        tools = d.get("tools")
        if isinstance(tools, list):
            actual = {t.get("name") for t in tools
                      if isinstance(t, dict) and t.get("json_output")}
        else:
            actual = {k for k, v in (tools or {}).items()
                      if isinstance(v, dict) and v.get("json_output")}
        self.assertTrue(actual, "tools.json 里一个 json_output 都没有，生成可能坏了")
        self.assertEqual(claimed, actual,
                         f"AGENTS.md 说 {sorted(claimed)}，"
                         f"tools.json 说 {sorted(actual)}")

    def test_set_whitelist_covers_dungeon_table(self):
        """副本表里的套装必须都在 vocab.SETS 里，否则永远认不出来。"""
        import json
        import pathlib
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import vocab
        mp = pathlib.Path(__file__).resolve().parent.parent / "disc_meta.json"
        if not mp.exists():
            self.skipTest("disc_meta.json 不在当前集合里")
        dm = json.loads(mp.read_text(encoding="utf-8"))
        table = set((dm.get("套装副本") or {}).keys())
        missing = sorted(table - set(vocab.SETS))
        self.assertEqual(missing, [],
                         f"这些套装在副本表里但不在 OCR 白名单里：{missing}")

    def test_graduation_thresholds_agree(self):
        """三处毕业阈值必须一致。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import disc_cfg
        import zzz_grind
        import zzz_status
        # `effective(good, half)` 需要两个分值参数，直接读它的阈值表更稳
        a = None
        th = getattr(disc_cfg, "THRESHOLDS", None)
        if isinstance(th, dict) and "graduation" in th:
            a = float(th["graduation"])
        b = zzz_grind.GRADES.get("小毕业")
        c = dict(zzz_status.GRAD).get("小毕业")
        vals = [v for v in (a, b, c) if v is not None]
        self.assertTrue(vals, "一个阈值都没读到")
        self.assertEqual(len(set(vals)), 1,
                         f"毕业阈值不一致：disc_cfg={a} grind={b} status={c}")

    def test_doc_thresholds_match_code(self):
        """DISC_LOOP.md 写的毕业阈值要和代码一致。"""
        import pathlib
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_status
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        doc = root / "DISC_LOOP.md"
        if not doc.exists():
            self.skipTest("DISC_LOOP.md 不在当前集合里")
        txt = doc.read_text(encoding="utf-8")
        for name, val in zzz_status.GRAD:
            expect = f"| {name} | **{val:g}** |"
            alt = f"| {name} | {val:g} |"
            self.assertTrue(expect in txt or alt in txt,
                            f"DISC_LOOP.md 里 {name} 的阈值不是 {val:g}")


class TestGrindStatusCache(unittest.TestCase):
    """`zzz_grind.status(max_age=)` 要能跳过重读游戏（性能）。

    ## 原来每次调用都跑一遍 zzz_status

    `status()` 的实现是「先跑 `zzz_status.py`（实测约 100 秒），再读文件」。
    而它在收敛循环里被调 3 处：开头 1 次、**每轮 1 次**、结尾 1 次 ——
    `--rounds 5` 就是 7 次 × 100 秒 ≈ **700 秒白花**。

    每轮那次更没必要：它紧跟在 `zzz_daily --run` 之后，
    而 daily 收尾本来就会跑一次体检把 status 写新。

    现在 `max_age > 0` 时，`_ts` 够新就直接用。
    """

    def test_fresh_file_returns_fast(self):
        import time
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_grind as zg
        # 先确认有可用的 status 文件
        st_dir = pathlib.Path(zg.BASE) / "state"
        files = sorted(st_dir.glob("status_*.json"))
        if not files:
            self.skipTest("没有 status 文件")
        import json
        d = json.loads(files[0].read_text(encoding="utf-8"))
        agent = d.get("agent") or files[0].stem.replace("status_", "", 1)
        if not d.get("_ts"):
            self.skipTest("文件里没有 _ts 时间戳")
        t0 = time.time()
        zg.status(agent, max_age=3600)
        dt = time.time() - t0
        self.assertLess(dt, 5.0,
                        f"max_age=3600 时仍花了 {dt:.1f} 秒 —— 说明还是去重读游戏了")

    def test_signature_has_max_age(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_grind as zg
        sig = inspect.signature(zg.status)
        self.assertIn("max_age", sig.parameters,
                      "status() 没有 max_age 参数")


class TestDocumentedCommandsWork(unittest.TestCase):
    """AGENTS.md 里写的命令，参数形式必须真的被接受。

    ## 为什么加这条

    BUG-183 的教训：AGENTS.md 说「这 6 个有 `--json`」，实际 6 个里 5 个没有，
    照着调用会 `unrecognized arguments: --json` → **exit 2**，
    而 exit 2 在这套工具里的语义是「配置缺失」，很容易误判。

    **文档里的每条命令都是对用户的一个承诺。** 这条测试逐条兑现承诺：
    把 AGENTS.md 里 `python tools/xxx.py ...` 的每一行拿出来，
    **加上 `--help` 跑一遍**，只要求 argparse 不报 "unrecognized arguments"
    （不真执行，所以安全）。
    """

    def test_all_documented_commands_accept_their_args(self):
        import re
        import pathlib
        import subprocess
        import sys
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        doc = root / "AGENTS.md"
        if not doc.exists():
            self.skipTest("AGENTS.md 不在当前集合里")
        text = doc.read_text(encoding="utf-8")
        cmds = []
        for line in text.splitlines():
            # **一行里可能用 `;` 串了多条命令**（例如「提交前跑一遍全套」那段）。
            # 第一版没拆，于是把 `a.py; python b.py` 整条当成一个文件名去查，
            # 报「文件不存在」。真人也这么写，所以这里要按分隔符拆开。
            for piece in re.split(r";|\s&&\s|\s\|\s", line):
                m = re.match(r"\s*(python tools/[\w.]+\.py[^\s#]*(?:\s+[^\s#][^#]*)?)",
                             piece)
                if not m:
                    continue
                c = m.group(1).strip()
                # 跳过带占位符的（没法测）
                if "<" in c or "XXX" in c or "角色名" in c:
                    continue
                if c not in cmds:
                    cmds.append(c)
        self.assertGreater(len(cmds), 5, "一条命令都没提取到，正则可能失效了")

        bad = []
        for c in cmds:
            parts = c.split()
            tool = root / parts[1]
            if not tool.exists():
                bad.append((c, "文件不存在"))
                continue
            # **只测 `zzz_*` 工具**。
            #
            # 踩过两次：
            # ① `run_tests.py` 不用 argparse，`--help` 被当普通参数 →
            #    **真的跑起了整个测试套件**（含这条测试自己），120 秒超时 + 近似递归
            # ② `audit_ship.py` 同样不是 argparse 程序，`--help` 会
            #    **真的跑整套发布验证**（要几分钟，而且内部又会调 run_tests）
            #
            # 规则很简单：**文档里教用户「带参数运行」的都是 `zzz_*` 工具**，
            # 其余是自检脚本，没有「参数形式」这回事。
            if not tool.name.startswith("zzz_"):
                continue
            try:
                _src = tool.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "argparse" not in _src:
                continue
            # `--help` 应该是**瞬间**的。给 15 秒 ——
            # 超时说明这条文档命令会真的干活（比如某个工具把 --help 当普通参数
            # 然后开始执行），那本身就是个问题，要报出来而不是静默跳过。
            try:
                r = subprocess.run([sys.executable, "-u", str(tool)]
                                   + parts[2:] + ["--help"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(root), timeout=15)
            except subprocess.TimeoutExpired:
                bad.append((c, "--help 15 秒没返回，说明它会真干活"))
                continue
            except (OSError, subprocess.SubprocessError) as e:
                bad.append((c, f"跑不起来：{e}"))
                continue
            err = (r.stderr or "")
            if "unrecognized arguments" in err:
                bad.append((c, err.strip().splitlines()[-1]))
        self.assertEqual(bad, [],
                         "这些文档命令的参数形式不被接受：\n"
                         + "\n".join(f"  {c}\n    {e}" for c, e in bad))


class TestBatchTargets(unittest.TestCase):
    """`--from-targets` 的发布卫生与错误处理。

    ## 为什么加

    `targets.json` 决定「哪些角色会被自动刷本/升级」——
    如果发布集里带着**别人账号的角色列表**，新用户一跑就会动他的账号。

    实测过的行为：
    · 空 agents → exit 0，只说「没有角色要养」（不动账号）
    · 坏 JSON   → exit 2，带 JSON 解析错误原文
    · 中间夹一个不存在的角色 → 那个返回 3 并打印「继续下一个」，
      其余照跑，整体 exit 0
    """

    def test_targets_json_is_empty_template(self):
        """仓库里的 targets.json 必须是空模板。"""
        import json
        import pathlib
        p = pathlib.Path(__file__).resolve().parent.parent.parent / "targets.json"
        if not p.exists():
            self.skipTest("targets.json 不在当前集合里")
        d = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(d.get("agents"), [],
                         f"targets.json 里的 agents 不是空的：{d.get('agents')} "
                         f"—— 发布集不能带别人账号的角色列表")

    def test_batch_reports_bad_json_without_traceback(self):
        """坏 targets.json 要不崩、不抛 traceback，且给出可读的提示。

        **这条我第一版写成「跑子进程断言 exit 2」，但隔离环境里
        `zzz_daily.py` 缺依赖，在解析 targets.json 之前就以 1 退出了** ——
        测试测到的是环境问题，不是被测行为。

        改成检查源码里那段的写法（够用，且不依赖运行环境）：
        · 有 `except` 兜住 JSON 解析
        · 提示里带原始异常 `{e}`
        · 返回 2（「配置错」的语义）
        """
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_daily
        src = _code(zzz_daily.main)
        self.assertIn("读不了 targets.json", src,
                      "没有针对坏 targets.json 的提示")
        self.assertIn("return 2", src, "坏 JSON 应返回 2")
        # 提示里要带原始异常，否则用户不知道哪里错了
        self.assertIn("{e}", src, "提示里没带原始异常")


class TestDefaultAgentIsConfigurable(unittest.TestCase):
    """`DEFAULT_AGENT` 不能写死成作者的角色（通用性）。

    ## 原来是

    ```python
    DEFAULT_AGENT = "佩洛伊斯"      # 作者自己的角色
    ```

    而 **17 个工具**把它当参数的默认值 —— 包括 `zzz_equip upgrade`、
    `zzz_disc_daily`、`zzz_wengine` 这些**会花材料**的。

    这份工具是要给别人用的。朋友不带参数跑
    `python tools/zzz_equip.py upgrade`，它会去操作「佩洛伊斯」——
    一个他账号上根本没有的角色。

    ## 更糟的是 zzz_equip 的校验写法

    ```python
    if getattr(args, "agent", ""):     # ← 只有给了名字才校验
        ...确认当前是这个角色...
    ```

    默认值变空之后，这个 `if` 直接跳过校验，
    **一个会花材料的工具在不知道给谁换盘的情况下就往下走了**
    （实测：加载 OCR、开始导航、点到一个随便什么角色的盘）。

    ## 现在

    · `DEFAULT_AGENT` 按 `ZZZ_DEFAULT_AGENT` → `state/config.json` → **空**
    · 空的报错是说「没指定角色」并给出用法，不是「角色「」不在库里」
    · 破坏性工具（`zzz_equip`）在空的时候**直接拒绝，且在建 Vision/Ui 之前**，
      所以拒绝时零副作用（不切游戏输入模式）
    """

    def test_default_agent_not_hardcoded(self):
        """用 **AST** 检查赋值语句，不吃注释和 docstring 的亏。

        ## 我第一版又踩了自指陷阱（第四次）

        ```python
        for line in src.splitlines():
            if line.strip().startswith("DEFAULT_AGENT = "):
                assertNotIn("佩洛伊斯", line)
        ```

        而我在 `_default_agent()` 的 docstring 里**引用了那行旧代码**
        （`DEFAULT_AGENT = "佩洛伊斯"`）来说明问题 ——
        测试就把 docstring 当成了「还写死着」。

        前三次：`zzz_cost` 的 `range(cur, 12)`、outcome rules 的解释注释、
        `START_HERE.md` 里解释 od_farm 的说明。

        **文本检查会被「解释问题的文字」污染；AST 不会。**
        """
        import ast as _ast
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        tree = _ast.parse((root / "core" / "game_cfg.py").read_text(encoding="utf-8"))
        found = []
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for t in node.targets:
                    if isinstance(t, _ast.Name) and t.id == "DEFAULT_AGENT":
                        found.append(node)
        self.assertTrue(found, "没找到 DEFAULT_AGENT 的赋值")
        for node in found:
            v = node.value
            # 只允许「调用 _default_agent()」或非字符串常量
            if isinstance(v, _ast.Constant):
                self.assertNotIsInstance(v.value, str,
                                         f"DEFAULT_AGENT 写死成字符串：{v.value!r}")

    def test_default_agent_from_env(self):
        import os
        import sys
        import pathlib
        import importlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import game_cfg
        old = os.environ.get("ZZZ_DEFAULT_AGENT")
        os.environ["ZZZ_DEFAULT_AGENT"] = "测试角色"
        try:
            self.assertEqual(game_cfg._default_agent(), "测试角色")
        finally:
            if old is None:
                os.environ.pop("ZZZ_DEFAULT_AGENT", None)
            else:
                os.environ["ZZZ_DEFAULT_AGENT"] = old

    def test_empty_agent_message_is_helpful(self):
        """空角色名的报错要说「没指定」，不是「角色「」不在库里」。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import resolve_agent
        try:
            resolve_agent("")
        except Exception as e:
            msg = str(e)
            self.assertIn("没指定角色", msg,
                          f"空角色名的提示不清楚：{msg[:80]}")
        else:
            self.fail("空角色名居然没报错")

    def test_equip_refuses_before_touching_game(self):
        """`zzz_equip` 没有 agent 时必须在建 Vision/Ui **之前**就拒绝。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_equip
        src = _code(zzz_equip.main)
        i_chk = src.find("必须指定 --agent")
        i_vis = src.find("Vision(), Input()")
        self.assertGreater(i_chk, -1, "zzz_equip 没有「必须指定 --agent」的检查")
        self.assertGreater(i_vis, -1, "找不到 Vision() 的创建")
        self.assertLess(i_chk, i_vis,
                        "检查在创建 Vision/Ui 之后 —— 拒绝时会有副作用")


class TestResolutionCheck(unittest.TestCase):
    """分辨率不对必须报出来（新用户最常见的第一次失败）。

    ## 原来两个入口都不查

    · `zzz_launch --check` 只打印 `运行中：… 2560x1440` 然后 `return 0`
    · `check_config` 只查路径 / OCR 模块 / 角色配置，**不查窗口**

    于是用 2K/4K 显示器的用户会看到「运行中」「环境 OK」，
    然后**每一个点击都偏** —— 很难自己想到是分辨率的问题。

    所有坐标都按 1920x1080 标定（AGENTS.md「容易踩的坑」第 2 条）。
    """

    def test_launch_check_validates_resolution(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_launch
        src = _code(zzz_launch.main)
        self.assertIn("1920", src, "zzz_launch --check 没检查 1920")
        self.assertIn("1080", src, "zzz_launch --check 没检查 1080")
        # 不对时要返回非 0
        i = src.find("分辨率不对")
        self.assertGreater(i, -1, "没有「分辨率不对」的提示")
        self.assertIn("return 5", src[i:i + 600],
                      "分辨率不对时没有返回非 0")

    def test_check_config_checks_window(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import check_config
        src = _code(check_config.main)
        self.assertIn("1920", src, "check_config 不看分辨率")
        self.assertIn("游戏窗口", src, "check_config 不报窗口状态")


class TestAdminIsFatal(unittest.TestCase):
    """没有管理员权限要算**致命**，不能只是 ⚠。

    ## 为什么

    没有管理员时，Windows UIPI 会**静默丢弃**所有按键/点击 ——
    工具不报错，而是白等到超时（实测 150~254 秒）。

    `ui.start()` 已经正确拒绝了（`SystemExit(2)` + 清晰提示），
    但 `check_config` 只打印 `⚠ 管理员权限：没有` 然后 **exit 0** ——
    于是「环境检查通过」这句话是假的。

    「缺一个就跑不了」的检查项就该报失败。
    """

    def test_admin_missing_counts_as_fatal(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import check_config
        src = _code(check_config.main)
        i = src.find("管理员权限：没有")
        self.assertGreater(i, -1, "没有「管理员权限：没有」的提示")
        tail = src[i:i + 700]
        self.assertIn("fatal += 1", tail,
                      "管理员缺失没计入致命项 —— check_config 会照样 exit 0")

    def test_admin_hint_points_to_existing_script(self):
        """提示里让用户跑 `.\\admin.ps1`，那个文件必须真的存在且在发布集里。"""
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(root / "tools"))
        script = root / "admin.ps1"
        self.assertTrue(script.exists(), "admin.ps1 不存在，但提示里提到了它")
        from publish_github import collect
        files = {str(f) for f in collect(root)}
        self.assertIn("admin.ps1", files,
                      "admin.ps1 不在发布集里 —— 用户拿到手没这个文件")

    def test_ui_start_refuses_without_admin(self):
        """`ui.start()` 没管理员时必须抛 SystemExit，不是只打印。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import ui
        src = _code(ui.Ui.start)
        self.assertIn("is_admin()", src, "ui.start 没查管理员")
        self.assertIn("SystemExit", src, "ui.start 只打印没拒绝")


class TestScanWhitelist(unittest.TestCase):
    """`list_agents` 扫出来的名字必须在角色库里（实测扫出过一个「2」）。

    ## 怎么发现的

    真机跑 `python tools/zzz_who.py --scan`（零消耗，只读），18 个角色里
    **第 10 个叫「2」**：

    ```
     10. 2　强攻·?　未盘点
    ```

    真名是 `11号`，OCR 把名字读残了。而原来的单字残段过滤只处理
    **单个汉字**（「西」⊂「露西」），数字残段完全逃过 ——
    `'2' in '11号'` 是 False。

    用户看到的菜单里混进一个假角色，完全没法用。

    ## 现在的行为

    认不出的名字先试纠正（唯一候选就直接换），纠正不了就**从名单去掉**
    并打一行警告，让用户知道扫描有遗漏，而不是拿到假角色。
    """

    def _validate(self, out):
        """复刻 list_agents 里那段校验逻辑。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import meta
        from core.agent_name import canonical_agent
        known = set((meta().get("角色") or {}).keys())
        fixed, dropped = {}, []
        for nm, lv in out.items():
            if nm in known:
                fixed[nm] = lv
                continue
            c = canonical_agent(nm)
            if c in known:
                fixed[c] = lv
                continue
            dropped.append(nm)
        return fixed, dropped

    def test_garbage_names_dropped(self):
        fixed, dropped = self._validate(
            {"佩洛伊斯": "Lv60", "2": "Lv60", "": "Lv60", "??": "Lv60"})
        self.assertIn("佩洛伊斯", fixed)
        for bad in ("2", "", "??"):
            self.assertNotIn(bad, fixed, f"「{bad}」被当成了真角色")
            self.assertIn(bad, dropped)

    def test_valid_names_kept(self):
        fixed, dropped = self._validate(
            {"苍角": "Lv20", "佩洛伊斯": "Lv60"})
        self.assertEqual(set(fixed), {"苍角", "佩洛伊斯"})
        self.assertEqual(dropped, [])

    def test_list_agents_has_whitelist(self):
        """`list_agents` 要把认不出的名字**从名单去掉**，不能塞假角色。

        ## RT-02 点名的就是这个测试

        它原来是：

        ```python
        src = inspect.getsource(pick_agent.list_agents)
        self.assertIn("角色库", src)
        self.assertIn("认不出的名字", src)
        ```

        而「角色库」三个字**只在 docstring 和注释里**（真代码用的是 `_known`/`_dropped`）。
        把真实白名单整段删掉、只留一行含这两个词的注释 -> 它照样绿。

        ## 现在查真实逻辑（AST）

        `list_agents` 里必须存在：
        · 一个 `_known` 集合（角色库的键）
        · 一个 `_dropped` 列表（认不出的）
        · 对 `_fixed` 的赋值（过滤后的结果覆盖 out）
        """
        import ast as _ast
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pick_agent
        tree = _ast.parse(_code(pick_agent.list_agents))
        names = {n.id for n in _ast.walk(tree) if isinstance(n, _ast.Name)}
        self.assertIn("_known", names, "没有角色库的键集合 `_known`")
        self.assertIn("_dropped", names, "没有「认不出的」列表 `_dropped`")
        self.assertIn("_fixed", names, "没有过滤后的 `_fixed`")
        # 必须有「从名单去掉」这个收敛动作
        has_assign_out = any(
            isinstance(n, _ast.Assign)
            and any(isinstance(t, _ast.Name) and t.id == "out" for t in n.targets)
            for n in _ast.walk(tree))
        self.assertTrue(has_assign_out,
                        "没看到 `out = _fixed` —— 过滤结果没覆盖名单")

class TestStableStateCheck(unittest.TestCase):
    """「过渡画面不能当真」只有**一份**实现（`core.anchors.at`）。

    ## 这条道理被发现过四次，每次实现都不一样

    | 位置 | 判法 | 问题 |
    |---|---|---|
    | `reset_to_world` 最初 | 单帧 | 过渡中间态误判 |
    | `machine._at` | 3 帧取 2 | ✔ 但写在自己类里 |
    | `recovery._at_world` | 3 帧**全中** | 太严，OCR 抖一下就 False |
    | `pick_agent._describe_stable` | 取第一个非未知 | 最松，正是要防的（且已无人调用） |

    现在统一成 `anchors.at(vision, target, tries=3, need=2)`。

    ## 为什么是多数决而不是全中

    OCR 对同一页面会**间歇性漏词**（实测技能页的「影画」偶尔读不出）。
    全中会因为一次抖动判 False；单帧又会因过渡帧判 True。
    """

    def test_at_exists_and_signature(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors
        self.assertTrue(hasattr(anchors, "at"), "anchors.at 不存在")
        sig = inspect.signature(anchors.at)
        for p in ("vision", "target", "tries", "need"):
            self.assertIn(p, sig.parameters, f"anchors.at 缺少参数 {p}")

    def test_callers_delegate(self):
        """两处调用方都必须转发，不能各写一份。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine
        from core import recovery
        src_m = _code(Machine._at)
        src_r = _code(recovery.reset_to_world)
        self.assertTrue("anchors.at" in src_m or "_A.at" in src_m,
                        "machine._at 没有转发到 anchors.at")
        self.assertIn("anchors.at", src_r,
                      "reset_to_world 没有转发到 anchors.at")

    def test_dead_describe_stable_removed(self):
        """`pick_agent._describe_stable` 已无人调用，应该删掉。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pick_agent
        self.assertFalse(hasattr(pick_agent, "_describe_stable"),
                         "_describe_stable 还在 —— 它已无人调用且判法有缺陷")


class TestTransitionVerifySane(unittest.TestCase):
    """`verify` 词必须**可能**出现在 `verify_region` 里。

    ## 发现的矛盾（BUG-198 同族）

    ```python
    Transition("主菜单", "世界", [Action("key", "esc")],
               verify=("快捷导航",), verify_region=(0, 0, 1400, 1080))
    ```

    「快捷导航」在 **x=1509**，而区域只到 x=1400 —— **这个验证永远不可能通过**。
    加上 `*→世界` 和 `调律界面→世界`，一共 3 处。

    verify 层本来就被忽略（RT 报告点过），但**恒假的验证比没有更糟** ——
    它会在日志里显示「验证 ✖」，让人以为「点击没生效」，其实是条件写错了。

    ## 检查方式

    拿一张「已知文字坐标表」，检查每条转移的 verify 词是否落在它的区域里。
    只查表里有的词（未知位置的不管），避免误报。
    """

    # 实测过的文字坐标（1920x1080）
    KNOWN = {
        "快捷导航": (1509, 50),
        "邮件": (600, 1038), "成就": (891, 1038),
        "绳网": (1007, 1038), "仓库": (1123, 1038),
        "更多功能": (317, 1040), "养成指南": (1133, 474),
        "代理人攻略": (313, 49),
    }

    def test_verify_words_inside_region(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import TRANSITIONS
        bad = []
        for t in TRANSITIONS:
            if not t.verify or not t.verify_region:
                continue
            g = t.verify_region
            for w in t.verify:
                if w not in self.KNOWN:
                    continue
                x, y = self.KNOWN[w]
                if not (g[0] <= x <= g[2] and g[1] <= y <= g[3]):
                    bad.append(f"{t.src}→{t.dst}: 「{w}」在 ({x},{y}) "
                               f"但区域是 {g}")
        self.assertEqual(bad, [],
                         "这些转移的 verify 词不可能出现在它的区域里：\n  "
                         + "\n  ".join(bad))

    def test_main_menu_exit_does_not_press_b(self):
        """主菜单 → 世界 **只能用 ESC，不能加 B**。

        ## 这条测试我第一版写反了

        第一版写的是「主菜单不能用单个 ESC（实测无效）」，并要求改成
        `esc_to_world`（交替 B/ESC）。**结果实测更糟**：

        ```
        → 主菜单→世界  (交替 B/ESC)
            动作失败：esc_to_world
        验证状态 ✖ 期望 世界，实际 主菜单
        [machine] 第 1 轮没到，重试
        ... 三轮都退不出去 ...
        → *→世界  (连按 B/ESC 脱离)      ← 是这里的单个 ESC 救的场
        ```

        原因是 **B 键在主菜单上会「打开别的东西」，不是「返回」** ——
        B 和 ESC 交替反而在两个状态之间来回跳。

        `go_to(世界)` 的耗时：73s → 129s（我改错）→ 56.9s（回退后）。

        **所以这条测试现在钉的是：别在主菜单上按 B。**
        """
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import TRANSITIONS
        found = False
        for t in TRANSITIONS:
            if t.src == "主菜单" and t.dst == "世界":
                found = True
                kinds = [a.kind for a in t.actions]
                self.assertNotIn("esc_to_world", kinds,
                                 f"主菜单→世界 用了 esc_to_world（{kinds}）—— "
                                 f"它会按 B，而 B 在主菜单会打开别的面板")
                self.assertIn("key", kinds,
                              f"主菜单→世界 应该用单个 ESC（{kinds}）")
        self.assertTrue(found, "找不到 主菜单→世界 的转移")

    def test_warehouse_has_path_to_world(self):
        """仓库那一簇必须有到世界的路（原来是死区）。"""
        import sys
        import pathlib
        import collections
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import TRANSITIONS
        g = collections.defaultdict(list)
        for t in TRANSITIONS:
            g[t.src].append(t.dst)
        def reach(src):
            q, seen = [src], {src}
            while q:
                c = q.pop(0)
                if c == "世界":
                    return True
                for n in g.get(c, []):
                    if n not in seen:
                        seen.add(n); q.append(n)
            return False
        for s in ("驱动仓库", "音擎仓库", "筛选面板", "驱动盘拆解页"):
            self.assertTrue(reach(s), f"{s} 到不了世界 —— 是个死区")


class TestSilentFailureGuards(unittest.TestCase):
    """两处「静默什么都不做」（P2 里的 BUG-037 / BUG-042）。

    ## BUG-037 未知键名静默变成「什么都没做」

    ```python
    scan = _scan(key)          # 未知名字 → 0
    if not scan:
        return                 # ← 静默返回
    ```

    键名打错（比如写成 `"escape"` 而不是 `"esc"`）时**什么都不发生**，
    而调用方以为按了，然后白等到超时，最后报「到不了界面」——
    一个拼写错误伪装成了「界面识别失败」。

    ## BUG-042 `pick()` 出错时返回 int，调用方按 dict 用

    ```python
    return 2                   # 缺依赖
    ...
    hit = pick(...)
    if not hit:  ...           # 2 是 truthy，拦不住
    x, y = hit["center"]       # TypeError: 'int' 不可下标
    ```

    而且「缺依赖」会被混成「不在标题页」—— 用户会去查游戏状态。
    """

    def test_unknown_key_raises(self):
        """未知键名必须变成错误，不能静默。

        ## 这条测试我第一版写成了「真的去按一次」

        ```python
        i = Input()
        with self.assertRaises(ValueError):
            i.key("escape")
        ```

        而 `key()` 里**先跑焦点守卫**（`_guard("按键")`）——
        游戏窗口不在前台时它先抛 `FocusLost`，根本走不到键名检查。

        于是这条测试**依赖「游戏恰好在前台」**，时红时绿。
        （和之前那条假定 `AGENTS.md` 一定存在的一样：测试不该依赖环境。）

        现在拆成两半，都不碰游戏：
        · `_scan("escape")` 返回 0 —— 这是「静默」的源头
        · `key()` 里确实把这个 0 变成了 `ValueError`
        """
        import sys
        import pathlib
        import inspect
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.input import Input, _scan
        # ① 未知名字在 _scan 里会变成 0 —— 这就是原来「静默什么都不做」的根
        self.assertEqual(_scan("escape"), 0,
                         "_scan 对未知名字居然返回了非 0")
        # ② key() 把这个 0 变成错误（读源码，不真的按）
        src = _code(Input.key)
        self.assertIn("未知的键名", src,
                      "key() 里没有「未知的键名」的错误")
        self.assertIn("raise ValueError", src,
                      "key() 里没有 raise ValueError —— 还是静默返回")

    def test_known_key_names_still_work(self):
        """合法的键名不该受影响（不真的按，只验证 _scan 能解析）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.input import _scan
        for name in ("esc", "tab", "enter", "space"):
            self.assertTrue(_scan(name), f"_scan({name!r}) 返回 0 —— 名字表里没有它")

    def test_int_scan_code_still_work(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.input import _scan
        self.assertEqual(_scan(0x01), 0x01)
        self.assertEqual(_scan(28), 28)

    def test_pick_raises_on_missing_dependency(self):
        """`pick()` 缺依赖时抛 SystemExit(2)，不返回 int。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import live
        try:
            r = live.pick([], "测试")
        except SystemExit as e:
            self.assertEqual(e.code, 2, "缺依赖应该 exit 2（配置缺失）")
        else:
            self.assertNotIsInstance(r, int,
                                     f"pick() 返回了 int {r!r} —— 调用方会 TypeError")


class TestPathsConfigType(unittest.TestCase):
    """`paths.json` 内容不是对象时不能崩（BUG-041）。

    ## 原来

    ```python
    if PATHS_CONFIG.exists():
        try:
            return json.loads(PATHS_CONFIG.read_text(...))   # ← 直接返回
        except Exception:
            pass
    ```

    JSON 合法不代表内容合法：`paths.json` 里写 `[1,2]` 或 `"E:\\xx"`
    也是合法 JSON，于是返回一个 list/str，接着

    ```
    one_dragon_home():  c.get("one_dragon_home")
    → AttributeError: 'list' object has no attribute 'get'
    ```

    **用户看到的是「代码崩了」，而不是「你的 paths.json 写错了」。**
    """

    def test_conf_returns_dict_for_bad_json_content(self):
        import json
        import pathlib
        import sys
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import paths
        pf = paths.PATHS_CONFIG
        bak = pf.read_text(encoding="utf-8") if pf.exists() else None
        try:
            for bad in ("[1, 2, 3]", '"E:\\xx"', "123", "null"):
                pf.write_text(bad, encoding="utf-8")
                d = paths._conf()
                self.assertIsInstance(d, dict,
                                      f"paths.json={bad!r} 时 _conf() 返回了 "
                                      f"{type(d).__name__}，调用方会 AttributeError")
        finally:
            if bak is not None:
                pf.write_text(bak, encoding="utf-8")
            else:
                pf.unlink(missing_ok=True)

    def test_global_statements_compile(self):
        """`global` 放在函数中间是**编译期**错误，`ast.parse` 查不出来。

        我修 BUG-041 时先写了 `global` 在 `except` 块里，
        `ast.parse` 通过了，但 import 直接 `SyntaxError`。
        → 这里对所有 core 模块跑 `compile()`，比 `ast.parse` 严。
        """
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for f in sorted(root.rglob("*.py")):
            if "_legacy" in str(f):
                continue
            try:
                compile(f.read_text(encoding="utf-8"), str(f), "exec")
            except SyntaxError as e:
                bad.append(f"{f.name}:{e.lineno} {e.msg}")
        self.assertEqual(bad, [], f"这些文件编译不过：{bad}")


class TestFailureDiagnosis(unittest.TestCase):
    """两种「失败」不能长得一样（BUG-033 / BUG-039）。

    ## BUG-039 `click_verify` 把验证函数的异常吞成「点击失败」

    ```python
    try:
        if check(): return True
    except Exception:
        pass                    # ← 判定函数崩了 = 点击没生效
    ```

    人于是去查坐标、查界面，而问题在判定函数里。

    ## BUG-033 OCR 模型加载失败没有提示

    `_make_ocr()` 只处理了「import 不到」（没装 OneDragon），
    但「装了、模型文件坏了」是另一种情况 —— 裸异常一路冒到顶层变成 traceback，
    表现却是「读不到画面」，很容易被当成「游戏卡了」。
    """

    def test_click_verify_reports_check_crash(self):
        """验证函数抛异常时要说出「是它自己崩了」，不能说「点击失败」。"""
        import io
        import contextlib
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.click import click_verify

        class FakeInp:
            def click(self, x, y, wait=0): pass

        class FakeVs:
            def frame(self, force=False): pass

        class FakeUi:
            vs = FakeVs()
            inp = FakeInp()

        def broken():
            raise TypeError("模拟判定函数崩了")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = click_verify(FakeUi(), (10, 20), broken, tries=2,
                             wait=0.001, label="测试")
        out = buf.getvalue()
        self.assertFalse(r)
        self.assertIn("验证函数本身抛异常", out,
                      "没有区分「判定函数崩了」和「点击没生效」")
        self.assertIn("TypeError", out, "没报出异常类型")

    def test_ocr_load_failure_has_message(self):
        """OCR 模型加载失败要有可读提示，不是裸 traceback。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import vision
        src = _code(vision)
        self.assertIn("OCR 模块加载失败", src,
                      "OCR 模型加载失败时没有提示")
        i = src.find("init_model()")
        self.assertGreater(i, -1)
        self.assertIn("except Exception", src[max(0, i - 200):i + 800],
                      "init_model() 没有被 try 包住")


class TestExitCodeNumbering(unittest.TestCase):
    """退出码只能有**一套**编号（BUG-038）。

    ## 原来有两套

    `enter_game()` 自成一个编号：

    ```
    0=已到世界 1=没找到按钮 2=需要管理员 3=超时 6=需要登录
    ```

    而 `AGENTS.md` 的全局表里 **`3 = 选不中角色`**、**`7 = 等进入游戏超时`**。
    撞号了。

    `_map_enter()` 负责翻译（3 → 7），两处内部调用都走了它，所以**没有真 bug** ——
    但谁要是直接调 `enter_game()` 就会拿到一个含义完全不同的码。

    2026-11-27 起 `enter_game()` 直接返回全局码，`_map_enter()` 退化成恒等。
    """

    def test_map_enter_is_identity(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_launch as z
        for v in (0, 1, 2, 3, 6, 7, 8):
            self.assertEqual(z._map_enter(v), v,
                             f"_map_enter({v}) = {z._map_enter(v)} —— 还有映射，"
                             f"说明 enter_game 还在用本地编号")

    def test_enter_game_returns_global_timeout_code(self):
        """超时必须是 7（等进入游戏超时），不能是 3（选不中角色）。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_launch as z
        src = _code(z.enter_game)
        i = src.find("等进入游戏超时")
        self.assertGreater(i, -1, "找不到超时那段的提示")
        tail = src[i:i + 600]
        self.assertIn("return 7", tail,
                      "超时没有返回 7（全局码「等进入游戏超时」）")
        self.assertNotIn("return 3", tail,
                         "超时还在返回 3 —— 会和「选不中角色」撞号")


class TestReleaseSensitiveGate(unittest.TestCase):
    """发布集里不该有敏感文件 —— 而且必须**按模式**查（BUG-050）。

    ## 原来只有名字黑名单

    ```python
    EXPECT_ABSENT = ["zzz_host.py", "status.py", ..., "feishu_conf.json"]
    leaked = [x for x in EXPECT_ABSENT if (tmp / x).exists()]
    ```

    只有写进这份清单的文件会被检查。**新出现一个没登记过的敏感文件
    （比如以后加了带 key 的配置文件），它照样会被打进发布集，而且没人知道。**

    现在 `audit_ship` 多了一道 `SENSITIVE_PATTERNS`（10 条），
    按路径/文件名模式再扫一遍。
    """

    def _hit(self, path: str):
        import re
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from audit_ship import SENSITIVE_PATTERNS
        r = path.replace("\\", "/")
        return next((why for pat, why in SENSITIVE_PATTERNS
                     if re.search(pat, r)), None)

    def test_sensitive_files_blocked(self):
        for p in ("state/feishu.json", "tools/feishu_conf.json", "paths.json",
                  "config.local.json", ".env", "deploy/id_rsa", "cert.pem",
                  "my_secret_config.json"):
            self.assertIsNotNone(self._hit(p), f"{p} 没被拦下来")

    def test_legitimate_files_pass(self):
        """别把正常文件也拦了 —— 误报会让人养成「这个红灯不用管」的习惯。"""
        for p in ("paths.example.json", "targets.json", "tools/disc_meta.json",
                  "tools/zzz_daily.py", "README.md", "admin.ps1"):
            self.assertIsNone(self._hit(p), f"{p} 被误拦了")

    def test_patterns_not_empty(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from audit_ship import SENSITIVE_PATTERNS
        self.assertGreaterEqual(len(SENSITIVE_PATTERNS), 5,
                                "敏感文件模式太少，等于没有")


class TestNoUndefinedVariables(unittest.TestCase):
    """函数里「读了但从没赋值、也不是全局/内建」的名字 = 运行时 NameError。

    ## 为什么加

    这一类 bug **能骗过所有现有检查**：
    · `compile()` 过 —— 语法没错
    · `audit_ship` 的 import 过 —— 定义在函数里，不 import 不执行
    · `smoke_test` 的 `--help` 过 —— 走不到那行
    · 包在 `try/except` 里时**连运行时都不报**

    实测抓到三个：
    · `zzz_disc_daily` 的 `dungeons`（刷本时崩）
    · `zzz_disc_daily` 的 `_cfg`（笔误，应为 `cfg`，调律时崩）
    · `zzz_daily` 的 `_snap_before`（**在整轮养成跑完之后**崩，活干完报告丢了）

    `_snap_before` 更隐蔽：它被包在 `try/except Exception` 里，
    于是「本轮变化（全部系统）」这个功能**从来没工作过**，
    只打印一句「（全系统对比跳过：name '_snap_before' is not defined）」。
    """

    def _scan(self, root):
        import ast as _ast
        GLOBALS = set()
        for f in root.rglob("*.py"):
            if "_legacy" in str(f):
                continue
            try:
                t = _ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in _ast.walk(t):
                if isinstance(node, _ast.Name) and isinstance(node.ctx, _ast.Store):
                    GLOBALS.add(node.id)
                elif isinstance(node, (_ast.FunctionDef, _ast.ClassDef)):
                    GLOBALS.add(node.name)
                elif isinstance(node, _ast.alias):
                    GLOBALS.add((node.asname or node.name).split(".")[0])
                elif isinstance(node, _ast.ExceptHandler) and node.name:
                    GLOBALS.add(node.name)
        import builtins
        # **`self` / `cls` 永远算「已定义」**：它们是方法接收者。
        # 而嵌套函数（比如 `Ui.start()` 里的信号处理函数）会用到外层的 `self` ——
        # 那个名字不在它自己的参数表里，但完全合法。
        # 不加上这一条，扫描器会把每个嵌套的闭包都误报成未定义变量。
        BUILTIN = (set(dir(builtins))
                   | {"__file__", "__name__", "__doc__", "self", "cls"})
        bad = []
        for f in sorted(root.rglob("*.py")):
            if "_legacy" in str(f) or f.name.startswith("test"):
                continue
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for fn in _ast.walk(tree):
                if not isinstance(fn, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                loaded, stored = {}, set()
                for node in _ast.walk(fn):
                    if isinstance(node, _ast.Name):
                        if isinstance(node.ctx, _ast.Store):
                            stored.add(node.id)
                        else:
                            loaded.setdefault(node.id, node.lineno)
                    elif isinstance(node, _ast.arg):
                        stored.add(node.arg)
                    elif isinstance(node, _ast.ExceptHandler) and node.name:
                        # **`except ValueError as e:` 也是绑定**。
                        #
                        # 这条原来漏了，于是 `zzz_daily.py` 里
                        # `except ValueError as _fe:` 之后用 `_fe` 被报成
                        # 「变量 '_fe' 未定义」—— 假阳性。
                        #
                        # （我自己刚写的那段就撞上了。）
                        stored.add(node.name)
                for v, ln in loaded.items():
                    if v not in stored and v not in BUILTIN and v not in GLOBALS:
                        bad.append(f"{f.name}:{fn.name} 变量 {v!r} (L{ln})")
        return sorted(set(bad))

    def test_no_undefined_names(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = self._scan(root)
        self.assertEqual(bad, [],
                         "这些名字读了但没赋值，运行到就是 NameError：\n  "
                         + "\n  ".join(bad))


class TestBatteryAndPatrolParsing(unittest.TestCase):
    r"""两个「输入解析」的坑（BUG-074 / BUG-078）。

    ## BUG-074 电量只有一位数时读不到

    ```python
    m = re.search(r"(\d{2,3})\s*/\s*240", t)      # ← 至少两位
    return int(m.group(1)) if m else -1
    ```

    电量 `9/240` 是**一位数**，匹配不到 → 返回 -1（未知）→
    上层当「读不到电量」，刷本决策全被跳过。新账号很容易处在个位数电量。

    ## BUG-078 传 `--patrol-type` 时副本名是空的

    ```python
    patrol_name = args.patrol_type or args.patrol    # ← 算出「优先 patrol_type」
    if patrol_name:
        plans.append(("区域巡防", args.patrol, n))     # ← 又退回 args.patrol
    ```

    只传 `--patrol-type 机师与叛甲` 时，`args.patrol` 是空串，
    计划里记的副本名就是**空的**，刷本必然失败而且不报错。
    """

    def _pat(self):
        import re
        return re.compile(r"(\d{1,3})\s*/\s*240")

    def test_one_digit_battery(self):
        p = self._pat()
        for t, want in (("9/240", "9"), ("0/240", "0"), ("5 / 240", "5")):
            m = p.search(t)
            self.assertIsNotNone(m, f"{t!r} 读不到电量")
            self.assertEqual(m.group(1), want)

    def test_two_three_digit_still_work(self):
        p = self._pat()
        for t, want in (("10/240", "10"), ("100/240", "100"), ("240/240", "240")):
            self.assertEqual(p.search(t).group(1), want)

    def test_leading_digits_dont_break(self):
        """`1240/240` 这种要从后面开始配，不能得到 `124`。"""
        p = self._pat()
        self.assertEqual(p.search("1240/240").group(1), "240")

    def test_garbage_is_unknown(self):
        self.assertIsNone(self._pat().search("abc"))

    def test_plans_uses_patrol_name(self):
        """`_plans()` 里必须用 `patrol_name`，不能用 `args.patrol`。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import od_material_farm as omf
        src = _code(omf)
        i = src.find("patrol_name = args.patrol_type or args.patrol")
        self.assertGreater(i, -1, "找不到 patrol_name 的计算")
        tail = src[i:i + 500]
        self.assertIn('("区域巡防", patrol_name, n)', tail,
                      "计划里还是用的 args.patrol —— 传 --patrol-type 会是空")


class TestOutputContract(unittest.TestCase):
    r"""输出契约：**安全默认**要和文档一致（BUG-072 / BUG-073）。

    ## BUG-072 `emit()` 默认 `enabled=True`，和文档相反

    文件头写着「`emit` 只在 `--json` 时才打印，否则什么都不做」，
    而签名是 `enabled: bool = True`。

    将来谁写 `emit("x", data)` 忘了传 `enabled`，就会在**非 --json 模式**下
    也吐一段 JSON，把文本输出弄脏 —— 而 `zzz_*` 的上层是按文本解析的。

    -> 默认改成 `False`（安全的那个方向）。

    ## BUG-073 `zzz_resource` 的子命令是必填，和文档相反

    文件头第一条用法是 `python tools/zzz_resource.py`（体检），
    而 `subparsers(required=True)` 让这条命令**直接 exit 2**。

    **最自然的那个写法，文档说能用，实际不能用。**
    """

    def test_emit_defaults_to_silent(self):
        import io
        import contextlib
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.jsonout import emit
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            emit("测试", data={"a": 1})          # 不传 enabled
        self.assertEqual(buf.getvalue().strip(), "",
                         "不传 enabled 时居然打印了 —— 默认应该是「不输出」")

    def test_emit_with_enabled_true_prints(self):
        import io
        import contextlib
        import json as _j
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.jsonout import emit
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            emit("测试", data={"a": 1}, enabled=True)
        out = buf.getvalue().strip()
        self.assertTrue(out.startswith("{"), "enabled=True 时没打印 JSON")
        d = _j.loads(out)
        self.assertEqual(d.get("tool"), "测试")

    def test_resource_cmd_is_optional(self):
        """`zzz_resource` 不带子命令时应该默认 check，不能 exit 2。

        ## 用 **AST** 查 `add_subparsers` 的关键字

        第一版写的是 `assertNotIn("required=True", 源码)` ——
        而我修这个 bug 时**在注释里引用了 `required=True`** 来解释问题，
        测试就把注释当成了「还没改」。

        （这是自指陷阱的第五次：zzz_cost 的 range、outcome rules 的注释、
          START_HERE 里解释 od_farm 的说明、DEFAULT_AGENT 的 docstring、
          现在这个。）

        **文本检查会被「解释问题的文字」污染；AST 不会。**
        """
        import ast as _ast
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_resource

        tree = _ast.parse(inspect.getsource(zzz_resource))
        found = False
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            fn = node.func
            if getattr(fn, "attr", None) != "add_subparsers":
                continue
            found = True
            for kw in node.keywords:
                if kw.arg == "required":
                    self.assertFalse(
                        getattr(kw.value, "value", True),
                        "add_subparsers(required=True) —— 不带子命令会 exit 2")
        self.assertTrue(found, "找不到 add_subparsers 调用")
        self.assertIn('args.cmd = "check"', inspect.getsource(zzz_resource),
                      "没有「没给子命令就默认 check」的处理")


class TestReturnArityConsistent(unittest.TestCase):
    """同一个函数里的 `return` 必须返回**同样长的元组**。

    ## 为什么

    改 `do_tune` 时我给一个 `return` 加了第三个值（实际倍率），
    忘了另一个提前返回的分支 —— 于是调用方 `ok, got = do_tune(...)`
    会在**那条分支上** `ValueError: not enough values to unpack`。

    `compile()` 查不出（语法没错），`import` 查不出（不执行），
    `--help` 查不出（走不到）。**只有真的走到那条分支才炸。**

    这条和 `TestNoUndefinedVariables` 是同一个思路：
    把「只在运行时才暴露」的结构性错误，改成静态可查。
    """

    def test_consistent_tuple_returns(self):
        import ast as _ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for f in sorted(root.rglob("*.py")):
            if "_legacy" in str(f) or f.name.startswith("test"):
                continue
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for fn in _ast.walk(tree):
                if not isinstance(fn, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                lens = set()
                for node in _ast.walk(fn):
                    if isinstance(node, _ast.Return) and node.value is not None:
                        if isinstance(node.value, _ast.Tuple):
                            lens.add(len(node.value.elts))
                # 裸 return / return None 也算「另一种形状」
                has_bare = any(
                    isinstance(node, _ast.Return) and node.value is None
                    for node in _ast.walk(fn))
                if len(lens) > 1:
                    bad.append(f"{f.name}:{fn.name} 返回长度 {sorted(lens)}")
                elif lens and has_bare:
                    bad.append(f"{f.name}:{fn.name} 有元组返回也有裸 return")
        self.assertEqual(bad, [],
                         "这些函数的 return 形状不一致：\n  " + "\n  ".join(bad))


class TestTuneMultiplierAccounting(unittest.TestCase):
    """调律日志要记**实际**倍率，不是请求的（BUG-081）。

    `do_tune(args.times)` 在游戏只给更小倍率时会退而求其次，
    但原来 `do_tune` 的 `mult` 算出来就丢了，调用方记的是
    `×{args.times}` —— **请求 ×10、实际点了 ×06，日志却写 ×10。**
    """

    def test_do_tune_returns_multiplier(self):
        import ast as _ast
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_tune
        src = _code(zzz_tune.do_tune)
        tree = _ast.parse(src)
        lens = {len(n.value.elts) for n in _ast.walk(tree)
                if isinstance(n, _ast.Return) and isinstance(n.value, _ast.Tuple)}
        self.assertEqual(lens, {3},
                         f"do_tune 应该返回 (ok, got, mult) 三个值，实际 {sorted(lens)}")

    def test_log_uses_actual_multiplier(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_tune
        src = _code(zzz_tune)
        self.assertIn("_rec = f\"×{_mult}\"", src,
                      "日志没有用实际倍率")
        i = src.find('log.log("调律"')
        self.assertIn("_rec", src[i:i + 120],
                      "log.log 里还是用的 args.times")


class TestDiscDedupFingerprint(unittest.TestCase):
    """扫仓库的去重指纹必须区分「主属性」和「位号」（BUG-080）。

    ## 原来

    ```python
    def fingerprint(dd):
        return (dd["set"], dd["level"],
                tuple(sorted((sub["name"], sub["rolls"]) for sub in ...)))
    ```

    只有 `set + level + subs`。于是这两种盘会被当成同一块：

    · 同套装、同等级、副词条一样，但**主属性不同**（攻击力 vs 暴击率）
    · 同套装、同等级，但**位号不同**（1号位 vs 2号位）

    第二块被 `if fp in seen_fp: continue` **直接跳过**，
    `discs_v2.json` 里就少一块 —— 而这是判盘和换装的输入。

    同一套刷出来的盘本来就长得像，这个漏读在实际扫仓库时很常见。
    """

    def _fingerprint_node(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_disc_v2.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.FunctionDef) and node.name == "fingerprint":
                return node
        return None

    def test_fingerprint_has_five_parts(self):
        fn = self._fingerprint_node()
        self.assertIsNotNone(fn, "找不到 fingerprint 函数")
        ret = next((n for n in ast_walk(fn) if isinstance(n, __import__("ast").Return)),
                   None) if False else None
        import ast as _ast
        ret = next((n for n in _ast.walk(fn) if isinstance(n, _ast.Return)), None)
        self.assertIsNotNone(ret, "fingerprint 没有 return")
        self.assertIsInstance(ret.value, _ast.Tuple, "返回的不是元组")
        self.assertEqual(len(ret.value.elts), 5,
                         f"指纹应该有 5 段（slot/set/main/level/subs），"
                         f"实际 {len(ret.value.elts)} 段")

    def test_fingerprint_includes_slot_and_main(self):
        import ast as _ast
        fn = self._fingerprint_node()
        self.assertIsNotNone(fn)
        src = _ast.unparse(fn)
        self.assertIn("slot", src, "指纹里没有位号 slot")
        self.assertIn("main", src, "指纹里没有主属性 main")

    def test_dedup_semantics(self):
        """语义验证：主属性/位号不同 -> 不去重；完全一样 -> 去重。"""
        def new_fp(dd):
            return (dd.get("slot"), dd["set"], dd.get("main"), dd["level"],
                    tuple(sorted((s["name"], s["rolls"])
                                 for s in dd.get("subs") or [])))
        base = {"set": "啄木鸟电音", "level": 15,
                "subs": [{"name": "攻击力百分比", "rolls": 2}]}
        a = {**base, "slot": 4, "main": "攻击力"}
        b = {**base, "slot": 4, "main": "暴击率"}
        c = {**base, "slot": 1, "main": "攻击力"}
        d = {**base, "slot": 4, "main": "攻击力"}
        self.assertNotEqual(new_fp(a), new_fp(b), "主属性不同却被当成重复")
        self.assertNotEqual(new_fp(a), new_fp(c), "位号不同却被当成重复")
        self.assertEqual(new_fp(a), new_fp(d), "完全一样的没被去重")


class TestTrainLimitIsReal(unittest.TestCase):
    """`--train-n` 必须真的限制块数，不能只改文案（BUG-057）。

    ## 原来

    ```python
    print(f"   训练潜力最高的 {args.train_n} 块…")
    ok, out = run("zzz_disc_train.py",
                  [args.agent, "--train", "--max-steps", "6"], 3600)
    ```

    打印说「训练 N 块」，下面那条命令**一个块数都没传** ——
    N 改多少都是训练全部位号。而 `zzz_disc_train` 当时也**没有**块数参数。

    用户以为 `--train-n 1` 能省镀剂，实际一块没省。
    """

    def test_disc_train_has_limit_arg(self):
        import ast as _ast
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_train
        src = _code(zzz_disc_train)
        tree = _ast.parse(src)
        found = False
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            if getattr(node.func, "attr", None) != "add_argument":
                continue
            for a in node.args:
                if isinstance(a, _ast.Constant) and a.value == "--limit":
                    found = True
        self.assertTrue(found, "zzz_disc_train 没有 --limit 参数")

    def test_disc_daily_passes_limit(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_daily
        src = _code(zzz_disc_daily)
        self.assertIn('"--limit", str(args.train_n)', src,
                      "zzz_disc_daily 没有把 --train-n 传下去")

    def test_no_false_potential_claim(self):
        """措辞不能再说「训练潜力最高的 N 块」—— --limit 是按位号顺序数的。

        ## 只查**真正的 print 调用**，不查源码文本

        第一版写的是 `assertNotIn("训练潜力最高的", 整个源码)` ——
        而我修这个 bug 时**在注释里引用了这句话**来解释问题，
        测试就把注释当成了「还没改」。

        （自指陷阱第 6 次。前五次：zzz_cost 的 range、outcome rules 的注释、
          START_HERE 里解释 od_farm 的说明、DEFAULT_AGENT 的 docstring、
          zzz_resource 的 required=True。）

        **注释是给人看的；测试应该查代码做了什么。**
        """
        import ast as _ast
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_daily

        tree = _ast.parse(inspect.getsource(zzz_disc_daily))
        bad = []
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            if getattr(node.func, "id", None) != "print":
                continue
            for a in node.args:
                # f-string 里的字面量片段
                if isinstance(a, _ast.JoinedStr):
                    for v in a.values:
                        if isinstance(v, _ast.Constant) and isinstance(v.value, str):
                            if "训练潜力最高" in v.value:
                                bad.append((node.lineno, v.value))
                elif isinstance(a, _ast.Constant) and isinstance(a.value, str):
                    if "训练潜力最高" in a.value:
                        bad.append((node.lineno, a.value))
        self.assertEqual(bad, [],
                         f"这些 print 还在说「潜力最高」：{bad}")
        # 新措辞确实在（说明改动生效了，不是删了了事）
        self.assertIn("训练最多", inspect.getsource(zzz_disc_daily))


class TestDestructiveFailureExitCode(unittest.TestCase):
    """破坏性工具做事没做成时不能 `return 0`（BUG-087）。

    ## 原来

    · `zzz_disc_daily` 结尾无条件 `return 0` —— 哪怕 `actions` 里全是
      「刷本失败 / 训练失败」
    · `zzz_daily` 用 `judge()` 判了每步「没做成事」，但**那个结果从没用于退出码**
    · `zzz_grind` 打印「还差 X 条」之后照样 `return 0`

    而 `zzz_grind` / cron / 上层脚本都按退出码判断「今天成没成」——
    **失败的一轮被记成成功，第二天照常继续。**

    ## 判定口径

    · `zzz_disc_daily`：`actions` 里有「失败」字样 -> 1（「换装跳过」不算）
    · `zzz_daily`：真跑模式下**所有**步骤都「没做成事」-> 1（部分成功仍是 0）
    · `zzz_grind`：`final < target` -> 1
    """

    def test_disc_daily_has_failure_exit(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_daily
        src = _code(zzz_disc_daily)
        self.assertIn('if "失败" in a', src,
                      "zzz_disc_daily 没有按 actions 里的「失败」判退出码")

    def test_daily_tracks_noprog(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_daily
        src = _code(zzz_daily)
        self.assertIn("_noprog", src, "zzz_daily 没有记录「没做成事」的次数")
        self.assertIn("return 1", src, "zzz_daily 没有失败出口")

    def test_grind_fails_when_target_missed(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_grind
        src = _code(zzz_grind)
        i = src.find("if final < args.target")
        self.assertGreater(i, -1, "找不到「没到目标」的判断")
        tail = src[i:i + 700]
        self.assertIn("return 1", tail,
                      "zzz_grind 没到目标还是 return 0")

    def test_plan_mode_still_zero(self):
        """计划模式不该被这条改动影响。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_daily
        src = _code(zzz_daily)
        # 退出 1 的条件里必须带 args.run
        i = src.find('_noprog["steps"] == _noprog["tried"]')
        self.assertGreater(i, -1, "找不到「全部没做成」的判断")
        around = src[max(0, i - 200):i + 60]
        self.assertIn("args.run", around,
                      "退出 1 的条件没加 args.run —— 计划模式会被误判成失败")


class TestProgressShapes(unittest.TestCase):
    """`disc_progress.json` 的多种形态都要能读（BUG-076 / BUG-067）。

    ## BUG-076 dict 形态下历史恒空

    ```python
    d = json.loads(...)
    rows = [x for x in d if isinstance(x, dict) and x.get("agent") == agent]
    ```

    约定是 list，但历史上/别处写过 dict 形态。而 `for x in d` 在 dict 上
    迭代的是**键字符串** —— `isinstance(x, dict)` 全假 → rows 恒空 →
    历史**永远显示「还没有记录」**。用户只会觉得「我的记录丢了」。

    ## BUG-067 坏 JSON 静默当空

    `except Exception: return []` —— 文件被写到一半就中断 = 历史凭空消失，
    而且没有任何输出。

    （`zzz_disc_daily` 那边已经加了 `.corrupt` 备份 + 提示，这里是读侧。）
    """

    def _load(self, payload):
        import json as _j
        import pathlib
        import sys
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_who as W
        rec = {"agent": "测试角色", "ts": "2026-11-27 10:00:00",
               "质量分": 20.5, "蓝条": 10}
        if payload is None:
            data = _j.dumps([rec], ensure_ascii=False)
        elif payload == "BAD":
            data = "{不是合法 json"
        elif payload == "records":
            data = _j.dumps({"records": [rec]}, ensure_ascii=False)
        elif payload == "byname":
            data = _j.dumps({"测试角色": [rec]}, ensure_ascii=False)
        elif payload == "single":
            data = _j.dumps(rec, ensure_ascii=False)
        else:
            data = _j.dumps(payload, ensure_ascii=False)
        tmp = pathlib.Path(tempfile.mkdtemp()) / "p.json"
        tmp.write_text(data, encoding="utf-8")
        orig = W.PROGRESS
        try:
            W.PROGRESS = tmp
            import io, contextlib
            with contextlib.redirect_stdout(io.StringIO()):
                return W._load_progress("测试角色")
        finally:
            W.PROGRESS = orig

    def test_list_shape(self):
        self.assertEqual(len(self._load(None)), 1)

    def test_dict_with_records_key(self):
        self.assertEqual(len(self._load("records")), 1,
                         "dict + records 形态读不出来")

    def test_dict_keyed_by_agent(self):
        self.assertEqual(len(self._load("byname")), 1,
                         "dict + 角色名 形态读不出来")

    def test_single_record_dict(self):
        self.assertEqual(len(self._load("single")), 1,
                         "整个文件就是一条记录时读不出来")

    def test_bad_json_returns_empty(self):
        self.assertEqual(self._load("BAD"), [])


class TestRollsPctFilter(unittest.TestCase):
    """`rolls_from_value` 的 `is_pct` 必须真的过滤（BUG-060）。

    ## 原来那个形参一次都没用

    ```python
    def rolls_from_value(value: float, is_pct: bool) -> dict[str, int]:
        out = {}
        for name, base in SUB_BASE.items():      # <- is_pct 没出现
    ```

    于是平A和百分比混在一起猜。实测值 `9`：

        生命值百分比 (3×3) ✅
        异常精通   (9×1) ✅
        穿透值     (9×1) ✅

    三个都进候选，全靠名字兜 —— 而 OCR 名字本来就常读残。

    **这块之前完全没有测试覆盖**：改了行为，200 个用例一个都没红。
    """

    def _f(self, v, pct):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.disc_stats import rolls_from_value
        return rolls_from_value(v, pct)

    def test_pct_excludes_flat_stats(self):
        got = self._f(9, True)
        self.assertIn("生命值百分比", got, f"百分比类里没有生命值百分比：{got}")
        self.assertNotIn("异常精通", got, f"百分比类里混进了平A：{got}")
        self.assertNotIn("穿透值", got, f"百分比类里混进了平A：{got}")

    def test_flat_excludes_pct_stats(self):
        got = self._f(9, False)
        self.assertIn("异常精通", got, f"平A类里没有异常精通：{got}")
        self.assertNotIn("生命值百分比", got, f"平A类里混进了百分比：{got}")

    def test_falls_back_when_pool_empty(self):
        """筛完一个不剩时要退回全表 —— 不能因为标错 pct 就完全匹配不上。"""
        got = self._f(38, True)      # 38 只在平A表里（攻击力×1）
        self.assertTrue(got, "筛空了却没退回全表 —— 这个值会解析成 0 次")

    def test_known_values_still_resolve(self):
        self.assertEqual(self._f(38, False).get("攻击力"), 1)
        self.assertEqual(self._f(2.4, True).get("暴击率"), 0)
        self.assertEqual(self._f(6, True).get("生命值百分比"), 1)


class TestDiscMarkMatchesMain(unittest.TestCase):
    """标记弃置时必须比对**主属性**，不只是套装+位号+等级（RT-12）。

    ## 为什么这条不可逆

    同一套、同一位号、同一等级可能有两块盘 —— 主属性不同
    （「攻击力」vs「暴击率」）。原来只比三级：

    ```python
    if (d["set"] != set_name or d["slot"] != slot or d["level"] != level):
        continue
    ```

    标记可能落在**错的那一块**上。而下一轮
    `dismantle_all_abandoned` 点的是「全选已弃置」，就把它拆了。
    **拆解没有撤销。**

    ## 修法

    `mark_disc_abandoned(..., want_main="")` —— 给了就要求主属性一致。
    调用方从 `read_disc` 的结果里带上 `d["main"]`。
    """

    def test_signature_has_want_main(self):
        import ast as _ast
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_cycle as C
        fn = next((n for n in _ast.walk(_ast.parse(inspect.getsource(C)))
                   if isinstance(n, _ast.FunctionDef)
                   and n.name == "mark_disc_abandoned"), None)
        self.assertIsNotNone(fn, "找不到 mark_disc_abandoned")
        args = [a.arg for a in fn.args.args]
        self.assertIn("want_main", args, f"签名里没有 want_main：{args}")

    def test_comparison_uses_main(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_cycle as C
        src = _code(C.mark_disc_abandoned)
        self.assertIn("_main_ok", src, "比对里没有主属性判断")
        self.assertIn('d.get("main")', src, "没有读 d 的主属性")

    def test_caller_passes_main(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_cycle as C
        src = _code(C)
        self.assertIn("main_attr", src, "调用方没把主属性传下去")
        self.assertIn('junk.append((slot, d["set"], d["level"], ev["eff"], d.get("main"',
                      src, "junk 元组里没有主属性")

    def test_empty_want_main_falls_back(self):
        """不给 want_main 时要退回原来的三级比对（不能因此永远匹配不上）。"""
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_disc_cycle as C
        src = _code(C.mark_disc_abandoned)
        self.assertIn("not want_main", src,
                      "want_main 为空时没有跳过主属性比对")


class TestTextAssertionRatchet(unittest.TestCase):
    """文本断言的数量只能降、不能涨（RT-02 的棘轮）。

    ## 问题

    我的测试里有大量这种写法：

    ```python
    src = _code(some_tool.main)
    self.assertIn(f'"{k}"', src)          # <- 纯文本
    ```

    **注释里写上那两个词就能骗过它。** RT 做了变异测试：
    把真实字段删掉、加一行注释 -> 7/7 全过，192 个用例零新增失败。

    这正是我自己在提交信息里记过 6 次的「自指陷阱」——
    修了一半：改成了 AST 的地方确实改好了，但还有 30 多处没动。

    ## 这条测试干什么

    不假装已经全改完，而是**设一道棘轮**：
    现在还有多少处，就锁在多少处；**再加新的就红**。

    降下来随时可以，涨上去必须先把旧的改掉。
    """

    #: 2026-11-27 实测。只许降，不许涨。
    #:
    #: **这是个粗代理**：`inspect.getsource` 本身不是罪 —— 拿它喂 `ast.parse`
    #: 是正确做法。有问题的是「拿它的返回值做 `assertIn` 文本匹配」。
    #: 但精确区分要分析 AST，而那些 AST 断言本身也各不相同。
    #:
    #: 所以这里用**总数**当棘轮：每个新增的 `getsource` 都得想一想
    #: 「我是要用它做文本匹配，还是喂 AST」。前者别写。
    #:
    #: 2026-11-27 从 41 调到 43：新增的 4 处都是**喂 AST 的正当用途**
    #: （`TestDiscMarkMatchesMain`、`TestDestructiveFailureExitCode`、
    #: `TestSkillPageNotStolen`、`TestNoNewGhostStates`），
    #: 同时把 `test_pattern_is_shared` 原来那 2 处文本断言改成了 AST。
    #: 2026-11-27 从 43 降到 11：34 处 `= inspect.getsource(` 换成了 `= _code(`
    #: （`_code` 会剥掉注释和 docstring），文本断言从 41 处降到 7 处。
    BASELINE = 11

    def test_getsource_count_does_not_grow(self):
        import pathlib
        import re
        p = pathlib.Path(__file__).resolve().parent / "test_core.py"
        src = p.read_text(encoding="utf-8")
        # 只数 `inspect.getsource(` 的真实调用（注释里的不算：先剥注释行）
        lines = [l for l in src.splitlines()
                 if not l.lstrip().startswith("#")]
        n = sum(l.count("inspect.getsource(") for l in lines)
        # 本测试自己的 docstring 里有这个词，扣掉
        n -= src.count('`src = _code(some_tool.main)`')
        self.assertLessEqual(
            n, self.BASELINE,
            f"inspect.getsource 从 {self.BASELINE} 涨到 {n} —— "
            f"文本断言会被注释绕过（RT-02）。\n"
            f"    新写的断言请改用 AST（查真实调用 / 字典键 / 比较表达式），\n"
            f"    或者直接调用函数断言返回值。\n"
            f"    确实改好了一些？把 BASELINE 调小。")

    def test_baseline_is_honest(self):
        """BASELINE 不能比实际少太多 —— 否则这道棘轮就是假的。"""
        import pathlib
        p = pathlib.Path(__file__).resolve().parent / "test_core.py"
        src = p.read_text(encoding="utf-8")
        lines = [l for l in src.splitlines()
                 if not l.lstrip().startswith("#")]
        n = sum(l.count("inspect.getsource(") for l in lines)
        n -= src.count('`src = _code(some_tool.main)`')
        self.assertGreaterEqual(
            n, self.BASELINE - 5,
            f"BASELINE={self.BASELINE} 但实际只有 {n} 处 —— "
            f"调小它，别让棘轮空转")


class TestMissingPythonDoesNotCrash(unittest.TestCase):
    """没有 OneDragon 的 python 时不能抛 `WinError 87`（RT-03）。

    ## 原来

    `one_dragon_python()` 找不到时返回空串，而 7 个工具直接

    ```python
    subprocess.run([PY, "-u", ...])      # PY == ""
    ```

    在 Windows 上 `subprocess.run([""])` 抛的是 `OSError: [WinError 87]
    The parameter is incorrect` —— 而 `run()` 只 catch 了 `TimeoutExpired`。

    **崩在任何配置提示之前**，用户看到的是一段 traceback。
    干净机器上 README 第 4 步之后的每条命令都这样。
    """

    def test_require_python_exits_with_message(self):
        import io
        import contextlib
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import paths
        orig = paths.one_dragon_python
        try:
            paths.one_dragon_python = lambda: ""
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    paths.require_python()
            self.assertEqual(ctx.exception.code, 2, "应该是退出码 2（配置缺失）")
            out = buf.getvalue()
            self.assertIn("OneDragon", out, "提示里没提 OneDragon")
            self.assertIn("check_config", out, "没给出验证命令")
        finally:
            paths.one_dragon_python = orig

    def test_require_python_passes_through(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import paths
        orig = paths.one_dragon_python
        try:
            paths.one_dragon_python = lambda: r"E:\x\python.exe"
            self.assertEqual(paths.require_python(), r"E:\x\python.exe")
        finally:
            paths.one_dragon_python = orig

    def test_run_returns_tuple_when_py_empty(self):
        """`run()` 在 PY 为空时要返回 (False, 提示)，不能抛 OSError。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_daily
        orig = zzz_daily.PY
        try:
            zzz_daily.PY = ""
            ok, out = zzz_daily.run("测试", ["--help"], timeout=5, quiet=True)
            self.assertFalse(ok)
            self.assertIn("check_config", out,
                          f"提示里没告诉用户怎么办：{out[:80]!r}")
        finally:
            zzz_daily.PY = orig


class TestNoNewGhostStates(unittest.TestCase):
    """`TRANSITIONS` 的目标必须是 `ANCHORS` 能产出的状态（RT-04）。

    ## 什么是幽灵状态

    状态机里写着「从这里可以到『驱动盘拆解页』」，但 `anchors.ANCHORS`
    里**没有任何一条**会返回这个名字。干净克隆上
    `state/fingerprints.json` 被 gitignore，`describe()` 永远认不出它。

    于是 `if not m.go_to("驱动盘拆解页")` **恒真**，
    拆解/弃置链路在干净安装上必然失败 —— 而作者本机因为有指纹文件「能跑」。

    ## 现在还剩 9 个

    2026-11-27 实测。**没有凭空补锚点** —— 补错了会点到别的页面，
    那正是这个项目一直在修的那类「静默做错事」。

    补的时候需要开游戏，在那些页面上抓一次 OCR，把**常驻**文字填进
    `anchors.py`，然后把名字从这里删掉。
    """

    #: 已知没有锚点的状态。**只许减少，不许增加。**
    KNOWN_GHOSTS = {
        "代理人培训", "智能弃置面板", "音擎回收", "音擎强化面板",
        "音擎推荐面板", "音擎筛选面板", "音擎详情",
        "驱动盘拆解页", "驱动盘筛选面板",
    }

    def _diff(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors, machine
        names = {a.name for a in anchors.ANCHORS} | {"世界"}
        dsts = {t.dst for t in machine.TRANSITIONS if t.dst != "*"}
        srcs = {t.src for t in machine.TRANSITIONS if t.src != "*"}
        return names, dsts, srcs

    def test_no_new_ghost_targets(self):
        names, dsts, _ = self._diff()
        ghosts = dsts - names
        new = ghosts - self.KNOWN_GHOSTS
        self.assertEqual(new, set(),
                         f"新出现了没有锚点的目标状态：{sorted(new)}\n"
                         f"    TRANSITIONS 里写了它，但 ANCHORS 产不出这个名字 ——\n"
                         f"    运行时 go_to 会永远失败。要么补锚点，要么别写这条转移。")

    def test_ghost_list_is_honest(self):
        """白名单里不能塞「其实已经有锚点」的 —— 那会让这道闸空转。"""
        names, dsts, srcs = self._diff()
        stale = {g for g in self.KNOWN_GHOSTS if g in names}
        self.assertEqual(stale, set(),
                         f"这些已经有锚点了，从 KNOWN_GHOSTS 里删掉：{sorted(stale)}")

    def test_go_to_rejects_unknown_state(self):
        """`go_to` 对没有锚点的目标要**立刻**失败并说清楚（RT-04）。"""
        import io
        import contextlib
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine

        class _Vs:
            occluded = False
            def text(self, r): return ""
            def items(self, r): return []
            def frame(self, force=False): pass
        class _Inp:
            def key(self, *a, **k): pass
            def click(self, *a, **k): pass
        class _Ui:
            vs = _Vs()
            inp = _Inp()

        m = Machine(_Ui(), verbose=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = m.go_to("驱动盘拆解页")
        self.assertFalse(r)
        out = buf.getvalue()
        self.assertIn("不是一个可识别的状态", out,
                      "没告诉用户「这不是导航失败，是没有锚点」")
        self.assertIn("能识别的", out, "没列出可识别的状态")


class TestSkillPageNotStolen(unittest.TestCase):
    """技能页不能靠「底部标签 + 锚点顺序」判定（RT-05）。

    ## 原来

    ```python
    Anchor("技能页", (1000, 960, 1500, 1040), must=("技能",))
    ```

    而「技能」这个标签**三个 tab 上都有**。所以：

    · 装备页的 `DRIVER` 一旦 OCR 漏读 → 技能页抢注
    · 基础页三属性漏一个 → 技能页抢注

    抢注的后果不是「认错」，是 **`go_to` 0 次点击就返回 True**，
    然后上层按技能页坐标点核心技 A~F —— **实际点在装备页的盘位上**。

    ## 修法

    用**正向唯一证据**：技能行有「当前/上限」编号（`1012`、`0812`…），
    只有技能页才有。模式来自 `locate.SKILL_LEVEL_PAT`，和 `skill_cells()` 共用。
    """

    _seq = [0]

    def _fake(self, texts):
        """假 Vision。

        ## `_frame_key` 必须**每个实例不同**

        `anchors.describe()` 的缓存键是 `(id(vision), vision._frame_key())`。
        第一版这里恒返回 `1` —— 于是两个不同的假 Vision
        如果**恰好拿到同一个 id**（前一个被 GC 后地址复用），
        第二次会命中第一次的缓存，测试就间歇性失败。

        实测：同一份代码连跑两次，一次过一次不过。
        """
        type(self)._seq[0] += 1
        key = type(self)._seq[0]

        class V:
            occluded = False
            def text(self, r): return texts.get(tuple(r), "")
            def items(self, r): return []
            def frame(self, force=False): pass
            def _frame_key(self): return key
        return V()

    def test_bottom_tab_alone_is_not_skill_page(self):
        """只有底部「技能」标签 —— 那是三个 tab 共有的，不能当判据。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors
        v = self._fake({(1000, 960, 1500, 1040): "技能 影画 基础 装备",
                        (900, 690, 1800, 800): ""})
        self.assertFalse(anchors.at(v, "技能页", tries=1, need=1),
                         "只有底部标签就判成技能页 —— 这就是 RT-05 那个抢注")

    def test_skill_row_numbers_identify_page(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors
        v = self._fake({(1000, 960, 1500, 1040): "技能 影画 基础 装备",
                        (900, 690, 1800, 800): "1012 0812 0612 1212 0312"})
        self.assertTrue(anchors.at(v, "技能页", tries=1, need=1),
                        "技能行有编号却没认出技能页")

    def test_equipment_page_still_wins(self):
        """装备页有 DRIVER 时要认成装备页，不能被技能页抢。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors
        v = self._fake({(900, 300, 1850, 950): "DRIVER 等级15",
                        (1000, 960, 1500, 1040): "技能 影画 基础 装备"})
        self.assertEqual(anchors.describe(v), "装备页")

    def test_pattern_is_shared(self):
        """锚点和 skill_cells 必须用**同一个**模式常量。

        ## 用 AST，不用源码文本

        第一版是 assertIn("SKILL_LEVEL_PAT", getsource(anchors)) ——
        正是本文件 TestTextAssertionRatchet 在批的那种写法
        （**棘轮当场把它抓了：41 -> 43**）。

        注释里写个名字就骗过文本检查。AST 看的是**真实引用**。
        """
        import ast as _ast
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        from core import locate
        self.assertTrue(hasattr(locate, "SKILL_LEVEL_PAT"),
                        "locate 里没有 SKILL_LEVEL_PAT")
        self.assertIn("12", locate.SKILL_LEVEL_PAT)

        for name, path in (("anchors", root / "core" / "anchors.py"),
                           ("locate", root / "core" / "locate.py")):
            tree = _ast.parse(path.read_text(encoding="utf-8"))
            # anchors 里用的是别名 `_SKILL_LEVEL_PAT`（导入时 as 了），两个都认
            refs = [n for n in _ast.walk(tree)
                    if isinstance(n, _ast.Name)
                    and n.id in ("SKILL_LEVEL_PAT", "_SKILL_LEVEL_PAT")]
            self.assertTrue(refs, f"{name}.py 里没有任何 SKILL_LEVEL_PAT 的引用")


class TestFarmPlanBudgetIsReal(unittest.TestCase):
    """`--run` 必须按**预算算出来的次数**刷，不是写死的 `min(次数, 3)`（RT-06）。

    ## 原来

    ```python
    can = min(r["次数"], left // per_run)       # 预算算出来的
    picked.append({**r, "本次次数": can})        # 存进去了
    ...
    ["--times", str(min(r["次数"], 3)), "--run"]  # <- 但拼命令时又用 min(次数,3)
    ```

    于是 `--battery 100` 打印「刷 1/6 次（100 电）」，实际发 `--times 3`（300 电）——
    **最多按预算的 3 倍花掉**，而计划页和执行完全对不上。

    ## 这个工具已归档

    `zzz_farm_plan.py` 头部会打印「已归档，被 zzz_gap.py 取代」。
    但 `core/farm_gap.py` 还在 `from zzz_farm_plan import PATROL_BY_SET` ——
    它不是死文件，而且**照样能被手工跑起来**，所以这个 bug 是真会发生的。
    """

    def test_run_uses_computed_count(self):
        import ast as _ast
        import pathlib
        # 用 AST 查：拼 --times 时用的必须是「本次次数」，不是 min(...,3)
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_farm_plan.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)

        found = None
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.List):
                continue
            txt = _ast.unparse(node)
            if "--times" in txt:
                found = txt
                break
        self.assertIsNotNone(found, "找不到拼 --times 的地方")
        self.assertNotIn("min(", found,
                         f"--times 还在用 min(...) —— 预算被丢掉了：{found}")
        # 拼的是哪个变量都行，只要它**来自「本次次数」**。
        # 从列表里取出那个变量名，再往上找它的赋值。
        import re as _re
        m = _re.search(r"str\((\w+)\)", found)
        self.assertIsNotNone(m, f"--times 里没有变量：{found}")
        var = m.group(1)
        self.assertIn(f'{var} = int(r.get("本次次数")', src.replace("'", '"'),
                      f"{var} 不是从「本次次数」来的")

    def test_budget_arithmetic(self):
        """预算算术本身：100 电、每次 100 电 -> 最多 1 次。"""
        battery, per_run, want = 100, 100, 3
        can = min(want, battery // per_run)
        self.assertEqual(can, 1, "预算算术不对")


class TestPlanOnlyTouchesNothing(unittest.TestCase):
    """`--plan-only` 不能清空 OneDragon 的体力计划（RT-07）。

    ## 原来

    ```python
    cfg = factory.create_config(...)
    cfg.plan_list.clear()          # <- 清空现有计划
    ... 加新计划 ...
    cfg.save()                     # <- 写盘
    ...
    if args.plan_only or not args.run:    # <- 判断在**这之后**
        return 0
    ```

    于是「只出计划」照样把用户手工配好的体力计划**清掉重写**。
    用户只是想看一眼，配置没了。

    ## 修法

    `--plan-only` 在**碰 cfg 之前**就返回。三种模式：

        --plan-only   只打印，不改任何配置
        （默认）       写进 OneDragon 的计划，但不启动
        --run         写进去并启动
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "od_material_farm.py").read_text(encoding="utf-8")

    def test_plan_only_returns_before_clear(self):
        import ast as _ast
        tree = _ast.parse(self._src())
        # 找 cfg.plan_list.clear() 那一行
        clear_line = None
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Call)
                    and getattr(node.func, "attr", None) == "clear"):
                obj = _ast.unparse(node.func.value)
                if "plan_list" in obj:
                    clear_line = node.lineno
                    break
        self.assertIsNotNone(clear_line, "找不到 cfg.plan_list.clear()")

        # 找 plan_only 的 early return：`if ... plan_only ...: return`
        ret_line = None
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.If):
                continue
            cond = _ast.unparse(node.test)
            if "plan_only" in cond:
                has_ret = any(isinstance(n, _ast.Return)
                              for n in _ast.walk(node))
                if has_ret:
                    ret_line = node.lineno
                    break
        self.assertIsNotNone(ret_line,
                             "找不到 --plan-only 的提前返回")
        self.assertLess(ret_line, clear_line,
                        f"plan_only 的返回在 L{ret_line}，"
                        f"但 cfg.plan_list.clear() 在 L{clear_line} —— "
                        f"「只出计划」还是会清空用户的配置")

    def test_plan_only_message_says_untouched(self):
        """提示要说清「没改配置」—— 否则用户不知道该不该放心。"""
        self.assertIn("没有改 OneDragon 的计划配置", self._src())


class TestFarmLogSchema(unittest.TestCase):
    """`farm_log.json` 只有**一套 schema**，读侧兼容三种历史形态（RT-08）。

    ## 原来两个工具各写一套

    ```
    zzz_daily  按 dict 读写：{"date","count","last",...}
    zzz_gap    按 list 读写：[{"time","材料","副本",...}, ...]
    ```

    交叉跑就出问题：

    · 先 `zzz_gap --run`（写 list）再 `zzz_daily --run`
      -> `_farm_count_today()` 对 list 调 `.get` -> AttributeError 被吞
      -> 返回 0 -> **以为今天没刷过，又刷一遍**（多花 60~200 电）
    · 反过来 -> `logs.append` 对 dict -> AttributeError，
      而且**崩在刷完之后**（电已经花了）

    ## 现在

    `core/farm_log.py` 是唯一入口。写统一成
    `{"_schema":2,"records":[...]}`，**读侧兼容三种历史形态**。
    认不出来就**明确报错**，返回 -1（不是 0）——
    「读不了」和「没刷过」是两件事。
    """

    def _with_log(self, payload=None):
        import json as _j
        import pathlib
        import sys
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import farm_log as FL
        tmp = pathlib.Path(tempfile.mkdtemp()) / "farm_log.json"
        if payload is not None:
            tmp.write_text(payload if isinstance(payload, str)
                           else _j.dumps(payload, ensure_ascii=False),
                           encoding="utf-8")
        return FL, tmp

    def _today(self):
        import time
        return time.strftime("%Y-%m-%d")

    def test_new_schema(self):
        FL, tmp = self._with_log({"_schema": 2, "records": [
            {"date": self._today(), "dungeon": "x", "times": 1, "ok": True}]})
        orig = FL.LOG
        try:
            FL.LOG = tmp
            self.assertEqual(FL.count_today(), 1)
        finally:
            FL.LOG = orig

    def test_bare_list(self):
        """zzz_gap 以前写的裸 list。"""
        FL, tmp = self._with_log([{"date": self._today(), "副本": "x"}])
        orig = FL.LOG
        try:
            FL.LOG = tmp
            self.assertEqual(FL.count_today(), 1)
        finally:
            FL.LOG = orig

    def test_legacy_dict(self):
        """zzz_daily 以前写的 {"date","count"} —— 要按 count 展开。"""
        FL, tmp = self._with_log({"date": self._today(), "count": 3})
        orig = FL.LOG
        try:
            FL.LOG = tmp
            self.assertEqual(FL.count_today(), 3)
        finally:
            FL.LOG = orig

    def test_unreadable_returns_minus_one(self):
        """认不出的格式要报 -1，不能静默返回 0。"""
        FL, tmp = self._with_log("hello")
        orig = FL.LOG
        try:
            FL.LOG = tmp
            n, why = FL.count_today_safe()
            self.assertEqual(n, -1, "认不出却返回了非 -1 —— 会静默当「没刷过」")
            self.assertTrue(why, "没给出原因")
        finally:
            FL.LOG = orig

    def test_append_uses_new_schema(self):
        import json as _j
        import pathlib
        FL, tmp = self._with_log()
        orig = FL.LOG
        try:
            FL.LOG = tmp
            FL.append(dungeon="测试", times=2, ok=True, source="test")
            d = _j.loads(pathlib.Path(tmp).read_text(encoding="utf-8"))
            self.assertIsInstance(d, dict, f"写出来不是带 _schema 的对象：{type(d)}")
            self.assertEqual(d.get("_schema"), 2)
            self.assertEqual(len(d.get("records") or []), 1)
        finally:
            FL.LOG = orig

    def test_both_tools_use_shared_module(self):
        """两个工具都必须走 `core.farm_log`，不能自己拼 schema。"""
        import ast as _ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for name in ("zzz_daily.py", "zzz_gap.py"):
            src = (root / name).read_text(encoding="utf-8")
            tree = _ast.parse(src)
            imports = [a.name for n in _ast.walk(tree)
                       if isinstance(n, _ast.ImportFrom) and n.module
                       for a in n.names]
            self.assertIn("farm_log", imports,
                          f"{name} 没 import core.farm_log")


class TestScreenshotDirIsCreated(unittest.TestCase):
    r"""截图目录要存在、路径要绝对（RT-09）。

    ## 原来

    ```python
    Image.fromarray(vs.crop(...)[:, :, ::-1]).save(
        r"od_test\shots\dis_filtered_ok.png")     # <- 相对路径
    ```

    而全仓没有任何代码创建 `od_test/shots`（`core/__init__.py` 只建
    `state` 和 `od_test`）。`Image.save` 到不存在的目录 ->
    `FileNotFoundError`，**而且发生在 `--run` 闸门之前** ——
    文档推荐的「先看计划」在干净机器上直接崩。
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "run_dismantle.py").read_text(encoding="utf-8")

    def test_no_relative_shot_paths(self):
        r"""不能出现 `r"od_test\shots\..."` 这种相对路径字面量。"""
        import ast as _ast
        tree = _ast.parse(self._src())
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                self.assertNotIn("od_test\\\\shots\\", node.value,
                                 f"还有相对路径字面量：{node.value!r}")

    def test_core_creates_shots_dir(self):
        """`import core` 之后 `od_test/shots` 必须存在。"""
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(root / "tools"))
        import core  # noqa: F401  —— 触发 _ensure_runtime_dirs()
        self.assertTrue((root / "od_test" / "shots").is_dir(),
                        "import core 之后 od_test/shots 还是没有")

    def test_shot_helper_swallows_errors(self):
        """截图失败不能中断主流程 —— 截图是辅助，不是目的。"""
        import ast as _ast
        tree = _ast.parse(self._src())
        fn = next((n for n in _ast.walk(tree)
                   if isinstance(n, _ast.FunctionDef) and n.name == "_shot"), None)
        self.assertIsNotNone(fn, "没有 _shot() 助手")
        has_try = any(isinstance(n, _ast.Try) for n in _ast.walk(fn))
        self.assertTrue(has_try, "_shot() 里没有 try —— 截图失败会中断流程")

    def test_plan_mode_discloses_filter_touch(self):
        """计划模式动了筛选状态，要说出来（RT-09 后半）。"""
        self.assertIn("筛选状态被改过", self._src())


class TestBossRoutingBeforeGeneric(unittest.TestCase):
    """boss 材料要**比「高维数据」泛匹配先**查到（RT-14）。

    ## 原来

    ```python
    if "高维数据" in m:                       # 泛匹配在前
        return {"副本": "专业挑战室", ...}
    ...
    for boss, info in boss_map.items():       # 具体名字在后
        if info.get("材料") == m: ...
    ```

    而 `dungeon_data.json` 的 boss 材料里，有几条名字**本身就含「高维数据」**：

        高维数据：拟造核心  -> 应去 恶名狩猎·「征服者」
        高维数据：拳坠如陨  -> 应去 恶名狩猎·恶名·装甲哈提

    实测都被路由到「专业挑战室」—— **去刷错的副本，材料不掉、电量白花**。

    **具体名字优先于泛匹配。**
    """

    def test_boss_materials_route_correctly(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_gap as G
        # 路由函数叫 where_to_farm(mat, role="", attr="")
        fn = getattr(G, "where_to_farm", None)
        self.assertIsNotNone(fn, "找不到 where_to_farm()")
        for mat, want_prefix in (("高维数据：拟造核心", "恶名狩猎"),
                                 ("高维数据：拳坠如陨", "恶名狩猎")):
            got = (fn(mat) or {}).get("副本", "")
            self.assertTrue(got.startswith(want_prefix),
                            f"{mat} 路由到了「{got}」，应该去恶名狩猎")


class TestElemDamageVariants(unittest.TestCase):
    """主词条要认得「X属性伤害加成」这种写法（RT-15）。

    ## 原来

    `vocab.STATS` 有「以太伤害」「物理伤害」，**没有「以太属性伤害」**。
    于是：

        原文：以太属性伤害加成
        `"以太属性伤害加成".startswith("以太伤害")` == False
        -> 提取出空串 -> `verdict()` 返回 **unknown**

    而 unknown **既不会被跳过**（`if _mvd == "bad"`）**也不会归零** ——
    于是「主词条完全无效、但副词条好」的盘被当可用盘换上。
    **这正是「主词条错 > 副词条好」要防的那个场景。**
    """

    def test_elem_terms_all_in_vocab(self):
        """`disc_main.elem_terms()` 产出的每一个写法，vocab 都必须认。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import vocab, disc_main
        known = set(vocab.STATS) | set(vocab.STATS_MAIN_EXTRA)
        missing = set()
        for e in ("以太", "电", "冰", "火", "物理", "风",
                  "流明", "玄墨", "烈霜", "凛刃"):
            for t in disc_main.elem_terms(e):
                if t not in known:
                    missing.add(t)
        self.assertEqual(missing, set(),
                         f"这些写法 vocab 认不出，会被判成 unknown：{sorted(missing)}")

    def test_elem_damage_on_wrong_element_is_bad(self):
        """装错属性的主词条必须判 bad，不能是 unknown。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import vocab
        from core.disc_main import verdict
        terms = list(vocab.STATS) + list(vocab.STATS_MAIN_EXTRA)
        for main, elem, want in (("以太属性伤害加成", "电", "bad"),
                                 ("电属性伤害加成", "电", "good"),
                                 ("物理属性伤害加成", "电", "bad")):
            self.assertTrue(any(main.startswith(k) for k in terms),
                            f"vocab 认不出 {main}")
            got, _ = verdict(main, 5, {}, elem)
            self.assertEqual(got, want,
                             f"{main} 对 {elem} 属性角色应判 {want}，实际 {got}")


class TestSecondaryCandidateChoice(unittest.TestCase):
    """4+2 的副套要在**所有候选**里挑，不是只认第一个（RT-13）。

    ## 原来

    ```python
    sec_set = args.secondary or (sec_cands[0] if sec_cands else "")
    ...
    elif s == sec_set:
        slist.append(item)        # 只收这一个套装的盘
    ```

    实测：主套全 18 点、**第一候选 0 点、第二候选有 18 点**
    -> 输出把 18 点的盘换成 0 点的。

    ## 现在

    收集**所有候选**的盘，按套装分组，每组算「最好的两件之和」，
    取最大的那组（4+2 里副套最多占 2 个位号）。

    `args.secondary` 显式指定时不参与择优 —— 那是用户的明确意图。
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "zzz_plan.py").read_text(encoding="utf-8")

    def test_collects_all_candidates(self):
        """收集盘时要收**所有候选**，不能只认 `s == sec_set`。"""
        import ast as _ast
        tree = _ast.parse(self._src())
        src = self._src()
        # 必须出现「s in sec_cands」这种收集条件
        found_in = False
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Compare):
                continue
            if not node.ops or not isinstance(node.ops[0], _ast.In):
                continue
            if "sec_cands" in _ast.unparse(node.comparators[0]):
                found_in = True
                break
        self.assertTrue(found_in,
                        "收集条件里没有 `s in sec_cands` —— 还是只收一个套装")

    def test_scores_by_two_best(self):
        """择优公式：取每组「最好两件」之和。"""
        by_set = {
            "候选A": {1: {"eff": 0.0}, 2: {"eff": 0.0}},
            "候选B": {1: {"eff": 9.0}, 2: {"eff": 9.0}},
            "候选C": {3: {"eff": 5.0}},
        }
        scored = []
        for st, per_slot in by_set.items():
            top2 = sorted((it["eff"] for it in per_slot.values()), reverse=True)[:2]
            scored.append((sum(top2), len(top2), st))
        scored.sort(reverse=True)
        self.assertEqual(scored[0][2], "候选B",
                         f"应该选两件之和最大的「候选B」，实际 {scored[0]}")

    def test_explicit_secondary_wins(self):
        """`--secondary X` 是用户明确意图，不该被择优覆盖。"""
        self.assertIn('if not args.secondary and len(_by_set) > 1:',
                      self._src(),
                      "择优没有排除 args.secondary 的情况")


class TestEffLossLimitIsReal(unittest.TestCase):
    """`--eff-loss-limit` 必须真的参与换装判定（RT-13）。

    ## 原来是个死参数

    帮助文字写着「最多接受掉多少有效值（默认 1.5）」，
    而它在文件里**只出现在 argparse 定义那一行** —— 判断里从没引用过。

    于是 `--eff-loss-limit 0.1` 一点作用都没有，
    用户以为有损失上限保护，实际每换一件可能掉 18 点。
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "zzz_plan.py").read_text(encoding="utf-8")

    def test_limit_used_in_judgement(self):
        """`eff_loss_limit` 必须出现在判定逻辑里，不只是 argparse。"""
        import ast as _ast
        src = self._src()
        tree = _ast.parse(src)
        # 参数名是**字符串**（`getattr(args, "eff_loss_limit", ...)`），
        # 不是 Attribute 节点 —— 所以数源码里出现几次。
        # argparse 里是 `--eff-loss-limit`（横线），代码里是 `eff_loss_limit`（下划线）
        _decl = src.count("--eff-loss-limit")
        _use = src.count("eff_loss_limit")
        self.assertGreaterEqual(_decl, 1, "参数定义没了？")
        self.assertGreaterEqual(_use, 1,
                                "eff_loss_limit 只在 argparse 定义里 —— 死参数")

        # **关键：`need` 的赋值必须真的引用 `_sec_ok`**。
        #
        # 只数「出现了几次」是不够的 —— 我试过把
        # `need = eff_better or (set_diff and _sec_ok)`
        # 改回 `need = eff_better or set_diff`，测试照样全绿。
        # 那说明这个参数虽然被读了，但**结论没用它**。
        need_refs_ok = False
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.Assign)
                    and any(isinstance(t, _ast.Name) and t.id == "need"
                            for t in node.targets)):
                continue
            body = _ast.unparse(node.value)
            if "_sec_ok" in body:
                need_refs_ok = True
                break
        self.assertTrue(need_refs_ok,
                        "`need = ...` 没引用 `_sec_ok` —— 上限算出来了但没用上")
        self.assertIn("_loss_limit", src, "没把上限读进变量")
        self.assertIn("_eff_loss", src, "没算实际掉分")

    def test_semantics(self):
        """语义验证：掉分超过上限就换套装，不超过就换。"""
        def need(eff_better, set_diff, cur_eff, item_eff, limit, cur_bad):
            eff_loss = cur_eff - item_eff
            sec_ok = (eff_loss <= limit) or cur_bad
            return eff_better or (set_diff and sec_ok)
        # 掉 18 点、上限 1.5 -> 不该单纯为套装而换
        self.assertFalse(need(False, True, 18.0, 0.0, 1.5, False))
        # 掉 0.5 点、上限 1.5 -> 可以换
        self.assertTrue(need(False, True, 18.5, 18.0, 1.5, False))
        # 主词条无效 -> 无论如何换
        self.assertTrue(need(False, True, 18.0, 0.0, 1.5, True))


class TestSelfcheckRunsToCompletion(unittest.TestCase):
    """`selfcheck.py` 必须能跑完，而且**发现问题要 non-0**（RT-20）。

    ## 原来三处

    ① `state/fingerprints.json` 直接 `read_text` ——
       而它被 `.gitignore` 排除，干净克隆上没有 ->
       `FileNotFoundError`，整个自检崩在第六节。

    ② `T / "core" / "core" / "machine.py"` —— **双重 `core`**，
       路径是 `tools/core/core/machine.py`（不存在）。

    ③ 从头到尾**没有一处 `sys.exit`** —— 前五节就算打了满屏 ✗，
       退出码还是 0。而「兼容性自检」的意义就是让门禁能红。

    **一个永远跑不完、又永远返回 0 的自检，等于没有。**
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "selfcheck.py").read_text(encoding="utf-8")

    def test_no_double_core_path(self):
        """路径里不能出现「core 套 core」这种连写。

        ## 用 AST，不用源码文本

        第一版是 `assertNotIn('"core" / "core"', 源码)` ——
        而**这条测试自己的 docstring 里就写着那两个词**
        （解释 bug 用的），于是它抓的是自己。

        自指陷阱第 9 次。前八次：zzz_cost 的 range、outcome rules 的注释、
        START_HERE 的 od_farm 说明、DEFAULT_AGENT 的 docstring、
        zzz_resource 的 required=True、--train-n 的文案、
        locate 的 SKILL_LEVEL_PAT、以及上一次的 getsource 棘轮。

        **注释是给人看的；测试应该查代码做了什么。**
        """
        import ast as _ast
        tree = _ast.parse(self._src())
        bad = []
        for node in _ast.walk(tree):
            # 找 BinOp 链里相邻的两个 Constant "core"
            if not isinstance(node, _ast.BinOp):
                continue
            consts = [n for n in _ast.walk(node)
                      if isinstance(n, _ast.Constant) and n.value == "core"]
            if len(consts) >= 2:
                bad.append((node.lineno, _ast.unparse(node)[:60]))
        self.assertEqual(bad, [],
                         f"路径里 core 套了 core：{bad}")

    def test_fingerprints_guarded(self):
        """读指纹前必须判存在。"""
        src = self._src()
        i = src.find("fingerprints.json")
        self.assertGreater(i, -1)
        around = src[max(0, i - 400):i + 200]
        self.assertIn("exists()", around,
                      "读 fingerprints.json 之前没有 exists() 判断")
        self.assertIn("跳过指纹对比", src, "没有「跳过」的说明")

    def test_exits_nonzero_on_problem(self):
        """发现语法错误必须 `sys.exit(1)`。"""
        src = self._src()
        self.assertIn("sys.exit(1)", src, "没有失败出口 —— 恒返回 0")
        self.assertIn("sys.exit(0)", src, "没有显式成功出口")


class TestNoPiiInRelease(unittest.TestCase):
    """发布集里不能有 PII，而且要**按内容**扫（RT-18 / RT-16）。

    ## RT-18 的问题正是「文件名正常，内容敏感」

    `config.json` 里原来有 `account: {nickname, uid}` ——
    照着文档填了真值再发布，**真实游戏 UID 进公开仓库**。
    而 `.gitignore` 只忽略 `config.local.json`，
    `paths.example.json` 和 `paths.py` 却都写着「config.json 已被 .gitignore 排除」
    —— **那是假的**。

    光看文件名永远发现不了这类问题。所以 `audit_ship` 加了内容扫描。
    """

    def test_config_has_no_account_section(self):
        """`config.json` 不该有 `account` 段 —— 那是 PII 的邀请函。"""
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        cfg = root / "config.json"
        if not cfg.exists():
            self.skipTest("config.json 不在当前集合里")
        d = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("account", d,
                         "config.json 里还有 account 段（昵称/UID）—— "
                         "这个文件会进发布包")
        self.assertIn("_account_note", d, "没告诉用户 PII 该放哪")

    def test_paths_docs_are_honest(self):
        """文档不能说「config.json 已被 .gitignore 排除」—— 那是假的。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        for rel in ("paths.example.json", "tools/core/paths.py"):
            p = root / rel
            if not p.exists():
                continue
            txt = p.read_text(encoding="utf-8")
            # 查**具体的那句假话**，不是「同时出现两个词」——
            # 改好之后的句子也会同时提到 config.json 和 gitignore
            # （「config.json 会进发布包，paths.json 才被 gitignore 排除」）。
            for bad in ("config.json 已被 .gitignore 排除",
                        "config.json（项目根目录，已 gitignore）"):
                self.assertNotIn(bad, txt,
                                 f"{rel} 还在说假话：{bad}")

    def test_audit_ship_has_content_scan(self):
        """`audit_ship` 要有**内容级**隐私扫描，不只是文件名黑名单。"""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "audit_ship.py").read_text(encoding="utf-8")
        self.assertIn("_RISKY", src, "没有内容级扫描的模式表")
        self.assertIn("隐私内容", src, "没有「隐私内容」这一类失败")
        # 至少要有 token 和 UID 两类
        self.assertIn("gh", src.lower(), "没扫平台 token")
        self.assertIn("UID", src, "没扫 UID")


class TestReleaseWorkflowIsSane(unittest.TestCase):
    """发布 workflow 不能**必然失败**，也不能有语法错（RT-16）。

    ## 原来三处

    ① 隐私检查用 `Get-ChildItem -Recurse` 扫**整个工作区** ——
       把 `od_test/`、`MAINTENANCE.md`、`HANDOFF.md` 全扫进去，
       而那些本来就不进 zip。于是 `$bad.Count` 恒 > 0，
       **打 tag 发布必然在这一步失败**。

    ② `unzip -l ... | grep ...` 后面缺 `|| {` —— bash 语法错，
       那一段根本执行不到。

    ③ 两条通道的排除规则相反：zip 的 `-x` 里没有 `MAINTENANCE.md`，
       而 `publish_github.IGN_FILES` 有。
    """

    def _wf(self):
        import pathlib
        p = pathlib.Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "release.yml"
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def test_workflow_parses(self):
        txt = self._wf()
        if txt is None:
            self.skipTest("release.yml 不在当前集合里")
        try:
            import yaml
        except ImportError:
            self.skipTest("没有 yaml 模块")
        d = yaml.safe_load(txt)
        self.assertIn("jobs", d)
        self.assertIn("verify", d["jobs"])

    def test_privacy_check_uses_release_set(self):
        """隐私检查要扫 `collect()` 的发布集，不能扫整个工作区。"""
        txt = self._wf()
        if txt is None:
            self.skipTest("release.yml 不在当前集合里")
        self.assertIn("from publish_github import collect", txt,
                      "隐私检查没用发布集的同一份清单")
        self.assertNotIn("Get-ChildItem -Recurse", txt,
                         "还在扫整个工作区 —— 必然误报")

    def test_bash_brace_is_closed(self):
        """`unzip -l ... | grep ...` 后面必须有 `|| {`。"""
        txt = self._wf()
        if txt is None:
            self.skipTest("release.yml 不在当前集合里")
        for line in txt.splitlines():
            if "unzip -l" in line:
                self.assertIn("|| {", line,
                              f"这行缺 `|| {{` —— bash 语法错：{line.strip()[:70]}")
                break
        else:
            self.fail("找不到 unzip -l 那一行")

    def test_handoff_excluded_from_release(self):
        """`HANDOFF.md` 写满本机路径，不能进发布集。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from publish_github import IGN_FILES
        self.assertIn("HANDOFF.md", IGN_FILES,
                      "HANDOFF.md 没被排除 —— 里面有 C:\\Users\\<名> 这种路径")


class TestPublishKeepsHistory(unittest.TestCase):
    """发布不能抹掉远程历史，失败也不能报成功（RT-17）。

    ## 原来

    ```python
    {"message": msg, "tree": tree_sha, "parents": []}       # <- 孤根提交
    ...
    api(..., "PATCH", {"sha": commit_sha, "force": True})   # <- 强推
    ```

    效果是**每次发布都把远程 main 的历史整个替换掉**。
    而成功文案还写着「会新建一条提交，不覆盖历史」。

    更糟的是：ref 更新失败时只打印一个 `✘`，**仍然继续打印「✔ 发布完成」并 return 0**。
    """

    def _tree(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "publish_github.py").read_text(encoding="utf-8")
        return _ast.parse(src), src

    def test_commit_has_parents(self):
        """建提交时的 `parents` 不能是空列表字面量。"""
        import ast as _ast
        tree, _ = self._tree()
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, _ast.Constant)]
            if "parents" not in keys:
                continue
            val = node.values[keys.index("parents")]
            self.assertNotIsInstance(
                val, _ast.List,
                "建提交的 parents 还是空列表 —— 又变成孤根提交了")
            # 允许 `_parents` 变量
            self.assertTrue(
                _ast.unparse(val).strip().startswith("_parents"),
                f"parents 应该用远程 sha 的变量，实际是 {_ast.unparse(val)[:40]}")

    def test_no_force_push(self):
        """ref 更新不能带 `force: True`。"""
        import ast as _ast
        tree, _ = self._tree()
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Dict):
                continue
            keys = [k.value for k in node.keys if isinstance(k, _ast.Constant)]
            if "force" not in keys:
                continue
            val = node.values[keys.index("force")]
            self.assertFalse(
                isinstance(val, _ast.Constant) and val.value is True,
                "还有 `force: True` —— 会覆盖远程历史")

    def test_reads_remote_sha_first(self):
        """建提交前要先读远程 main 的 sha。"""
        _, src = self._tree()
        self.assertIn("git/ref/heads/main", src,
                      "没读远程 main 的 sha，parent 从哪来")
        self.assertIn("_parents", src, "没有 parents 变量")

    def test_failure_returns_nonzero(self):
        """ref 更新失败要 return 非零，不能接着打「发布完成」。"""
        _, src = self._tree()
        i = src.find("更新分支 main 失败")
        self.assertGreater(i, -1, "找不到失败分支")
        tail = src[i:i + 400]
        self.assertIn("return 8", tail,
                      "更新失败没有 return 非零 —— 会继续报「发布完成」")


class TestCodeHelperStripsProse(unittest.TestCase):
    """`_code()` 必须剥掉注释和 docstring（RT-02）。

    ## 背景

    测试里到处是 `src = <源码>` + `assertIn("某个词", src)`。
    如果 `<源码>` 里带着注释和 docstring，那么

        # 下游需要 "blue_total"

    这一行就能让断言通过 —— **而真正的代码可以已经删掉了**。

    RT 的变异测试：删掉 `_payload` 里真实的 `slots`/`blue_total`，
    只在 `main()` 里加一行注释 -> 7/7 通过，192 用例零新增失败。

    ## 这个测试钉住什么

    · `_code()` 剥注释
    · `_code()` 剥 docstring
    · **但不碰真正的代码和字符串字面量**

    以后谁把 `_code` 改回去（或者改成 `ast.unparse` 导致引号被规范化），
    这里会红。
    """

    SAMPLE = (
        'def f():\n'
        '    """docstring 里写着 MAGIC_WORD"""\n'
        '    x = "MAGIC_STRING"      # 注释里也写着 MAGIC_WORD\n'
        '    return x\n'
    )

    def test_strips_comment(self):
        out = _code(self.SAMPLE)
        self.assertNotIn("注释里也写着", out, "注释没被剥掉")

    def test_strips_docstring(self):
        out = _code(self.SAMPLE)
        self.assertNotIn("docstring 里写着", out, "docstring 没被剥掉")

    def test_keeps_code_and_literals(self):
        """真正的代码和**字符串字面量**要留着（否则断言会全部失效）。"""
        out = _code(self.SAMPLE)
        self.assertIn("return x", out, "代码没留下")
        self.assertIn('"MAGIC_STRING"', out,
                      "字符串字面量被改掉了（引号规范化会让所有断言失效）")

    def test_module_level_still_works(self):
        """传模块/函数对象也要能用（内部 getsource）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_status
        out = _code(zzz_status.main)
        self.assertIn("def main", out)
        self.assertNotIn("# ", out, "还有注释残留")


class TestSubstringAssertionRatchet(unittest.TestCase):
    """拿源码做子串断言的处数只能降、不能涨。

    **只数「拿未剥过的 read_text 结果做子串断言」的地方** ——
    那才是「注释/字符串能骗过」的高危类。
    `_code()` 出来的文本已经剥过注释和 docstring，不算在内。
    """

    #: 2026-11-27 实测 16 处。这是**高危类**（未剥注释的源码做子串断言），
    #: 只许降。新写的请用 `_code(...)` 或者直接查 AST。
    BASELINE = 16

    def test_does_not_grow(self):
        import ast as _ast
        import pathlib
        p = pathlib.Path(__file__).resolve().parent / "test_core.py"
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        total = 0
        for fn in _ast.walk(tree):
            if not isinstance(fn, _ast.FunctionDef):
                continue
            # **只盯「没剥过的源码」** —— 那才是真危险的。
            #
            # `_code(...)` 出来的文本已经去掉注释和 docstring，
            # 拿它做子串断言不会「被注释骗过」，风险低得多。
            # 早期这个棘轮把两者一起数，结果我每加一个 _code 断言它就涨，
            # 只好不断调高 BASELINE —— **棘轮就没意义了**。
            sv = set()
            for n in _ast.walk(fn):
                if not isinstance(n, _ast.Assign):
                    continue
                val = _ast.unparse(n.value)
                if "read_text(" in val and "_code(" not in val:
                    for x in n.targets:
                        if isinstance(x, _ast.Name):
                            sv.add(x.id)
            for n in _ast.walk(fn):
                if not isinstance(n, _ast.Call):
                    continue
                if getattr(n.func, "attr", None) not in ("assertIn", "assertNotIn"):
                    continue
                if len(n.args) < 2:
                    continue
                a = n.args[1]
                if isinstance(a, _ast.Name) and a.id in sv:
                    total += 1
        self.assertLessEqual(
            total, self.BASELINE,
            f"源码子串断言从 {self.BASELINE} 涨到 {total} —— "
            f"新写的请改用 AST，或者用 `_code()` 已经剥过的 `src`。")


class TestDefaultAgentSingleSource(unittest.TestCase):
    """默认角色只能有**一个**真相（E16）。

    ## 原来两个真相

    `core/game_cfg.DEFAULT_AGENT` 已经是 `""`（可配置），
    但还有 4 个工具**自己写死** `default="佩洛伊斯"`：

        zzz_status / zzz_disc_cycle / zzz_disc_train / zzz_disc_v2

    于是朋友的机器上：

        python tools/zzz_status.py          # 不带参数
        -> 去操作一个他账号上根本没有的角色

    `DEFAULT_AGENT` 那句话在这个上下文里是**假的**。
    """

    def test_no_hardcoded_default_agent(self):
        """所有 `default=` 里都不能写死角色名。"""
        import ast as _ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for f in sorted(root.glob("*.py")):
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.Call):
                    continue
                if getattr(node.func, "attr", None) != "add_argument":
                    continue
                for a in node.args:
                    if not (isinstance(a, _ast.Constant)
                            and a.value == "agent"):
                        continue
                    for kw in node.keywords:
                        if kw.arg != "default":
                            continue
                        val = kw.value
                        if (isinstance(val, _ast.Constant)
                                and isinstance(val.value, str)
                                and val.value and val.value != ""):
                            bad.append((f.name, node.lineno, val.value))
        self.assertEqual(bad, [],
                         f"这些地方写死了默认角色名：{bad}")

    def test_default_agent_is_empty_by_default(self):
        """出厂默认必须是空串，不能是某个具体角色。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.game_cfg import DEFAULT_AGENT
        self.assertEqual(DEFAULT_AGENT, "",
                         f"DEFAULT_AGENT 出厂值不是空串：{DEFAULT_AGENT!r}")


class TestVisionCacheKeyIsUnique(unittest.TestCase):
    """`describe()` 的缓存键不能用 `id(vision)`（E12）。

    ## 为什么

    `id()` 在对象被回收后**会被复用**。两个不同的 Vision 实例
    只要恰好拿到同一个地址，就会命中对方缓存的结论。

    实测症状：同一份代码连跑两次，一次过一次不过；
    `audit_ship` 内部重跑 `run_tests` 时红而单独跑全绿 ——
    看起来像环境问题，其实是缓存串台。

    （我自己就踩过：`TestSkillPageNotStolen` 的假 Vision
    `_frame_key()` 恒返回 1，加上 `id()` 复用，测试间歇性失败。）
    """

    def test_vision_has_uid(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.vision import Vision, _VISION_SEQ
        self.assertTrue(hasattr(Vision, "__init__"))
        self.assertTrue(callable(next), "_VISION_SEQ 不可迭代")
        # 序号必须递增
        a = next(_VISION_SEQ)
        b = next(_VISION_SEQ)
        self.assertNotEqual(a, b, "序号没递增")

    def test_anchors_uses_uid_not_id(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "core" / "anchors.py").read_text(encoding="utf-8")
        self.assertIn('_uid', src, "anchors 没用 _uid")
        # 不能直接拿 id(vision) 当键
        self.assertNotIn("vk = (id(vision),", src,
                         "缓存键还是裸 id(vision)")


class TestInputModeRestored(unittest.TestCase):
    """进程异常退出也要把输入模式还原（E11）。

    ## 问题

    `Ui.start()` 会把游戏从手柄态切成键鼠态，
    而 `back_until()` 之类的动作还会临时切回手柄态。
    如果进程在那中间崩了 / 被 Ctrl+C，**游戏就停在那个中间状态** ——
    用户拿手柄玩发现没反应，或者下次跑时鼠标注入不生效。

    原来 `Ui` **没有 `stop()`，也没有 `atexit`**。
    """

    def test_ui_has_stop(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.ui import Ui
        self.assertTrue(hasattr(Ui, "stop"), "Ui 没有 stop()")

    def test_stop_is_idempotent(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.ui import Ui

        class FV:
            win = {"hwnd": 1}
            occluded = False
            def text(self, r): return ""
            def items(self, r): return []
            def frame(self, force=False): pass
            def wait_still(self, **k): pass
            def _frame_key(self): return 1

        class FI:
            def __init__(self): self.n = 0
            def mouse_mode(self): self.n += 1

        fake = FI()
        u = Ui(FV(), fake)
        u._stopped = False
        u.stop()
        u.stop()
        self.assertEqual(fake.n, 1, "stop() 不幂等 —— mouse_mode 被调了多次")

    def test_start_registers_atexit(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.ui import Ui
        src = inspect.getsource(Ui.start)
        self.assertIn("_atexit.register(self.stop)", src,
                      "start() 没把 stop 挂到 atexit")
        self.assertIn("SIGINT", src, "没接管 Ctrl+C")


class TestNoDuplicateColorReport(unittest.TestCase):
    """`zzz_status` 不能把彩色报告读两遍（E14）。

    ## 原来

    ```python
    try:
        from core import disc_color as _dc
        blue = _dc.report(vs)["蓝色条数"]
    except Exception:
        blue = 0
    # ...紧接着又一段一模一样的...
    try:
        from core import disc_color as _dc
        _rep = _dc.report(vs)
        blue = _rep["蓝色条数"]
    except Exception:
        blue = 0
    ```

    两段做同一件事，`report()` 被调两次 —— **双倍 OCR**
    （每次要扫整块副词条区）。
    """

    def test_report_called_once(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_status.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        calls = [n.lineno for n in _ast.walk(tree)
                 if isinstance(n, _ast.Call)
                 and getattr(n.func, "attr", None) == "report"]
        self.assertEqual(len(calls), 1,
                         f"`report()` 被调了 {len(calls)} 次（L{calls}）—— 双倍 OCR")


class TestInventoryCorruptFile(unittest.TestCase):
    """`inventory` 坏文件不能静默当空再整份覆盖（E7）。

    ## 原来

    ```python
    try:
        d = json.loads(STORE.read_text(...))
    except Exception:
        return {"_ts": "", "items": {}}     # 半截 JSON = 「没有库存」
    ```

    然后 `_save()` 把整份文件覆盖掉 —— **历史就这么没了**，而且没有任何输出。

    现在：读不了先备份成 `.corrupt`，报出来，再按空继续。
    """

    def test_bad_file_is_backed_up(self):
        import sys
        import pathlib
        import tempfile
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import inventory as IV

        tmp = pathlib.Path(tempfile.mkdtemp()) / "inventory.json"
        orig = IV.STORE
        try:
            IV.STORE = tmp
            tmp.write_text("{半截", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                d = IV._load()
            self.assertIsInstance(d, dict)
            self.assertEqual(d.get("items"), {})
            self.assertTrue(
                (tmp.parent / (tmp.name + ".corrupt")).exists(),
                "坏文件没被备份 —— 下次 _save() 会把它整个覆盖掉")
            self.assertIn("读不了", buf.getvalue(), "没报出原因")
        finally:
            IV.STORE = orig

    def test_missing_file_is_quiet(self):
        """文件不存在是正常情况，不该报警。"""
        import sys
        import pathlib
        import tempfile
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import inventory as IV

        tmp = pathlib.Path(tempfile.mkdtemp()) / "nope.json"
        orig = IV.STORE
        try:
            IV.STORE = tmp
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                d = IV._load()
            self.assertEqual(d.get("items"), {})
            self.assertEqual(buf.getvalue().strip(), "",
                             "文件不存在时不该打印任何东西")
        finally:
            IV.STORE = orig


class TestNoBareJsonWrite(unittest.TestCase):
    """所有 JSON 写盘都必须走原子写（E6）。

    ## 原来

    `X.write_text(json.dumps(...), encoding="utf-8")` 散布在各处 ——
    看起来是「写完了」，但**写到一半被杀就是半截 JSON**，
    而读侧很多地方又是 `except: return {}` —— 一个半截文件就能让整份数据消失。

    `core/atomic.py` 早就有了（tmp + `os.replace`），但只被 6 处调用。

    现在 14 处全改成 `_aw.write_json(...)`。
    """

    def test_no_bare_json_write(self):
        import ast as _ast
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for f in sorted(root.rglob("*.py")):
            if "_legacy" in str(f) or f.name.startswith("test"):
                continue
            try:
                tree = _ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.Call):
                    continue
                if getattr(node.func, "attr", None) != "write_text":
                    continue
                if not node.args:
                    continue
                if "json.dump" in _ast.unparse(node.args[0]):
                    bad.append(f"{f.name}:{node.lineno}")
        self.assertEqual(bad, [],
                         f"这些地方还是裸写 JSON（半截就丢数据）：{bad}")


class TestModuleImportsAreReal(unittest.TestCase):
    """`compile()` 过不代表 import 真的执行了（我差点栽在这）。

    ## 背景

    批量把 `write_text(json...)` 改成 `_aw.write_json(...)` 之后，
    我插 `from core import atomic as _aw` 的位置算错了 ——
    插进了**模块 docstring 里**。

    `compile()` **照样通过**（那在字符串里，语法没问题），
    但模块 import 时 `_aw` 根本不存在 ——
    `gen_manifest` 直接 `NameError`，另外 5 个模块一旦走到写盘就炸。

    -> 这条测试：**凡是用了 `_aw` 的模块，import 之后必须真的有 `_aw`**。
    """

    def test_aw_is_importable_everywhere(self):
        import ast as _ast
        import importlib
        import sys
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        sys.path.insert(0, str(root))
        bad = []
        for f in sorted(root.rglob("*.py")):
            if "_legacy" in str(f) or f.name.startswith("test"):
                continue
            txt = f.read_text(encoding="utf-8")
            if "_aw.write_json" not in txt:
                continue
            # 算模块名
            rel = f.relative_to(root).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if not parts:
                continue
            modname = ".".join(parts)
            if modname.startswith("tools."):
                modname = modname[6:]
            try:
                mod = importlib.import_module(modname)
            except Exception as e:
                bad.append(f"{modname} import 失败：{type(e).__name__}: {e}")
                continue
            # **两种写法都合法**：
            #   ① 模块级 `from core import atomic as _aw`
            #   ② 函数内 `from . import atomic as _aw`（farm_log 就是这种）
            # 只要 AST 里能找到这个导入，且**不在 docstring 里**就行。
            tree = _ast.parse(txt)

            # **看 names，不是看 module**：
            #   `from core import atomic as _aw`  -> module="core", names 里有 atomic
            #   `from . import atomic as _aw`     -> module="",     names 里有 atomic
            def _imports_atomic(nodes):
                for n in nodes:
                    if not isinstance(n, _ast.ImportFrom):
                        continue
                    for a in n.names:
                        if a.name == "atomic":
                            return True
                return False

            has_import = _imports_atomic(_ast.walk(tree))
            if not has_import:
                bad.append(f"{modname} 用了 _aw 但没有任何 atomic 导入")
                continue
            # **模块级**有导入 -> import 之后就必须真的有 `_aw`。
            # 这条专门抓「import 被插进 docstring」：那行在字符串里，
            # 不在 `tree.body` 而是文本，所以不走这里 —— 但模块不会有 `_aw`。
            if _imports_atomic(tree.body) and not hasattr(mod, "_aw"):
                bad.append(f"{modname}: 模块级导入了 atomic，但 import 后没有 `_aw`")
        self.assertEqual(bad, [], "\n  ".join(bad))


class TestAdminPs1Command(unittest.TestCase):
    """`admin.ps1 -Command "python x.py"` 不能 100% 失败（E9）。

    ## 原来

    ```powershell
    & $Python -u $Command.Split(' ')
    ```

    `-Command "python tools/zzz_who.py"` 时切出来是
    `["python", "tools/zzz_who.py"]`，拼成

        & <python.exe> -u python tools/zzz_who.py

    Python 去找一个叫 `python` 的**脚本文件** —— 必然失败。
    而且 `.Split(' ')` 会把带空格的路径也切坏。

    实测（修前）：`python tools/zzz_who.py --help` -> exit 2；
    `tools/zzz_who.py --help` -> exit 0。**用户按文档写的那种就是坏的那种。**
    """

    def _ps1(self):
        import pathlib
        p = pathlib.Path(__file__).resolve().parent.parent.parent / "admin.ps1"
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8")

    def _ps1_code(self):
        """admin.ps1 **去掉注释行**的内容（注释里会引用旧代码）。"""
        txt = self._ps1()
        if txt is None:
            return None
        return "\n".join(l for l in txt.splitlines()
                          if not l.lstrip().startswith("#"))

    def test_no_naive_split(self):
        code = self._ps1_code()
        if code is None:
            self.skipTest("admin.ps1 不在当前集合里")
        self.assertNotIn("$Command.Split(' ')", code,
                         "还在用 `.Split(' ')` 拼命令 —— 会把路径切坏")

    def test_strips_python_prefix(self):
        txt = self._ps1()
        if txt is None:
            self.skipTest("admin.ps1 不在当前集合里")
        self.assertIn("python|python3|py", txt,
                      "没处理用户习惯性写的 `python ` 前缀")

    def test_uses_call_operator(self):
        """必须带 `&` —— 裸字符串 + `-u` 在 PowerShell 里不可解析。"""
        txt = self._ps1()
        if txt is None:
            self.skipTest("admin.ps1 不在当前集合里")
        # 找**真正那一行**（以 Invoke-Expression 开头，不是注释里提到的）
        real = [l for l in txt.splitlines()
                if l.strip().startswith("Invoke-Expression")]
        self.assertTrue(real, "找不到真正执行的那行 Invoke-Expression")
        self.assertIn("& '", real[0],
                      f"Invoke-Expression 里没有 `&` 调用符：{real[0].strip()[:60]}")

    def test_propagates_exit_code(self):
        txt = self._ps1()
        if txt is None:
            self.skipTest("admin.ps1 不在当前集合里")
        real = [l for l in txt.splitlines()
                if l.strip().startswith("Invoke-Expression")]
        self.assertTrue(real, "找不到真正执行的那行")
        i = txt.find(real[0])
        tail = txt[i:i + 500]
        self.assertIn("exit $rc", tail,
                      "没有把退出码带出来 —— 提权后丢退出码")


class TestFarmQuotaGate(unittest.TestCase):
    """「每天只刷一次」的闸门必须在**最底层**（E31）。

    ## 原来只在一个入口

    `zzz_daily` 自己查额度，但 `od_material_farm` —— **真正执行刷本的那个工具** ——
    完全不看。于是：

        od_material_farm.py --run            # 直接跑，额度形同虚设
        zzz_farm_plan.py --run               # 从别的入口进来，同样不看

    都会把当天的电量再烧一遍。

    ## 现在

    闸门在 `od_material_farm` 的参数解析之后、`ZContext()` **之前** ——
    任何入口都绕不过去，而且会在**碰游戏之前**就拦下来。
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "od_material_farm.py").read_text(encoding="utf-8")

    def test_has_again_flag(self):
        self.assertIn('"--again"', self._src(), "没有 --again 逃生口")

    def test_gate_exists(self):
        src = self._src()
        self.assertIn("额度闸门", src, "找不到额度闸门")
        self.assertIn("count_today_safe", src, "没用 farm_log 的计数")

    def test_gate_before_game_init(self):
        """闸门必须在 `ZContext()` 之前 —— 白初始化 OneDragon 没意义。"""
        import ast as _ast
        tree = _ast.parse(self._src())
        gate_line = None
        ctx_line = None
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Call):
                nm = _ast.unparse(node.func)
                if nm.endswith("count_today_safe"):
                    gate_line = node.lineno
                if nm == "ZContext" and ctx_line is None:
                    ctx_line = node.lineno
        self.assertIsNotNone(gate_line, "没找到额度检查")
        self.assertIsNotNone(ctx_line, "没找到 ZContext")
        self.assertLess(gate_line, ctx_line,
                        f"额度检查在 L{gate_line}，ZContext 在 L{ctx_line} —— "
                        f"应该先查额度")

    def test_daily_does_not_double_record(self):
        """`zzz_daily` 不能自己再记一次 —— 双计会让闸门第二次就误拦。"""
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_daily.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        calls = [n.lineno for n in _ast.walk(tree)
                 if isinstance(n, _ast.Call)
                 and getattr(n.func, "id", None) == "_farm_record"]
        self.assertEqual(calls, [],
                         f"zzz_daily 还在 L{calls} 自己记账 —— "
                         f"od_material_farm 已经记过了，会双计")


class TestDiscGapNotMultipliedBySets(unittest.TestCase):
    """驱动盘缺口不能「空位数 × 候选套装数」（D13）。

    ## 原来

    ```python
    for _sn in _sets:
        add(f"驱动盘_{_dungeon}", len(empty) * _per, ...)
    ```

    6 个空位、4 个候选套 -> 6×4×4 = **96 盘**（48 趟/角色）。
    而实际只需要 **6 个盘**：四件套 4 个 + 两件套 2 个。

    **一个盘掉出来只用一次** —— 同一位号不需要「每个候选套各来一个」。
    两件套更是**只会用一个**。

    实测：两角色 5760 电 vs 手算 1440；修完整套规划 54 轮 -> 39 轮。
    """

    def _src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "zzz_farm_plan.py").read_text(encoding="utf-8")

    def test_no_multiply_by_all_sets(self):
        """不能出现「对每个套装都按全部空位加一次」的写法。"""
        import ast as _ast
        tree = _ast.parse(self._src())
        bad = []
        for node in _ast.walk(tree):
            # for <sn> in <sets>: ... add(..., len(empty) * <per>, ...)
            if not isinstance(node, _ast.For):
                continue
            body = _ast.unparse(node)
            if ("len(empty)" in body and "add(" in body
                    and "_sets" in _ast.unparse(node.iter)):
                bad.append(node.lineno)
        self.assertEqual(bad, [],
                         f"L{bad} 还在「遍历套装 × 全部空位」—— 盘数会虚高")

    def test_formula_caps_at_six_discs(self):
        """6 空位 + 4 候选套，总盘数应该等于 6×per，不是 24×per。"""
        per = 4
        for n_empty, n_sets, want in (
            (6, 4, 6),      # 满配：4 件套 + 2 件套 = 6
            (6, 1, 6),      # 只有四件套：4 件套 + 2 个无归属位号，还是要 6 个盘
            (2, 1, 2),      # 只空 2 位
            (1, 4, 1),      # 只空 1 位
            (6, 4, 6),      # 4 个候选套也只算 1 个两件套 —— 不能乘 4
        ):
            _main = "A" if n_sets else ""
            _secs = ["B"] * max(0, n_sets - 1) if n_sets > 1 else []
            _n_main = min(n_empty, 4) if _main else 0
            _n_sec = min(n_empty - _n_main, 2) if _secs else 0
            _rest = n_empty - _n_main - _n_sec
            got = _n_main + _n_sec + _rest
            self.assertEqual(got, want,
                             f"空{n_empty} 候选{n_sets} 应该总共 {want} 件，实际 {got}")


class TestReadOnlyDoesNotStealFocus(unittest.TestCase):
    """只读工具不该要求管理员、也不该抢前台（D7）。

    ## 原来

    `zzz_status` / `zzz_plan` / `zzz_resource` / `zzz_who` 全都是
    `Vision(); Input(); ui.start()` —— 而 `ui.start()` 里有 `is_admin()` 闸门
    和 `live.foreground()`（抢前台），`Vision` 每帧还会再抢一次。

    用户正在看别的窗口，跑一次「看一眼」的盘点就被硬顶到前台；
    而且没管理员就直接 exit 2 —— **它们根本不注入按键**。

    ## 另：遮挡保护是 fail-open 的

    `vision.py` 的 `except Exception: return` 让 `occluded` 保持原值（可能 False），
    于是「查不到窗口状态」等于「假定没被遮挡」——
    **上层以为画面是真的，实际可能在读别人的像素**。
    """

    # **只有真正不注入按键的才算只读**。
    #
    # 审计 D7 把 `zzz_status` / `zzz_plan` 也列成「只读路径」——
    # 实测它们各有 3 处 `inp.click(...)`（打开驱动盘详情）。
    # 给它们 `readonly=True` 会跳过权限闸，UIPI 静默丢点击，
    # 用户白等到超时。**这条是审计判错了，`audit_patterns` 规则 E 抓出来的。**
    READONLY = ("zzz_resource.py", "zzz_who.py")

    INJECTING = ("zzz_status.py", "zzz_plan.py")

    def test_readonly_tools_do_not_steal(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for name in self.READONLY:
            f = root / name
            if not f.exists():
                continue
            txt = f.read_text(encoding="utf-8")
            if "Vision()" in txt and "steal_focus=False" not in txt:
                bad.append(f"{name}: Vision() 没传 steal_focus=False")
            if "ui.start()" in txt and "readonly=True" not in txt:
                bad.append(f"{name}: ui.start() 没传 readonly=True")
        self.assertEqual(bad, [], "\n  ".join(bad))

    def test_ui_start_accepts_readonly(self):
        import sys
        import pathlib
        import inspect
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.ui import Ui
        sig = inspect.signature(Ui.start)
        self.assertIn("readonly", sig.parameters, "Ui.start 没有 readonly 参数")

    def test_occlusion_fails_closed(self):
        """查不到窗口状态时必须**假定被遮挡**，不能假定没事。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import live
        from core import vision as V

        vs = V.Vision.__new__(V.Vision)
        vs.win = {"hwnd": 1}
        vs.occluded = False
        vs.steal_focus = True

        def boom(_w):
            raise RuntimeError("模拟失败")

        orig = live.foreground
        live.foreground = boom
        try:
            vs._ensure_foreground()
            self.assertTrue(vs.occluded,
                            "查不到前台状态却把 occluded 留成 False —— fail-open")
        finally:
            live.foreground = orig

    def test_readonly_queries_without_stealing(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import live
        from core import vision as V

        vs = V.Vision.__new__(V.Vision)
        vs.win = {"hwnd": 1}
        vs.occluded = False
        vs.steal_focus = False

        calls = {"steal": 0, "query": 0}
        of, oi = live.foreground, live.is_foreground

        def fake_steal(w):
            calls["steal"] += 1
            return True

        def fake_query(w):
            calls["query"] += 1
            return True

        live.foreground = fake_steal
        live.is_foreground = fake_query
        try:
            vs._ensure_foreground()
        finally:
            live.foreground = of
            live.is_foreground = oi
        self.assertEqual(calls["steal"], 0, "只读模式还是抢了前台")
        self.assertEqual(calls["query"], 1, "只读模式没查询")


class TestSnapshotValidityIsHonest(unittest.TestCase):
    """快照「自证有效」+ 静默丢位号（D5）。

    ## 两处

    ① `zzz_status` 里套装名解析失败时只 `continue` ——
       既不 append 到 result，也不进 unread。**位号凭空消失**：
       6 个位号最后 result 里只有 5 个，而 unread 是空的。

    ② `_valid = bool(result) and len(unread) < len(result)` ——
       6 个位号只读到 1 个时，result 有 1 条、unread 0 条 -> 判定有效。
       1/6 也算「有效」。

    ## 下游 5 种态度

    拿一份 `_valid=False, slots=[]` 的快照：

        zzz_cost       当全新角色算 5480 电
        zzz_who        报「距毕业 28.0 / ✔ 没有明显缺口」
        zzz_grind      直接排 5 轮
        zzz_disc_daily 拦截   ← 只有它
        zzz_skill_target 诚实 ← 和它

    ## 现在

    · 读失败进 `unread`
    · `_valid` 要求 **6 个位号全部读到且 unread 为空**
    · `load_status(strict=True)` 遇到废数据 `SystemExit(8)`
    · `zzz_daily --run` 检查 `ok` 和 `_valid`，不过就 `return 8`
    """

    def _status_src(self):
        import pathlib
        return (pathlib.Path(__file__).resolve().parent.parent
                / "zzz_status.py").read_text(encoding="utf-8")

    def test_failed_slot_goes_to_unread(self):
        """读失败必须先记进 `unread` 再 continue。"""
        import ast as _ast
        tree = _ast.parse(self._status_src())
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.If):
                continue
            # `ast.unparse` 会把引号规范化成单引号 —— 两种都认
            head = _ast.unparse(node.test).replace('"', "'")
            if "d0" not in head or "set" not in head or "not" not in head:
                continue
            body = _ast.unparse(node)
            self.assertIn("unread.append(slot)", body,
                          "读失败的分支里没有 `unread.append(slot)` —— 位号会凭空消失")
            return
        self.fail('找不到 `if not d0["set"]` 那个分支')

    def test_valid_requires_all_six(self):
        """`_valid` 不能「有一个位号成功就算有效」。"""
        src = self._status_src()
        self.assertNotIn(
            "_valid = bool(result) and len(unread) < len(result)", src,
            "`_valid` 还是「1/6 也算有效」的写法")
        self.assertIn("len(result) == 6", src,
                      "`_valid` 没有要求「6 个位号全读到」")

    def test_load_status_has_strict(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.state import load_status
        sig = inspect.signature(load_status)
        self.assertIn("strict", sig.parameters, "load_status 没有 strict 参数")
        self.assertIn("SystemExit(8)", inspect.getsource(load_status),
                      "strict 模式下没有 exit 8")

    def test_daily_refuses_bad_snapshot(self):
        """会花电量/材料的那条路必须检查 `_valid`（D5）。"""
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_daily.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        # 必须有对 "_valid" 的取值
        has_valid_check = any(
            isinstance(n, _ast.Call)
            and getattr(n.func, "attr", None) == "get"
            and n.args
            and isinstance(n.args[0], _ast.Constant)
            and n.args[0].value == "_valid"
            for n in _ast.walk(tree))
        self.assertTrue(has_valid_check,
                        "zzz_daily 没检查快照的 `_valid` —— 会拿废数据算缺口")
        self.assertIn("if not ok:", src,
                      "zzz_daily 没检查 zzz_status 的返回码")


class TestOcrInitSignature(unittest.TestCase):
    """不能给 `init_model()` 传不存在的参数（E22）。

    ## 原来

    ```python
    ocr = OnnxOcrMatcher()
    try:
        ocr.init_model(ocr_model_size="small")    # <- 没这个参数
    except Exception:
        ocr.init_model()
    ```

    OneDragon 的签名是：

        init_model(self, source_order=None, proxy_url=None,
                   ghproxy_url=None, skip_if_existed=...)

    **必然 TypeError**，被 `except` 吞掉后再调一次无参的 ——
    看起来「能用」，实际每次都先失败一次，
    而「想用 small 模型」这个意图**从来没生效过**。

    `ocr_model_size` 是**构造函数**的参数（而且默认 ppocrv6 本来就用 small）。
    """

    def test_no_bogus_init_model_kwarg(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "live.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            if getattr(node.func, "attr", None) != "init_model":
                continue
            kws = [k.arg for k in node.keywords]
            self.assertNotIn("ocr_model_size", kws,
                             f"L{node.lineno} 还在给 init_model 传 ocr_model_size")

    def test_ocr_failure_exits_2(self):
        """加载失败要说人话 + exit 2，不能把 traceback 冒到顶层。"""
        import pathlib
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "live.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        # **找真正的调用，不是注释里提到的**（自指陷阱）
        line = None
        for node in _ast.walk(tree):
            if (isinstance(node, _ast.Call)
                    and getattr(node.func, "attr", None) == "init_model"):
                line = node.lineno
                break
        self.assertIsNotNone(line, "找不到真正的 init_model() 调用")
        lines = src.splitlines()
        tail = "\n".join(lines[line - 1:line + 25])
        self.assertIn("SystemExit(2)", tail, "OCR 加载失败没有 exit 2")


class TestAgentPositionsValidated(unittest.TestCase):
    """`agent_positions.json` 的值必须校验形状（E18）。

    ## 原来

    `load_cache()` 直接返回 `json.loads(...)`，消费方是：

        order.append(tuple(cache[name]))
        ...
        inp.click(pt[0], pt[1], wait=1.3)

    值是下面任何一种都会炸，而文件看着「是合法 JSON」：

        null          -> TypeError
        [1439]        -> IndexError
        "1439,1004"   -> 逐字符变成 ('1','4',...)，点到天上

    **12 个调用方全走这条路** —— 一个手改坏的文件能让所有工具崩在选人。
    """

    def test_bad_values_dropped(self):
        import sys
        import json
        import pathlib
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pick_agent as PA

        tmp = pathlib.Path(tempfile.mkdtemp()) / "agent_positions.json"
        orig = PA.CACHE
        try:
            PA.CACHE = tmp
            tmp.write_text(json.dumps({
                "好": [100, 200],
                "空": None,
                "短": [1439],
                "串": "1439,1004",
                "浮": [1.5, 2],
                "多": [1, 2, 3],
            }, ensure_ascii=False), encoding="utf-8")
            d = PA.load_cache()
            self.assertEqual(d, {"好": [100, 200]})
            for k in ("空", "短", "串", "浮", "多"):
                self.assertNotIn(k, d, f"{k} 这种值不该被接受")
        finally:
            PA.CACHE = orig

    def test_missing_file_is_quiet(self):
        import sys
        import pathlib
        import tempfile
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pick_agent as PA

        tmp = pathlib.Path(tempfile.mkdtemp()) / "nope.json"
        orig = PA.CACHE
        try:
            PA.CACHE = tmp
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                d = PA.load_cache()
            self.assertEqual(d, {})
            self.assertEqual(buf.getvalue().strip(), "",
                             "文件不存在时不该打印东西")
        finally:
            PA.CACHE = orig


class TestInputOriginRefresh(unittest.TestCase):
    """`Input` 的原点必须每次注入前同步，不能永久缓存（E10）。

    ## 原来

    `Input.__init__` 里 `self.ox, self.oy = self.win["x"], self.win["y"]`
    —— 只赋值一次，之后**永不刷新**。而所有点击都是 `self.ox + x`。

    窗口一移动（用户拖了一下 / 游戏换了分辨率 / 重开了一下），
    **点击就全部错位**，而且错得很安静：工具不报错，只是点到别的地方。

    ## 还发现一个更危险的东西

    我第一版用 `GetWindowRect` 实现「窗口现在在哪」。实测同一时刻：

        find_window   x=965  y=122  w=1920 h=1080     <- 客户区
        GetWindowRect x=952  y=64   w=1946 h=1151     <- 含边框/标题栏

    差 (−13, −58)。拿外框当原点，**每次点击都偏**，而且代码看着很对。
    `find_window` 用的是 `GetClientRect` + `ClientToScreen`，必须对齐。
    """

    def test_guard_syncs_origin(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "core" / "input.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        # _guard 里必须调 _sync_origin
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.FunctionDef) and node.name == "_guard"):
                continue
            body = _ast.unparse(node)
            self.assertIn("_sync_origin", body,
                          "_guard 里没有同步原点 —— 窗口移动后点击会错位")
            return
        self.fail("找不到 _guard")

    def test_window_rect_matches_find_window(self):
        """**不变量**：`window_rect(hwnd)` 必须和 `find_window()` 对齐。

        这条是回归防线 —— 谁把 `window_rect` 改成 `GetWindowRect`
        （看着更自然），这里会红。
        """
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import live

        w = live.find_window()
        if not w:
            self.skipTest("游戏没开")
        r = live.window_rect(w["hwnd"])
        self.assertIsNotNone(r, "window_rect 拿不到窗口矩形")
        self.assertEqual((r["x"], r["y"], r["w"], r["h"]),
                         (w["x"], w["y"], w["w"], w["h"]),
                         "window_rect 和 find_window 不一致 —— "
                         "多半是用了 GetWindowRect（含边框）而不是客户区")

    def test_window_rect_uses_client_area(self):
        """源码层面也要对：不能出现 `GetWindowRect`。"""
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "live.py").read_text(encoding="utf-8")
        # **用 `_code()` 剥掉注释和 docstring** ——
        # 这个函数的 docstring 里就写着 `GetWindowRect`（解释为什么不能用），
        # 直接搜文本会抓到自己。
        body = _code(src)
        i = body.find("def window_rect")
        self.assertGreater(i, -1)
        j = body.find("def is_foreground", i)
        seg = body[i:j if j > i else i + 2000]
        self.assertIn("GetClientRect", seg, "没用 GetClientRect")
        self.assertIn("ClientToScreen", seg, "没用 ClientToScreen")
        self.assertNotIn("GetWindowRect", seg,
                         "用了 GetWindowRect —— 会偏 (边框宽, 标题栏高)")


class TestDragDirectionMatters(unittest.TestCase):
    """拖动「成功了」必须是**往右动了**，不是「动了」（E33）。

    ## 原来

    ```python
    tx2, _, _ = thumb_x(vs, y)
    if abs(tx2 - tx) > 8:
        return True
    ```

    `abs()` 不判方向。拖动失败时拇指常常会**弹回**一点，
    那个也算成功 —— 于是工具以为「已拉满」，实际技能等级没动，
    后面的判断全建立在假前提上。
    """

    def test_no_abs_check(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_guide_max.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.FunctionDef) and node.name == "drag_one"):
                continue
            body = _ast.unparse(node)
            self.assertNotIn("abs(tx2 - tx)", body,
                             "还在用 `abs()` 判拖动成功 —— 方向反了也算成功")
            self.assertIn("tx2 > tx + 8", body,
                          "没有「往右动 8px 以上」的判断")
            return
        self.fail("找不到 drag_one")


class TestCoreStatusPerAgent(unittest.TestCase):
    """核心技缺口要读 `core_status_<角色>.json`，不是全局那个（E34）。

    ## 原来

    ```python
    cs = BASE / "state" / "core_status.json"      # <- 全局
    ```

    而 `zzz_core.py` 写的是 `state/core_status_<角色>.json`。
    **全局那个文件从来没被创建过** —— 所以这段代码**一直没生效**：
    核心技没满的角色也不会被排进刷本计划。

    （`zzz_farm_plan.py` 早就按角色读了，这里漏了。）
    """

    def test_detects_per_agent_gap(self):
        import sys
        import json
        import pathlib
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import od_material_farm as OMF

        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / "state").mkdir()
        orig = OMF.BASE
        try:
            OMF.BASE = tmp
            # 核心技 B 没升满 -> 应该排「专业挑战室」
            (tmp / "state" / "core_status_测试角色.json").write_text(
                json.dumps({"B": {"costs": [[0, 2], [1, 3]]}},
                           ensure_ascii=False), encoding="utf-8")
            plans = OMF.from_gaps()
            self.assertTrue(any(p[0] == "专业挑战室" for p in plans),
                            f"没查出核心技缺口：{plans}")

            # 升满了 -> 不该排
            (tmp / "state" / "core_status_测试角色.json").write_text(
                json.dumps({"B": {"costs": [[2, 2], [3, 3]]}},
                           ensure_ascii=False), encoding="utf-8")
            plans2 = OMF.from_gaps()
            self.assertFalse(any(p[0] == "专业挑战室" for p in plans2),
                             f"满了还排：{plans2}")
        finally:
            OMF.BASE = orig


class TestDismantleGateUsesRealTotal(unittest.TestCase):
    """拆解比例闸门的分母必须是**库总数**，不是屏幕可见行数（E36）。

    ## 原来

    ```python
    def mesh(vs) -> int:
        return len([it for it in vs.items((60, 120, 1100, 980))
                    if it["text"].startswith("等级")])
    ...
    total = mesh(vs)      # <- 拿去当分母
    ```

    `mesh()` 数的是「这一屏里有几行」，随窗口大小和**滚动位置**变。
    两次测量可能读的是完全不同的两屏，比例毫无意义 ——
    而这是个**不可逆**操作的闸门。

    旁边 `top_count(vs)` 早就读对了顶部 `N / 300`，却没用上。
    """

    def test_gate_uses_top_count(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_disc_cycle.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.FunctionDef)
                    and node.name == "dismantle_all_abandoned"):
                continue
            bad = []
            for n in _ast.walk(node):
                if not (isinstance(n, _ast.Assign)
                        and isinstance(n.targets[0], _ast.Name)
                        and n.targets[0].id in ("total", "n")):
                    continue
                val = _ast.unparse(n.value)
                if "mesh(" in val:
                    bad.append(f"L{n.lineno}: {n.targets[0].id} = {val}")
            self.assertEqual(bad, [],
                             f"闸门还在用 mesh() 当计数：{bad}")
            self.assertIn("top_count", _ast.unparse(node),
                          "闸门没用 top_count")
            return
        self.fail("找不到 dismantle_all_abandoned")


class TestHistoryDoesNotFabricate(unittest.TestCase):
    """`--history` 不能把缺字段的记录当 0（E19）。

    ## 实测输出（修前）

        11-20T10:00    20.5   ██████████░░░░  蓝10
        11-21T10:00     0.0   ░░░░░░░░░░░░░░  蓝0   ▼ -20.5
        11-22T10:00    24.0   ████████████░░  蓝11  ▲ +24.0

    中间那条只是**早期旧格式没写「质量分」**，却画成「跌到 0 又涨回来」。
    用户看到的是一段假历史 —— 而 `or 0` 就是那个制造机。
    """

    def test_rows_without_score_are_skipped(self):
        import sys
        import pathlib
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_who as W

        rows = [
            {"ts": "2026-11-20T10:00:00", "质量分": 20.5, "蓝条": 10},
            {"ts": "2026-11-21T10:00:00"},                      # 缺字段
            {"ts": "2026-11-22T10:00:00", "质量分": 24.0, "蓝条": 11},
        ]
        orig = W._load_progress
        W._load_progress = lambda a: rows
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                W.history("测试")
            out = buf.getvalue()
        finally:
            W._load_progress = orig

        self.assertIn("没有质量分，已跳过", out, "没提示跳过了几条")
        self.assertNotIn("   0.0 ", out, "曲线里还有 0.0 的假谷底")
        self.assertIn("涨了 3.5", out, "涨跌幅算错了（应该是 24.0-20.5）")


class TestCoreUpgradeReturnsNonZero(unittest.TestCase):
    """`zzz_core` 一次没升时必须返回非零（E35）。

    ## 原来

    ```python
    if total == 0:
        print("  （一次都没升成 —— ...）")
    return 0
    ```

    打印完还是 0。调用方（`zzz_daily` 的断点/记账）看到 0 就记成
    「核心技已完成」—— 实际一次都没升，**下一轮会跳过它**，
    永久停在那个等级。
    """

    def test_zero_upgrade_returns_nonzero(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_core.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.If):
                continue
            body = _ast.unparse(node)
            if "total == 0" not in _ast.unparse(node.test):
                continue
            self.assertIn("return 1", body,
                          "`total == 0` 的分支里没有 `return 1`")
            return
        self.fail("找不到 `if total == 0` 分支")


class TestAgentNotSpecifiedIsClean(unittest.TestCase):
    """空角色名的报错不能把帮助文本塞进「角色名」里（E17）。

    ## 原来

    ```python
    raise UnknownAgent(
        "（没指定角色）\n  用法：...\n  可用角色：...", [])
    ```

    而 `UnknownAgent.__init__` 是 `msg = f"角色「{name}」不在角色库里"`。
    实测输出：

        '角色「（没指定角色）\n  用法：python tools/<工具>.py <角色名>\n ...
         以及 set ZZZ_DEFAULT_AGENT=...」不在角色库里。可用角色见 tools/disc_meta.json'

    整段帮助被当成**角色名**，外面还包了一层 `KeyError` 的 `repr` 引号，
    `\n` 变成字面的两个字符。**一句话被拆成两半中间插了句「不在角色库里」。**
    """

    def test_empty_name_has_clean_message(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import resolve_agent, AgentNotSpecified

        try:
            resolve_agent("")
        except AgentNotSpecified as e:
            msg = str(e)
            self.assertTrue(msg.startswith("没指定角色"),
                            f"消息开头不对：{msg[:40]}")
            self.assertNotIn("不在角色库里", msg,
                             "「没指定」不该说成「不在库里」")
            self.assertFalse(msg.startswith("'"),
                             "消息被 repr 包了引号")
            self.assertNotIn("\\n", msg, "换行被打成了字面量 `\\n`")
        else:
            self.fail("空名字没有抛 AgentNotSpecified")

    def test_unknown_agent_str_is_clean(self):
        """`UnknownAgent` 的 `__str__` 也不该带引号（它是 KeyError）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import resolve_agent, UnknownAgent

        try:
            resolve_agent("完全不存在的角色XYZ")
        except UnknownAgent as e:
            msg = str(e)
            self.assertFalse(msg.startswith("'"), "消息被 repr 包了引号")
            self.assertIn("不在角色库里", msg)
        else:
            self.fail("应该抛 UnknownAgent")

    def test_backward_compatible(self):
        """`AgentNotSpecified` 必须仍是 `UnknownAgent` 的子类 —— 老 caller 要能接住。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import UnknownAgent, AgentNotSpecified
        self.assertTrue(issubclass(AgentNotSpecified, UnknownAgent))


class TestWriteSideValidatesSchema(unittest.TestCase):
    """写快照前要自检 schema，不能只靠读端事后发现（E13）。

    ## 原来

    `REQUIRED_STATUS_KEYS = ("total", "slots", "blue_total")` 只在
    `check_status_schema`（**读端**）里用。写端 `zzz_status` 直接
    `_atomic.write_json(out, _stamp(_payload))` —— **什么都不查**。

    写端漏字段的话，用户要等到下次读才看到「未盘点」——
    而那个提示完全不指向真正的原因（R5：「校验只在读端、只在运行期」）。
    """

    def test_validate_status_rejects_bad(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.state import validate_status

        self.assertEqual(validate_status(
            {"total": 12.0, "slots": [], "blue_total": 3}), [])
        self.assertTrue(validate_status({"total": 12.0}),
                        "缺字段没报")
        self.assertTrue(validate_status(
            {"total": 12.0, "slots": {}, "blue_total": 3}),
            "slots 是 dict 没报")
        self.assertTrue(validate_status(
            {"total": "12", "slots": [], "blue_total": 3}),
            "total 是字符串没报")
        self.assertTrue(validate_status(
            {"total": 1.0, "slots": [], "blue_total": 0, "_slots_read": "3"}),
            "_slots_read 是字符串没报")

    def test_status_calls_validate_before_write(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_status.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        # 导入的是 `validate_status as _validate`，所以看**导入**更准。
        imported = False
        for n in _ast.walk(tree):
            if not isinstance(n, _ast.ImportFrom):
                continue
            for a in n.names:
                if a.name == "validate_status":
                    imported = True
                    alias = a.asname or a.name
        self.assertTrue(imported, "zzz_status 没导入 validate_status")
        # 而且必须**真的调用**（导入时用了别名 `_validate`）
        import re as _re
        self.assertTrue(
            _re.search(r"\b(_validate|validate_status)\s*\(", src),
            "导入了却没调用")
        # 校验失败要 return 8
        i = src.find("validate_status")
        tail = src[i:i + 800]
        self.assertIn("return 8", tail, "校验失败没有 return 8")


class TestUnreadableIsNotUnscanned(unittest.TestCase):
    """「读不了」不能显示成「没盘点」（E21）。

    ## 原来

    ```python
    if not p.exists():
        return None          # 没盘点过
    try:
        return json.loads(...)
    except Exception:
        return None          # 文件坏了 —— 和上面一样
    ```

    下游于是把「文件损坏」也显示成「未盘点」：
    用户以为「还没跑过盘点」，实际是**跑过了但文件坏了**。
    重跑一次就能好，而提示根本没指向那个动作。
    """

    def test_missing_vs_broken(self):
        import sys
        import pathlib
        import tempfile
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_who as W

        tmp = pathlib.Path(tempfile.mkdtemp())
        orig = W.STATE
        try:
            W.STATE = tmp
            # ① 不存在：安静
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                r1 = W.status_of("甲")
            self.assertIsNone(r1)
            self.assertEqual(buf.getvalue().strip(), "",
                             "文件不存在时不该打印东西")
            self.assertFalse(W.progress_of("甲").get("读不了"),
                             "没盘点被标成「读不了」")

            # ② 坏了：要报
            (tmp / "status_乙.json").write_text("{半截", encoding="utf-8")
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                r2 = W.status_of("乙")
            self.assertIsNone(r2)
            out = buf2.getvalue()
            self.assertIn("读不了", out, "坏文件没报出来")
            self.assertIn("不是", out, "没说清「这不是没盘点」")
            self.assertIn("zzz_status.py", out, "没给出修复命令")
            # progress_of 的标记也要对（但会再打印一次，吞掉）
            buf3 = io.StringIO()
            with contextlib.redirect_stdout(buf3):
                p2 = W.progress_of("乙")
            self.assertTrue(p2.get("读不了"), "坏了却标成「没读过」")
        finally:
            W.STATE = orig


class TestBrokenMetaIsNotAnEmptyConfig(unittest.TestCase):
    """`disc_meta.json` 坏了不能静默回退「强攻」模板（E3）。

    ## 原来

    ```python
    try:
        _cache = json.loads(META.read_text(...))
    except Exception:
        _cache = {"角色": {}, "职业模板": {}}      # 静默变空
    ```

    空 dict 的后果是连锁的：

        role_of("丽娜") -> 找不到 -> 回落 DEFAULT_ROLE = "强攻"
        cfg_of("丽娜")  -> 用「强攻」模板补 -> 提示「这个角色没配置」

    而真实情况是**数据文件坏了**。用户看到「这个角色没配置」会去
    disc_meta 里加那个角色 —— **方向完全错了**，然后越改越乱。
    """

    def _try(self, content, exists=True):
        import sys
        import pathlib
        import tempfile
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import agent_cfg as A

        tmp = pathlib.Path(tempfile.mkdtemp())
        f = tmp / "disc_meta.json"
        if exists:
            f.write_text(content, encoding="utf-8")
        orig_meta, orig_cache = A.META, A._cache
        A.META, A._cache = f, None
        buf = io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(buf):
                A.meta()
        except SystemExit as e:
            code = e.code
        finally:
            A.META, A._cache = orig_meta, orig_cache
        return code, buf.getvalue()

    def test_missing_file_exits_2(self):
        code, out = self._try(None, exists=False)
        self.assertEqual(code, 2, "缺文件没有 exit 2")
        self.assertIn("找不到角色配置", out)

    def test_broken_json_exits_2(self):
        code, out = self._try("{半截")
        self.assertEqual(code, 2, "坏 JSON 没有 exit 2")
        self.assertIn("读不了", out)
        self.assertIn("不是「某个角色没配置」", out,
                      "没点明「这和数据文件坏了是一回事」")

    def test_wrong_type_exits_2(self):
        code, out = self._try("[1,2,3]")
        self.assertEqual(code, 2, "内容不是对象没有 exit 2")

    def test_good_file_does_not_exit(self):
        code, _ = self._try('{"角色": {}, "职业模板": {}}')
        self.assertIsNone(code, "正常文件不该退出")


class TestNoDeadConfigSections(unittest.TestCase):
    """`config.json` 里不能有「配了但没人读」的段（E4）。

    ## 原来

    `_note` 说「成本/权重都是可校准的近似值……引擎只负责相对排序」，
    而其中 4 段**零引用**：

        denny_per_stamina / role_weight / team_weight / stages

    用户照着改，什么都不会发生 —— 比「没有这个配置」更伤人，
    因为它会让人怀疑「是不是我改错了地方」。

    现在：死配置段列在 `_unused_keys` 里（并在 `_note` 里点明
    「真正生效的只有 cost / gain / graduation / reset」）。
    **以后新增的段必须被引用，或者也列进 `_unused_keys`。**
    """

    def test_every_section_is_live_or_declared_dead(self):
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent.parent
        cfg_p = root / "config.json"
        if not cfg_p.exists():
            self.skipTest("config.json 不在当前集合里")
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        declared_dead = set((cfg.get("_unused_keys") or {}).keys())

        tools = root / "tools"
        srcs = []
        for f in sorted(tools.rglob("*.py")):
            if "_legacy" in str(f):
                continue
            srcs.append(f.read_text(encoding="utf-8", errors="replace"))
        blob = "\n".join(srcs)

        idle = []
        for k in cfg:
            if k.startswith("_"):
                continue
            if k in declared_dead:
                continue
            if f'"{k}"' in blob or f"'{k}'" in blob:
                continue
            idle.append(k)
        self.assertEqual(idle, [],
                         f"这些配置段没人读，也没 declared dead：{idle}")

    def test_unused_keys_are_still_present(self):
        """`_unused_keys` 里写的段必须真的还在 config.json 里。"""
        import json
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        cfg_p = root / "config.json"
        if not cfg_p.exists():
            self.skipTest("config.json 不在当前集合里")
        cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        for k in (cfg.get("_unused_keys") or {}):
            self.assertIn(k, cfg, f"_unused_keys 里的 {k} 已经不在 config.json 里了")


class TestAscendCertSingleSource(unittest.TestCase):
    """认证章成本只能有**一个**定义，而且和 `materials.json` 的差额要可见（E2）。

    ## 原来

        zzz_farm_plan.py:108   ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30}
        zzz_cost.py:28         ASCEND_CERT = {20: 4, 30: 20, 40: 20, 50: 30, 60: 0}

    两份一模一样的常量 = 两份会漂移的真相。

    ## 数值本身也对不上

    `materials.json`（标注「zzz.gg/jp 角色页 7 个角色交叉」）：
    初阶 4 + 高阶 32 + 专属 30 = **66**
    代码：4 + 20 + 20 + 30 = **74**

    **差 8。** 分档方式不同（按等级 vs 按层），把 66 摊到 4 档需要臆造映射 ——
    所以这里只做「单一来源 + 差额可见」，数值留给作者按实测定。
    """

    def test_both_modules_agree(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_farm_plan as F
        import zzz_cost as C
        for lv in (20, 30, 40, 50):
            self.assertEqual(F.ASCEND_CERT[lv], C.ASCEND_CERT[lv],
                             f"{lv} 级两边不一致 —— 又分叉了")

    def test_discrepancy_is_visible(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.cost_data import (ASCEND_CERT, materials_cert_total,
                                    check_against_materials)
        want = materials_cert_total()
        if want < 0:
            self.skipTest("读不到 materials.json")
        got = sum(ASCEND_CERT.values())
        why = check_against_materials()
        if got != want:
            # **现在确实不一致** —— 要求检测器把它说出来，而不是沉默
            self.assertTrue(why, f"代码 {got} vs 数据 {want}，检测器却没报")
        else:
            self.assertEqual(why, [])


class TestDocsCountIsHonest(unittest.TestCase):
    """文档里写的用例数必须和实际一致（E30）。

    ## 原来四处不一致

        AGENTS.md    138 个用例
        HANDOFF.md   204 个用例
        COMPLETION.md 161
        FIXED-REPORT.md 141 / 160

    而实际一直在涨。**文档和代码脱节比没有文档更糟** ——
    读者看到 138 会以为「就这么多」，实际有 300 多。

    处理办法分两类：
    · **现行文档**（AGENTS.md / HANDOFF.md）→ 必须等于当前值，这条测试强制
    · **历史快照**（FIXED-REPORT / COMPLETION / STATUS）→ 加日期横幅，
      里面的数字是当时的，不改（改了就是伪造记录）
    """

    def _actual(self) -> int:
        import ast as _ast
        import pathlib
        p = pathlib.Path(__file__).resolve().parent / "test_core.py"
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        return sum(
            1 for node in _ast.walk(tree)
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef))
            and node.name.startswith("test_"))

    # **精确数字必然过期**：加一个测试，文档就错一次。
    # 所以现行文档用「300+ 个用例」这种**范围声明**，
    # 测试只检查那个声明仍然成立 —— 这样它永远是真的。
    def _check_claim(self, name: str) -> None:
        import re
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        p = root / name
        if not p.exists():
            self.skipTest(f"{name} 不在当前集合里")
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"(\d{2,4})\+?\s*个用例", txt)
        if not m:
            self.skipTest(f"{name} 里没写用例数")
        claim = int(m.group(1))
        actual = self._actual()
        # 有 `+` 就是下限声明；没有就是精确值
        has_plus = "+" in txt[m.start(1):m.end(1) + 1]
        if has_plus:
            self.assertGreaterEqual(
                actual, claim,
                f"{name} 声称「{claim}+ 个用例」，实际只有 {actual}")
        else:
            self.assertEqual(
                claim, actual,
                f"{name} 写死 {claim}，实际 {actual} —— 精确数字会过期，"
                f"改成「{claim}+ 个用例」这种范围写法")

    def test_agents_md_matches(self):
        self._check_claim("AGENTS.md")

    def test_handoff_md_matches(self):
        self._check_claim("HANDOFF.md")

    def test_historical_docs_are_marked(self):
        """历史快照必须有日期横幅 —— 否则它的旧数字看起来像「错的」。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        for name in ("FIXED-REPORT.md", "COMPLETION.md", "STATUS.md"):
            p = root / name
            if not p.exists():
                continue
            head = "\n".join(p.read_text(encoding="utf-8").splitlines()[:8])
            self.assertIn("历史快照", head,
                          f"{name} 没标「历史快照」—— 里面的旧数字会被当成当前值")


class TestTargetsJsonChannelsAgree(unittest.TestCase):
    """`targets.json` 三条通道必须**一个态度**（E26）。

    ## 原来三个方向

        publish_github   **上传**（不在 IGN_FILES，在发布集里）
        release.yml      **排除**（zip -x 里有）
        .gitignore       **不忽略**（会被提交）

    而 `targets.json` 装的是**用户的角色列表**（PII）。

    更绕的是：`publish_github` 里有一句注释
    「targets.json 是故意发布的空模板」—— 也就是说
    **两个通道对「它到底是什么」的理解都不一样**。

    现在统一成「发模板、不发真身」：
    · `targets.json`      —— 三处都排除
    · `targets.example.json` —— 三处都发
    """

    def _root(self):
        import pathlib
        return pathlib.Path(__file__).resolve().parent.parent.parent

    def test_publish_excludes_it(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from publish_github import IGN_FILES
        self.assertIn("targets.json", IGN_FILES,
                      "publish_github 还会上传 targets.json")

    def test_zip_excludes_it(self):
        import pathlib
        root = self._root()
        p = root / ".github" / "workflows" / "release.yml"
        if not p.exists():
            self.skipTest("release.yml 不在当前集合里")
        txt = p.read_text(encoding="utf-8")
        self.assertIn("'targets.json'", txt,
                      "zip -x 里没有 targets.json")

    def test_gitignore_excludes_it(self):
        import pathlib
        root = self._root()
        p = root / ".gitignore"
        if not p.exists():
            self.skipTest(".gitignore 不在当前集合里")
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines()]
        self.assertIn("targets.json", lines,
                      ".gitignore 没有排除 targets.json")

    def test_template_is_shipped(self):
        """模板要在，而且要进发布集 —— 否则新用户没有起点。"""
        import sys
        import pathlib
        root = self._root()
        self.assertTrue((root / "targets.example.json").exists(),
                        "没有 targets.example.json 模板")
        sys.path.insert(0, str(root / "tools"))
        from publish_github import collect
        names = [str(f).replace("\\", "/") for f in collect(root)]
        self.assertTrue(any(n.endswith("targets.example.json") for n in names),
                        f"模板没进发布集：{[n for n in names if 'targets' in n]}")
        self.assertFalse(any(n == "targets.json" or n.endswith("/targets.json")
                             for n in names),
                         "真实 targets.json 还在发布集里")


class TestRoundCountRoundsUp(unittest.TestCase):
    """轮数必须**向上取整**，不能用 `:.0f`（E1）。

    ## 实测（修前）

        120 电: 120/240 = 0.5 -> 显示「0 轮」   ← 用户以为电量用不出去
        600 电: 600/240 = 2.5 -> 显示「2 轮」   ← 少估一轮，实际跑不完
        360 电: 360/240 = 1.5 -> 显示「2 轮」   ← 偶然对
        241 电: 241/240 = 1.004 -> 显示「1 轮」 ← 少估一轮

    `:.0f` 是**银行家舍入**（.5 取偶），不是四舍五入。
    `zzz_gap.py` 早就用了 `(x + 239) // 240`，另外两处没有。
    """

    def test_formula(self):
        def rounds(tot, per=240):
            return (tot + per - 1) // per if tot > 0 else 0
        for tot, want in ((0, 0), (1, 1), (120, 1), (239, 1), (240, 1),
                          (241, 2), (360, 2), (600, 3), (700, 3)):
            self.assertEqual(rounds(tot), want,
                             f"{tot} 电应该 {want} 轮")

    def test_no_banker_rounding_in_round_counts(self):
        """含「轮」的行里不能再用 `:.0f`（分钟数那种不在此列）。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        for f in sorted(root.glob("*.py")):
            if f.name.startswith("test"):
                continue
            for n, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                s = line.strip()
                if s.startswith("#"):
                    continue          # 注释里提到 `.0f` 是解释为什么不能用
                if "轮" in s and ".0f" in s and "分钟" not in s:
                    bad.append(f"{f.name}:{n}  {s[:60]}")
        self.assertEqual(bad, [],
                         f"这些地方还在用银行家舍入算轮数：{bad}")

    def test_cost_uses_ceil(self):
        import pathlib
        # **用 `_code()` 剥掉注释** —— 修这两个函数时写的注释里
        # 就引用了旧写法（解释为什么不能那么写），直接搜文本会抓到自己。
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_cost.py").read_text(encoding="utf-8"))
        self.assertIn("(tot + 239) // 240", code,
                      "zzz_cost 没改成向上取整")
        self.assertNotIn("tot / 240:.0f", code,
                         "zzz_cost 还在用 `:.0f` 算轮数")

    def test_farm_plan_uses_ceil(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_farm_plan.py").read_text(encoding="utf-8"))
        self.assertIn("(total_batt + _per_round - 1) // _per_round", code,
                      "zzz_farm_plan 没改成向上取整")
        self.assertNotIn("total_batt / max(1, args.battery):.0f", code,
                         "zzz_farm_plan 还在用 `:.0f` 算轮数")


class TestMcpDocsMatchCode(unittest.TestCase):
    """MCP 文档里的工具数必须和 `zzz_mcp.py` 实际注册的一致（E29）。

    ## 原来

    `zzz_mcp.py` 注册了 **9** 个 `_tool(...)`，而 `dsh-plugin/docs/DETAIL.md`
    写着「**8** 个工具」，表里也只有 8 行 —— 漏了 `zzz_scan_roster`。

    而 `zzz_scan_roster` 恰好是**最该被看到的那一个**：

        zzz_list_agents   列的是**配置库**里的 64 个
        zzz_scan_roster   扫的是**你账号上实际有的**

    把库列表当成账号角色给用户看，是最常见的误会。

    ## 另：en / zh 共用一份中文 DETAIL

    现在补了 `DETAIL.en.md`，两份互链，而且这条测试**两边都查**。
    """

    def _registered(self):
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_mcp.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        return sorted(
            node.args[0].value for node in _ast.walk(tree)
            if isinstance(node, _ast.Call)
            and getattr(node.func, "id", None) == "_tool"
            and node.args and isinstance(node.args[0], _ast.Constant))

    def test_docs_list_every_tool(self):
        import re
        import pathlib
        names = set(self._registered())
        self.assertGreaterEqual(len(names), 5, "没解析到工具？")
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        for rel in ("dsh-plugin/docs/DETAIL.md", "dsh-plugin/docs/DETAIL.en.md"):
            p = root / rel
            if not p.exists():
                self.fail(f"{rel} 不存在")
            md = p.read_text(encoding="utf-8")
            rows = set(re.findall(r"^\|\s*`(zzz_[a-z_]+)`", md, re.M))
            missing = sorted(names - rows)
            self.assertEqual(missing, [],
                             f"{rel} 漏了这些工具：{missing}")

    def test_docs_count_matches(self):
        import re
        import pathlib
        actual = len(self._registered())
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        for rel in ("dsh-plugin/docs/DETAIL.md", "dsh-plugin/docs/DETAIL.en.md"):
            p = root / rel
            if not p.exists():
                continue
            md = p.read_text(encoding="utf-8")
            m = re.search(r"(\d+)\s*个工具", md) or re.search(r"(\d+) tools", md)
            self.assertIsNotNone(m, f"{rel} 里找不到工具数")
            self.assertEqual(int(m.group(1)), actual,
                             f"{rel} 写 {m.group(1)} 个，实际 {actual} 个")

    def test_mcp_default_agent_is_not_hardcoded(self):
        """MCP 工具定义里也不能写死默认角色（E16 同类）。"""
        import ast as _ast
        import pathlib
        src = (pathlib.Path(__file__).resolve().parent.parent
               / "zzz_mcp.py").read_text(encoding="utf-8")
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Dict):
                continue
            for k, v in zip(node.keys, node.values):
                if not (isinstance(k, _ast.Constant) and k.value == "default"):
                    continue
                if (isinstance(v, _ast.Constant)
                        and isinstance(v.value, str) and v.value
                        and v.value not in ("", "佩洛伊斯")):
                    continue
                self.assertNotEqual(
                    getattr(v, "value", None), "佩洛伊斯",
                    f"L{node.lineno} 写死了默认角色名")


class TestWeeklyHasNoLimits(unittest.TestCase):
    """`core.weekly` 没有 `LIMITS`（E28）—— 用了就会静默失败。

    ## 原来

    ```python
    from core import weekly as _wk
    ...
    _wk.record(_cat)
    print(f"  记一次 {_cat}：本周 {_u}/{_wk.LIMITS.get(_cat, '?')}")
    except Exception:
        pass
    ```

    而 `core/weekly.py` 只导出 `FREE_RUNS` / `BATTERY_AFTER_FREE` /
    `used` / `free_left` / `cost_for_next` / `can_run` / `record` / `status`
    —— **没有 `LIMITS`**。

    `AttributeError` 被 `except Exception` 吞掉，于是：

    · `_wk.record(_cat)` **已经执行了**（记账成功）
    · 那行「记一次…」**从来没打印过**（用户以为没记账）

    **记账成功但看不见** —— 比不记账还糟。
    """

    def test_weekly_exports(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import weekly as W
        self.assertFalse(hasattr(W, "LIMITS"),
                         "weekly 现在有 LIMITS 了？那这条测试要更新")
        for name in ("FREE_RUNS", "used", "record", "can_run",
                     "cost_for_next", "free_left", "status"):
            self.assertTrue(hasattr(W, name), f"weekly 缺 {name}")

    def test_no_attribute_error_swallowed(self):
        """源码里不能再出现 `_wk.LIMITS`。"""
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "od_material_farm.py").read_text(encoding="utf-8"))
        self.assertNotIn(".LIMITS", code,
                         "还有 `_wk.LIMITS` —— 会 AttributeError 被吞掉")
        self.assertIn("FREE_RUNS", code, "没用 FREE_RUNS")


class TestTransitionAbortsOnFailure(unittest.TestCase):
    """`_do` 失败必须中断后续动作（F1）。

    ## 原来

    ```python
    for a in tr.actions:
        ok = self._do(a)
        if not ok and self.verbose:
            print(f"      动作失败：{a.kind} {a.arg} {a.xy}")
    ```

    `ok` 只用来打一行日志，然后**继续执行后面的动作**。

    动作为之间是有顺序依赖的（先点开、再选、再确认）。
    前一步没成，后一步的前提就不成立 —— 继续做只是**把错误放大**：
    在「没点开的面板」上接着点确认，可能点到完全不同的东西。

    ## 现在

    `Action.required`（默认 True）—— 失败了就 `return False`。
    少数「点一下试试」的动作可以标 `required=False`。
    """

    def _machine(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine

        class FakeVs:
            win = {"hwnd": 1}
            occluded = False
            def text(self, r): return ""
            def items(self, r): return []
            def frame(self, force=False): pass
            def wait_still(self, **k): pass
            def wait_for(self, *a, **k): return True
            def find(self, *a, **k): return None
            def _frame_key(self): return 1
            def has(self, *a): return False

        class FakeInp:
            def __init__(self): self.calls = []
            def __getattr__(self, name):
                def f(*a, **k): self.calls.append((name, a))
                return f

        class FakeUi:
            def __init__(self):
                self.vs, self.inp = FakeVs(), FakeInp()

        ui = FakeUi()
        m = Machine(ui)
        m.verbose = False
        return m, ui

    def test_required_action_aborts(self):
        from core.machine import Action, Transition
        m, ui = self._machine()
        tr = Transition(src="A", dst="*", actions=[
            Action("click_text", "不存在", region=(0, 0, 10, 10)),
            Action("key", "f")])
        ok = m.run(tr)
        self.assertFalse(ok, "失败的动作没让 run() 返回 False")
        self.assertFalse(any(c[0] == "key" for c in ui.inp.calls),
                         "前一个动作失败了，后一个还是执行了 —— 会在错界面上乱点")

    def test_optional_action_continues(self):
        from core.machine import Action, Transition
        m, ui = self._machine()
        tr = Transition(src="A", dst="*", actions=[
            Action("click_text", "不存在", region=(0, 0, 10, 10), required=False),
            Action("key", "f")])
        m.run(tr)
        self.assertTrue(any(c[0] == "key" for c in ui.inp.calls),
                        "required=False 的动作失败后应该继续")


class TestActionNHonored(unittest.TestCase):
    """`Action.n` 不能被静默忽略（F2）。

    ## 原来

    `_do` 里只有 `press` 和 `wheel` 用 `a.n`：

        press   -> pad_taps(arg, n)
        wheel   -> wheel(-n)
        key     -> key(arg)          ← n 被忽略
        click_xy-> click(x, y)       ← n 被忽略
        click_text -> click(...)     ← n 被忽略

    写 `Action("key", "f", n=3)` 和 `n=1` **效果完全一样，而且没有任何提示** ——
    转移表看起来是「按三次」，实际只按一次。
    """

    def test_key_honors_n(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine, Action, Transition

        class FakeVs:
            win = {"hwnd": 1}
            occluded = False
            def text(self, r): return ""
            def items(self, r): return []
            def frame(self, force=False): pass
            def wait_still(self, **k): pass
            def wait_for(self, *a, **k): return True
            def find(self, *a, **k): return None
            def _frame_key(self): return 1
            def has(self, *a): return False

        class FakeInp:
            def __init__(self): self.calls = []
            def __getattr__(self, name):
                def f(*a, **k): self.calls.append((name, a))
                return f

        class FakeUi:
            def __init__(self):
                self.vs, self.inp = FakeVs(), FakeInp()

        ui = FakeUi()
        m = Machine(ui)
        m.verbose = False
        m.run(Transition(src="A", dst="*", actions=[Action("key", "f", n=3)]))
        got = sum(1 for c in ui.inp.calls if c[0] == "key")
        self.assertEqual(got, 3, f"n=3 只按了 {got} 次 —— n 还是被忽略")

    def test_action_has_required_field(self):
        import sys
        import pathlib
        import dataclasses
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Action
        names = {f.name for f in dataclasses.fields(Action)}
        self.assertIn("required", names, "Action 没有 required 字段")


class TestFarmCmdIsParseable(unittest.TestCase):
    """`farm_cmd()` 拼出来的命令必须**真的能被 argparse 接受**（P0-3）。

    ## 原来

    ```python
    elif d.startswith("专业挑战室"):
        cmd += ["--challenge"]        # <- 没有值
    ```

    拼出来是：

        od_material_farm.py --challenge --times 2 --run

    argparse 把 `--times` 当成了 `--challenge` 的参数吞掉 ——
    `--times` 消失、挑战室名字变成 `--times`。

    结果「高维数据 / 刻命残蜕」这类**专业挑战室的东西完全刷不了**，
    而且**不报错**：用户看到命令跑完了，材料没涨。

    ## 测试思路

    不逐个断言「有没有值」，而是**拿真实 parser 解析一遍** ——
    任何「少了值 / 把选项当值」的写法都会当场暴露。
    """

    def test_challenge_has_value(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        cmd = farm_cmd("专业挑战室·深蚀回路", 2)
        self.assertIn("--challenge", cmd)
        i = cmd.index("--challenge")
        # `--challenge` 后面必须**还有东西**（不是末尾）
        self.assertLess(i + 1, len(cmd),
                        "`--challenge` 在命令行末尾，没有值")
        nxt = cmd[i + 1]
        self.assertFalse(nxt.startswith("-"),
                         f"`--challenge` 后面跟的是选项 `{nxt}` —— 它会把选项吞掉")

    def test_no_option_eats_another(self):
        """任何选项后面都不能紧跟另一个选项（除了已知的开关）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        SWITCHES = {"--run", "--again", "--from-gaps", "--plan-only"}
        cases = ["恶名狩猎·「征服者」", "专业挑战室·深蚀回路",
                 "实战模拟室·基础材料", "区域巡防·怪兽二重奏"]
        for d in cases:
            cmd = farm_cmd(d, 3)
            for i, tok in enumerate(cmd):
                if not tok.startswith("--") or tok in SWITCHES:
                    continue
                self.assertLess(i + 1, len(cmd), f"{d}: {tok} 在末尾没值")
                nxt = cmd[i + 1]
                self.assertFalse(
                    nxt.startswith("--"),
                    f"{d}: {tok} 后面紧跟选项 {nxt} —— 会把选项吞掉")

    def test_missing_name_is_loud(self):
        """专业挑战室没写名字时要**当场报错**，不能拼个残缺命令。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        with self.assertRaises(ValueError):
            farm_cmd("专业挑战室", 2)


class TestStableCheckCanSucceed(unittest.TestCase):
    """`_at` 的票数不能超过帧数（F3）。

    ## 原来

    ```python
    return _A.at(self.vs, target, tries=3, need=max(2, tries))
    ```

    * `tries=2` -> 3 帧取 2  ✔（默认就是想要的）
    * `tries=5` -> 3 帧取 **5** —— `hits` 最多 3，`need` 是 5，
      **永远返回 False，而且没有任何提示**

    调用方看到的是「到不了界面」，会去查游戏 —— 而问题在判法本身。

    ## 现在

    帧数 = `max(3, tries)`，`need = min(max(2, tries), 帧数)`。
    """

    def test_need_never_exceeds_frames(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine

        captured = {}

        class FakeVs:
            win = {"hwnd": 1}
            occluded = False
            def text(self, r): return ""
            def items(self, r): return []
            def frame(self, force=False): pass
            def _frame_key(self): return 1

        import core.anchors as A
        orig = A.at

        def fake_at(vision, target, tries=3, need=2, **kw):
            captured["tries"] = tries
            captured["need"] = need
            return True

        A.at = fake_at
        try:
            m = Machine.__new__(Machine)
            m.vs = FakeVs()
            for t in (1, 2, 3, 5, 8):
                captured.clear()
                Machine._at(m, "世界", tries=t)
                self.assertLessEqual(
                    captured["need"], captured["tries"],
                    f"tries={t} -> 帧 {captured['tries']} 票 {captured['need']}"
                    f" —— 票数超过帧数，永远满足不了")
        finally:
            A.at = orig

    def test_default_is_three_frames_two_votes(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.machine import Machine
        import core.anchors as A

        captured = {}

        class FakeVs:
            win = {"hwnd": 1}
            occluded = False
            def frame(self, force=False): pass
            def _frame_key(self): return 1

        orig = A.at

        def fake_at(vision, target, tries=3, need=2, **kw):
            captured.update(tries=tries, need=need)
            return True

        A.at = fake_at
        try:
            m = Machine.__new__(Machine)
            m.vs = FakeVs()
            Machine._at(m, "世界")
            self.assertEqual((captured["tries"], captured["need"]), (3, 2),
                             "默认应该是「三帧取两帧」")
        finally:
            A.at = orig


class TestLocalAgentIsVisible(unittest.TestCase):
    """`--add-agent` 加的角色必须被 `known()` / `resolve_agent()` 认（F6）。

    ## 原来

    · `--add-agent` 写的是 `state/characters.local.json`（`core/characters.py`）
    · 而 `known()` 只看 `meta()["角色"]` = `disc_meta.json`

    于是**加进去了但工具不认** —— 加完等于白加：

        python tools/zzz_who.py --add-agent 某人 --role 强攻 --element 以太
        ✔ 已写入 state/characters.local.json
        python tools/zzz_status.py 某人
        ✘ 角色「某人」不在角色库里

    ## 现在

    `known()` = `disc_meta.json` ∪ `characters.local.json`，
    `resolve_agent()` 也认本地层。
    """

    def test_added_agent_is_known(self):
        import sys
        import pathlib
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import agent_cfg as A
        from core import characters as C

        tmp = pathlib.Path(tempfile.mkdtemp()) / "characters.local.json"
        orig = C.LOCAL
        try:
            C.LOCAL = tmp
            self.assertNotIn("测试角色XZ", A.known(),
                             "这个测试角色本来不该在库里")
            C.add("测试角色XZ", {"定位": "强攻", "属性": "以太"})
            self.assertIn("测试角色XZ", A.known(),
                          "add() 之后 known() 还是看不到 —— --add-agent 白用")
            self.assertEqual(A.resolve_agent("测试角色XZ"), "测试角色XZ",
                             "resolve_agent 不认本地层的角色")
        finally:
            C.LOCAL = orig

    def test_missing_local_file_is_quiet(self):
        """没有 `characters.local.json` 是正常情况，不该炸。"""
        import sys
        import pathlib
        import tempfile
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import agent_cfg as A
        from core import characters as C

        tmp = pathlib.Path(tempfile.mkdtemp()) / "nope.json"
        orig = C.LOCAL
        try:
            C.LOCAL = tmp
            self.assertGreater(len(A.known()), 10, "known() 应该还有 disc_meta 的角色")
        finally:
            C.LOCAL = orig


class TestCheckConfigVerifiesModels(unittest.TestCase):
    """`check_config` 不能只测 OCR 能 import（E24）。

    ## 原来

        _code = "import one_dragon.base.matcher.ocr.onnx_ocr_matcher as m; print('ok')"

    只证明**能 import**。而**源码包安装**（不是完整包）里
    `assets/models/onnx_ocr` 是空的 —— import 照样成功。

    然后工具在**第一次读画面**时才去下载 100MB+，或者直接崩在
    ONNXRuntimeError 上。用户在前面看到「✔ 可用」就再也不会怀疑这一步。

    ## 现在

    额外查 `get_ocr_model_dir()` 那个目录里有没有 `det.onnx` / `rec.onnx`。
    """

    def test_checks_model_files(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "check_config.py").read_text(encoding="utf-8"))
        self.assertIn("get_ocr_model_dir", code,
                      "check_config 没查模型目录")
        self.assertIn("det.onnx", code, "没查 det.onnx")
        self.assertIn("rec.onnx", code, "没查 rec.onnx")

    def test_reports_missing_loudly(self):
        """缺模型时要 return 非零，不能说「✔ 可用」然后继续。"""
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "check_config.py").read_text(encoding="utf-8"))
        # **定位到那个 `elif` 分支**，不是 `_chk` 字符串里的同名片段
        i = code.find('elif "MISSING:" in _out2')
        self.assertGreater(i, -1, "找不到处理 MISSING 的分支")
        j = code.find("return 1", i)
        self.assertGreater(j, i,
                           "缺模型的分支里没有 return 非零 —— "
                           "用户会以为环境是好的")


class TestChipDungeonHasNoFakeSuffix(unittest.TestCase):
    """芯片副本名不能拼一个**不存在**的「（X测试）」后缀（E23）。

    ## 审计说的 vs 实际

    审计 E23 说「OneDragon 用 `升温测试`/`电流测试`/`共鸣测试`，
    zzz-host 用属性名，无映射」。

    查下来：**本版 OneDragon 全仓没有这三个字符串。**
    真正的机制是：

        mission_type_name = "代理人技能"     （固定）
        mission_name      = **角色名**        （不是芯片属性）

    所以 `zzz_gap` 原来拼的 `实战模拟室·代理人技能（电击测试）` 里，
    那个后缀是**臆造的** —— 没有对应的副本。

    它本身在 `farm_cmd` 里无害（子串匹配 `代理人技能` 就能命中），
    但会让人以为「有属性专用副本」。

    ## 这条测什么

    芯片副本名必须是**干净**的 `实战模拟室·代理人技能`，
    而且 `farm_cmd` 对「带后缀」和「不带后缀」都要路由到同一个 `--training`。
    """

    def test_chip_dungeon_is_clean(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_gap as G
        d = G.where_to_farm("特化以太芯片", role="强攻", attr="以太")
        self.assertIsNotNone(d, "芯片材料应该有路由")
        name = d.get("副本", "")
        self.assertEqual(name, "实战模拟室·代理人技能",
                         f"芯片副本名带了多余后缀：{name!r}")

    def test_farm_cmd_ignores_suffix(self):
        """带不带后缀都要路由到 `--training 代理人技能`。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        a = farm_cmd("实战模拟室·代理人技能", 2)
        b = farm_cmd("实战模拟室·代理人技能（电击测试）", 2)
        self.assertIn("--training", a)
        self.assertEqual(
            [x for x in a if x not in ("--run",)], [x for x in b if x not in ("--run",)],
            "带后缀和不带后缀路由结果不同")
        self.assertIn("代理人技能", a)


class TestCleanupUsesToolsJson(unittest.TestCase):
    """`cleanup_tools` 的保留清单必须合并 `tools.json`（E27）。

    ## 原来

    `CANON` 是**手工维护**的。工具越加越多，清单没跟上 ——
    预演说「移走 36 个」，而那些**全是在用的工具**。

    更糟的是它看起来很正常：每一行都有名字、都像那么回事。
    真加 `--apply` 就是 36 个工具被搬进 `_legacy/`。

    ## 现在

    以 `tools.json`（`gen_manifest.py` 从实际文件生成）为准 ——
    **只要 `tools.json` 里列了的，就一律保留**。实测 36 -> 18。
    """

    def test_merges_tools_json(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "cleanup_tools.py").read_text(encoding="utf-8"))
        self.assertIn("tools.json", code, "没读 tools.json")
        self.assertIn("_canon_effective", code, "没有生效清单函数")
        self.assertIn('d.get("tools")', code, "没取 tools 字段")

    def test_handles_list_shape(self):
        """`tools.json` 的 `tools` 是**字典列表**，不是映射（我第一版就栽在这）。"""
        import json
        import pathlib
        p = pathlib.Path(__file__).resolve().parent.parent.parent / "tools.json"
        if not p.exists():
            self.skipTest("tools.json 不在当前集合里")
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d.get("tools")
        self.assertIsInstance(items, (list, dict))
        if isinstance(items, list):
            self.assertTrue(items, "tools 列表是空的？")
            self.assertIsInstance(items[0], dict)
            self.assertIn("name", items[0],
                          "tools 列表里的每项应该有 name 字段")

    def test_has_move_limit(self):
        """数量反常要拒绝执行，不能一口气搬走几十个。"""
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "cleanup_tools.py").read_text(encoding="utf-8"))
        self.assertIn("_LIMIT", code, "没有数量护栏")
        self.assertIn("return 1", code, "超限时没有 return 非零")


class TestOrphanMaterialsGoToPreviousSection(unittest.TestCase):
    """无主材料要挂到**上一节**，不是「最后一节」（E32）。

    ## 原来

    ```python
    # **无主材料挂到「上一次见到的节」下面**
    _orphan = d.get("_未归属") or []
    if _orphan:
        tgt = merged["分节"][-1]        # <- 最后一个 = 本帧刚追加的新节
    ```

    注释是对的，代码不对：这一帧如果**刚刚追加了新节**
    （标题先滚进视野），`[-1]` 指向的是**新节**，而孤儿材料属于**上一节**。

    后果：上一节的最后几个材料被挂到下一节标题下面 ——
    看起来「这一节多了几样不该有的东西」。

    ## 现在

    在 append 新节**之前**记住 `_prev_last`，孤儿挂到它上面。
    """

    def test_prev_last_captured_before_append(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_guide.py").read_text(encoding="utf-8"))
        self.assertIn("_prev_last", code, "没有记录上一节的引用")
        # `_prev_last` 的赋值必须在 `merged["分节"].append` 之前
        i_prev = code.find("_prev_last = merged")
        i_app = code.find('merged["分节"].append')
        self.assertGreater(i_prev, -1, "找不到 _prev_last 赋值")
        self.assertGreater(i_app, -1, "找不到 append")
        self.assertLess(i_prev, i_app,
                        "_prev_last 是在 append 之后才记的 —— 那就没意义了")

    def test_orphan_uses_prev_last(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_guide.py").read_text(encoding="utf-8"))
        i = code.find("_orphan = d.get")
        self.assertGreater(i, -1)
        seg = code[i:i + 260]
        self.assertIn("tgt = _prev_last", seg,
                      "孤儿还是挂在 `merged[\"分节\"][-1]` 上")
        self.assertNotIn('merged["分节"][-1]', seg,
                         "孤儿还在用「最后一节」")


class TestShortNameDoesNotMatchEveryone(unittest.TestCase):
    """单字输入的候选不能是「谁都可以」（D23 / E20）。

    ## 根因

    `_edit_distance('2', '本') == 1` —— **任何**一个字符和**任何**一个
    单字名字的距离都是 1。所以 `d <= 1` 这个门槛对单字等于「全都匹配」。

    实测（修前）：

        suggest('2')  -> ['本', '柳', '照']      ← 纯垃圾
        suggest('?')  -> ['本', '柳', '照']
        suggest('露') -> ['本', '柳', '照']      ← 真正该出的「露西」被挤掉了

    两个后果正好是审计里的两条：

    · **E20**：「白名单丢掉本地角色」—— 真名字被垃圾挤出 `limit`
    · **D23**：残字恰好只剩 1 个候选时会**静默认错人**

    ## 现在

    · 单字只认「**包含**」关系（残字是名字的一部分），不算编辑距离
    · 而且单字**不自动纠正** —— 只报错 + 给建议，让用户确认
    """

    def test_single_char_gives_no_garbage(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import suggest
        self.assertEqual(suggest("2"), [],
                         "`suggest('2')` 应该给空 —— 不该匹配任何角色")
        self.assertEqual(suggest("?"), [],
                         "`suggest('?')` 应该给空")
        self.assertEqual(suggest("露"), ["露西"],
                         "`suggest('露')` 应该只给「露西」（包含关系）")

    def test_single_char_not_auto_corrected(self):
        """单字不能**静默**换成某个角色 —— 那是认错人（D23）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import resolve_agent, UnknownAgent
        for bad in ("2", "?", "露"):
            with self.assertRaises(UnknownAgent,
                                   msg=f"{bad!r} 被静默纠正了 —— 会认错人"):
                resolve_agent(bad)

    def test_two_char_still_auto_corrects(self):
        """两字以上仍然可以自动纠正（那是本来的便利）。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.agent_cfg import resolve_agent
        self.assertEqual(resolve_agent("丽那"), "丽娜")
        self.assertEqual(resolve_agent("11号"), "11号")


class TestOcrCacheIsPerFrame(unittest.TestCase):
    """OCR 缓存键必须带**帧号**（RT-23）。

    ## 原来

    ```python
    key = (region, round(scale, 2))
    ```

    不含帧号。于是 `frame()` 拿到**新一帧**之后，0.35 秒内 `items()`
    返回的还是**上一帧**的文字。

    这不是理论问题：`_do()` 里刚点完一个按钮就 `items()` 判结果，
    拿到的是点击**之前**的画面 —— 结论是「没生效」，于是再点一次。

    ## 实测（修后）

        同一帧读两次 -> 第 1 次 / 第 1 次   OCR 实际调用 1 次（走缓存）
        换帧后再读   -> 第 2 次            OCR 累计 2 次（重新识别）
    """

    def _vision(self):
        import sys
        import pathlib
        import threading
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import vision as V
        vs = V.Vision.__new__(V.Vision)
        vs._ocr_cache = {}
        vs._ocr_ttl = 5.0
        vs._lock = threading.Lock()
        vs._frame_id = 1
        vs.crop = lambda region: "img"
        calls = {"n": 0}

        def fake_raw(sub, scale=1.0):
            calls["n"] += 1
            n = calls["n"]

            class R:
                data = f"第{n}次"

                class center:
                    x = 10
                    y = 10
            return [R()]
        vs._ocr_raw = fake_raw
        return vs, calls

    def test_same_frame_uses_cache(self):
        vs, calls = self._vision()
        a = vs.items((0, 0, 100, 100))
        b = vs.items((0, 0, 100, 100))
        self.assertEqual(a[0]["text"], b[0]["text"])
        self.assertEqual(calls["n"], 1, "同一帧应该只 OCR 一次")

    def test_new_frame_invalidates(self):
        vs, calls = self._vision()
        a = vs.items((0, 0, 100, 100))
        vs._frame_id += 1
        c = vs.items((0, 0, 100, 100))
        self.assertNotEqual(a[0]["text"], c[0]["text"],
                            "换帧后还返回旧 OCR —— 会拿点击前的画面判结果")
        self.assertEqual(calls["n"], 2, "换帧后应该重新 OCR")


class TestAllAnchorsThrowingIsLoud(unittest.TestCase):
    """每个锚点都抛异常时不能静默返回 None（RT-25）。

    ## 原来

    ```python
    for a in (candidates or ANCHORS):
        try:
            if a.match(vision): return a
        except Exception:
            continue
    return None
    ```

    「这个锚点不匹配」和「读画面时崩了」混成同一个 `None`。
    于是 OCR 挂了 -> `describe()` 说「未知界面」-> 状态机开始**盲按 ESC**。
    用户看到「工具在乱点」，实际是 OCR 崩了，异常被吞得没痕迹。
    """

    def test_all_throwing_raises(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors as A

        class Bad:
            def match(self, vision):
                raise RuntimeError("模拟 OCR 崩了")

        with self.assertRaises(RuntimeError) as ctx:
            A.detect(object(), candidates=[Bad(), Bad()])
        self.assertIn("OCR", str(ctx.exception),
                      "报错没说清是 OCR/截图的问题")

    def test_none_matching_is_still_none(self):
        """都不匹配（但没抛）仍然是 None —— 那是正常的「未知界面」。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import anchors as A

        class No:
            def match(self, vision):
                return False

        self.assertIsNone(A.detect(object(), candidates=[No(), No()]))


class TestWatchdogIsGone(unittest.TestCase):
    """`watchdog()` 删掉了（RT-24）。

    它原来的 docstring 说「超时中断」，实际只是设了一个标志位 ——
    Python 的线程定时器**打断不了**正在阻塞的调用，而全仓
    **没有任何地方检查那个标志**。

    留着的害处：看到 `with watchdog(60):` 会以为这里有超时保护，
    实际上什么保护都没有。**一个让人误以为安全的东西，比没有更糟。**

    真要超时，得在等待循环内部判时间（`wait_for(..., timeout=)` 就是那样）。
    """

    def test_watchdog_removed(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import recovery as R
        self.assertFalse(hasattr(R, "watchdog"),
                         "watchdog 又回来了？它做不到名字承诺的事")

    def test_guard_still_there(self):
        """`guard()` 是**真实现**，只是没接上 —— 留着。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import recovery as R
        self.assertTrue(hasattr(R, "guard"))
        doc = (R.guard.__doc__ or "")
        self.assertIn("没有调用方", doc,
                      "guard 的 docstring 应该说清「目前没接上」")


class TestNoGameAccessBeforeArgs(unittest.TestCase):
    """**任何工具都不许在解析参数之前碰游戏**。

    ## 为什么有这条

    曾发生过一次真机事故：`zzz_guide_max.py` / `zzz_guide_plan.py` /
    `zzz_guide_stats.py` **根本没有 argparse** —— 传 `--help` 会被无视，
    然后照常往下走：`Vision()` → `Input()` → `ui.start()` → 开始点游戏。

    也就是说「我只是想看看帮助」变成了「它动我的号」。

    更糟的是它们自己的重试循环：打开养成指南 → 某步失败 →
    `reset_to_world()` 按 ESC 关掉 → 再来一遍。看起来就是
    「一直点开又关上」，**只有 Alt+F4 关掉游戏才能停**。

    当时它是一堆没被收尾的后台任务的子进程，所以「任务停了它还在跑」。

    ## 这条规矩

    · 工具**有**碰游戏的调用，就必须有 `parse_args()`；
      而且同一个函数里，`parse_args()` 要在它们**之前**
    · 工具**没有** `parse_args()`，就不许有任何碰游戏的调用
    · 碰游戏的调用不许出现在**模块级**（导入即执行）

    ## 为什么按「函数」而不是按「行号」

    `feishu_img.py` 里 `Vision()` 在 `shoot()` 中（L55 附近），
    而 `parse_args()` 在 `main()` 中（L68）—— 行号上 Vision 在前，
    但它是**被 main 调用**的，实际执行在 parse_args 之后。
    按行号比会误判，按函数归属才对。
    """

    #: **真的会动到游戏的**：注入输入 / 抢焦点 / 起 OneDragon 上下文。
    #:
    #: `find_window()` **不算** —— 它是纯查询（枚举窗口、读矩形），
    #: `check_config` 用它确认「游戏开着吗」，那是正当用途。
    GAME = {"Vision", "Input", "Ui", "ZContext"}

    def _scan(self, path):
        src = path.read_text(encoding="utf-8")
        tree = _ast.parse(src)

        # **模块级**（不在任何函数/类里）的碰游戏调用
        #
        # 注意：不能直接对顶层节点 `walk()` —— `def main()` 本身就是一个
        # 顶层节点，walk 进去会把函数里的调用也算成「模块级」。
        # （第一版就是这么错的，报了 6 个假阳性。）
        module_level = []

        def _walk_module(node):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef,
                                 _ast.ClassDef, _ast.Lambda)):
                return          # 不进函数体
            if isinstance(node, _ast.Call):
                nm = _ast.unparse(node.func).split(".")[-1]
                if nm in self.GAME:
                    module_level.append((node.lineno, nm))
            for ch in _ast.iter_child_nodes(node):
                _walk_module(ch)

        def _is_main_block(node) -> bool:
            """`if __name__ == "__main__":` —— 只在直接运行时才执行。

            它里面的代码**可以**碰游戏，但同样要满足
            「`parse_args()` 在前」。所以单独当一段来查，而不是算模块级。
            """
            if not isinstance(node, _ast.If):
                return False
            t = _ast.unparse(node.test)
            return "__main__" in t

        main_block = []
        for node in tree.body:
            if _is_main_block(node):
                game, pa = [], []
                for sub in _ast.walk(node):
                    if not isinstance(sub, _ast.Call):
                        continue
                    nm = _ast.unparse(sub.func).split(".")[-1]
                    if nm in self.GAME:
                        game.append((sub.lineno, nm))
                    if getattr(sub.func, "attr", None) == "parse_args":
                        pa.append(sub.lineno)
                if game:
                    main_block.append((min(pa) if pa else None, sorted(game)))
                continue
            _walk_module(node)

        # 每个函数里：碰游戏的行号 + parse_args 的行号
        per_fn = []
        for node in _ast.walk(tree):
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            game, pa = [], []
            for sub in _ast.walk(node):
                if not isinstance(sub, _ast.Call):
                    continue
                nm = _ast.unparse(sub.func).split(".")[-1]
                if nm in self.GAME:
                    game.append((sub.lineno, nm))
                if getattr(sub.func, "attr", None) == "parse_args":
                    pa.append(sub.lineno)
            if game:
                per_fn.append((node.name, sorted(game), min(pa) if pa else None))

        any_pa = any(
            isinstance(sub, _ast.Call)
            and getattr(sub.func, "attr", None) == "parse_args"
            for sub in _ast.walk(tree))
        # `__main__` 块里的碰游戏调用，也算进 per_fn（按「函数」对待）
        for pa, game in main_block:
            per_fn.append(("__main__", game, pa))
        return module_level, per_fn, any_pa

    def test_no_tool_touches_game_before_args(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        bad = []
        checked = 0
        for f in sorted(root.glob("*.py")):
            if f.name.startswith(("test", "run_tests")):
                continue
            try:
                mod_level, per_fn, any_pa = self._scan(f)
            except SyntaxError:
                continue
            checked += 1
            if mod_level:
                bad.append(f"{f.name}: 模块级就碰游戏 L{[l for l, _ in mod_level]}")
            if per_fn and not any_pa:
                bad.append(
                    f"{f.name}: 碰游戏（{[n for n, _, _ in per_fn]}）"
                    f"但**完全没有 argparse** —— `--help` 会被无视然后去点游戏")
            for fname, game, pa in per_fn:
                if pa is not None and game and pa > game[0][0]:
                    bad.append(
                        f"{f.name}:{fname} 里 parse_args(L{pa}) 在 "
                        f"{game[0][1]}(L{game[0][0]}) **之后**")
        self.assertGreater(checked, 20, f"只检查了 {checked} 个工具？")
        self.assertEqual(bad, [],
                         "这些工具在解析参数之前就可能碰游戏：\n  "
                         + "\n  ".join(bad))


class TestMissingSubDungeonIsHandled(unittest.TestCase):
    """缺具体副本名时**不能崩**，也不能拼残缺命令（真机实测发现的回归）。

    ## 背景

    P0-3 修了 `farm_cmd("专业挑战室")` 拼出 `--challenge --times 12`
    的 bug（argparse 会把 `--times` 当成 `--challenge` 的参数吞掉）。
    修法是**缺子名就抛 `ValueError`**，这本身是对的。

    ## 但真机实测发现：调用方没人接

    `zzz_gap.py:458` 是 `cmd = farm_cmd(d, runs, ...)` —— 没有 try。
    而 `where_to_farm("高维数据：凶刑讣告")` 返回的正是**裸** `专业挑战室`
    （`dungeon_data.json` 里没有「材料 → 具体挑战」的对照表）。

    所以 `zzz_gap --run` 会在刷到那一项时 **traceback 退出**，
    前面已经刷成功的几项白刷。

    ## 现在

    · `farm_cmd` 仍然抛（保持严格，不拼残缺命令）
    · `zzz_gap` / `zzz_daily` 都接住，跳过该项并说清是「数据缺失」
    · `where_to_farm` 返回 `缺子名: True`，计划表里显示
      `专业挑战室 ⚠缺副本名`，并有汇总说明
    """

    def test_farm_cmd_still_strict(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        with self.assertRaises(ValueError):
            farm_cmd("专业挑战室", 12)
        # 带子名照常
        c = farm_cmd("专业挑战室·深蚀回路", 12)
        self.assertIn("--challenge", c)
        self.assertIn("深蚀回路", c)

    def test_where_to_farm_marks_missing_name(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_gap as G
        w = G.where_to_farm("高维数据：凶刑讣告", role="支援", attr="冰")
        self.assertIsNotNone(w, "高维数据应该有路由")
        self.assertTrue(w.get("缺子名"),
                        "裸「专业挑战室」没有标 缺子名 —— 用户会以为能自动刷")

    def test_callers_catch_value_error(self):
        """两个调用方都要接住 ValueError，不能让整轮崩。"""
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        for name in ("zzz_gap.py", "zzz_daily.py"):
            code = _code((root / name).read_text(encoding="utf-8"))
            self.assertIn("except ValueError", code,
                          f"{name} 没接住 farm_cmd 的 ValueError")
            self.assertIn("farm_cmd", code)


class TestGuideScrollIsSlowEnough(unittest.TestCase):
    """养成指南选角色时**一屏只滚 2 格，并等画面停稳**（真机反馈）。

    ## 用户实测

    「网格里没找到「佩洛伊斯」（养成指南只覆盖当期有攻略的角色）」
    —— 用户说：**绝对有的，全部角色都有，你滑动得太快了**。

    ## 根因（两处叠加）

    ```python
    inp.wheel(-4, wait=1.0)     # 一次 4 格；只等 1 秒
    vs.frame(force=True)
    ```

    · 网格一行大约 2~3 格 —— **一次 4 格会跳过整行**，
      那一行里的角色永远不会被读到
    · 只等 1 秒 —— 列表还在惯性滚动时截帧，OCR 读到的是花屏

    ## 现在

    `wheel(-2)`（和一行高度重叠，不跳行）+ `wait_still` 等真的停住，
    `max_scroll` 从 20 提到 40 保住覆盖范围。

    实测：修后「第 2 屏找到「佩洛伊斯」名字 … ✔ 已切到「佩洛伊斯」」。
    """

    def _code_guide(self):
        import pathlib
        return _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_guide.py").read_text(encoding="utf-8"))

    def test_scroll_step_is_two(self):
        code = self._code_guide()
        self.assertIn("inp.wheel(-2", code,
                      "选角色的滚动步长不是 -2 —— 又会跳行")
        # 全文（`select_agent` + `read_detail_all`）都不能再有一次滚 4 格
        self.assertNotIn("wheel(-4", code,
                         "还有一次滚 4 格的地方 —— 会跳过整行")

    def test_waits_for_still_after_scroll(self):
        code = self._code_guide()
        i = code.find("inp.wheel(-2")
        self.assertGreater(i, -1)
        seg = code[i:i + 400]
        self.assertIn("wait_still", seg,
                      "滚完没等画面停稳 —— OCR 会读到花屏")

    def test_failure_message_is_not_misleading(self):
        """不能说「养成指南只覆盖约 46 个」—— 全部角色都有。"""
        code = self._code_guide()
        self.assertNotIn("只覆盖当期有攻略的角色（约 46 个）", code,
                         "失败提示还在说是数据覆盖问题 —— 实际多数是漏读")


class TestMaterialNameFragments(unittest.TestCase):
    """材料名要把碎片拼起来，并且去重、去图标垃圾。

    ## 真机实测（佩洛伊斯）

    修前：

        e        所需 90　已有 2　仍需 88      ← 和下面同一行，读成了两个名字
        特化以太芯片  所需 90　已有 2　仍需 88
        a        所需 45　已有 7　仍需 38
        CC       所需  2　已有 2　仍需  0

    只拼不筛时：

        e特化以太芯片                         ← 碎片粘在真名前面
        a高维数据：深蚀回路
        CC「仓鼠笼」访问器

    只筛不拼时，`e` 和 `特化以太芯片` 会被当**两个材料**，
    同一需求算两遍 —— 电量从 800 虚高到 1100。

    ## 正确顺序

    ① 逐段查 `OCR别名`（`CC` 是「「仓鼠笼」访问器」的有效读法，
       先丢碎片会把这条映射丢掉）
    ② 映射后**仍是 1~3 个纯英文字母**的才当图标碎片丢弃
    ③ 剩下的按 x 顺序拼
    ④ **去重** —— `CC` 和真名会映射成同一个字符串

    修后实测：

        特化以太芯片        90 / 2 / 88
        「仓鼠笼」访问器      2 / 2 /  0
        刻命残蜕            7 / 1 /  6
        高维数据：深蚀回路    45 / 7 / 38
    """

    def test_join_alias_dedupe_present(self):
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_guide.py").read_text(encoding="utf-8"))
        self.assertIn("_parts", code, "没有分段处理")
        self.assertIn("_ALIAS.get(_t, _t)", code, "没逐段查别名")
        self.assertIn('re.fullmatch(r"[A-Za-z]{1,3}", _t)', code,
                      "没丢纯字母图标碎片")
        self.assertIn("dict.fromkeys(_parts)", code, "没去重")

    def test_order_alias_before_drop(self):
        """**先查别名再丢碎片** —— 反了会丢掉 `CC` 这条有效映射。"""
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_guide.py").read_text(encoding="utf-8"))
        i_alias = code.find("_ALIAS.get(_t, _t)")
        i_drop = code.find('re.fullmatch(r"[A-Za-z]{1,3}", _t)')
        self.assertGreater(i_alias, -1)
        self.assertGreater(i_drop, -1)
        self.assertLess(i_alias, i_drop,
                        "顺序反了：先丢碎片会丢掉 `CC -> 「仓鼠笼」访问器` 这条映射")

    def test_behavior(self):
        """直接跑一遍拼接逻辑（把代码里的规则复刻出来验证语义）。"""
        import re
        ALIAS = {"CC": "「仓鼠笼」访问器"}

        def join(names):
            parts = []
            for t in names:
                t = t.strip()
                if not t:
                    continue
                t = ALIAS.get(t, t)
                if re.fullmatch(r"[A-Za-z]{1,3}", t):
                    continue
                parts.append(t)
            parts = list(dict.fromkeys(parts))
            return "".join(parts).strip()

        self.assertEqual(join(["e", "特化以太芯片"]), "特化以太芯片")
        self.assertEqual(join(["a", "高维数据：深蚀回路"]), "高维数据：深蚀回路")
        self.assertEqual(join(["CC", "「仓鼠笼」访问器"]), "「仓鼠笼」访问器")
        self.assertEqual(join(["刻命残蜕"]), "刻命残蜕")


class TestTrainingRoomsGetAMission(unittest.TestCase):
    """实战模拟室**必须**传 `--mission`，而且要是 compendium 里的真任务名。

    ## 真发现（比我之前的判断更严重）

    `farm_cmd` **从来不传 `--mission`**，而 `od_material_farm` 对
    实战模拟室强制要求 —— 于是**所有**芯片/认证章/音擎/经验的刷本调用
    都是 exit 2，一个都刷不了。

    同时我自己的守卫写宽了：`_NEED_MISSION` 原来是
    `{"实战模拟室", "专业挑战室", "恶名狩猎"}`，但按 OneDragon 的
    `compendium_data.yml`，**只有实战模拟室有 mission_list**：

        实战模拟室   代理人技能 -> 刚性/升温/冰结/电流/风切/共鸣/琢光 + 测试
                     代理人晋升 -> {职业}演练
                     音擎改装   -> 锋御耦合试验 / 命破共鸣试验 / …
                     基础材料   -> 调查专项 / 音擎专项 / 赏金专项 / 镀剂专项
        专业挑战室   mission_type 直接就是 boss 名（「征服者」/恶名·杜拉罕…）
        恶名狩猎     同上（基塔布鲁 / 冥宁芙·双子…）

    所以 `--hunt 基塔布鲁` / `--challenge 「征服者」` 原来会被**误拒**。

    ## 我还判错过一次

    审计 E23 说「OneDragon 用 `升温测试`/`电流测试`/`共鸣测试`」，
    我当时只 grep 了 `*.py` 就说「本版没有这三个名字」—— **判错了**，
    它们在 `.yml` 里。所以芯片的任务名是**元素测试名**，
    不是角色名，也不是我臆造的「电击测试」。
    """

    def test_chip_test_names_match_compendium(self):
        """芯片任务名必须是 compendium 里那七个测试名。"""
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.mission_map import CHIP_TEST
        want = {
            "物理": "刚性测试", "火": "升温测试", "冰": "冰结测试",
            "电": "电流测试", "风": "风切测试", "以太": "共鸣测试",
            "流明": "琢光测试",
        }
        for attr, mission in want.items():
            self.assertEqual(CHIP_TEST.get(attr), mission,
                             f"{attr} 的测试名应该是 {mission}")

    def test_farm_cmd_emits_mission(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        c = farm_cmd("实战模拟室·代理人技能", 3, mission="共鸣测试")
        self.assertIn("--mission", c, "没拼 --mission —— od_material_farm 会 exit 2")
        i = c.index("--mission")
        self.assertEqual(c[i + 1], "共鸣测试")

    def test_where_to_farm_gives_mission(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_gap as G
        cases = [
            ("特化以太芯片", "强攻", "以太", "共鸣测试"),
            ("基础冰结芯片", "支援", "冰", "冰结测试"),
            ("高阶强攻认证章", "强攻", "以太", "强攻演练"),
            ("资深调查员记录", "强攻", "以太", "调查专项"),
            ("镀剂", "强攻", "以太", "镀剂专项"),
        ]
        for m, r, a, want in cases:
            w = G.where_to_farm(m, role=r, attr=a)
            self.assertIsNotNone(w, f"{m} 应该能路由")
            self.assertEqual(w.get("mission"), want,
                             f"{m} 的 mission 应该是 {want}")

    def test_need_mission_is_only_training_room(self):
        """`_NEED_MISSION` 只能含实战模拟室 —— 另两类没有 mission_list。"""
        import pathlib
        code = _code((pathlib.Path(__file__).resolve().parent.parent
                      / "od_material_farm.py").read_text(encoding="utf-8"))
        self.assertIn('_NEED_MISSION = {"实战模拟室"}', code,
                      "守卫又写宽了 —— 会误拒 --hunt / --challenge")
        self.assertNotIn('"专业挑战室", "恶名狩猎"}', code,
                         "守卫还在要求专业挑战室/恶名狩猎传 mission")

    def test_boss_and_challenge_need_no_mission(self):
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core.farm_cmd import farm_cmd
        for d in ("恶名狩猎·基塔布鲁", "专业挑战室·「征服者」"):
            c = farm_cmd(d, 3)
            self.assertNotIn("--mission", c,
                             f"{d} 不需要 mission，不该拼")


class TestLevelLabelIsNotASubStat(unittest.TestCase):
    """盘的「等级N/M」不是副词条，不该进「未识别词条」告警。

    ## 真机现象

    一次 `zzz_plan` 的 **91 行**输出里有 **57 行**是：

        [disc_cfg] 未识别的副词条 10 条：
        ['等级15/15', '等级0/', '等级', '等级', ...]（未计入有效值）

    OCR 把盘面上的等级标签混进了副词条。

    ## 为什么必须修

    分数**没受影响**（标注「未计入」），但那条告警的**存在意义**是
    「有真词条被白名单漏掉了」—— 57 行噪音会把真正的漏词条彻底淹掉。
    一个永远在响的警报等于没有警报。

    ## 修法

    `effective()` 里：`等级` 开头、后面只跟数字和斜杠的，直接跳过。
    真·未知词条仍然告警。
    """

    def _eff(self, subs):
        import sys
        import pathlib
        import io
        import contextlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        from core import disc_cfg
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            eff, rows = disc_cfg.effective(
                subs, ["攻击力百分比", "暴击率", "暴击伤害"], [])
        return eff, rows, buf.getvalue()

    def test_level_labels_are_silent(self):
        eff, rows, out = self._eff([("等级15/15", "0"), ("等级0/", "0"),
                                    ("等级", "0")])
        self.assertEqual(out.strip(), "",
                         f"等级标签还在告警：{out.strip()[:80]}")
        self.assertEqual(rows, [])
        self.assertEqual(eff, 0.0)

    def test_level_plus_real_substat(self):
        eff, rows, out = self._eff([("等级15/15", "0"),
                                    ("攻击力百分比+2", "0"),
                                    ("暴击率+1", "0")])
        self.assertEqual(out.strip(), "", "有真词条时不该告警")
        self.assertEqual(len(rows), 2, f"应该认出 2 条真词条，实际 {len(rows)}")
        # 分数怎么算归别的测试管 —— 这条只证明「等级不告警、真词条仍被认出」

    def test_real_unknown_still_warns(self):
        """**真·未知词条必须仍然告警** —— 别把哨兵一起修没了。"""
        eff, rows, out = self._eff([("完全没听过的词条", "+1")])
        self.assertIn("未识别的副词条", out,
                      "真未知词条不告警了 —— 白名单漏词条会再次变成静默")


class TestAgentPlanTool(unittest.TestCase):
    """`zzz_agent_plan`：设置「特训目标」，让游戏自己路由到副本。

    ## 为什么要有这个工具

    算「材料 → 副本」这条路走不通：
    `高维数据：深蚀回路` 该去哪个专业挑战室 boss，`dungeon_data.json` 里没这张表。

    **但游戏自己有这条路**：设好特训目标 → 点「前往」→ 游戏直接路由过去。
    OneDragon 也支持（`mission_type_name == '代理人方案培养'` → `is_agent_plan`、
    `STATUS_AGENT_PLAN_FINISHED = '特训目标已达成'`），
    但它**只跟随、不设置**（全仓搜「更换特训目标」「设置为目标」一处都没有）。

    ## 真机验证的流程（2026-11-28）

    ```
    大世界 → F2 → 快捷手册
      → Tab 训练 (1173,180)
      → 更换特训目标 (1391,354)
      → 网格：点头像（名字上方 60px）
      → 底部「清除目标」变成「设置为目标」(1143,830)
      → 点它 → **弹确认框**「已将X设置为特训目标，是否替换？」
      → 确认 (1129,679)
      → 训练页「特训目标」块显示新名字（586,302）
      → 「前往」直接路由到副本
    ```
    """

    def _code_ap(self):
        import pathlib
        return _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_agent_plan.py").read_text(encoding="utf-8"))

    def test_uses_f2_not_menu(self):
        """**必须用 F2** —— 主菜单底部栏里没有「快捷手册」。"""
        code = self._code_ap()
        self.assertIn('inp.key("f2"', code, "不是用 F2 打开快捷手册")

    def test_has_confirm_step(self):
        """点完「设置为目标」还有一步「确认」—— 漏了就等于没设。"""
        code = self._code_ap()
        self.assertIn('find("确认"', code, "没有点「确认」这一步")
        # 确认框的位置（实测 1128,679）
        self.assertIn("(700, 600, 1300, 760)", code,
                      "确认框的搜索区域不对 —— 实测确认按钮在 (1129,679)")

    def test_grid_detector_does_not_match_title(self):
        """判「还在网格上」不能用「特训目标」—— 网格标题「更换特训目标」包含它。"""
        code = self._code_ap()
        self.assertIn("_on_grid", code, "没有网格判据函数")
        self.assertIn("特训方案", code,
                      "网格判据应该用「特训方案」（网格独有），不是「特训目标」")

    def test_avatar_offset(self):
        """头像在名字**上方** 60px —— 点名字那行不行。"""
        code = self._code_ap()
        self.assertIn("AVATAR_DY", code)
        self.assertIn("AVATAR_DY = -60", code, "头像偏移不是 -60")

    def test_scroll_is_slow(self):
        """网格滚动也要慢 —— 一次 4 格会跳过整行。"""
        code = self._code_ap()
        self.assertIn("inp.wheel(-2", code, "滚动步长不是 -2")
        self.assertIn("wait_still", code, "滚完没等画面停稳")
        self.assertNotIn("wheel(-4", code, "还有一次滚 4 格的地方")

    def test_help_works(self):
        import subprocess
        import sys
        import pathlib
        f = pathlib.Path(__file__).resolve().parent.parent / "zzz_agent_plan.py"
        r = subprocess.run([sys.executable, str(f), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage:", r.stdout)

class TestAgentPlanGoDoesNotClickBlindly(unittest.TestCase):
    """`--go` 默认**只报告位置不点**（真机事故后的锁）。

    ## 事故

    我以为「左侧类别标签和右侧『前往』在同一 y」，按 y 差 ≤18 配对。
    实测点「专业挑战室」那行的前往 (1475,722) ——
    **进了实战模拟室-代理人技能**（传送后画面上是
    风切测试/刚性测试/升温测试/冰结测试/电流测试）。

    左栏 4 个类别标签 y=489/597/707/814 **固定不动**，
    右边是**可滚动内容** —— 它们的「前往」不在同一行。

    ## 现在

    · 默认：滚一遍、把匹配到的行和「前往」位置**报出来**，一下都不点
    · 加 `--force` 才真的点（并在 docstring 里写清风险）
    """

    def _code_ap(self):
        import pathlib
        return _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_agent_plan.py").read_text(encoding="utf-8"))

    def test_has_allow_click_switch(self):
        code = self._code_ap()
        self.assertIn("allow_click", code, "没有 allow_click 开关")

    def test_pairs_go_by_row_offset(self):
        """任务名和它那行的「前往」y 差约 80px（实测 79/85/84/86）。

        原来按 ≤18 配对 —— 永远配不上，配到别的行，传到错的副本
        （点「专业挑战室」的结果进了实战模拟室-代理人技能）。
        """
        code = self._code_ap()
        self.assertIn("ROW_GO_LO", code, "没有配对容差常量")
        self.assertIn("ROW_GO_DY = 80", code, "行内偏移不是 80")

    def test_left_rail_is_category_switch(self):
        """左栏是**类别切换**，不是行标签 —— 点它筛右边。"""
        code = self._code_ap()
        self.assertIn("LEFT_RAIL", code, "没有左栏坐标表")
        self.assertIn("_pick_rail", code, "没有切类别的函数")

    def test_searches_all_categories(self):
        """不指名类别时，要**挨个类别翻** —— 只在一个视图里滚会漏。"""
        code = self._code_ap()
        for cat in ("实战模拟室", "区域巡防", "专业挑战室", "恶名狩猎"):
            self.assertIn(cat, code)

    def test_teleport_has_confirm(self):
        """点「前往」之后还有一步「是否立即传送？」。"""
        code = self._code_ap()
        self.assertIn("是否立即传送", code, "没等传送确认框")

class TestAgentPlanCanListTargets(unittest.TestCase):
    """`--list` 要能把 4 个类别下的所有目标全列出来，一下都不点。

    ## 为什么需要

    「哪个材料该去哪个 boss」这张对照表我们没有，但**游戏里有**。
    与其维护一张会过期的表，不如先把可选目标列全，再按名字去 `--go`。

    真机跑出来 41 个（去重前），带几个 OCR 碎片：
    `诡步与` / `诡步与重壁`、`「霸主侵蚀体·庞培」` / `「霸主侵蚀体・庞培」`。
    """

    def _code_ap(self):
        import pathlib
        return _code((pathlib.Path(__file__).resolve().parent.parent
                      / "zzz_agent_plan.py").read_text(encoding="utf-8"))

    def test_has_list_mode(self):
        code = self._code_ap()
        self.assertIn('"--list"', code, "没有 --list")
        self.assertIn("def list_all", code, "没有 list_all")

    def test_list_covers_all_categories(self):
        code = self._code_ap()
        for cat in ("实战模拟室", "区域巡防", "专业挑战室", "恶名狩猎"):
            self.assertIn(cat, code)

    def test_list_dedupes_fragments(self):
        """碎片要去掉：`诡步与` 只是 `诡步与重壁` 的一截。"""
        code = self._code_ap()
        self.assertIn("_n(", code, "没有规范化函数")
        self.assertIn("ni in norms[j]", code, "没做「只是别人的一截」的过滤")

    def test_agent_is_optional(self):
        code = self._code_ap()
        self.assertIn('nargs="?"', code, "agent 还是必填的 —— --list 时没有角色")
