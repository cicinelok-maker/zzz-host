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
            raise RuntimeError("没找到游戏窗口")
        self.ocr = ocr or self._make_ocr()
        self._img = None
        self._img_t = 0.0
        self._frame_id = 0                 # 每抓一帧 +1，OCR 缓存按它失效
        self._cache_ms = cache_ms
        self._ocr_cache: dict[tuple, tuple[float, list]] = {}
        self._ocr_ttl = 0.35               # OCR 结果有效期（秒）
        self._lock = threading.Lock()

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
        o = OnnxOcrMatcher()
        o.init_model()
        return o

    # ================= 帧 =================
    def frame(self, force: bool = False) -> np.ndarray:
        now = time.time() * 1000
        if force or self._img is None or now - self._img_t > self._cache_ms:
            self._img = live.grab(self.win)
            self._img_t = now
            self._frame_id += 1
            if force:
                # 强制刷帧必须同时清 OCR 缓存，否则换界面后还会读到上一屏的文字
                with self._lock:
                    self._ocr_cache.clear()
        return self._img

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

    def text_scaled(self, region: Region, scale: float = 2.0) -> str:
        """小字区域用：放大后再读"""
        return self.text(region, scale=scale)

    def text_verified(self, region: Region, tries: int = 2,
                      min_agree: int = 2) -> tuple[str, bool]:
        """多帧投票：读两次结果一致才采信。返回 (文本, 是否可信)。"""
        seen: dict[str, int] = {}
        last = ""
        for i in range(tries):
            last = self.text(region)
            seen[last] = seen.get(last, 0) + 1
            if seen[last] >= min_agree:
                return last, True
            self.frame(force=True)
            time.sleep(0.12)
        best = max(seen.items(), key=lambda kv: kv[1])[0]
        return best, seen[best] >= min_agree

    def text_many(self, regions: dict[str, Region]) -> dict[str, str]:
        """多区域读取。

        **实测结论：并行没有收益。**
        三个区域串行 808ms，开 4 线程并行 851ms（预热后仍然如此）——
        ONNX 推理吃满 CPU，线程争用抵消了并行收益，再叠加 GIL。
        所以这里老老实实串行；真正省时间的办法是「缩小区域」和「用模板/颜色」。
        """
        self.frame()
        return {name: self.text(r) for name, r in regions.items()}

    def find(self, keyword: str, region: Region, exact: bool = False,
             **kw) -> dict | None:
        for it in self.items(region, **kw):
            if (it["text"] == keyword) if exact else (keyword in it["text"]):
                return it
        return None

    def find_all(self, keyword: str, region: Region) -> list[dict]:
        """返回区域内所有含 keyword 的文字块（含坐标）"""
        return [i for i in self.items(region) if keyword in i["text"]]

    def find_corrected(self, keyword: str, region: Region,
                       corrector=None) -> dict | None:
        """容忍 OCR 错字的查找：先精确找，再纠错比对"""
        hit = self.find(keyword, region)
        if hit:
            return hit
        if corrector is None:
            return None
        for it in self.items(region):
            if corrector(it["text"]) == keyword:
                return it
        return None

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

    # ================= 颜色 =================
    def color_at(self, x: int, y: int, radius: int = 4) -> tuple[int, int, int]:
        """取点的平均 RGB（BGR→RGB）"""
        img = self.frame()
        patch = img[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
        if patch.size == 0:
            return (0, 0, 0)
        b, g, r = patch[:, :, 0].mean(), patch[:, :, 1].mean(), patch[:, :, 2].mean()
        return (int(r), int(g), int(b))

    def is_highlighted(self, x: int, y: int, radius: int = 18,
                       thresh: float = 110) -> bool:
        """是否块状高亮（选中项底色偏亮）"""
        img = self.frame()
        patch = img[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
        return bool(patch.size and patch[:, :, :3].mean() > thresh)

    def rarity_at(self, x: int, y: int) -> str:
        """按颜色判断稀有度：金=S 紫=A 蓝=B 其它=?"""
        r, g, b = self.color_at(x, y, radius=6)
        if r > 150 and g > 110 and b < 110:
            return "S"
        if r > 110 and b > 130 and g < 110:
            return "A"
        if b > 130 and r < 110:
            return "B"
        return "?"

    def find_color(self, rgb: tuple[int, int, int], region: Region,
                   tol: int = 26, min_ratio: float = 0.02) -> tuple[int, int] | None:
        """在区域里找指定颜色，返回第一个匹配点（步进采样，快）"""
        x0, y0, x1, y1 = region
        sub = self.crop(region)
        r, g, b = rgb
        mask = ((np.abs(sub[:, :, 2].astype(int) - r) < tol) &
                (np.abs(sub[:, :, 1].astype(int) - g) < tol) &
                (np.abs(sub[:, :, 0].astype(int) - b) < tol))
        if mask.mean() < min_ratio:
            return None
        ys, xs = np.nonzero(mask)
        return (int(xs.mean()) + x0, int(ys.mean()) + y0)

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

    def save_template(self, name: str, region: Region) -> Path:
        import cv2
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMPLATE_DIR / f"{name}.png"
        img = np.ascontiguousarray(self.crop(region))
        ok, buf = cv2.imencode(".png", img)
        if not ok:
            raise RuntimeError(f"模板编码失败: {name}")
        path.write_bytes(buf.tobytes())
        return path

    # ================= 变化检测 =================
    def wait_change(self, region: Region, timeout: float = 8.0,
                    thresh: float = 6.0) -> bool:
        base = self.crop(region).astype("float32")
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(0.08)
            cur = self.crop(region).astype("float32")
            if float(np.abs(cur - base).mean()) > thresh:
                return True
        return False

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
