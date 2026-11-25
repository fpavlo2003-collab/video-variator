# -*- coding: utf-8 -*-
"""
Розширені покращення для Video Variator (оновлюється разом із програмою):
  • розумне кадрування під 9:16 / 1:1 / 4:5 — камера «стежить» за обличчям або людиною;
  • автосубтитри (Whisper, локально) у стилі CapCut з підсвіткою слова;
  • автокорекція кольору й експозиції;
  • якісна двопрохідна стабілізація (vidstab);
  • AI-апскейл (Real-ESRGAN) та AI-плавність / сповільнення (RIFE);
  • очищення голосу від шуму.
Важкі компоненти (OpenCV, Whisper, Real-ESRGAN, RIFE) встановлюються з програми один раз.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import math
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
TOOLS_DIR = APP_DIR / "tools"
CACHE_DIR = APP_DIR / "cache"
IS_WIN = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
_REPO_RAW = "https://raw.githubusercontent.com/fpavlo2003-collab/video-variator/main/"


def _ascii_home() -> Path:
    """Папка без кирилиці для моделей (деякі AI-бібліотеки не люблять кирилицю у шляху)."""
    base = os.environ.get("LOCALAPPDATA") if IS_WIN else os.path.expanduser("~/.cache")
    p = Path(base or tempfile.gettempdir()) / "VideoVariator"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        p = Path(tempfile.gettempdir()) / "VideoVariator"
        p.mkdir(parents=True, exist_ok=True)
    return p


MODELS_DIR = _ascii_home() / "models"

# ---------------------------------------------------------------------------
#  Компоненти
# ---------------------------------------------------------------------------

COMPONENTS: dict[str, dict] = {
    "opencv": {"title": "OpenCV", "kind": "pip", "pip": ["opencv-python"], "module": "cv2",
               "size": "≈60 МБ", "for": "розумного кадрування"},
    "whisper": {"title": "Whisper", "kind": "pip", "pip": ["faster-whisper"], "module": "faster_whisper",
                "size": "≈150 МБ", "for": "автосубтитрів"},
    "esrgan": {"title": "Real-ESRGAN", "kind": "zip", "exe": "realesrgan-ncnn-vulkan", "size": "≈45 МБ",
               "for": "AI-апскейлу",
               "win": [("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
                        "realesrgan-ncnn-vulkan-20220424-windows.zip",
                        "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d")],
               "other": [("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/"
                          "realesrgan-ncnn-vulkan-20220424-ubuntu.zip",
                          "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96")]},
    "rife": {"title": "RIFE", "kind": "zip", "exe": "rife-ncnn-vulkan", "size": "≈12 МБ",
             "for": "AI-плавності кадрів",
             "win": [(_REPO_RAW + "tools/rife-ncnn-vulkan-win-slim.zip",
                      "ad5cbfea66156d8474db5738ce1bd4d00db4b5f724c683068cc5eed4cad8b4fc"),
                     ("https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/"
                      "rife-ncnn-vulkan-20221029-windows.zip", None)],
             "other": [("https://github.com/nihui/rife-ncnn-vulkan/releases/download/20221029/"
                        "rife-ncnn-vulkan-20221029-ubuntu.zip", None)]},
}
YUNET_URL = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
             "face_detection_yunet/face_detection_yunet_2023mar.onnx")
YUNET_SHA = None  # файл маленький, перевіряємо, що це справді ONNX (а не HTML-сторінка)

UPSCALE_MODELS = {"Швидка ×2": ("realesr-animevideov3", 2), "Якісна ×4 (повільно)": ("realesrgan-x4plus", 4)}
SMOOTH_MODES = ["Вимкнено", "Плавні 60 к/с", "Сповільнення ×2"]
VOICE_LEVELS = {"Легке": 8, "Середнє": 14, "Сильне": 22}
WHISPER_MODELS = {"Швидка (base)": "base", "Точна (small)": "small", "Найточніша (medium)": "medium"}
WHISPER_SIZES = {"base": "≈145 МБ", "small": "≈480 МБ", "medium": "≈1.5 ГБ"}
SUB_LANGS = {"Авто": None, "Українська": "uk", "English": "en", "Русский": "ru", "Polski": "pl",
             "Deutsch": "de", "Español": "es", "Français": "fr", "Italiano": "it", "Português": "pt"}
SUB_STYLES = ["Обводка", "Плашка", "Тінь"]
SUB_COLORS = {"Жовтий": (255, 221, 0), "Зелений": (0, 230, 118), "Фіолетовий": (140, 105, 255),
              "Червоний": (255, 64, 64), "Без підсвітки": None}
SUB_POSITIONS = ["Знизу", "По центру", "Зверху"]


def _module_ok(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def tool_exe(name: str) -> str | None:
    comp = COMPONENTS[name]
    folder = TOOLS_DIR / name
    if not folder.is_dir():
        return None
    target = comp["exe"] + (".exe" if IS_WIN else "")
    for p in sorted(folder.rglob(target)):
        if p.is_file():
            return str(p)
    return None


def component_ready(name: str) -> bool:
    comp = COMPONENTS[name]
    if comp["kind"] == "pip":
        return _module_ok(comp["module"])
    return tool_exe(name) is not None


def component_installable(name: str) -> bool:
    return not (FROZEN and COMPONENTS[name]["kind"] == "pip")


def python_cli() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def _refresh_paths():
    try:
        user_site = site.getusersitepackages()
        if user_site and user_site not in sys.path and os.path.isdir(user_site):
            site.addsitedir(user_site)
    except Exception:  # noqa: BLE001
        pass
    importlib.invalidate_caches()


def _download(url: str, dst: Path, progress: Callable[[float, str], None] | None, label: str,
              stop: threading.Event | None = None) -> None:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "VideoVariator"})
    tmp = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(req, timeout=40) as r, open(tmp, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            if stop is not None and stop.is_set():
                raise RuntimeError("скасовано")
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if progress and now - last > 0.25:
                last = now
                frac = done / total if total else 0.0
                progress(frac, f"{label}: {done / 1e6:.0f}" + (f" з {total / 1e6:.0f} МБ" if total else " МБ"))
    os.replace(tmp, dst)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_yunet(log: Callable[[str], None] | None = None) -> str | None:
    """Модель детектора облич YuNet (~230 КБ). Повертає шлях або None."""
    dst = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
    if dst.is_file() and dst.stat().st_size > 100_000:
        return str(dst)
    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        _download(YUNET_URL, dst, None, "YuNet")
        if dst.stat().st_size < 100_000:
            dst.unlink()
            return None
        return str(dst)
    except Exception as exc:  # noqa: BLE001
        if log:
            log(f"   (детектор YuNet недоступний: {exc} — використаю класичний)")
        return None


def install_component(name: str, log: Callable[[str], None],
                      progress: Callable[[float, str], None]) -> bool:
    comp = COMPONENTS[name]
    title = comp["title"]
    if comp["kind"] == "pip":
        if FROZEN:
            log(f"✖ {title}: у версії .exe встановлення бібліотек недоступне — запускайте через «Запуск.bat»")
            return False
        cmd = [python_cli(), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade"]
        if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
            cmd.append("--user")
        cmd += comp["pip"]
        log(f"■ Встановлюю {title} ({comp['size']}) — це може зайняти кілька хвилин…")
        progress(0.0, f"Встановлення {title}…")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        except OSError as exc:
            log(f"✖ Не вдалося запустити pip: {exc}")
            return False
        tail: list[str] = []
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            tail = (tail + [line])[-6:]
            if line.startswith(("Collecting", "Downloading", "Installing", "Successfully")):
                progress(0.5, line[:90])
            if line.startswith(("Successfully", "ERROR")):
                log("   " + line[:200])
        proc.wait()
        _refresh_paths()
        if proc.returncode != 0 or not _module_ok(comp["module"]):
            log(f"✖ {title} не встановився. Останні рядки pip:\n   " + "\n   ".join(tail))
            return False
        if name == "opencv":
            ensure_yunet(log)
        log(f"✔ {title} встановлено")
        return True

    urls = comp["win"] if IS_WIN else comp["other"]
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zpath = TOOLS_DIR / f"{name}.zip"
    last_err = "невідома помилка"
    for url, sha in urls:
        try:
            log(f"■ Завантажую {title} ({comp['size']})…")
            _download(url, zpath, progress, f"Завантаження {title}")
            if sha and _sha256(zpath).lower() != sha:
                raise RuntimeError("контрольна сума не збігається")
            folder = TOOLS_DIR / name
            shutil.rmtree(folder, ignore_errors=True)
            with zipfile.ZipFile(zpath) as z:
                for member in z.namelist():
                    if member.startswith("/") or ".." in Path(member).parts:
                        raise RuntimeError("підозрілий архів")
                z.extractall(folder)
            zpath.unlink(missing_ok=True)
            exe = tool_exe(name)
            if not exe:
                raise RuntimeError("у архіві немає програми")
            if not IS_WIN:
                os.chmod(exe, 0o755)
            log(f"✔ {title} встановлено")
            return True
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            zpath.unlink(missing_ok=True)
    log(f"✖ {title}: {last_err}")
    return False


def cache_size_mb() -> float:
    total = 0
    if CACHE_DIR.is_dir():
        for p in CACHE_DIR.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    return total / 1e6


def clear_cache():
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


# ---------------------------------------------------------------------------
#  Запуск процесів
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    ffmpeg: str
    log: Callable[[str], None]
    progress: Callable[[float, str], None]
    stop: threading.Event
    register: Callable[[subprocess.Popen], None] | None = None
    unregister: Callable[[subprocess.Popen], None] | None = None

    def popen(self, cmd: list[str], cwd: str | None = None, binary: bool = False, **kw) -> subprocess.Popen:
        if binary:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                                 creationflags=NO_WINDOW, **kw)
        else:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, text=True,
                                 encoding="utf-8", errors="replace", creationflags=NO_WINDOW, **kw)
        if self.register:
            self.register(p)
        return p

    def done(self, p: subprocess.Popen):
        if self.unregister:
            self.unregister(p)

    def stopped(self) -> bool:
        return self.stop.is_set()


def _drain(stream, buf: list):
    try:
        buf.append(stream.read())
    except Exception:  # noqa: BLE001
        pass


def run_ffmpeg(ctx: Ctx, cmd: list[str], duration: float, label: str, cwd: str | None = None,
               base: float = 0.0, span: float = 1.0) -> tuple[bool, str]:
    """Запускає ffmpeg з -progress pipe:1 і показує прогрес."""
    cmd = cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]
    p = ctx.popen(cmd, cwd=cwd)
    err: list[str] = []
    t = threading.Thread(target=_drain, args=(p.stderr, err), daemon=True)
    t.start()
    last = 0.0
    for line in p.stdout:
        if ctx.stopped():
            p.terminate()
            break
        k, _, v = line.strip().partition("=")
        if k == "out_time_us" and duration > 0:
            try:
                frac = min(0.999, int(v) / 1e6 / duration)
            except ValueError:
                continue
            now = time.monotonic()
            if now - last > 0.3:
                last = now
                ctx.progress(base + span * frac, f"{label} {frac * 100:.0f}%")
    p.wait()
    t.join(timeout=2)
    ctx.done(p)
    lines = "".join(err).strip().splitlines()
    return p.returncode == 0, (lines[-1] if lines else f"код {p.returncode}")


def file_key(path: str, *extra) -> str:
    try:
        st = os.stat(path)
        sig = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    except OSError:
        sig = os.path.abspath(path)
    raw = sig + "|" + "|".join(str(e) for e in extra)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _seek_args(t0: float, tlen: float | None, duration: float) -> tuple[list[str], list[str]]:
    """Вхідні опції обрізки (обидві ставляться перед -i)."""
    pre = ["-ss", f"{t0:.3f}"] if t0 > 0 else []
    if tlen and tlen < duration - 0.01:
        pre += ["-t", f"{tlen:.3f}"]
    return pre, []


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


# ---------------------------------------------------------------------------
#  Розумне кадрування
# ---------------------------------------------------------------------------

def reframe_geometry(src_w: int, src_h: int, ratio: tuple[int, int]) -> dict | None:
    """Розмір вікна кропу у вихіднику під потрібне співвідношення. None — якщо кадрувати не треба."""
    rw, rh = ratio
    target = rw / rh
    cur = src_w / src_h
    if abs(cur - target) / target < 0.03:
        return None
    if cur > target:  # ширше, ніж треба → панорама по горизонталі
        cw = min(src_w, _even(src_h * target))
        return {"axis": "x", "w": cw, "h": src_h, "frac": cw / src_w, "len": src_w, "crop": cw}
    ch = min(src_h, _even(src_w / target))
    return {"axis": "y", "w": src_w, "h": ch, "frac": ch / src_h, "len": src_h, "crop": ch}


class _FaceFinder:
    def __init__(self, cv2, w: int, h: int, log):
        self.cv2 = cv2
        self.yunet = None
        model = ensure_yunet(log)
        if model and hasattr(cv2, "FaceDetectorYN"):
            try:
                # копія в тимчасову папку — OpenCV не відкриває шляхи з кирилицею
                tmp = Path(tempfile.gettempdir()) / "vv_yunet.onnx"
                if not tmp.exists() or tmp.stat().st_size != os.path.getsize(model):
                    shutil.copyfile(model, tmp)
                self.yunet = cv2.FaceDetectorYN.create(str(tmp), "", (w, h), 0.6, 0.3, 50)
            except Exception:  # noqa: BLE001
                self.yunet = None
        self.haar = None
        if self.yunet is None:
            try:
                self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            except Exception:  # noqa: BLE001
                self.haar = None
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def faces(self, img, gray) -> list[tuple[float, float, float, float, float]]:
        out = []
        if self.yunet is not None:
            try:
                _, res = self.yunet.detect(img)
                if res is not None:
                    for r in res:
                        out.append((float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[-1])))
            except Exception:  # noqa: BLE001
                pass
        elif self.haar is not None:
            for (x, y, w, h) in self.haar.detectMultiScale(gray, 1.1, 5, minSize=(18, 18)):
                out.append((float(x), float(y), float(w), float(h), 0.8))
        return out

    def people(self, img) -> list[tuple[float, float, float, float]]:
        try:
            rects, weights = self.hog.detectMultiScale(img, winStride=(8, 8), padding=(8, 8), scale=1.06)
        except Exception:  # noqa: BLE001
            return []
        return [(float(x), float(y), float(w), float(h)) for (x, y, w, h), wt in zip(rects, weights)
                if float(wt) > 0.4]


def analyze_reframe(ctx: Ctx, src: str, info, t0: float, tlen: float, geo: dict,
                    base: float = 0.0, span: float = 1.0) -> dict:
    """Аналізує, де в кадрі людина. Повертає {"fps": f, "track": [центр 0..1], "cuts": [індекси]}."""
    import cv2  # noqa: F401
    import numpy as np
    key = file_key(src, "rf4", t0, tlen, geo["axis"], round(geo["frac"], 4))
    cache = CACHE_DIR / "reframe" / f"{key}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    W, H = info.width, info.height
    aw = 480 if W >= H else 300
    ah = _even(aw * H / W)
    fps_s = 5.0 if tlen <= 150 else max(1.0, 750.0 / max(tlen, 1.0))
    pre, post = _seek_args(t0, tlen, info.duration)
    cmd = [ctx.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *pre, "-i", src, *post, "-an",
           "-vf", f"fps={fps_s:.4f},scale={aw}:{ah},format=bgr24", "-f", "rawvideo", "-"]
    p = ctx.popen(cmd, binary=True)
    errbuf: list = []
    threading.Thread(target=_drain, args=(p.stderr, errbuf), daemon=True).start()
    finder = _FaceFinder(cv2, aw, ah, ctx.log)
    frame_bytes = aw * ah * 3
    expected = max(1, int(tlen * fps_s))
    axis = geo["axis"]
    frac = geo["frac"]
    vals: list[float | None] = []
    cuts: list[int] = []
    prev_small = None
    prev_gray = None
    last: float | None = None
    k = 0
    while True:
        if ctx.stopped():
            p.terminate()
            break
        buf = p.stdout.read(frame_bytes)
        if not buf or len(buf) < frame_bytes:
            break
        img = np.frombuffer(buf, np.uint8).reshape(ah, aw, 3)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, max(2, int(64 * ah / aw))))
        if prev_small is not None and float(cv2.absdiff(small, prev_small).mean()) > 38:
            cuts.append(k)
            last = None
        prev_small = small

        pos = None
        faces = finder.faces(img, gray)
        if faces:
            def score(f):
                cx = (f[0] + f[2] / 2) / aw if axis == "x" else (f[1] + f[3] / 2) / ah
                s = f[2] * f[3] * (0.5 + f[4])
                if last is not None and abs(cx - last) < frac * 0.4:
                    s *= 1.6
                return s
            faces.sort(key=score, reverse=True)
            f0 = faces[0]
            if axis == "x":
                c0 = (f0[0] + f0[2] / 2) / aw
                # двоє людей поруч, що влазять у кадр, — тримаємо обох
                if len(faces) > 1:
                    f1 = faces[1]
                    c1 = (f1[0] + f1[2] / 2) / aw
                    if f1[2] * f1[3] > 0.45 * f0[2] * f0[3] and abs(c1 - c0) < frac * 0.7:
                        c0 = (c0 + c1) / 2
                pos = c0
            else:
                pos = (f0[1] + f0[3] * 0.5) / ah + frac * 0.12   # обличчя трохи вище центру
        else:
            people = finder.people(img)
            if people:
                people.sort(key=lambda r: r[2] * r[3], reverse=True)
                x, y, w, h = people[0]
                pos = (x + w / 2) / aw if axis == "x" else (y + h * 0.3) / ah + frac * 0.12
            elif prev_gray is not None:
                diff = cv2.absdiff(cv2.GaussianBlur(gray, (5, 5), 0), cv2.GaussianBlur(prev_gray, (5, 5), 0))
                _, th = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                m = cv2.moments(th, binaryImage=True)
                if m["m00"] > 0.005 * aw * ah:
                    pos = (m["m10"] / m["m00"]) / aw if axis == "x" else (m["m01"] / m["m00"]) / ah
        prev_gray = gray
        vals.append(pos)
        if pos is not None:
            last = pos
        k += 1
        if k % 5 == 0:
            ctx.progress(base + span * min(0.99, k / expected), f"Розумне кадрування: аналіз {min(99, k * 100 // expected)}%")
    p.wait()
    ctx.done(p)
    track = smooth_track(vals, cuts, fps_s, frac)
    data = {"fps": fps_s, "track": track, "cuts": cuts,
            "found": sum(1 for v in vals if v is not None), "total": len(vals)}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def _gauss(seq: list[float], sigma: float) -> list[float]:
    if sigma <= 0 or len(seq) < 3:
        return list(seq)
    r = max(1, int(sigma * 3))
    ker = [math.exp(-(i * i) / (2 * sigma * sigma)) for i in range(-r, r + 1)]
    out = []
    n = len(seq)
    for i in range(n):
        acc = wsum = 0.0
        for j, w in enumerate(ker):
            idx = min(n - 1, max(0, i + j - r))
            acc += seq[idx] * w
            wsum += w
        out.append(acc / wsum)
    return out


def smooth_track(vals: list[float | None], cuts: list[int], fps: float, frac: float) -> list[float]:
    """Плавна «операторська» траєкторія: мертва зона, згладжування, різкі переходи на склейках."""
    n = len(vals)
    if n == 0:
        return []
    lo, hi = frac / 2, 1 - frac / 2
    bounds = sorted(set([0] + [c for c in cuts if 0 < c < n] + [n]))
    out: list[float] = []
    for a, b in zip(bounds, bounds[1:]):
        seg = vals[a:b]
        known = [v for v in seg if v is not None]
        if not known:
            seg_f = [out[-1] if out else 0.5] * len(seg)
        else:
            seg_f = []
            cur = known[0]
            for v in seg:
                if v is not None:
                    cur = v
                seg_f.append(cur)
        seg_f = [min(hi, max(lo, v)) for v in seg_f]
        # медіана прибирає поодинокі хибні спрацювання детектора
        med = []
        for i in range(len(seg_f)):
            w = sorted(seg_f[max(0, i - 2):i + 3])
            med.append(w[len(w) // 2])
        # спокійний план (людина майже не рухається) — камера стоїть нерухомо
        if max(med) - min(med) < frac * 0.12:
            moved = [sum(med) / len(med)] * len(med)
        else:
            # згладжування в обидва боки — без запізнення камери за рухом
            moved = _gauss(med, sigma=max(1.0, fps * 0.5))
        out += [min(hi, max(lo, v)) for v in moved]
    return out


def track_value(data: dict, t: float) -> float:
    """Центр кадру (0..1) у момент t (секунди від початку шматка), без змазування через склейки."""
    tr = data.get("track") or []
    if not tr:
        return 0.5
    f = max(0.0, t * data["fps"])
    i = int(f)
    if i >= len(tr) - 1:
        return tr[-1]
    if (i + 1) in set(data.get("cuts", [])):
        return tr[i]
    a = f - i
    return tr[i] * (1 - a) + tr[i + 1] * a


def write_reframe_cmds(path: Path, data: dict, geo: dict, fps: float, duration: float) -> int:
    """Файл команд sendcmd для crop@rf: позиція вікна на кожен кадр."""
    axis = geo["axis"]
    total, crop = geo["len"], geo["crop"]
    lines = []
    prev = None
    fps = max(1.0, min(120.0, fps))
    n = int(duration * fps) + 2
    for k in range(n):
        t = k / fps
        px = int(round(track_value(data, t) * total - crop / 2))
        px = max(0, min(total - crop, px))
        px -= px % 2
        if px != prev:
            lines.append(f"{t:.4f} crop@rf {axis} {px};")
            prev = px
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def reframe_start(data: dict, geo: dict, t: float = 0.0) -> int:
    total, crop = geo["len"], geo["crop"]
    px = int(round(track_value(data, t) * total - crop / 2))
    px = max(0, min(total - crop, px))
    return px - px % 2


# ---------------------------------------------------------------------------
#  Автокорекція кольору / експозиції
# ---------------------------------------------------------------------------

_STAT_RE = re.compile(r"lavfi\.signalstats\.(YLOW|YHIGH|YAVG|UAVG|VAVG|SATAVG)=([\d.]+)")


def analyze_color(ctx: Ctx, src: str, info, t0: float, tlen: float, tonemap: str | None) -> dict | None:
    key = file_key(src, "color1", t0, tlen)
    cache = CACHE_DIR / "color" / f"{key}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    n = 24
    fps = max(0.05, n / max(tlen, 1.0))
    pre, post = _seek_args(t0, tlen, info.duration)
    chain = (tonemap + "," if tonemap else "") + \
        f"fps={fps:.4f},scale=320:-2,format=yuv420p,signalstats,metadata=mode=print"
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", *pre, "-i", src, *post, "-an",
           "-vf", chain, "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None
    vals: dict[str, list[float]] = {}
    for m in _STAT_RE.finditer(r.stderr + r.stdout):
        vals.setdefault(m.group(1), []).append(float(m.group(2)))
    if not vals.get("YAVG"):
        return None

    def med(k, d):
        v = sorted(vals.get(k) or [d])
        return v[len(v) // 2]
    data = {k: med(k, d) for k, d in (("YLOW", 16), ("YHIGH", 235), ("YAVG", 110),
                                       ("UAVG", 128), ("VAVG", 128), ("SATAVG", 30))}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass
    return data


def color_filters(st: dict, strength: float) -> list[str]:
    """М'яка автокорекція: розтягування тонового діапазону, експозиція, баланс білого."""
    s = max(0.0, min(1.0, strength))
    if s <= 0:
        return []
    ylow, yhigh, yavg = st["YLOW"], st["YHIGH"], st["YAVG"]
    span = max(40.0, yhigh - ylow)
    c = min(1.30, max(1.0, 205.0 / span))           # контраст лише підсилюємо, не зменшуємо
    c = 1 + (c - 1) * s
    mid = (ylow + yhigh) / 2 / 255
    b = 0.0 if abs(mid - 0.5) < 0.04 else max(-0.08, min(0.08, -(mid - 0.5) * c)) * s
    avg2 = min(0.95, max(0.05, (yavg / 255 - 0.5) * c + 0.5 + b))
    g = 1.0 if abs(avg2 - 0.46) < 0.05 else min(1.30, max(0.80, math.log(avg2) / math.log(0.46)))
    g = 1 + (g - 1) * s                              # gamma > 1 — світліше (eq: x^(1/g))
    if abs(c - 1) < 0.01 and abs(b) < 0.005 and abs(g - 1) < 0.01:
        out: list[str] = []
    else:
        out = [f"eq=contrast={c:.3f}:brightness={b:.3f}:gamma={g:.3f}"]
    du, dv = st["UAVG"] - 128, st["VAVG"] - 128
    if abs(du) > 2.5 or abs(dv) > 2.5:
        k = 1.4 * s
        rm = max(-0.12, min(0.12, -dv / 128 * k))
        bm = max(-0.12, min(0.12, -du / 128 * k))
        gm = max(-0.06, min(0.06, (du + dv) / 256 * k * 0.6))
        out.append(f"colorbalance=rm={rm:.3f}:gm={gm:.3f}:bm={bm:.3f}")
    if st.get("SATAVG", 30) < 18:   # бляклі кадри — трохи насиченості
        out.append(f"eq=saturation={1 + 0.15 * s:.3f}")
    return out


