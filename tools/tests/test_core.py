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
        src = inspect.getsource(Input.key)
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
        src = inspect.getsource(vision)
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
        src = inspect.getsource(z.enter_game)
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
        import builtins
        BUILTIN = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
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
        src = inspect.getsource(omf)
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
        src = inspect.getsource(zzz_tune.do_tune)
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
        src = inspect.getsource(zzz_tune)
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
        src = inspect.getsource(zzz_disc_train)
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
        src = inspect.getsource(zzz_disc_daily)
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
        src = inspect.getsource(zzz_disc_daily)
        self.assertIn('if "失败" in a', src,
                      "zzz_disc_daily 没有按 actions 里的「失败」判退出码")

    def test_daily_tracks_noprog(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_daily
        src = inspect.getsource(zzz_daily)
        self.assertIn("_noprog", src, "zzz_daily 没有记录「没做成事」的次数")
        self.assertIn("return 1", src, "zzz_daily 没有失败出口")

    def test_grind_fails_when_target_missed(self):
        import inspect
        import sys
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        import zzz_grind
        src = inspect.getsource(zzz_grind)
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
        src = inspect.getsource(zzz_daily)
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
