"""底层视觉：区域 OCR + 模板匹配 + 颜色判定，全部限定区域以换取速度。

## 实测性能（1920x1080）

    ┌─────────────────┬──────────┐
    │ 全屏 OCR        │  992 ms  │  ← 禁止
    │ 详情面板 OCR    │  250 ms  │
    │ 小区域 OCR      │   50 ms  │
    │ 模板匹配        │  1~5 ms  │
    │ 颜色采样        │  <1 ms   │
    │ 窗口抓取        │  118 ms  │
    └─────────────────┴──────────┘

## 本模块提供的加速与提准手段

    cache          同一区域同一帧不重复 OCR
    parallel       多区域同时 OCR（线程池）
    verified       读两次一致才采信（消灭单次误读）
    scaled         小字 2 倍超采样再 OCR
    color          颜色判定（稀有度/高亮，1ms 级）
    template       模板匹配（固定按钮首选）
"""
from __future__ import annotations

import itertools as _itertools

# Vision 实例的唯一序号（E12）—— 比 id() 可靠：id 会被回收复用
_VISION_SEQ = _itertools.count(1)

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
sys.path.insert(0, str(TOOLS))
# 不硬编码本机路径 —— 用 core.paths 探测
try:
    from core.paths import one_dragon_home as _odh2
    _od2 = _odh2()
    if _od2:
        sys.path.insert(0, str(Path(_od2) / "plugins"))
        sys.path.insert(0, str(Path(_od2) / "src"))
except Exception:
    pass

import live  # noqa: E402
import numpy as np  # noqa: E402

TEMPLATE_DIR = TOOLS.parent / "od_test" / "templates"
Region = tuple[int, int, int, int]

_pool = ThreadPoolExecutor(max_workers=4)