# ---------------------------------------------------------------------------
#  Стабілізація vidstab
# ---------------------------------------------------------------------------

def vidstab_detect(ctx: Ctx, src: str, info, t0: float, tlen: float, workdir: Path, name: str,
                   base: float = 0.0, span: float = 1.0) -> bool:
    pre, post = _seek_args(t0, tlen, info.duration)
    cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", *pre, "-i", src, *post, "-an",
           "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result={name}", "-f", "null", "-"]
    ok, err = run_ffmpeg(ctx, cmd, tlen, "Стабілізація: аналіз тремтіння", cwd=str(workdir), base=base, span=span)
    if not ok:
        ctx.log(f"   ⚠ стабілізація: {err}")
    return ok and (workdir / name).is_file()


# ---------------------------------------------------------------------------
#  Субтитри
# ---------------------------------------------------------------------------

def _decode_audio(ctx: Ctx, src: str, info, t0: float, tlen: float):
    import numpy as np
    pre, post = _seek_args(t0, tlen, info.duration)
    cmd = [ctx.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *pre, "-i", src, *post,
           "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    p = ctx.popen(cmd, binary=True)
    data, _ = p.communicate()
    ctx.done(p)
    return np.frombuffer(data, dtype=np.float32).copy()


def parse_srt(text: str) -> list[dict]:
    segs = []
    tm = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            m = tm.search(ln)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / (1000 if len(m.group(4)) == 3 else 100)
                b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / (1000 if len(m.group(8)) == 3 else 100)
                txt = " ".join(re.sub(r"<[^>]+>", "", x).strip() for x in lines[i + 1:])
                if txt:
                    segs.append({"start": a, "end": b, "text": txt, "words": []})
                break
    return segs


def _srt_time(t: float) -> str:
    t = max(0.0, t)
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(segs: list[dict], path: Path):
    out = []
    for i, s in enumerate(segs, 1):
        out.append(f"{i}\n{_srt_time(s['start'])} --> {_srt_time(s['end'])}\n{s['text'].strip()}\n")
    path.write_text("\n".join(out), encoding="utf-8")


def transcribe(ctx: Ctx, src: str, info, t0: float, tlen: float, model_label: str, lang_label: str,
               base: float = 0.0, span: float = 1.0, srt_from: str | None = None) -> list[dict]:
    """Розпізнає мову у шматку [t0, t0+tlen]. Час — від початку шматка. Кешується."""
    # власні субтитри поруч із відео мають пріоритет (можна виправити помилки розпізнавання)
    own = Path(srt_from or src).with_suffix(".srt")
    if own.is_file():
        segs = parse_srt(own.read_text(encoding="utf-8", errors="replace"))
        segs = [dict(s, start=s["start"] - t0, end=s["end"] - t0) for s in segs if s["end"] > t0]
        ctx.log(f"   субтитри з файлу {own.name}: {len(segs)} фраз")
        return segs
    model_name = WHISPER_MODELS.get(model_label, "small")
    lang = SUB_LANGS.get(lang_label)
    key = file_key(src, "wh1", t0, tlen, model_name, lang)
    cache = CACHE_DIR / "subs" / f"{key}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    if not info.has_audio:
        ctx.log("   у відео немає звуку — субтитри пропущено")
        return []
    if sys.stderr is None:                      # pythonw: прогрес-бари бібліотек пишуть у stderr
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from faster_whisper import WhisperModel
    audio = _decode_audio(ctx, src, info, t0, tlen)
    if audio.size < 1600:
        return []
    mdir = MODELS_DIR / "whisper"
    mdir.mkdir(parents=True, exist_ok=True)
    if not any(mdir.glob(f"*{model_name}*")):
        ctx.log(f"   завантажую модель Whisper «{model_name}» ({WHISPER_SIZES.get(model_name, '')}) — лише перший раз…")
    ctx.progress(base, "Субтитри: завантаження моделі…")
    model = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(mdir),
                         cpu_threads=max(1, (os.cpu_count() or 4) - 1))
    ctx.progress(base, "Субтитри: розпізнавання мови…")
    segments, tinfo = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True,
                                       beam_size=5, condition_on_previous_text=False)
    if lang is None:
        ctx.log(f"   мова: {tinfo.language} ({tinfo.language_probability:.0%})")
    out = []
    dur = max(0.1, len(audio) / 16000)
    for seg in segments:
        if ctx.stopped():
            break
        words = [[round(w.start, 3), round(w.end, 3), w.word.strip()] for w in (seg.words or []) if w.word.strip()]
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(),
                    "words": words})
        ctx.progress(base + span * min(0.99, seg.end / dur), f"Субтитри: розпізнано {min(99, int(seg.end / dur * 100))}%")
    if not ctx.stopped():
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return out


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_color(rgb: tuple[int, int, int], alpha: int = 0) -> str:
    r, g, b = rgb
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_escape(s: str) -> str:
    return s.replace("\\", "⧵").replace("{", "(").replace("}", ")").replace("\n", " ")


