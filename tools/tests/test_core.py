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
        src = inspect.getsource(Vision.__init__)
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
        """`zzz_status` 写出的 payload 必须包含全部 REQUIRED 键。"""
        import inspect
        import zzz_status
        from core.state import REQUIRED_STATUS_KEYS
        src = inspect.getsource(zzz_status.main)
        for k in REQUIRED_STATUS_KEYS:
            self.assertIn(f'"{k}"', src,
                          f"zzz_status 的 _payload 没写 {k}")


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
        src = inspect.getsource(zzz_status.main)
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
        src = inspect.getsource(zc.read_levels)
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
        src = inspect.getsource(zzz_mcp.call_tool)
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
    """`zzz_daily --run` 要记得今天刷过没（BUG-091）。

    ## 原来完全不记

    `zzz_daily --run` 一天跑两次就刷两次本 —— **第二天的电量被提前烧掉**。
    而这是「每日养成」工具，每天的额度应该只花一次。

    修法：`state/farm_log.json` 记 `{date, count, last, last_dungeon}`，
    刷本前看今天的 count；已有就跳过（`--again` 可强制）。
    """

    def setUp(self):
        import zzz_daily as zd
        self.zd = zd
        self.f = zd._farm_log_path()
        self.bak = self.f.read_text(encoding="utf-8") if self.f.exists() else None
        self.f.unlink(missing_ok=True)

    def tearDown(self):
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
        d["date"] = "2000-01-01"
        self.f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.zd._farm_count_today(), 0)

    def test_record_survives_bad_file(self):
        """坏 JSON 不能让记账崩掉，也不能误判成「刷过了」。"""
        self.f.write_text("{半截", encoding="utf-8")
        self.assertEqual(self.zd._farm_count_today(), 0)
        self.zd._farm_record("测A", 1)          # 不抛异常
        self.assertEqual(self.zd._farm_count_today(), 1)

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
        src = inspect.getsource(zd.read_status)
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
        """AGENTS.md 说「有 --json」的工具必须真的在 --help 里出现 --json。"""
        import re
        import pathlib
        import subprocess
        import sys
        root = pathlib.Path(__file__).resolve().parent.parent.parent
        doc = root / "AGENTS.md"
        if not doc.exists():
            # **发布集里可能没有 AGENTS.md** —— `audit_ship` 会把发布集
            # 复制到临时目录里跑测试，那份集合是仓库的子集。
            # 测试不能假定「仓库里有的文件发布集里也有」。
            self.skipTest("AGENTS.md 不在当前集合里（发布集子集）")
        txt = doc.read_text(encoding="utf-8")
        # 取「只有这 6 个有 --json」之后那个代码块
        m = re.search(r"现在只有这 \d+ 个有：\s*```\s*\n(.*?)```", txt, re.S)
        if not m:
            self.skipTest("AGENTS.md 里没找到那份清单（可能措辞变了）")
        claimed = re.findall(r"(\w+)\.py", m.group(1))
        self.assertGreater(len(claimed), 0)
        for name in claimed:
            p = root / "tools" / f"{name}.py"
            self.assertTrue(p.exists(), f"AGENTS.md 声称 {name}.py 有 --json，但文件不存在")
            try:
                r = subprocess.run([sys.executable, "-u", str(p), "--help"],
                                   capture_output=True, text=True,
                                   encoding="utf-8", errors="replace",
                                   cwd=str(root), timeout=120)
            except (OSError, subprocess.SubprocessError) as e:
                self.skipTest(f"跑不起来 {name}.py --help：{e}")
            self.assertIn("--json", r.stdout or "",
                          f"AGENTS.md 说 {name}.py 有 --json，实测没有")


class TestSetCoverageAndThresholds(unittest.TestCase):
    """套装白名单要覆盖副本表，毕业阈值三处要一致（BUG-184 顺带）。

    ## 套装白名单漏了 2 个

    `vocab.SETS` 是 **OCR 纠错的目标集合** —— 不在里面的名字认不出来。
    实测 `disc_meta.套装副本` 有 31 个套装，而白名单只有 29 个：
    漏了 `山大王` 和 `月光摇篮曲`。

    于是这两个套装的盘会被当成「未知套装」，主词条/套装判定全失效。

    ## 毕业阈值写在 3 个地方

    ```
    core/disc_cfg.py:80     "graduation": 28.0
    tools/zzz_grind.py:42   GRADES = {"小毕业": 28.0, ...}
    tools/zzz_status.py:27  GRAD = [("小毕业", 28.0), ...]
    ```

    现在三处一致（28 / 32 / 37），但没有东西保证以后也一致。
    """

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
            m = re.match(r"\s*(python tools/[\w.]+\.py[^\s#]*(?:\s+[^\s#][^#]*)?)", line)
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
        src = inspect.getsource(zzz_daily.main)
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
        src = inspect.getsource(zzz_equip.main)
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
        src = inspect.getsource(zzz_launch.main)
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
        src = inspect.getsource(check_config.main)
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
        src = inspect.getsource(check_config.main)
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
        src = inspect.getsource(ui.Ui.start)
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
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import pick_agent
        src = inspect.getsource(pick_agent.list_agents)
        self.assertIn("角色库", src, "list_agents 里没有白名单校验")
        self.assertIn("认不出的名字", src, "没有「认不出」的警告")


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
        src_m = inspect.getsource(Machine._at)
        src_r = inspect.getsource(recovery.reset_to_world)
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