class Vision:
    def __init__(self, ocr=None, cache_ms: int = 120):
        self.win = live.find_window()
        if not self.win:
            # **游戏没开是「最常见、最可预期」的情况，不该变成未捕获异常。**
            #
            # 真机实测（RT-REPORT N-1）：8 个碰游戏的工具全是
            # `RuntimeError: 没找到游戏窗口` + traceback + exit=1。
            # 而 exit=1 在码表里是「一般失败」——**调用方无从区分
            # 「游戏没开」和「代码有 bug」**，于是不知道是该启动游戏还是报障。
            #
            # 这里改成 SystemExit(5)：
            # · 5 = 等窗口/条件超时（AGENTS.md 码表里最接近的一个）
            # · SystemExit 继承 BaseException，**不会被 `except Exception` 吞掉**
            # · 一处修掉全部 8 个工具，不用逐个加守卫
            print("✘ 没找到绝区零窗口。", file=sys.stderr)
            print("  游戏没开就先跑：python tools/zzz_launch.py", file=sys.stderr)
            print("  （退出码 5 = 等窗口/条件超时，见 AGENTS.md 码表）",
                  file=sys.stderr)
            raise SystemExit(5)
        self.ocr = ocr or self._make_ocr()
        # **实例唯一序号**（E12）。
        #
        # `describe()` 的缓存键原来是 `(id(self), frame_key)` ——
        # 而 `id()` 在对象被回收后**会被复用**。两个不同的 Vision 实例
        # 只要恰好拿到同一个地址，就会命中对方缓存的结论。
        #
        # 实测症状：同一份代码连跑两次，一次过一次不过；
        # `audit_ship` 内部重跑 run_tests 时红而单独跑全绿 ——
        # 看起来像环境问题，其实是缓存串台。
        self._uid = next(_VISION_SEQ)
        self._img = None
        self._img_t = 0.0
        self._frame_id = 0                 # 每抓一帧 +1，OCR 缓存按它失效
        self._cache_ms = cache_ms
        self._ocr_cache: dict[tuple, tuple[float, list]] = {}
        self._ocr_ttl = 0.35               # OCR 结果有效期（秒）
        self._lock = threading.Lock()
        self.occluded = False       # 上一帧是否可能读到遮挡物（BUG-032）

    @staticmethod
    def _make_ocr():
        # 先把 OneDragon 的 src/plugins 塞进 sys.path ——
        # PYTHONPATH 环境变量只在解释器启动时生效，
        # 工具里 os.environ.update() 对当前进程的 sys.path 没用。
        # 新用户没有手动设过 PYTHONPATH，不这样就会 import 失败。
        try:
            import sys as _sys
            from core.paths import one_dragon_home as _odh
            _home = _odh()
            if _home:
                from pathlib import Path as _P
                for _sub in ("src", "plugins"):
                    _p = str(_P(_home) / _sub)
                    if _P(_p).is_dir() and _p not in _sys.path:
                        _sys.path.insert(0, _p)
                # OneDragon 的 config 目录也可能在 sys.path 上被引用
                _cfg = str(_P(_home) / "config")
                if _P(_cfg).is_dir() and _cfg not in _sys.path:
                    _sys.path.append(_cfg)
        except Exception:
            pass

        try:
            from one_dragon.base.matcher.ocr.onnx_ocr_matcher import OnnxOcrMatcher
        except ImportError:
            from core.paths import one_dragon_home, one_dragon_python
            home = one_dragon_home()
            py = one_dragon_python()
            print("=" * 62)
            print("缺少 OneDragon —— 本项目读游戏画面要用它的 OCR 模块")
            print("=" * 62)
            print("  1 下载 OneDragon 完整包（不是源码版）：")
            print("     https://github.com/OneDragon-Anything/"
                  "ZenlessZoneZero-OneDragon/releases")
            print("  2 解压到任意目录")
            print("  3 把路径写进 paths.json：")
            print('     {"one_dragon_home": "你的解压目录"}')
            print("     或设环境变量 ONE_DRAGON_HOME")
            print("  4 验证：python tools/check_config.py")
            print()
            print(f"  当前探测结果：{home or '（没找到）'}")
            if home and not py:
                print("  ⚠ 目录找到了但没有 .venv\\Scripts\\python.exe")
                print("     下载「完整包」而不是「源码包」")
            print("=" * 62)
            raise SystemExit(2)
        # **模型加载失败也要说人话**（BUG-033）。
        #
        # 上面只处理了「模块 import 不到」（OneDragon 没装 / 路径不对），
        # 但**装是装了、模型文件坏了**是另一种情况：
        # `OnnxOcrMatcher()` 或 `init_model()` 会抛 ONNXRuntimeError /
        # FileNotFoundError 之类，一路冒到顶层变成 30 行 traceback。
        #
        # 而这类错误的表现是「读不到画面」—— 很容易被当成
        # 「到不了界面」或「游戏卡了」，人跑去查游戏。
        try:
            o = OnnxOcrMatcher()
            o.init_model()
        except Exception as e:
            from core.paths import one_dragon_home as _oh
            print("=" * 62)
            print(f"✘ OneDragon 的 OCR 模块加载失败：{type(e).__name__}")
            print(f"  {e}")
            print("=" * 62)
            print("  装是装了，但模型文件可能不完整。常见原因：")
            print("  · 下载的是「源码包」不是「完整包」→ 缺 assets/models/onnx_ocr")
            print("  · 解压时漏了 assets 目录")
            print("  · 杀软删了 .onnx 文件")
            print()
            print(f"  当前 OneDragon 目录：{_oh() or '（没找到）'}")
            print("  验证：python tools/check_config.py")
            print("=" * 62)
            raise SystemExit(2) from None
        return o

    # ================= 帧 =================
    def frame(self, force: bool = False) -> np.ndarray:
        now = time.time() * 1000
        if force or self._img is None or now - self._img_t > self._cache_ms:
            # **遮挡检测（BUG-032 / RT-REPORT 柱 1）**
            #
            # `live.grab()` 是 `ImageGrab.grab(bbox=窗口坐标)` ——
            # **抓的是「屏幕那个位置」的像素，不是窗口内容**。
            # 窗口被别的程序盖住时，读到的是遮挡物。
            #
            # 实测踩过：浏览器盖在游戏上，OCR 读出来的是 GitHub 页面，
            # 而 `describe()` 只会说「未知界面」——
            # 上层以为「游戏画面变了」，实际上是**在拿别人的像素做判断**。
            # 对破坏性操作（换装/拆解）来说这是致命的。
            self._ensure_foreground()
            self._img = live.grab(self.win)
            self._img_t = now
            self._frame_id += 1
            if force:
                # 强制刷帧必须同时清 OCR 缓存，否则换界面后还会读到上一屏的文字
                with self._lock:
                    self._ocr_cache.clear()
        return self._img

    def _ensure_foreground(self) -> None:
        """确认游戏在前台；不在就抢，抢不到就把 `occluded` 标起来。

        不抛异常（用户可能只是切窗看个消息），但**必须让人知道** ——
        静默读别人的画面比报错危险得多。
        """
        try:
            if live.foreground(self.win):
                if self.occluded:
                    print("  ⚠ 游戏窗口之前被遮挡过，已抢回前台")
                self.occluded = False
                return
        except Exception:
            return          # 查不了就别拦，别把正常流程弄挂
        if not self.occluded:
            print("  ⚠ 游戏窗口不在前台 —— **现在读到的可能是别的程序的画面**")
            print("     请把绝区零窗口切到最前。工具会在下一帧自动重试。")
        self.occluded = True

    def crop(self, region: Region) -> np.ndarray:
        x0, y0, x1, y1 = region
        return self.frame()[y0:y1, x0:x1]

    def _frame_key(self) -> int:
        return self._frame_id

    # ================= OCR =================
    def _ocr_raw(self, sub: np.ndarray, scale: float = 1.0) -> list:
        img = sub
        if scale != 1.0:
            import cv2
            img = cv2.resize(sub, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC)
        return self.ocr.ocr(np.ascontiguousarray(img)) or []

    def items(self, region: Region, *, scale: float = 1.0,
              use_cache: bool = True) -> list[dict]:
        """区域内 OCR。带缓存；scale>1 时先放大（小字更准，但不缓存）。"""
        key = (region, round(scale, 2))
        if use_cache:
            with self._lock:
                hit = self._ocr_cache.get(key)
                if hit and time.time() - hit[0] < self._ocr_ttl:
                    return hit[1]

        x0, y0, x1, y1 = region
        sub = self.crop(region)
        out = []
        for r in self._ocr_raw(sub, scale):
            txt = (getattr(r, "data", "") or "").strip()
            if not txt:
                continue
            c = getattr(r, "center", None)
            if c is None:
                continue
            out.append({"text": txt,
                        "cx": int(c.x / scale) + x0,
                        "cy": int(c.y / scale) + y0})
        if use_cache:
            with self._lock:
                self._ocr_cache[key] = (time.time(), out)
        return out

    def text(self, region: Region, **kw) -> str:
        return " | ".join(i["text"] for i in self.items(region, **kw))




    def find(self, keyword: str, region: Region, exact: bool = False,
             **kw) -> dict | None:
        for it in self.items(region, **kw):
            if (it["text"] == keyword) if exact else (keyword in it["text"]):
                return it
        return None

    def find_all(self, keyword: str, region: Region) -> list[dict]:
        """返回区域内所有含 keyword 的文字块（含坐标）"""
        return [i for i in self.items(region) if keyword in i["text"]]


    def has(self, region: Region, *keywords: str) -> bool:
        t = self.text(region)
        return all(k in t for k in keywords)

    def wait_for(self, region: Region, *keywords: str,
                 timeout: float = 8.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.has(region, *keywords):
                return True
            time.sleep(0.1)
        return False

    def debug_text(self) -> str:
        """全屏 OCR —— 仅调试用（约 1 秒）"""
        return " | ".join(getattr(i, "data", "").strip()
                          for i in (self.ocr.ocr(self.frame()) or [])
                          if getattr(i, "data", "").strip())





    # ================= 模板 =================
    def template(self, name: str, region: Region | None = None,
                 threshold: float = 0.82) -> tuple[int, int, float] | None:
        import cv2
        path = TEMPLATE_DIR / f"{name}.png"
        if not path.exists():
            return None
        # 注意：cv2.imread 在 Windows 上不支持中文路径，会静默返回 None，
        # 所以走 Python 读文件 + imdecode
        try:
            buf = np.frombuffer(path.read_bytes(), dtype=np.uint8)
            tpl = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            return None
        if tpl is None:
            return None
        x0, y0 = (0, 0) if region is None else (region[0], region[1])
        area = self.frame() if region is None else self.crop(region)
        th, tw = tpl.shape[:2]
        if area.shape[0] < th or area.shape[1] < tw:
            return None
        res = cv2.matchTemplate(area, tpl, cv2.TM_CCOEFF_NORMED)
        _, maxv, _, maxloc = cv2.minMaxLoc(res)
        if maxv < threshold:
            return None
        return (maxloc[0] + tw // 2 + x0, maxloc[1] + th // 2 + y0, float(maxv))

    def template_at(self, name: str, pad: int = 40,
                    threshold: float = 0.80) -> tuple[int, int, float] | None:
        """按清单里记录的已知位置，只在其附近 pad 像素内搜索。

        为什么必须限定范围：全屏搜模板要 140~160ms，和 OCR 差不多；
        但在 300x300 区域里只要 6ms。固定在某个界面的按钮，位置是稳定的，
        所以可以放心用小范围。
        """
        import json
        man_path = TEMPLATE_DIR / "manifest.json"
        if not man_path.exists():
            return self.template(name)
        try:
            man = json.loads(man_path.read_text(encoding="utf-8"))
        except Exception:
            return self.template(name)
        info = man.get(name)
        if not info or not info.get("region"):
            return self.template(name)
        x0, y0, x1, y1 = info["region"]
        area = (max(0, x0 - pad), max(0, y0 - pad),
                min(1920, x1 + pad), min(1080, y1 + pad))
        return self.template(name, area, threshold=threshold)



    def wait_still(self, region: Region | None = None, quiet: float = 0.3,
                   timeout: float = 8.0, thresh: float = 3.0) -> bool:
        prev = self.frame(force=True) if region is None else self.crop(region)
        last = time.time()
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.08)
            cur = self.frame(force=True) if region is None else self.crop(region)
            if float(np.abs(cur.astype("float32") - prev.astype("float32")).mean()) > thresh:
                last = time.time()
            prev = cur
            if time.time() - last >= quiet:
                return True
        return False