def font_family(path: str | None) -> str:
    if path:
        try:
            from PIL import ImageFont
            return ImageFont.truetype(path, 20).getname()[0] or "Arial"
        except Exception:  # noqa: BLE001
            pass
    return "Arial"


def build_ass(segs: list[dict], W: int, H: int, st: dict) -> str:
    """st: family, size, style, color, words, pos, upper."""
    fs = max(18, int(min(W, H) * float(st.get("size", 0.075))))
    style = st.get("style", "Обводка")
    pos = st.get("pos", "Знизу")
    align = {"Знизу": 2, "По центру": 5, "Зверху": 8}.get(pos, 2)
    mv = {"Знизу": int(H * 0.22), "По центру": 0, "Зверху": int(H * 0.14)}.get(pos, int(H * 0.22))
    ml = int(W * 0.07)
    white = _ass_color((255, 255, 255))
    if style == "Плашка":
        bs, outline, shadow, oc, bc = 3, max(4, int(fs * 0.22)), 0, _ass_color((0, 0, 0), 0x50), _ass_color((0, 0, 0), 0x50)
    elif style == "Тінь":
        bs, outline, shadow, oc, bc = 1, max(1, int(fs * 0.02)), max(2, int(fs * 0.07)), _ass_color((0, 0, 0), 0x40), _ass_color((0, 0, 0), 0x30)
    else:
        bs, outline, shadow, oc, bc = 1, max(2, int(fs * 0.085)), max(1, int(fs * 0.035)), _ass_color((0, 0, 0)), _ass_color((0, 0, 0), 0x60)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Main,{st.get('family', 'Arial')},{fs},{white},{white},{oc},{bc},-1,0,0,0,100,100,0,0,"
        f"{bs},{outline},{shadow},{align},{ml},{ml},{mv},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    hl = SUB_COLORS.get(st.get("color", "Жовтий"))
    hl_tag = "{\\c" + _ass_color(hl) + "&}" if hl else ""
    reset = "{\\c" + white + "&}"
    upper = bool(st.get("upper", True))
    per_line = max(1, min(8, int(st.get("words", 3))))
    max_chars = max(8, int(W * 0.86 / (fs * 0.56)))

    def fmt(w: str) -> str:
        w = _ass_escape(w)
        return w.upper() if upper else w

    events: list[tuple[float, float, str]] = []
    for si, seg in enumerate(segs):
        words = [w for w in seg.get("words") or [] if str(w[2]).strip()]
        nxt_start = segs[si + 1]["start"] if si + 1 < len(segs) else seg["end"] + 1.0
        if not words:   # без таймінгу слів — показуємо фразу цілком
            if seg["end"] > 0:
                events.append((max(0.0, seg["start"]), seg["end"], fmt(seg["text"])))
            continue
        chunks: list[list] = []
        cur: list = []
        for w in words:
            if cur and (len(cur) >= per_line or w[0] - cur[-1][1] > 0.7
                        or sum(len(x[2]) + 1 for x in cur) + len(w[2]) > max_chars
                        or cur[-1][2][-1:] in ".!?…"):
                chunks.append(cur)
                cur = []
            cur.append(w)
        if cur:
            chunks.append(cur)
        for ci, ch in enumerate(chunks):
            c_start = ch[0][0]
            limit = chunks[ci + 1][0][0] if ci + 1 < len(chunks) else nxt_start
            c_end = min(ch[-1][1] + 0.25, limit)
            if c_end <= 0:
                continue
            if hl:
                for wi, w in enumerate(ch):
                    ws = c_start if wi == 0 else w[0]
                    we = ch[wi + 1][0] if wi + 1 < len(ch) else c_end
                    if we <= ws:
                        continue
                    text = " ".join((hl_tag + fmt(x[2]) + reset) if j == wi else fmt(x[2])
                                    for j, x in enumerate(ch))
                    events.append((max(0.0, ws), we, text))
            else:
                events.append((max(0.0, c_start), c_end, " ".join(fmt(x[2]) for x in ch)))
    body = "".join(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Main,,0,0,0,,{t}\n"
                   for a, b, t in events if b > a)
    return head + body


