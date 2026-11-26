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
import unittest
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parent.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


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
