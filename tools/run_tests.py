"""跑所有单元测试。

## 用法

```
python tools/run_tests.py            # 简洁输出
python tools/run_tests.py -v         # 每个用例都列出来
```

## 为什么要有这个

`smoke_test` 只跑 `--help`，`audit_*` 只做静态扫描。
**判盘逻辑、止损线、调律预算这些算法原本一条测试都没有。**

这个跑 `tools/tests/` 下的 unittest 用例。
**不碰游戏、不碰 OCR**，所以任何机器上都能跑。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = HERE / "tests"


def main() -> int:
    if not TESTS.is_dir():
        print(f"✘ 没有测试目录：{TESTS}")
        return 2

    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    # 让 tests/ 能 import core.*
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE.parent))

    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS), pattern="test_*.py",
                            top_level_dir=str(HERE))

    if suite.countTestCases() == 0:
        print("✘ 一个用例都没找到")
        return 2

    runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
    result = runner.run(suite)

    print()
    print("=" * 60)
    total = result.testsRun
    bad = len(result.failures) + len(result.errors)
    if bad == 0:
        print(f"✔ 全部通过：{total} 个用例")
        print("=" * 60)
        return 0
    print(f"✘ {total} 个用例里 {bad} 个失败")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