def sample_segments() -> list[dict]:
    words = [[0.0, 0.4, "Так"], [0.4, 0.8, "виглядатимуть"], [0.8, 1.2, "субтитри"]]
    return [{"start": 0.0, "end": 9999.0, "text": "Так виглядатимуть субтитри", "words": words}]


def preview_ass(W: int, H: int, st: dict) -> str:
    """Статичний приклад для превʼю: друге слово підсвічене."""
    st = dict(st, words=3)
    hl = SUB_COLORS.get(st.get("color", "Жовтий"))
    segs = sample_segments()
    full = build_ass(segs, W, H, st)
    head, _, _ = full.partition("[Events]")
    upper = bool(st.get("upper", True))
    ws = ["Так", "виглядатимуть", "субтитри"]
    ws = [w.upper() if upper else w for w in ws]
    if hl:
        ws[1] = "{\\c" + _ass_color(hl) + "&}" + ws[1] + "{\\c" + _ass_color((255, 255, 255)) + "&}"
    return (head + "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,9:00:00.00,Main,,0,0,0,,{' '.join(ws)}\n")


# ---------------------------------------------------------------------------
#  AI-апскейл та плавність (через кадри)
# ---------------------------------------------------------------------------

def _count(folder: Path) -> int:
    try:
        return sum(1 for _ in folder.iterdir())
    except OSError:
        return 0


