# 状态对账（重要）

## 数字变了：93 → 205

新拿到的 `AUDIT-BUGS.md` 已经不是 93 条了：

```
第一轮 93（P0 9 / P1 20 / P2 13 / P3 11 / P4 40）
第二轮 112（P0 3 / P1 24 / P2 35 / P3 22 / P4 28）
合计 205
```

## 一个坑：新文件的 baseline 是 `0ce6aa5`

`0ce6aa5` 比我现在的 HEAD（`578ce3c`）旧。
所以这 205 条是**基于旧代码的全量重扫** ——
**我已经修好的 20 条，在新文件里仍然标着 `status: open`。**

那 20 条是：

```
BUG-001 002 003 004   拆解链（等级匹配 + 两道安全阀）
BUG-005               换装没验证
BUG-006               zzz_plan --apply 用旧坐标
BUG-007               zzz_level read 会真晋升
BUG-008               无条件转化 5 种材料
BUG-009               三个破坏性工具被标成只读
BUG-011               生命/防御百分比被静默丢
BUG-013               rolls 上限算成 7
BUG-014               2 条盘决策倒挂
BUG-015               繁体双字键永不命中
BUG-016               套装名配错副本
BUG-026               名字正则（读侧）
BUG-030               Unity 窗口绕过标题校验
BUG-043               5 个自检脚本恒 exit 0
BUG-046               测试全 skip 也算通过
BUG-069 070           两处 NameError
```

## 别把「文件里还 open」当成「没修」

下次对齐时，请以**代码**为准，不要只看 `status` 字段。
验证方式（三条都能独立跑）：

```bash
python tools/run_tests.py          # 66 个用例（原 43，新增的都对应上面每一条）
python tools/audit_patterns.py     # 现在真的会 exit 1
grep -n "_farm_cmd\|_equip_confirmed\|_level_label\|allow_convert" tools/*.py tools/core/*.py
```

## 真机报告（RT-REPORT）已经修的 3 条

RT 报告给了「最小可行修复顺序」，按它修了前三项：

| RT 条目 | 修了什么 | commit |
|---|---|---|
| 第 1 条 | `Vision.__init__` 改成 `SystemExit(5)` + 中文提示（一处修 8 个工具） | `578ce3c` |
| 第 2 条 | `zzz_status` 补 `blue_total`/`unread`；`stamp()` 加 `_schema` | `578ce3c` |
| 第 3 条 | 加「技能页」「基础页」锚点并排在「代理人列表」前面 | `578ce3c` |
| 第 6 条 | 4 个自检脚本改成能变红 | `a28fe09` |

**还没修的第 4、5 条**（`reset_to_world` 确认、`verify` 层参与判定）
都要改导航主链，且必须真机验 —— 盲改会把现在能走的路弄坏。

## RT 报告**证伪**了我几条静态预测（这些不用修）

| 被证伪的 | 实测结论 |
|---|---|
| `smoke_test` env 残缺致 cv2 崩 | 本机 39 行全 ✔，只有干净机器才成立 |
| `machine.py:185-188` 代理人列表→装备页 永不成立 | **那条边是通的**（`reached=装备页`） |
| `pick_agent` 名字正则让 9/64 角色整链不可用 | 正则在**读侧**，输入侧 `zzz_who 本/照/简` 全正常 |
| `zzz_status` 错名走 `SystemExit(2)` | 实际是 RuntimeError + exit 1（已按 RT-1 修成 exit 5） |
| `zzz_equip --help` 只有 `-h` | 有 `upgrade/equip/show` 子命令，正常 |
| `selfcheck --help` 立刻崩 | 是跑完前五节才崩在第六节 |

**所以第一轮那 93 条里，至少 6 条是不成立的。**
剩下的 205 条清单里可能还有同类误报 —— 建议按 RT 报告那种「真机验一遍」再定。