def _run_tool(ctx: Ctx, cmd: list[str], cwd: Path, out_dir: Path, expected: int, label: str,
              base: float, span: float) -> tuple[bool, str]:
    p = ctx.popen(cmd, cwd=str(cwd))
    err: list[str] = []
    out: list[str] = []
    threading.Thread(target=_drain, args=(p.stderr, err), daemon=True).start()
    threading.Thread(target=_drain, args=(p.stdout, out), daemon=True).start()
    while p.poll() is None:
        if ctx.stopped():
            p.terminate()
            break
        n = _count(out_dir)
        frac = min(0.99, n / max(1, expected))
        ctx.progress(base + span * frac, f"{label} {frac * 100:.0f}% ({n}/{expected} кадрів)")
        time.sleep(1.0)
    p.wait()
    ctx.done(p)
    msg = ("".join(err) + "".join(out)).strip().splitlines()
    tail = [ln for ln in msg if ln.strip() and "%" not in ln][-2:]
    return p.returncode == 0 and _count(out_dir) > 0, " / ".join(tail) or f"код {p.returncode}"


def prepare_ai_source(ctx: Ctx, src: str, info, t0: float, tlen: float, upscale: str | None,
                      need_short: int, smooth: str, tonemap: str | None, probe_fn) -> tuple[str, object] | None:
    """Створює проміжне відео (апскейл / плавність). Повертає (шлях, MediaInfo) або None."""
    src_short = min(info.width, info.height)
    want_up = False
    model = scale = None
    if upscale:
        if need_short <= src_short * 1.05:
            ctx.log(f"   AI-апскейл не потрібен: роздільність уже достатня ({info.width}×{info.height})")
        elif not tool_exe("esrgan"):
            ctx.log("   ⚠ AI-апскейл: компонент Real-ESRGAN не встановлено (вкладка «Покращення»)")
        else:
            model, scale = UPSCALE_MODELS.get(upscale, UPSCALE_MODELS["Швидка ×2"])
            want_up = True
    want_smooth = smooth in SMOOTH_MODES[1:]
    if smooth == "Плавні 60 к/с" and info.fps >= 48:
        ctx.log(f"   плавність: відео вже {info.fps:.0f} к/с — пропускаю")
        want_smooth = False
    if not (want_up or want_smooth):
        return None
    use_rife = want_smooth and tool_exe("rife") is not None
    out_short = min(need_short, src_short * (scale or 1)) if want_up else src_short
    out_short = _even(out_short)
    key = file_key(src, "ai2", t0, tlen, model, scale, out_short, smooth if want_smooth else "-", use_rife)
    root = CACHE_DIR / "ai"
    root.mkdir(parents=True, exist_ok=True)
    final = root / f"{key}.mp4"
    if final.is_file() and final.stat().st_size > 1000:
        ctx.log("   AI-обробка: беру готовий результат з кешу")
        return str(final), probe_fn(str(final))
    work = root / f"{key}_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    fps = info.fps
    fps_s = f"{fps:.3f}".rstrip("0").rstrip(".")
    pre, post = _seek_args(t0, tlen, info.duration)
    slow = want_smooth and smooth == "Сповільнення ×2"
    try:
        frames_needed = want_up or use_rife
        scale_vf = (f"scale=-2:{out_short}:flags=lanczos" if info.width >= info.height
                    else f"scale={out_short}:-2:flags=lanczos")
        if frames_needed:
            n_est = max(1, int(tlen * fps))
            gb = n_est * info.width * info.height * 3 * (scale or 1) ** 2 / 2.5e9
            ctx.log(f"   AI-обробка: ~{n_est} кадрів" + (f", тимчасово до {gb:.1f} ГБ на диску" if gb > 1 else ""))
            (work / "in").mkdir()
            vf = (tonemap + "," if tonemap else "") + f"fps={fps_s}"
            ok, err = run_ffmpeg(ctx, [ctx.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", *pre, "-i", src,
                                       *post, "-an", "-vf", vf, "-start_number", "1", "in/%08d.png"],
                                 tlen, "AI: розбиваю на кадри", cwd=str(work), base=0.0, span=0.08)
            if not ok or ctx.stopped():
                raise RuntimeError(f"не вдалося отримати кадри: {err}")
            n = _count(work / "in")
            cur, ext = "in", "png"
            if want_up:
                exe = tool_exe("esrgan")
                mdir = str(Path(exe).parent / "models")
                (work / "up").mkdir()
                ext_up = "jpg" if scale >= 4 else "png"
                ctx.log(f"   AI-апскейл ({model} ×{scale}) — це довго, можна займатися іншим")
                ok, err = _run_tool(ctx, [exe, "-i", "in", "-o", "up", "-n", model, "-s", str(scale),
                                          "-m", mdir, "-f", ext_up], work, work / "up", n,
                                    "AI-апскейл:", 0.08, 0.6 if use_rife else 0.82)
                if not ok or ctx.stopped():
                    raise RuntimeError(f"Real-ESRGAN: {err} (потрібна відеокарта з підтримкою Vulkan)")
                shutil.rmtree(work / "in", ignore_errors=True)
                cur, ext = "up", ext_up
            if use_rife:
                exe = tool_exe("rife")
                mdir = str(Path(exe).parent / "rife-v4.6")
                (work / "rf").mkdir()
                ok, err = _run_tool(ctx, [exe, "-i", cur, "-o", "rf", "-m", mdir, "-f", f"%08d.{ext}"],
                                    work, work / "rf", _count(work / cur) * 2, "AI-плавність:",
                                    0.68 if want_up else 0.08, 0.22 if want_up else 0.82)
                if not ok or ctx.stopped():
                    raise RuntimeError(f"RIFE: {err} (потрібна відеокарта з підтримкою Vulkan)")
                shutil.rmtree(work / cur, ignore_errors=True)
                cur = "rf"
            in_rate = f"{fps * 2:.3f}" if (use_rife and not slow) else fps_s
            cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                   "-framerate", in_rate, "-i", f"{cur}/%08d.{ext}"]
            vfs = []
            if want_up:
                vfs.append(scale_vf)
            if want_smooth and not use_rife:
                vfs.append(f"minterpolate=fps={fps * 2:.3f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
                if slow:
                    vfs += ["setpts=2*PTS", f"fps={fps_s}"]
        else:
            # тільки FFmpeg-плавність без AI — напряму з відео
            cmd = [ctx.ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
            vfs = ([tonemap] if tonemap else []) + [
                f"minterpolate=fps={fps * 2:.3f}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"]
            if slow:
                vfs += ["setpts=2*PTS", f"fps={fps_s}"]
            ctx.log("   плавність через FFmpeg (для кращої якості встановіть RIFE на вкладці «Покращення»)")
        has_audio_input = info.has_audio
        if frames_needed and has_audio_input:
            cmd += [*pre, "-i", src, *post]
        elif not frames_needed:
            cmd += [*pre, "-i", src, *post]
        cmd += ["-map", "0:v:0"]
        if has_audio_input:
            cmd += ["-map", ("1" if frames_needed else "0") + ":a:0?"]
            if slow:
                cmd += ["-af", "atempo=0.5"]
            cmd += ["-c:a", "aac", "-b:a", "256k"]
        if vfs:
            cmd += ["-vf", ",".join(vfs)]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "13", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", "out.mp4"]
        out_len = tlen * (2 if slow else 1)
        ok, err = run_ffmpeg(ctx, cmd, out_len, "AI: збираю відео", cwd=str(work), base=0.9, span=0.1)
        if not ok or ctx.stopped():
            raise RuntimeError(f"збірка відео: {err}")
        os.replace(work / "out.mp4", final)
        return str(final), probe_fn(str(final))
    finally:
        shutil.rmtree(work, ignore_errors=True)
