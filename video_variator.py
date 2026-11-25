#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Video Variator 3 — пакетна генерація візуальних варіацій відео
для A/B-тестування стилів монтажу. Інтерфейс: CustomTkinter, обробка: FFmpeg.

Можливості:
  • кілька вихідних відео за раз, N варіацій для кожного;
  • легкі випадкові зміни (колір, зум/рамка, зерно, темп, віддзеркалення, метадані);
  • стильові пресети (теплий, холодний, кіно, вінтаж…) з регулюванням сили
    та рівномірним розподілом між варіаціями (зручно для A/B-груп);
  • попередній перегляд кадрів перед рендером;
  • кодування на CPU або відеокарті (NVIDIA / Intel / AMD) з автовизначенням;
  • паралельна обробка кількох файлів;
  • CSV-звіт з параметрами кожної варіації, відтворюваність через seed;
  • збереження налаштувань між запусками.

Залежності: pip install customtkinter pillow ; FFmpeg + FFprobe.
"""

from __future__ import annotations

import csv
import json
import math
import os
import queue
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path
from tkinter import filedialog, messagebox, colorchooser

import customtkinter as ctk

APP_VERSION = "3.2.0"
APP_TITLE = "Video Variator " + ".".join(APP_VERSION.split(".")[:2])
UPDATE_REPO = "fpavlo2003-collab/video-variator"
UPDATE_BRANCH = "main"
APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
SETTINGS_FILE = APP_DIR / "settings.json"
DEFAULT_OUT_DIR = APP_DIR / "Готові відео"
VIDEO_TYPES = [("Відео", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"), ("Усі файли", "*.*")]
BORDER_COLORS = [
    "0x000000", "0xFFFFFF", "0x1A1A1A", "0xF2F2F2", "0x202A44",
    "0x3B2F2F", "0xE8DCC8", "0x2E4A3A", "0x6B1F2A", "0xC9A227",
]
ZOOM_MODES = ["Випадково", "Тільки зум", "Тільки рамка"]
ASPECTS = {"Як в оригіналі": None, "9:16 (Reels / TikTok)": (9, 16), "1:1 (квадрат)": (1, 1),
           "4:5 (пост Instagram)": (4, 5), "16:9 (YouTube)": (16, 9)}
WM_TYPES = ["Логотип", "Текст"]
RANGE_KEYS = ("color_min", "color_max", "bright_min", "bright_max", "hue_max",
              "zoom_min", "zoom_max", "grain_min", "grain_max", "tempo_min", "tempo_max")
BITRATE_MODES = ["Якість (CRF)", "Фіксований бітрейт"]
AUDIO_BITRATES = ["128k", "160k", "192k", "256k"]
HOOK_POSITIONS = ["Зверху", "По центру", "Знизу"]
HOOK_STYLES = ["Темна плашка", "Біла плашка", "Обводка без плашки"]
FONT_LIBRARY = [  # (назва, файли-кандидати)
    ("Impact", ["impact.ttf"]),
    ("Arial Black", ["ariblk.ttf"]),
    ("Montserrat Bold", ["Montserrat-Bold.ttf", "Montserrat-ExtraBold.ttf", "Montserrat[wght].ttf"]),
    ("Bebas Neue", ["BebasNeue-Regular.ttf", "BebasNeue.ttf"]),
    ("Poppins Bold", ["Poppins-Bold.ttf"]),
    ("Segoe UI Bold", ["segoeuib.ttf"]),
    ("Bahnschrift", ["bahnschrift.ttf"]),
    ("Arial Bold", ["arialbd.ttf"]),
    ("Verdana Bold", ["verdanab.ttf"]),
    ("DejaVu Sans Bold", ["DejaVuSans-Bold.ttf"]),
]
WM_POSITIONS = ["Правий нижній", "Лівий нижній", "Правий верхній", "Лівий верхній", "По центру"]
VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

try:  # перетягування файлів мишкою (необов'язково)
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_BASES = (TkinterDnD.DnDWrapper,)
except Exception:  # noqa: BLE001
    TkinterDnD = None
    DND_FILES = None
    _DND_BASES = ()
BORDER_COLOR_MODES = ["Випадковий", "Свій"]
X264_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"]
RES_OPTIONS = {"Як в оригіналі": 0, "720p": 720, "1080p": 1080, "1440p (2K)": 1440, "2160p (4K)": 2160}
FPS_OPTIONS = ["Як в оригіналі", "24", "25", "30", "50", "60"]
HDR_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
              "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")

ENCODERS = {
    "CPU (libx264)": "libx264",
    "NVIDIA (NVENC)": "h264_nvenc",
    "Intel (Quick Sync)": "h264_qsv",
    "AMD (AMF)": "h264_amf",
}

ACCENT = ("#6C4DFF", "#7C5CFF")
ACCENT_HOVER = ("#5A3CF0", "#6847F5")
SECONDARY = ("#E3E5EE", "#2A2D38")
SECONDARY_HOVER = ("#D3D6E2", "#363A48")
SECONDARY_TEXT = ("#1E2028", "#E6E8EF")
DANGER = ("#D64545", "#B33A3A")
DANGER_HOVER = ("#C03636", "#CC4444")
CARD = ("#FFFFFF", "#1C1E26")
WINDOW_BG = ("#F1F2F7", "#121319")
INPUT_BG = ("#F7F8FB", "#15171E")
HINT = ("#6B7080", "#8A8FA3")
SEG_SELECTED = ("#C4B6FF", "#7C5CFF")
SEG_SELECTED_HOVER = ("#B3A2FF", "#6847F5")
SEG_TEXT = ("#1E2028", "#FFFFFF")


def apply_theme():
    """Фірмова тема: фіолетовий акцент, темні картки, шрифт Segoe UI."""
    t = ctk.ThemeManager.theme

    def put(widget, **kw):
        if widget in t:
            for k, v in kw.items():
                if k in t[widget]:
                    t[widget][k] = list(v) if isinstance(v, tuple) else v

    put("CTk", fg_color=WINDOW_BG)
    put("CTkToplevel", fg_color=WINDOW_BG)
    put("CTkFrame", fg_color=CARD, top_fg_color=("#F4F5FA", "#23262F"), corner_radius=12)
    put("CTkButton", fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=8)
    put("CTkCheckBox", fg_color=ACCENT, hover_color=ACCENT_HOVER, corner_radius=5)
    put("CTkSwitch", progress_color=ACCENT)
    put("CTkRadioButton", fg_color=ACCENT, hover_color=ACCENT_HOVER)
    put("CTkSlider", progress_color=ACCENT, button_color=ACCENT, button_hover_color=ACCENT_HOVER)
    put("CTkProgressBar", progress_color=ACCENT)
    put("CTkOptionMenu", fg_color=SECONDARY, button_color=SECONDARY_HOVER, button_hover_color=ACCENT,
        text_color=SECONDARY_TEXT, corner_radius=8)
    put("CTkComboBox", button_color=SECONDARY_HOVER, button_hover_color=ACCENT)
    put("CTkSegmentedButton", selected_color=SEG_SELECTED, selected_hover_color=SEG_SELECTED_HOVER,
        unselected_color=SECONDARY, unselected_hover_color=SECONDARY_HOVER, fg_color=SECONDARY,
        text_color=SEG_TEXT)
    put("CTkEntry", fg_color=INPUT_BG, border_color=("#D3D6E2", "#2E3240"), corner_radius=8)
    put("CTkTextbox", fg_color=INPUT_BG, border_color=("#D3D6E2", "#2E3240"))
    put("CTkScrollableFrame", label_fg_color=SECONDARY)
    if "CTkFont" in t:
        for plat in ("Windows", "macOS", "Linux"):
            if plat in t["CTkFont"] and "family" in t["CTkFont"][plat]:
                t["CTkFont"][plat]["family"] = {"Windows": "Segoe UI", "macOS": "SF Pro Display"}.get(
                    plat, t["CTkFont"][plat]["family"])


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if x != 0 else "0"


# ----------------------------------------------------------------------------
#  Стильові пресети: функція від сили k (0..1) -> список фільтрів FFmpeg
# ----------------------------------------------------------------------------

STYLE_PRESETS = {
    "Теплий": lambda k: [
        f"colorbalance=rs={_f(.10*k)}:gs={_f(.03*k)}:bs={_f(-.10*k)}:rm={_f(.05*k)}:bm={_f(-.05*k)}",
        f"eq=saturation={_f(1+.06*k)}",
    ],
    "Холодний": lambda k: [
        f"colorbalance=rs={_f(-.08*k)}:bs={_f(.10*k)}:rm={_f(-.04*k)}:bm={_f(.06*k)}",
    ],
    "Кіно (teal & orange)": lambda k: [
        f"colorbalance=rs={_f(-.08*k)}:bs={_f(.10*k)}:rh={_f(.10*k)}:bh={_f(-.10*k)}",
        f"eq=contrast={_f(1+.08*k)}:saturation={_f(1+.05*k)}",
        f"vignette=a={_f(max(.05, .55*k))}",
    ],
    "Вінтаж": lambda k: [
        f"curves=all='0/{_f(.06*k)} 1/{_f(1-.06*k)}'",
        f"colorbalance=rs={_f(.06*k)}:bs={_f(-.07*k)}",
        f"eq=saturation={_f(1-.25*k)}",
    ],
    "Матовий": lambda k: [
        f"curves=all='0/{_f(.10*k)} 1/{_f(1-.05*k)}'",
        f"eq=saturation={_f(1-.12*k)}",
    ],
    "Яскравий": lambda k: [
        f"eq=contrast={_f(1+.08*k)}:saturation={_f(1+.30*k)}",
    ],
    "Драматичний": lambda k: [
        f"eq=contrast={_f(1+.20*k)}:saturation={_f(1-.10*k)}:brightness={_f(-.02*k)}",
        f"vignette=a={_f(max(.05, .8*k))}",
    ],
    "Ч/Б": lambda k: [
        f"hue=s={_f(1-k)}",
        f"eq=contrast={_f(1+.12*k)}",
    ],
}


# ----------------------------------------------------------------------------
#  FFmpeg / FFprobe
# ----------------------------------------------------------------------------

def locate_ffmpeg() -> str:
    """ffmpeg з PATH, поруч із програмою або з папки winget (Windows)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates = [APP_DIR / exe]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / exe)
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            candidates += sorted(pkgs.glob(f"Gyan.FFmpeg*/**/bin/{exe}"))
    for c in candidates:
        if c.is_file():
            return str(c)
    return "ffmpeg"


def find_ffprobe(ffmpeg_path: str) -> str:
    p = Path(ffmpeg_path)
    name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
    candidate = p.with_name(name)
    if str(p.parent) not in ("", ".") and candidate.exists():
        return str(candidate)
    return shutil.which("ffprobe") or name


@dataclass
class MediaInfo:
    width: int
    height: int
    duration: float
    has_audio: bool
    fps: float = 30.0
    bitrate: int = 0
    hdr: bool = False


def probe(ffprobe: str, path: str) -> MediaInfo:
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", path]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", creationflags=_NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe не зміг прочитати файл: {res.stderr.strip()}")
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise RuntimeError("у файлі немає відеодоріжки")
    w, h = int(v["width"]), int(v["height"])

    rotation = 0
    try:
        rotation = int(float(v.get("tags", {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if abs(rotation) % 180 == 90:
        w, h = h, w

    duration = 0.0
    for src in (data.get("format", {}), v):
        try:
            duration = float(src.get("duration", 0) or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            break
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    fps = 30.0
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(v.get(key, "0/0")).partition("/")
        try:
            val = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            val = 0
        if 1 <= val <= 240:
            fps = val
            break
    bitrate = 0
    for src in (v, data.get("format", {})):
        try:
            bitrate = int(src.get("bit_rate") or 0)
        except (TypeError, ValueError):
            bitrate = 0
        if bitrate:
            break
    hdr = v.get("color_transfer") in ("smpte2084", "arib-std-b67")
    return MediaInfo(w - w % 2, h - h % 2, duration, has_audio, fps, bitrate, hdr)


_FILTER_CACHE: dict[str, set] = {}


def has_filter(ffmpeg: str, name: str) -> bool:
    if ffmpeg not in _FILTER_CACHE:
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
            _FILTER_CACHE[ffmpeg] = {ln.split()[1] for ln in r.stdout.splitlines()
                                     if len(ln.split()) > 2 and len(ln.split()[0]) == 3}
        except OSError:
            _FILTER_CACHE[ffmpeg] = set()
    return name in _FILTER_CACHE[ffmpeg]


def target_size(info: MediaInfo, res_label: str) -> tuple[int, int]:
    short = RES_OPTIONS.get(res_label, 0)
    W, H = info.width, info.height
    if not short:
        return W, H
    k = short / min(W, H)
    return int(round(W * k / 2)) * 2, int(round(H * k / 2)) * 2


def target_fps(info: MediaInfo, fps_label: str) -> str:
    if fps_label in FPS_OPTIONS[1:]:
        return fps_label
    return f"{info.fps:.3f}".rstrip("0").rstrip(".")


def encoder_pix_fmt(encoder: str) -> str:
    return "nv12" if encoder in ("h264_qsv", "h264_amf") else "yuv420p"


def encoder_args(encoder: str, crf: int, x264_preset: str, mbps: float | None = None) -> list[str]:
    q = str(crf)
    pf = encoder_pix_fmt(encoder)
    if mbps:
        b = f"{mbps:.2f}M"
        mx = f"{mbps * 1.5:.2f}M"
        buf = f"{mbps * 2:.2f}M"
        rate = ["-b:v", b, "-maxrate", mx, "-bufsize", buf]
        if encoder == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", *rate, "-pix_fmt", pf]
        if encoder == "h264_qsv":
            return ["-c:v", "h264_qsv", "-preset", "medium", *rate, "-pix_fmt", pf]
        if encoder == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "vbr_peak", *rate, "-pix_fmt", pf]
        return ["-c:v", "libx264", "-preset", x264_preset, *rate, "-pix_fmt", pf]
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", q,
                "-b:v", "0", "-pix_fmt", pf]
    if encoder == "h264_qsv":
        return ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", q, "-pix_fmt", pf]
    if encoder == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                "-qp_i", q, "-qp_p", q, "-qp_b", q, "-pix_fmt", pf]
    return ["-c:v", "libx264", "-preset", x264_preset, "-crf", q, "-pix_fmt", pf]


def detect_encoders(ffmpeg: str) -> list[str]:
    """Повертає назви з ENCODERS, які реально працюють на цьому комп'ютері."""
    ok = []
    for label, enc in ENCODERS.items():
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2:r=25",
               "-vf", f"format={encoder_pix_fmt(enc)}", "-frames:v", "3",
               *encoder_args(enc, 23, "veryfast"), "-f", "null", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=20, creationflags=_NO_WINDOW)
            if r.returncode == 0:
                ok.append(label)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ok


# ----------------------------------------------------------------------------
#  Налаштування та варіації
# ----------------------------------------------------------------------------

@dataclass
class Options:
    strip_metadata: bool = True
    color: bool = True
    zoom_border: bool = True
    zoom_mode: str = "Випадково"
    border_color_mode: str = "Випадковий"
    border_color: str = "0x000000"
    grain: bool = True
    tempo: bool = True
    hflip: bool = False
    randomize_set: bool = True
    effect_chance: float = 0.65
    # діапазони ефектів (задаються в інтерфейсі)
    color_min: float = 3.0      # контраст/насиченість, %
    color_max: float = 5.0
    bright_min: float = 1.0     # яскравість, %
    bright_max: float = 4.0
    hue_max: float = 0.0        # зсув відтінку, градуси (0 = вимкнено)
    zoom_min: float = 1.0       # мікрозум/кроп, %
    zoom_max: float = 3.0
    grain_min: int = 3          # сила зерна
    grain_max: int = 7
    tempo_min: float = -2.0     # темп, %
    tempo_max: float = 3.0
    # обрізка та експорт
    trim_enabled: bool = False
    trim_start: float = 0.0     # секунд прибрати з початку
    trim_end: float = 0.0       # секунд прибрати з кінця
    bitrate_mode: str = "Якість (CRF)"
    video_mbps: float = 8.0
    audio_bitrate: str = "192k"
    use_styles: bool = False
    styles: list = field(default_factory=lambda: ["Теплий", "Холодний", "Кіно (teal & orange)"])
    style_strength: float = 0.6
    encoder_label: str = "CPU (libx264)"
    crf: int = 18
    x264_preset: str = "medium"
    parallel: int = 2
    sharpen: bool = True
    resolution: str = "Як в оригіналі"
    fps: str = "Як в оригіналі"
    bitrate_cap: bool = True
    # оформлення
    aspect: str = "Як в оригіналі"
    wm_enabled: bool = False
    wm_type: str = "Логотип"
    wm_logo: str = ""
    wm_text: str = "@my_account"
    wm_pos: str = "Правий нижній"
    wm_opacity: float = 0.7
    wm_size: float = 0.15
    hook_enabled: bool = False
    hook_text: str = ""
    hook_seconds: float = 3.0
    hook_font: str = "Impact"
    hook_pos: str = "Зверху"
    hook_style: str = "Темна плашка"
    hook_size: float = 0.07
    thumbnails: bool = False
    # покращення
    detail: float = 0.0
    denoise: bool = False
    deshake: bool = False
    loudnorm: bool = True
    lut_enabled: bool = False
    lut_file: str = ""


@dataclass
class Variation:
    index: int
    style: str | None = None
    style_strength: float | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    zoom: float | None = None
    zoom_x: float | None = None
    zoom_y: float | None = None
    border_px: int | None = None
    border_color: str | None = None
    grain: int | None = None
    tempo: float | None = None
    hflip: bool = False
    hue: float | None = None
    metadata_stripped: bool = False

    def signature(self) -> tuple:
        d = asdict(self)
        d.pop("index")
        return tuple(sorted((k, str(v)) for k, v in d.items()))

    def describe(self) -> str:
        parts = []
        if self.style:
            parts.append(f"стиль «{self.style}» {self.style_strength:.0%}")
        if self.brightness is not None:
            parts.append(f"яскр {self.brightness:+.3f}, контр ×{self.contrast:.3f}, "
                         f"насич ×{self.saturation:.3f}")
        if self.hue is not None:
            parts.append(f"відтінок {self.hue:+.1f}°")
        if self.zoom is not None:
            parts.append(f"зум ×{self.zoom:.3f}")
        if self.border_px is not None:
            parts.append(f"рамка {self.border_px}px {self.border_color}")
        if self.grain is not None:
            parts.append(f"зерно {self.grain}")
        if self.tempo is not None:
            parts.append(f"темп ×{self.tempo:.3f}")
        if self.hflip:
            parts.append("дзеркало")
        return "; ".join(parts) or "без візуальних змін"


def _span(a: float, b: float, lo: float, hi: float) -> tuple[float, float]:
    """Впорядковує й обмежує діапазон від/до розумними межами."""
    a, b = max(lo, min(hi, float(a))), max(lo, min(hi, float(b)))
    return (a, b) if a <= b else (b, a)


def _signed(rng: random.Random, lo: float, hi: float) -> float:
    return rng.uniform(lo, hi) * rng.choice((-1, 1))


def make_variation(index: int, opt: Options, info: MediaInfo, rng: random.Random,
                   style: str | None) -> Variation:
    var = Variation(index=index, metadata_stripped=opt.strip_metadata)
    if style:
        var.style = style
        var.style_strength = opt.style_strength

    def use(enabled: bool) -> bool:
        if not enabled:
            return False
        return (rng.random() < opt.effect_chance) if opt.randomize_set else True

    flags = {"color": use(opt.color), "zoom_border": use(opt.zoom_border),
             "grain": use(opt.grain), "tempo": use(opt.tempo)}
    enabled = [k for k in flags if getattr(opt, k)]
    if enabled and not any(flags.values()) and not style:
        flags[rng.choice(enabled)] = True

    if flags["color"]:
        b0, b1 = _span(opt.bright_min, opt.bright_max, 0, 10)
        c0, c1 = _span(opt.color_min, opt.color_max, 0, 15)
        var.brightness = round(_signed(rng, b0 / 100, b1 / 100), 4)
        var.contrast = round(1 + _signed(rng, c0 / 100, c1 / 100), 4)
        var.saturation = round(1 + _signed(rng, c0 / 100, c1 / 100), 4)
        h1 = max(0.0, min(15.0, float(opt.hue_max)))
        if h1 > 0:
            var.hue = round(rng.uniform(-h1, h1), 2)

    if flags["zoom_border"]:
        mode = opt.zoom_mode
        if mode == "Випадково":
            mode = rng.choice(["Тільки зум", "Тільки рамка"])
        if mode == "Тільки зум":
            z0, z1 = _span(opt.zoom_min, opt.zoom_max, 0.2, 10)
            var.zoom = round(1 + rng.uniform(z0, z1) / 100, 4)
            var.zoom_x = round(rng.random(), 3)
            var.zoom_y = round(rng.random(), 3)
        else:
            px = max(2, round(min(info.width, info.height) * rng.uniform(0.004, 0.012)))
            var.border_px = px + px % 2
            var.border_color = (opt.border_color if opt.border_color_mode == "Свій"
                                else rng.choice(BORDER_COLORS))

    if flags["grain"]:
        g0, g1 = _span(opt.grain_min, opt.grain_max, 1, 25)
        var.grain = rng.randint(int(g0), int(g1))

    if flags["tempo"]:
        t0, t1 = _span(opt.tempo_min, opt.tempo_max, -10, 10)
        if not (t0 == 0 and t1 == 0):
            t = 1.0
            for _ in range(50):
                t = 1 + rng.uniform(t0, t1) / 100
                if abs(t - 1.0) >= 0.003:
                    break
            if abs(t - 1.0) >= 0.001:
                var.tempo = round(t, 4)

    if opt.hflip:
        var.hflip = rng.random() < 0.5
    return var


def plan_variations(count: int, opt: Options, info: MediaInfo, rng: random.Random) -> list[Variation]:
    """N унікальних варіацій; пресети розподіляються рівномірно (A/B-групи)."""
    styles: list[str | None] = [None] * count
    chosen = [s for s in opt.styles if s in STYLE_PRESETS]
    if opt.use_styles and chosen:
        pool = (chosen * math.ceil(count / len(chosen)))[:count]
        rng.shuffle(pool)
        styles = pool
    seen: set[tuple] = set()
    plan = []
    for i in range(count):
        var = None
        for _ in range(50):
            var = make_variation(i + 1, opt, info, rng, styles[i])
            if var.signature() not in seen:
                break
        seen.add(var.signature())
        plan.append(var)
    return plan


def find_font() -> str | None:
    for f in FONT_CANDIDATES:
        if os.path.isfile(f):
            return f
    return None


def _font_dirs() -> list[Path]:
    dirs = []
    if sys.platform == "win32":
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(Path(la) / "Microsoft" / "Windows" / "Fonts")
    elif sys.platform == "darwin":
        dirs += [Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path.home() / "Library/Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".local/share/fonts", Path.home() / ".fonts"]
    dirs.append(APP_DIR / "fonts")
    return [d for d in dirs if d.is_dir()]


_FONT_CACHE: dict | None = None


def available_fonts() -> dict:
    """{назва: шлях} — шрифти зі списку, які є на цьому комп'ютері (+ будь-які .ttf з папки fonts поруч)."""
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    found: dict = {}
    index: dict = {}
    for d in _font_dirs():
        try:
            for f in d.rglob("*"):
                if f.suffix.lower() in (".ttf", ".otf"):
                    index.setdefault(f.name.lower(), str(f))
        except OSError:
            pass
    for label, names in FONT_LIBRARY:
        for n in names:
            if n.lower() in index:
                found[label] = index[n.lower()]
                break
    own = APP_DIR / "fonts"
    if own.is_dir():
        for f in sorted(own.glob("*.[ot]tf")):
            found.setdefault(f.stem, str(f))
    _FONT_CACHE = found
    return found


def resolve_font(name_or_path: str) -> str | None:
    if name_or_path and os.path.isfile(name_or_path):
        return name_or_path
    fonts = available_fonts()
    if name_or_path in fonts:
        return fonts[name_or_path]
    return next(iter(fonts.values()), None) or find_font()


def render_hook_png(opt: Options, canvas_w: int, out_path: Path) -> bool:
    """Малює текст-хук як прозору PNG: перенос рядків по ширині, шрифт, плашка (як у CapCut)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False
    text = opt.hook_text.strip()
    font_path = resolve_font(opt.hook_font)
    if not text or not font_path:
        return False
    max_w = int(canvas_w * 0.86)
    size = max(12, int(canvas_w * max(0.03, min(0.15, opt.hook_size))))
    probe_img = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(probe_img)

    def wrap(font):
        lines = []
        for para in text.splitlines() or [""]:
            words, cur = para.split(), ""
            for w in words:
                trial = (cur + " " + w).strip()
                if d.textlength(trial, font=font) <= max_w or not cur:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
        return lines

    def load(sz):
        f = ImageFont.truetype(font_path, sz)
        try:  # змінні шрифти (Montserrat[wght] тощо) — беремо жирне накреслення
            names = [n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()]
            for want in ("ExtraBold", "Bold", "Black", "SemiBold"):
                if want in names:
                    f.set_variation_by_name(want)
                    break
        except Exception:  # noqa: BLE001
            pass
        return f

    while True:
        font = load(size)
        lines = wrap(font)
        widest = max(d.textlength(l, font=font) for l in lines)
        if widest <= max_w or size <= 12:
            break
        size = int(size * 0.92)

    stroke = max(2, size // 14) if opt.hook_style == "Обводка без плашки" else 0
    asc, desc = font.getmetrics()
    line_h = asc + desc
    gap = int(size * 0.18)
    text_h = line_h * len(lines) + gap * (len(lines) - 1)
    pad_x, pad_y = int(size * 0.55), int(size * 0.35)
    box_w = int(widest) + pad_x * 2 + stroke * 2
    box_h = text_h + pad_y * 2 + stroke * 2
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    if opt.hook_style == "Темна плашка":
        bg, fg = (0, 0, 0, 175), (255, 255, 255, 255)
    elif opt.hook_style == "Біла плашка":
        bg, fg = (255, 255, 255, 240), (15, 15, 15, 255)
    else:
        bg, fg = None, (255, 255, 255, 255)
    if bg:
        dr.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=int(size * 0.45), fill=bg)
    y = pad_y + stroke
    for l in lines:
        lw = dr.textlength(l, font=font)
        dr.text(((box_w - lw) / 2, y), l, font=font, fill=fg,
                stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += line_h + gap
    img.save(out_path)
    return True


def assets_for_source(base: dict, opt: Options, info: MediaInfo, folder: Path) -> dict:
    """Додає PNG хука під ширину кадру конкретного відео."""
    a = dict(base)
    if opt.hook_enabled and opt.hook_text.strip():
        cw, _ = canvas_size(info, opt)
        png = folder / f"hook_{cw}.png"
        if png.exists() or render_hook_png(opt, cw, png):
            a["hook_png"] = str(png)
    return a


def prepare_assets(opt: Options, folder: Path) -> dict:
    """Кладе шрифт, тексти та LUT у робочу папку FFmpeg (без проблем зі шляхами Windows)."""
    a = {"font": False, "hook": False, "wmtext": False, "lut": False, "logo": None, "warnings": []}
    want_hook = opt.hook_enabled and opt.hook_text.strip()
    want_wmtext = opt.wm_enabled and opt.wm_type == "Текст" and opt.wm_text.strip()
    if want_hook or want_wmtext:
        font = find_font()
        if font:
            shutil.copyfile(font, folder / "font.ttf")
            a["font"] = True
        else:
            a["warnings"].append("не знайдено шрифт — текст на відео пропущено")
    if a["font"] and want_hook:
        (folder / "hook.txt").write_text(opt.hook_text.strip(), encoding="utf-8")
        a["hook"] = True
    if a["font"] and want_wmtext:
        (folder / "wm.txt").write_text(opt.wm_text.strip(), encoding="utf-8")
        a["wmtext"] = True
    if opt.wm_enabled and opt.wm_type == "Логотип":
        if os.path.isfile(opt.wm_logo):
            a["logo"] = opt.wm_logo
        else:
            a["warnings"].append("файл логотипа не знайдено — водяний знак пропущено")
    if opt.lut_enabled:
        if os.path.isfile(opt.lut_file):
            shutil.copyfile(opt.lut_file, folder / "lut.cube")
            a["lut"] = True
        else:
            a["warnings"].append("файл LUT не знайдено — LUT пропущено")
    return a


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def canvas_size(info: MediaInfo, opt: Options) -> tuple[int, int]:
    """Розмір вихідного кадру з урахуванням роздільності та формату (9:16 тощо)."""
    W, H = target_size(info, opt.resolution)
    ratio = ASPECTS.get(opt.aspect)
    if not ratio:
        return W, H
    rw, rh = ratio
    S = min(W, H)
    if rw <= rh:
        cw = _even(S)
        ch = _even(cw * rh / rw)
    else:
        ch = _even(S)
        cw = _even(ch * rw / rh)
    return cw, ch


def _pos(pos: str, kind: str) -> tuple[str, str]:
    """Вирази позиції: kind='overlay' (W,w,H,h) або 'text' (w,text_w,h,text_h)."""
    if kind == "overlay":
        BW, bw, BH, bh, m = "W", "w", "H", "h", "W*0.03"
    else:
        BW, bw, BH, bh, m = "w", "text_w", "h", "text_h", "w*0.03"
    return {
        "Правий нижній": (f"{BW}-{bw}-{m}", f"{BH}-{bh}-{m}"),
        "Лівий нижній": (m, f"{BH}-{bh}-{m}"),
        "Правий верхній": (f"{BW}-{bw}-{m}", m),
        "Лівий верхній": (m, m),
        "По центру": (f"({BW}-{bw})/2", f"({BH}-{bh})/2"),
    }.get(pos, (f"{BW}-{bw}-{m}", f"{BH}-{bh}-{m}"))


def build_graph(var: Variation, info: MediaInfo, opt: Options, pix_fmt: str = "yuv420p",
                tonemap: bool = False, for_preview: bool = False, assets: dict | None = None,
                has_cas: bool = True, tail: str | None = None) -> tuple[str, list[str], str | None]:
    """Повертає (filter_complex, додаткові вхідні файли, аудіофільтр). Вихід відео — мітка [vout]."""
    assets = assets or {}
    W, H = target_size(info, opt.resolution)
    CW, CH = canvas_size(info, opt)

    pre: list[str] = []
    if opt.deshake and not for_preview:
        pre.append("deshake")
    if info.hdr and tonemap:
        pre.append(HDR_TO_SDR)
    if opt.denoise:
        pre.append("hqdn3d=2:1.5:3:3")
    if var.zoom is not None:
        z = var.zoom
        pre.append(f"crop=trunc(iw/{z}/2)*2:trunc(ih/{z}/2)*2:(iw-ow)*{var.zoom_x}:(ih-oh)*{var.zoom_y}")
        pre.append(f"scale={W}:{H}:flags=lanczos")
    elif var.border_px is not None:
        b = var.border_px
        pre.append(f"scale={W - 2 * b}:{H - 2 * b}:flags=lanczos")
        pre.append(f"pad={W}:{H}:{b}:{b}:color={var.border_color}")
    else:
        pre.append(f"scale={W}:{H}:flags=lanczos")

    post: list[str] = []
    if var.style:
        post += STYLE_PRESETS[var.style](var.style_strength or 0.6)
    if var.brightness is not None:
        post.append(f"eq=brightness={var.brightness}:contrast={var.contrast}:saturation={var.saturation}")
    if var.hue is not None:
        post.append(f"hue=h={var.hue}")
    if assets.get("lut"):
        post.append("lut3d=file=lut.cube:interp=tetrahedral")
    if opt.sharpen:
        amount = 0.35 + (0.25 if (W * H) > (info.width * info.height) else 0)
        post.append(f"unsharp=5:5:{amount}:5:5:0")
    if opt.detail > 0:
        post.append(f"cas=strength={opt.detail:.2f}" if has_cas
                    else f"unsharp=3:3:{0.6 * opt.detail:.2f}:3:3:0")
    if var.grain is not None:
        post.append(f"noise=alls={var.grain}:allf=t+u")
    if var.hflip:
        post.append("hflip")
    if assets.get("hook") and not assets.get("hook_png"):
        enable = "" if for_preview else f":enable='lt(t,{float(opt.hook_seconds):.2f})'"
        post.append("drawtext=fontfile=font.ttf:textfile=hook.txt:expansion=none:fontsize=h*0.055"
                    ":fontcolor=white:borderw=3:bordercolor=black@0.6:box=1:boxcolor=black@0.35"
                    f":boxborderw=18:line_spacing=8:x=(w-text_w)/2:y=h*0.14{enable}")
    if assets.get("wmtext"):
        x, y = _pos(opt.wm_pos, "text")
        op = max(0.05, min(1.0, opt.wm_opacity))
        fs = 0.035 * (opt.wm_size / 0.15)
        post.append(f"drawtext=fontfile=font.ttf:textfile=wm.txt:expansion=none:fontsize=h*{fs:.4f}"
                    f":fontcolor=white@{op:.2f}:borderw=2:bordercolor=black@{op * 0.6:.2f}:x={x}:y={y}")

    final: list[str] = []
    if not for_preview:
        if var.tempo is not None:
            final.append(f"setpts=PTS/{var.tempo}")
        final.append(f"fps={target_fps(info, opt.fps)}")
        final += ["setsar=1", f"format={pix_fmt}"]
    if tail:
        final.append(tail)

    parts: list[str] = []
    extra_inputs: list[str] = []
    if ASPECTS.get(opt.aspect):
        parts.append("[0:v]" + ",".join(pre + ["split=2[fg0][bg0]"]))
        parts.append(f"[bg0]scale={CW}:{CH}:force_original_aspect_ratio=increase,crop={CW}:{CH},"
                     f"boxblur=20:3,eq=brightness=-0.06[bg]")
        parts.append(f"[fg0]scale={CW}:{CH}:force_original_aspect_ratio=decrease:force_divisible_by=2[fg]")
        head = "[bg][fg]overlay=(W-w)/2:(H-h)/2"
        main = [head] + post
        prefix = ""
    else:
        main = pre + post
        prefix = "[0:v]"

    overlays = []  # (вхід, ланцюжок для картинки, x, y, enable)
    hook_png = assets.get("hook_png")
    if hook_png:
        hy = {"Зверху": "H*0.12", "По центру": "(H-h)/2", "Знизу": "H-h-H*0.17"}.get(opt.hook_pos, "H*0.12")
        en = "" if for_preview else f":enable='lt(t,{float(opt.hook_seconds):.2f})'"
        overlays.append((hook_png, "format=rgba", "(W-w)/2", hy, en))
    logo = assets.get("logo")
    if logo:
        x, y = _pos(opt.wm_pos, "overlay")
        op = max(0.05, min(1.0, opt.wm_opacity))
        lw = _even(CW * max(0.03, min(0.6, opt.wm_size)))
        overlays.append((logo, f"scale={lw}:-1,format=rgba,colorchannelmixer=aa={op:.2f}", x, y, ""))

    if overlays:
        parts.append(prefix + ",".join(main or ["null"]) + "[b0]")
        cur = "b0"
        for k, (path, chain, x, y, en) in enumerate(overlays, start=1):
            extra_inputs.append(path)
            parts.append(f"[{k}:v]{chain}[ov{k}]")
            last = k == len(overlays)
            nxt = "vout" if last else f"b{k}"
            tail_f = ("," + ",".join(final)) if (last and final) else ""
            parts.append(f"[{cur}][ov{k}]overlay={x}:{y}{en}{tail_f}[{nxt}]")
            cur = nxt
    else:
        parts.append(prefix + ",".join((main + final) or ["null"]) + "[vout]")

    af: list[str] = []
    if info.has_audio and not for_preview:
        if var.tempo is not None:
            af.append(f"atempo={var.tempo}")
        if opt.loudnorm:
            af.append("loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000")
    return ";".join(parts), extra_inputs, (",".join(af) or None)


def trim_window(info: MediaInfo, opt: Options) -> tuple[float, float]:
    """(початок, тривалість вихідного шматка в секундах вихідника). Без обрізки — (0, повна тривалість)."""
    if not opt.trim_enabled or info.duration <= 0:
        return 0.0, info.duration
    a = max(0.0, float(opt.trim_start))
    b = max(0.0, float(opt.trim_end))
    if info.duration - a - b < 0.5:   # щоб не обрізати відео «в нуль»
        return 0.0, info.duration
    return a, info.duration - a - b


def build_command(ffmpeg: str, src: str, dst: str, var: Variation, info: MediaInfo,
                  opt: Options, assets: dict | None = None) -> list[str]:
    encoder = ENCODERS.get(opt.encoder_label, "libx264")
    fc, extra, af = build_graph(var, info, opt, encoder_pix_fmt(encoder),
                                tonemap=has_filter(ffmpeg, "zscale"), assets=assets,
                                has_cas=has_filter(ffmpeg, "cas"))
    t0, tlen = trim_window(info, opt)
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
    if t0 > 0:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-i", src]
    for e in extra:
        cmd += ["-i", e]
    cmd += ["-filter_complex", fc, "-map", "[vout]", "-map", "0:a:0?"]
    if af:
        cmd += ["-af", af]
    if var.metadata_stripped:
        cmd += ["-map_metadata", "-1", "-map_chapters", "-1",
                "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    fixed = opt.bitrate_mode == "Фіксований бітрейт"
    mbps = max(0.5, min(100.0, float(opt.video_mbps))) if fixed else None
    cmd += encoder_args(encoder, opt.crf, opt.x264_preset, mbps)
    if opt.trim_enabled and tlen < info.duration:
        cmd += ["-t", f"{tlen / (var.tempo or 1.0):.3f}"]
    if opt.bitrate_cap and not fixed:
        cmd += bitrate_cap_args(info, opt)
    cmd += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"] \
        if (info.hdr or info.height >= 720) else []
    if info.has_audio:
        ab = opt.audio_bitrate if opt.audio_bitrate in AUDIO_BITRATES else "192k"
        cmd += ["-c:a", "aac", "-b:a", ab]
    if dst.lower().endswith((".mp4", ".mov", ".m4v")):
        cmd += ["-movflags", "+faststart"]
    cmd += ["-progress", "pipe:1", "-nostats", "-loglevel", "error", dst]
    return cmd


def bitrate_cap_args(info: MediaInfo, opt: Options) -> list[str]:
    """Стеля бітрейту, щоб зерно не роздувало файли: ~1.6× оригіналу з поправкою на роздільність/fps."""
    W, H = canvas_size(info, opt)
    px_ratio = (W * H) / max(1, info.width * info.height)
    fps_ratio = float(target_fps(info, opt.fps)) / max(1.0, info.fps)
    base = info.bitrate or int(W * H * float(target_fps(info, opt.fps)) * 0.1)
    cap = int(max(base * 1.6 * px_ratio * max(1.0, fps_ratio), W * H * 2.5))
    return ["-maxrate", str(cap), "-bufsize", str(cap * 2)]


def source_rng(seed: int, source_index: int) -> random.Random:
    return random.Random(f"{seed}:{source_index}")


# ----------------------------------------------------------------------------
#  Фонові задачі
# ----------------------------------------------------------------------------

@dataclass
class Job:
    src: str
    dst: str
    name: str
    info: MediaInfo
    var: Variation


class BatchWorker(threading.Thread):
    def __init__(self, ffmpeg: str, sources: list[str], out_dir: str, count: int,
                 opt: Options, seed: int, events: queue.Queue):
        super().__init__(daemon=True)
        self.ffmpeg = os.path.abspath(ffmpeg) if os.path.isfile(ffmpeg) else ffmpeg
        self.sources = [os.path.abspath(x) for x in sources]
        self.out_dir = os.path.abspath(out_dir)
        self.count, self.opt, self.seed, self.events = count, opt, seed, events
        self._stop_evt = threading.Event()
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()
        self._fractions: dict[int, float] = {}
        self._last_emit = 0.0
        self.failed = 0

    def stop(self):
        self._stop_evt.set()
        with self._lock:
            for p in list(self._procs):
                if p.poll() is None:
                    try:
                        p.terminate()
                    except OSError:
                        pass

    def emit(self, kind: str, **data):
        self.events.put((kind, data))

    def run(self):
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001
            self.emit("error", message=str(exc))
        finally:
            self.emit("done", stopped=self._stop_evt.is_set(), failed=self.failed)

    def _run(self):
        ffprobe = find_ffprobe(self.ffmpeg)
        os.makedirs(self.out_dir, exist_ok=True)
        self.assets_dir = Path(tempfile.mkdtemp(prefix="vvar_assets_"))
        self.assets = prepare_assets(self.opt, self.assets_dir)
        for w in self.assets["warnings"]:
            self.emit("log", text=f"⚠ {w}")
        width = max(3, len(str(self.count)))
        jobs: list[Job] = []
        for si, src in enumerate(self.sources):
            try:
                info = probe(ffprobe, src)
            except Exception as exc:  # noqa: BLE001
                self.emit("log", text=f"✖ Пропуск {Path(src).name}: {exc}")
                continue
            sp = Path(src)
            ext = sp.suffix.lower() if sp.suffix.lower() in (".mp4", ".mov", ".mkv", ".m4v") else ".mp4"
            ow, oh = canvas_size(info, self.opt)
            self.emit("log", text=f"■ {sp.name}: {info.width}×{info.height} @ {info.fps:.2f} к/с, "
                                  f"{info.duration:.1f} с, аудіо: {'так' if info.has_audio else 'ні'}"
                                  f" → {ow}×{oh} @ {target_fps(info, self.opt.fps)} к/с")
            if info.hdr:
                self.emit("log", text="   HDR-відео: " + (
                    "конвертую в SDR (BT.709), щоб кольори не вигоріли" if has_filter(self.ffmpeg, "zscale")
                    else "⚠ у вашому FFmpeg немає zscale — кольори можуть бути блідими"))
            for var in plan_variations(self.count, self.opt, info, source_rng(self.seed, si)):
                name = f"{sp.stem}_var_{var.index:0{width}d}{ext}"
                n = 1
                while (Path(self.out_dir) / name).exists():  # ніколи не перезаписуємо старі файли
                    n += 1
                    name = f"{sp.stem}_var_{var.index:0{width}d}_{n}{ext}"
                jobs.append(Job(src, str(Path(self.out_dir) / name), name, info, var))
        if not jobs:
            raise RuntimeError("Немає жодного придатного відео для обробки.")

        self.total = len(jobs)
        self.emit("log", text=f"Усього файлів: {self.total} • кодер: {self.opt.encoder_label} • "
                              f"паралельно: {self.opt.parallel} • seed: {self.seed}")
        results: list[dict | None] = [None] * len(jobs)
        with ThreadPoolExecutor(max_workers=max(1, self.opt.parallel)) as ex:
            futures = [ex.submit(self._run_job, i, job, results) for i, job in enumerate(jobs)]
            for f in futures:
                f.result()

        rows = [r for r in results if r]
        if rows:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            report = Path(self.out_dir) / f"variations_{stamp}_seed{self.seed}.csv"
            with open(report, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), delimiter=";")
                writer.writeheader()
                writer.writerows(rows)
            self.emit("log", text=f"Звіт параметрів: {report.name}")

    def _run_job(self, i: int, job: Job, results: list):
        if self._stop_evt.is_set():
            return
        assets = assets_for_source(self.assets, self.opt, job.info, self.assets_dir)
        cmd = build_command(self.ffmpeg, job.src, job.dst, job.var, job.info, self.opt, assets)
        out_dur = trim_window(job.info, self.opt)[1] / (job.var.tempo or 1.0)
        ok, err = self._encode(cmd, i, out_dur)
        if self._stop_evt.is_set():
            try:
                if os.path.exists(job.dst):
                    os.remove(job.dst)
            except OSError:
                pass
            return
        self._set_fraction(i, 1.0, force=True)
        if ok:
            if self.opt.thumbnails:
                self._thumbnail(job.dst, out_dur)
            self.emit("log", text=f"✔ {job.name}: {job.var.describe()}")
            row = {"source": Path(job.src).name, "file": job.name}
            row.update(asdict(job.var))
            results[i] = row
        else:
            self.failed += 1
            self.emit("log", text=f"✖ {job.name}: {err}")

    def _thumbnail(self, video: str, duration: float):
        jpg = str(Path(video).with_suffix(".jpg"))
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-ss", f"{max(0.0, duration * 0.3):.2f}", "-i", video,
               "-frames:v", "1", "-q:v", "3", jpg]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, creationflags=_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _set_fraction(self, i: int, frac: float, force: bool = False):
        with self._lock:
            self._fractions[i] = frac
            done = sum(1 for v in self._fractions.values() if v >= 1.0)
            overall = sum(self._fractions.values()) / self.total
            now = time.monotonic()
            if not force and now - self._last_emit < 0.15:
                return
            self._last_emit = now
        self.emit("progress", value=overall,
                  label=f"Готово {done} з {self.total} • {overall * 100:.0f}%")

    def _encode(self, cmd: list[str], i: int, out_duration: float) -> tuple[bool, str]:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace",
                                cwd=str(self.assets_dir), creationflags=_NO_WINDOW)
        with self._lock:
            self._procs.add(proc)
        err_buf: list[str] = []
        t = threading.Thread(target=lambda: err_buf.append(proc.stderr.read()), daemon=True)
        t.start()
        for line in proc.stdout:
            if self._stop_evt.is_set():
                break
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and out_duration > 0:
                try:
                    sec = int(value) / 1_000_000
                except ValueError:
                    continue
                self._set_fraction(i, min(sec / out_duration, 0.999))
        proc.wait()
        t.join(timeout=2)
        with self._lock:
            self._procs.discard(proc)
        lines = "".join(err_buf).strip().splitlines()
        return proc.returncode == 0, (lines[-1] if lines else f"код {proc.returncode}")


class PreviewWorker(threading.Thread):
    """Рендерить по одному кадру оригіналу та перших варіацій першого відео."""
    MAX_FRAMES = 11

    def __init__(self, ffmpeg: str, src: str, count: int, opt: Options, seed: int,
                 events: queue.Queue):
        super().__init__(daemon=True)
        self.ffmpeg = os.path.abspath(ffmpeg) if os.path.isfile(ffmpeg) else ffmpeg
        self.src, self.count = os.path.abspath(src), count
        self.opt, self.seed, self.events = opt, seed, events

    def run(self):
        try:
            info = probe(find_ffprobe(self.ffmpeg), self.src)
            plan = plan_variations(self.count, self.opt, info, source_rng(self.seed, 0))
            tmp = Path(tempfile.mkdtemp(prefix="vvar_preview_"))
            assets = prepare_assets(self.opt, tmp)
            info_assets = None
            tonemap = has_filter(self.ffmpeg, "zscale")
            has_cas = has_filter(self.ffmpeg, "cas")
            t = max(0.0, info.duration * 0.4)
            items = []
            frames = [(None, "Оригінал")] + [(v, f"#{v.index:03d}  {v.describe()}")
                                              for v in plan[:self.MAX_FRAMES]]
            for n, (var, caption) in enumerate(frames):
                out = tmp / f"f{n:02d}.png"
                cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                       "-ss", f"{t:.3f}", "-i", self.src]
                if var is None:
                    orig = (HDR_TO_SDR + ",scale=480:-2") if (info.hdr and tonemap) else "scale=480:-2"
                    cmd += ["-frames:v", "1", "-vf", orig, str(out)]
                else:
                    if info_assets is None:
                        info_assets = assets_for_source(assets, self.opt, info, tmp)
                    fc, extra, _ = build_graph(var, info, self.opt, tonemap=tonemap, for_preview=True,
                                               assets=info_assets, has_cas=has_cas, tail="scale=480:-2")
                    for e in extra:
                        cmd += ["-i", e]
                    cmd += ["-filter_complex", fc, "-map", "[vout]", "-frames:v", "1", str(out)]
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", cwd=str(tmp), creationflags=_NO_WINDOW)
                if r.returncode == 0 and out.exists():
                    items.append((str(out), caption))
                self.events.put(("progress", {"value": (n + 1) / len(frames),
                                              "label": f"Превʼю {n + 1} з {len(frames)}"}))
            self.events.put(("preview", {"items": items, "total": len(plan)}))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", {"message": str(exc)}))
        finally:
            self.events.put(("preview_done", {}))


# ----------------------------------------------------------------------------
#  Інтерфейс
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
#  Автооновлення з GitHub
# ----------------------------------------------------------------------------

def _ver_tuple(v: str) -> tuple:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


def _raw_url(path: str) -> str:
    from urllib.parse import quote
    return f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}/{quote(path)}"


def _http_get(url: str, timeout: float = 8.0) -> bytes:
    import urllib.request
    req = urllib.request.Request(url + ("&" if "?" in url else "?") + f"t={int(time.time())}",
                                 headers={"User-Agent": "VideoVariator-Updater", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check_update() -> dict | None:
    """Повертає інформацію про нову версію або None. Ніколи не кидає винятків."""
    try:
        info = json.loads(_http_get(_raw_url("version.json")).decode("utf-8"))
        if _ver_tuple(info.get("version", "0")) > _ver_tuple(APP_VERSION):
            return info
    except Exception:  # noqa: BLE001
        pass
    return None


def install_update(info: dict) -> list[str]:
    """Завантажує файли нової версії, перевіряє SHA-256 і що код компілюється, робить резервні копії."""
    import hashlib
    files = info.get("files") or {"video_variator.py": None}
    if isinstance(files, list):
        files = {f: None for f in files}
    downloaded = {}
    for name, sha in files.items():
        if "/" in name or "\\" in name or name.startswith("."):
            raise RuntimeError(f"підозріла назва файлу: {name}")
        data = _http_get(_raw_url(name), timeout=30)
        if sha and hashlib.sha256(data).hexdigest().lower() != str(sha).lower():
            raise RuntimeError(f"контрольна сума не збігається: {name}")
        if name.endswith(".py"):
            compile(data.decode("utf-8"), name, "exec")
        downloaded[name] = data
    backup = APP_DIR / "backup"
    backup.mkdir(exist_ok=True)
    for name, data in downloaded.items():
        target = APP_DIR / name
        if target.exists():
            shutil.copyfile(target, backup / name)
        tmp = target.with_suffix(target.suffix + ".new")
        tmp.write_bytes(data)
        os.replace(tmp, target)
    return list(downloaded)


class App(ctk.CTk, *_DND_BASES):
    def __init__(self):
        super().__init__()
        self.dnd_ok = False
        if TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:  # noqa: BLE001
                self.dnd_ok = False
        ctk.set_default_color_theme("blue")
        apply_theme()
        self._appearance = "dark"
        try:
            self._appearance = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")).get("appearance", "dark")
        except (OSError, ValueError):
            pass
        ctk.set_appearance_mode(self._appearance)
        self.configure(fg_color=WINDOW_BG)
        self.report_callback_exception = self._log_exception
        self.title(APP_TITLE)
        self.geometry("980x920")
        self.minsize(900, 800)

        self.events: queue.Queue = queue.Queue()
        self.worker: BatchWorker | None = None
        self.preview_worker: PreviewWorker | None = None
        self.sources: list[str] = []
        self._had_error = False
        self._preview_images = []

        s = self._load_settings()
        o: Options = s["options"]
        self.presets: dict = s.get("presets", {}) if isinstance(s.get("presets"), dict) else {}

        out_dir = (s.get("out_dir") or "").strip()
        # старі автоматичні папки «variations» біля відео замінюємо на одну постійну папку
        if not out_dir or Path(out_dir).name.lower() == "variations":
            out_dir = str(DEFAULT_OUT_DIR)
        self.out_var = ctk.StringVar(value=out_dir)
        self.count_var = ctk.StringVar(value=str(s.get("count", 20)))
        self.seed_var = ctk.StringVar()
        self.ffmpeg_var = ctk.StringVar(value=s.get("ffmpeg") or locate_ffmpeg())

        self.bool_vars = {k: ctk.BooleanVar(value=getattr(o, k)) for k in
                          ("strip_metadata", "color", "zoom_border", "grain", "tempo",
                           "hflip", "randomize_set", "use_styles")}
        self.zoom_mode_var = ctk.StringVar(value=o.zoom_mode)
        self.range_vars = {k: ctk.StringVar(value=f"{getattr(o, k):g}") for k in RANGE_KEYS}
        self.chance_var = ctk.DoubleVar(value=o.effect_chance)
        self.border_mode_var = ctk.StringVar(value=o.border_color_mode)
        self.border_color = o.border_color
        self.style_vars = {name: ctk.BooleanVar(value=name in o.styles) for name in STYLE_PRESETS}
        self.strength_var = ctk.DoubleVar(value=o.style_strength)
        self.encoder_var = ctk.StringVar(value=o.encoder_label if o.encoder_label in ENCODERS
                                         else "CPU (libx264)")
        self.crf_var = ctk.IntVar(value=o.crf)
        self.x264_var = ctk.StringVar(value=o.x264_preset)
        self.parallel_var = ctk.IntVar(value=o.parallel)
        self.sharpen_var = ctk.BooleanVar(value=o.sharpen)
        self.cap_var = ctk.BooleanVar(value=o.bitrate_cap)
        self.trim_var = ctk.BooleanVar(value=o.trim_enabled)
        self.trim_start_var = ctk.StringVar(value=f"{o.trim_start:g}")
        self.trim_end_var = ctk.StringVar(value=f"{o.trim_end:g}")
        self.br_mode_var = ctk.StringVar(value=o.bitrate_mode if o.bitrate_mode in BITRATE_MODES else BITRATE_MODES[0])
        self.mbps_var = ctk.StringVar(value=f"{o.video_mbps:g}")
        self.abr_var = ctk.StringVar(value=o.audio_bitrate if o.audio_bitrate in AUDIO_BITRATES else "192k")
        self.res_var = ctk.StringVar(value=o.resolution if o.resolution in RES_OPTIONS else "Як в оригіналі")
        self.fps_var = ctk.StringVar(value=o.fps if o.fps in FPS_OPTIONS else "Як в оригіналі")
        # оформлення
        self.aspect_var = ctk.StringVar(value=o.aspect if o.aspect in ASPECTS else "Як в оригіналі")
        self.wm_enabled_var = ctk.BooleanVar(value=o.wm_enabled)
        self.wm_type_var = ctk.StringVar(value=o.wm_type if o.wm_type in WM_TYPES else "Логотип")
        self.wm_logo_var = ctk.StringVar(value=o.wm_logo)
        self.wm_text_var = ctk.StringVar(value=o.wm_text)
        self.wm_pos_var = ctk.StringVar(value=o.wm_pos if o.wm_pos in WM_POSITIONS else "Правий нижній")
        self.wm_opacity_var = ctk.DoubleVar(value=o.wm_opacity)
        self.wm_size_var = ctk.DoubleVar(value=o.wm_size)
        self.hook_enabled_var = ctk.BooleanVar(value=o.hook_enabled)
        self.hook_text_init = o.hook_text
        self.hook_secs_var = ctk.StringVar(value=f"{o.hook_seconds:g}")
        self.font_names = list(available_fonts()) or ["(шрифти не знайдено)"]
        self.hook_font_var = ctk.StringVar(value=o.hook_font if (o.hook_font in self.font_names
                                                                 or os.path.isfile(o.hook_font))
                                           else self.font_names[0])
        self.hook_pos_var = ctk.StringVar(value=o.hook_pos if o.hook_pos in HOOK_POSITIONS else "Зверху")
        self.hook_style_var = ctk.StringVar(value=o.hook_style if o.hook_style in HOOK_STYLES else "Темна плашка")
        self.hook_size_var = ctk.DoubleVar(value=o.hook_size)
        self.thumbs_var = ctk.BooleanVar(value=o.thumbnails)
        # покращення
        self.detail_var = ctk.DoubleVar(value=o.detail)
        self.denoise_var = ctk.BooleanVar(value=o.denoise)
        self.deshake_var = ctk.BooleanVar(value=o.deshake)
        self.loudnorm_var = ctk.BooleanVar(value=o.loudnorm)
        self.lut_enabled_var = ctk.BooleanVar(value=o.lut_enabled)
        self.lut_file_var = ctk.StringVar(value=o.lut_file)
        self.preset_var = ctk.StringVar(value="— пресет —")

        self._build_ui()
        if self.dnd_ok:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:  # noqa: BLE001
                self.dnd_ok = False
        for p in s.get("sources", []):
            if os.path.isfile(p):
                self._add_source(p)
        self.after(100, self._poll_events)
        if not getattr(sys, "frozen", False):
            self.after(2500, lambda: self._check_updates(manual=False))
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- налаштування ------------------------------------------------------
    def _load_settings(self) -> dict:
        data: dict = {}
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        names = {f.name for f in fields(Options)}
        opt_data = {k: v for k, v in data.get("options", {}).items() if k in names}
        try:
            data["options"] = Options(**opt_data)
        except TypeError:
            data["options"] = Options()
        return data

    def _save_settings(self):
        try:
            data = {"options": asdict(self._collect_options()),
                    "out_dir": self.out_var.get(), "count": self.count_var.get(),
                    "ffmpeg": self.ffmpeg_var.get(), "sources": self.sources,
                    "presets": self.presets, "appearance": self._appearance}
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        except OSError:
            pass

    def _collect_options(self) -> Options:
        b = {k: v.get() for k, v in self.bool_vars.items()}
        return Options(
            **b,
            zoom_mode=self.zoom_mode_var.get(),
            border_color_mode=self.border_mode_var.get(),
            border_color=self.border_color,
            styles=[n for n, v in self.style_vars.items() if v.get()],
            style_strength=round(float(self.strength_var.get()), 2),
            encoder_label=self.encoder_var.get(),
            crf=int(self.crf_var.get()),
            x264_preset=self.x264_var.get(),
            parallel=int(self.parallel_var.get()),
            sharpen=self.sharpen_var.get(),
            resolution=self.res_var.get(),
            fps=self.fps_var.get(),
            bitrate_cap=self.cap_var.get(),
            trim_enabled=self.trim_var.get(),
            trim_start=self._num(self.trim_start_var.get(), 0.0, 0.0, 600.0),
            trim_end=self._num(self.trim_end_var.get(), 0.0, 0.0, 600.0),
            bitrate_mode=self.br_mode_var.get(),
            video_mbps=self._num(self.mbps_var.get(), 8.0, 0.5, 100.0),
            audio_bitrate=self.abr_var.get(),
            effect_chance=round(float(self.chance_var.get()), 2),
            **self._ranges(),
            aspect=self.aspect_var.get(),
            wm_enabled=self.wm_enabled_var.get(),
            wm_type=self.wm_type_var.get(),
            wm_logo=self.wm_logo_var.get().strip(),
            wm_text=self.wm_text_var.get(),
            wm_pos=self.wm_pos_var.get(),
            wm_opacity=round(float(self.wm_opacity_var.get()), 2),
            wm_size=round(float(self.wm_size_var.get()), 3),
            hook_enabled=self.hook_enabled_var.get(),
            hook_text=self.hook_box.get("1.0", "end").strip() if hasattr(self, "hook_box") else self.hook_text_init,
            hook_seconds=self._float(self.hook_secs_var.get(), 3.0),
            hook_font=self.hook_font_var.get(),
            hook_pos=self.hook_pos_var.get(),
            hook_style=self.hook_style_var.get(),
            hook_size=round(float(self.hook_size_var.get()), 3),
            thumbnails=self.thumbs_var.get(),
            detail=round(float(self.detail_var.get()), 2),
            denoise=self.denoise_var.get(),
            deshake=self.deshake_var.get(),
            loudnorm=self.loudnorm_var.get(),
            lut_enabled=self.lut_enabled_var.get(),
            lut_file=self.lut_file_var.get().strip(),
        )

    @staticmethod
    def _num(v, default: float, lo: float, hi: float) -> float:
        try:
            return round(max(lo, min(hi, float(str(v).replace(",", ".")))), 3)
        except ValueError:
            return default

    def _ranges(self) -> dict:
        d = Options()
        out = {}
        for k in RANGE_KEYS:
            try:
                v = float(str(self.range_vars[k].get()).replace(",", ".").replace("+", ""))
            except ValueError:
                v = getattr(d, k)
            out[k] = int(round(v)) if k.startswith("grain") else round(v, 2)
        return out

    @staticmethod
    def _float(v, default: float) -> float:
        try:
            return max(0.5, min(60.0, float(str(v).replace(",", "."))))
        except ValueError:
            return default

    def _apply_options(self, o: Options):
        for k, var in self.bool_vars.items():
            var.set(getattr(o, k))
        self.zoom_mode_var.set(o.zoom_mode)
        for k in RANGE_KEYS:
            self.range_vars[k].set(f"{getattr(o, k):g}")
        self.chance_var.set(o.effect_chance)
        self.chance_label.configure(text=f"{o.effect_chance:.0%}")
        self.border_mode_var.set(o.border_color_mode)
        self.border_color = o.border_color
        try:
            self.color_btn.configure(fg_color="#" + o.border_color[2:], hover_color="#" + o.border_color[2:],
                                     text_color=self._contrast_text(o.border_color))
        except Exception:  # noqa: BLE001
            pass
        for n, v in self.style_vars.items():
            v.set(n in o.styles)
        self.strength_var.set(o.style_strength)
        self.strength_label.configure(text=f"{o.style_strength:.0%}")
        if o.encoder_label in ENCODERS:
            self.encoder_var.set(o.encoder_label)
        self.crf_var.set(o.crf)
        self.crf_label.configure(text=str(o.crf))
        self.x264_var.set(o.x264_preset)
        self.parallel_var.set(o.parallel)
        self.par_label.configure(text=str(o.parallel))
        self.sharpen_var.set(o.sharpen)
        self.cap_var.set(o.bitrate_cap)
        self.trim_var.set(o.trim_enabled)
        self.trim_start_var.set(f"{o.trim_start:g}")
        self.trim_end_var.set(f"{o.trim_end:g}")
        self.br_mode_var.set(o.bitrate_mode)
        self.mbps_var.set(f"{o.video_mbps:g}")
        self.abr_var.set(o.audio_bitrate)
        self.res_var.set(o.resolution)
        self.fps_var.set(o.fps)
        self.aspect_var.set(o.aspect)
        self.wm_enabled_var.set(o.wm_enabled)
        self.wm_type_var.set(o.wm_type)
        self.wm_logo_var.set(o.wm_logo)
        self.wm_text_var.set(o.wm_text)
        self.wm_pos_var.set(o.wm_pos)
        self.wm_opacity_var.set(o.wm_opacity)
        self.wm_size_var.set(o.wm_size)
        self.hook_enabled_var.set(o.hook_enabled)
        self.hook_box.delete("1.0", "end")
        self.hook_box.insert("1.0", o.hook_text)
        self.hook_secs_var.set(f"{o.hook_seconds:g}")
        self.hook_font_var.set(o.hook_font)
        self.hook_pos_var.set(o.hook_pos)
        self.hook_style_var.set(o.hook_style)
        self.hook_size_var.set(o.hook_size)
        self.thumbs_var.set(o.thumbnails)
        self.detail_var.set(o.detail)
        self.denoise_var.set(o.denoise)
        self.deshake_var.set(o.deshake)
        self.loudnorm_var.set(o.loudnorm)
        self.lut_enabled_var.set(o.lut_enabled)
        self.lut_file_var.set(o.lut_file)
        self._refresh_labels()

    def _refresh_labels(self):
        self.wm_op_label.configure(text=f"{self.wm_opacity_var.get():.0%}")
        self.wm_size_label.configure(text=f"{self.wm_size_var.get():.0%}")
        self.hook_size_label.configure(text=f"{self.hook_size_var.get() / 0.07:.0%}")
        d = self.detail_var.get()
        self.detail_label.configure(text="вимк." if d <= 0 else f"{d:.0%}")

    # --- пресети -----------------------------------------------------------
    def _preset_names(self) -> list[str]:
        return list(self.presets) or ["— немає пресетів —"]

    def _load_preset(self, name: str):
        data = self.presets.get(name)
        if not data:
            return
        names = {f.name for f in fields(Options)}
        try:
            o = Options(**{k: v for k, v in data.items() if k in names})
        except TypeError:
            return
        self._apply_options(o)
        self.status.configure(text=f"Завантажено пресет «{name}»")

    def _save_preset(self):
        dlg = ctk.CTkInputDialog(text="Назва пресету:", title="Зберегти пресет")
        name = (dlg.get_input() or "").strip()
        if not name:
            return
        self.presets[name] = asdict(self._collect_options())
        self.preset_menu.configure(values=self._preset_names())
        self.preset_var.set(name)
        self._save_settings()
        self.status.configure(text=f"Пресет «{name}» збережено")

    def _delete_preset(self):
        name = self.preset_var.get()
        if name in self.presets and messagebox.askyesno(APP_TITLE, f"Видалити пресет «{name}»?"):
            del self.presets[name]
            self.preset_menu.configure(values=self._preset_names())
            self.preset_var.set("— пресет —")
            self._save_settings()

    # --- перетягування файлів ---------------------------------------------
    def _on_drop(self, event):
        added = 0
        for p in self.tk.splitlist(event.data):
            if os.path.isdir(p):
                for f in sorted(Path(p).iterdir()):
                    if f.suffix.lower() in VIDEO_EXTS:
                        self._add_source(str(f))
                        added += 1
            elif p.lower().endswith(VIDEO_EXTS):
                self._add_source(p)
                added += 1
        if added and not self.out_var.get().strip():
            self.out_var.set(str(DEFAULT_OUT_DIR))
        self.status.configure(text=f"Додано відео: {added}" if added else "Це не відеофайли")

    # --- побудова UI -------------------------------------------------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))
        ctk.CTkLabel(hdr, text="🎬", font=ctk.CTkFont(size=30)).pack(side="left")
        tbox = ctk.CTkFrame(hdr, fg_color="transparent")
        tbox.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(tbox, text="Video Variator", font=ctk.CTkFont(size=24, weight="bold"),
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(tbox, text="Пакетні варіації відео: стилі, оформлення, хуки, формати",
                     text_color=HINT, font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
        ctk.CTkLabel(hdr, text=f" v{APP_VERSION} ", fg_color=ACCENT, corner_radius=8, text_color="white",
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left", padx=12, pady=(0, 18))
        self.theme_btn = ctk.CTkButton(hdr, text="", width=150, height=34, command=self._toggle_theme,
                                       fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT)
        self.theme_btn.pack(side="right")
        self._update_theme_btn()
        self.update_btn = ctk.CTkButton(hdr, text="⟳ Оновлення", width=130, height=34,
                                        command=lambda: self._check_updates(manual=True),
                                        fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT)
        self.update_btn.pack(side="right", padx=8)

        pb = ctk.CTkFrame(self, fg_color="transparent")
        pb.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 0))
        ctk.CTkLabel(pb, text="Пресет:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        self.preset_menu = ctk.CTkOptionMenu(pb, values=self._preset_names(), variable=self.preset_var,
                                             width=220, command=self._load_preset)
        self.preset_menu.pack(side="left", padx=8)
        ctk.CTkButton(pb, text="💾 Зберегти як…", width=130, command=self._save_preset).pack(side="left", padx=4)
        ctk.CTkButton(pb, text="🗑", width=36, fg_color=SECONDARY, hover_color=DANGER, text_color=SECONDARY_TEXT,
                      command=self._delete_preset).pack(side="left", padx=4)
        ctk.CTkLabel(pb, text=("  Можна перетягувати відео мишкою у вікно" if self.dnd_ok
                               else "  (перетягування файлів недоступне: pip install tkinterdnd2)"),
                     text_color=HINT).pack(side="left", padx=10)

        tabs = ctk.CTkTabview(self, height=440, corner_radius=14,
                              segmented_button_selected_color=SEG_SELECTED,
                              segmented_button_selected_hover_color=SEG_SELECTED_HOVER,
                              segmented_button_unselected_color=SECONDARY,
                              segmented_button_unselected_hover_color=SECONDARY_HOVER,
                              segmented_button_fg_color=SECONDARY, text_color=SEG_TEXT)
        tabs.grid(row=2, column=0, sticky="nsew", padx=14, pady=(4, 0))
        for name in ("Файли", "Ефекти", "Стилі", "Оформлення", "Покращення", "Експорт"):
            tabs.add(name)
        self._tab_files(tabs.tab("Файли"))
        self._tab_effects(tabs.tab("Ефекти"))
        self._tab_styles(tabs.tab("Стилі"))
        self._tab_design(tabs.tab("Оформлення"))
        self._tab_enhance(tabs.tab("Покращення"))
        self._tab_export(tabs.tab("Експорт"))

        ctl = ctk.CTkFrame(self, corner_radius=14)
        ctl.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctl.grid_columnconfigure(0, weight=1)
        self.progress = ctk.CTkProgressBar(ctl, height=12, corner_radius=6)
        self.progress.set(0)
        self.progress.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        self.status = ctk.CTkLabel(ctl, text="Додайте відео й натисніть «Старт»", anchor="w",
                                   text_color=HINT)
        self.status.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        btns = ctk.CTkFrame(ctl, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, padx=10, pady=8)
        self.preview_btn = ctk.CTkButton(btns, text="👁 Превʼю", width=110, height=40, command=self._preview,
                                         fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT)
        self.preview_btn.pack(side="left", padx=3)
        self.start_btn = ctk.CTkButton(btns, text="▶  Старт", width=140, height=40, command=self._start,
                                       font=ctk.CTkFont(size=15, weight="bold"))
        self.start_btn.pack(side="left", padx=3)
        self.stop_btn = ctk.CTkButton(btns, text="■ Стоп", width=90, height=40, state="disabled",
                                      fg_color=DANGER, hover_color=DANGER_HOVER, command=self._stop)
        self.stop_btn.pack(side="left", padx=3)
        self.open_btn = ctk.CTkButton(btns, text="📂", width=44, height=40, command=self._open_out,
                                      fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT)
        self.open_btn.pack(side="left", padx=3)

        self.log = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="Consolas", size=12),
                                  corner_radius=12, border_width=1)
        self.log.grid(row=4, column=0, sticky="nsew", padx=14, pady=(10, 14))
        for tag, col in (("ok", "#3DDC97"), ("err", "#FF6B6B"), ("warn", "#FFC857"), ("head", "#A996FF")):
            try:
                self.log.tag_config(tag, foreground=col)
            except Exception:  # noqa: BLE001
                pass
        self.log.configure(state="disabled")

    def _log_exception(self, exc, val, tb):
        import traceback
        try:
            with open(APP_DIR / "error.log", "a", encoding="utf-8") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + "".join(traceback.format_exception(exc, val, tb)) + "\n")
        except OSError:
            pass
        try:
            self.status.configure(text=f"Помилка інтерфейсу: {val} (деталі в error.log)")
        except Exception:  # noqa: BLE001
            pass

    # --- оновлення --------------------------------------------------------
    def _check_updates(self, manual: bool):
        if getattr(sys, "frozen", False):
            if manual:
                messagebox.showinfo(APP_TITLE, "Версія .exe не оновлюється автоматично.\n"
                                               "Використовуйте версію із «Запуск.bat».")
            return
        self.update_btn.configure(state="disabled", text="Перевіряю…")

        def job():
            self.events.put(("update_info", {"info": check_update(), "manual": manual}))
        threading.Thread(target=job, daemon=True).start()

    def _on_update_info(self, info, manual: bool):
        self.update_btn.configure(state="normal", text="⟳ Оновлення")
        if not info:
            if manual:
                messagebox.showinfo(APP_TITLE, f"У вас остання версія ({APP_VERSION}).")
            return
        notes = str(info.get("notes", "")).strip()
        msg = f"Є нова версія {info.get('version')} (у вас {APP_VERSION})."
        if notes:
            msg += "\n\nЩо нового:\n" + notes
        msg += "\n\nОновити зараз? Програма перезапуститься."
        if not messagebox.askyesno(APP_TITLE, msg):
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "Дочекайтеся завершення обробки й спробуйте ще раз.")
            return
        self.update_btn.configure(state="disabled", text="Завантажую…")

        def job():
            try:
                done = install_update(info)
                self.events.put(("update_done", {"files": done}))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("update_failed", {"message": str(exc)}))
        threading.Thread(target=job, daemon=True).start()

    def _restart(self):
        self._save_settings()
        script = str(APP_DIR / "video_variator.py")
        exe = sys.executable
        if sys.platform == "win32" and exe.lower().endswith("python.exe"):
            exe = exe[:-10] + "pythonw.exe"
        try:
            subprocess.Popen([exe, script], cwd=str(APP_DIR), creationflags=_NO_WINDOW)
        except OSError:
            subprocess.Popen([sys.executable, script], cwd=str(APP_DIR))
        self.destroy()

    def _update_theme_btn(self):
        self.theme_btn.configure(text="☀  Світла тема" if self._appearance == "dark" else "🌙  Темна тема")

    def _toggle_theme(self):
        self._appearance = "light" if self._appearance == "dark" else "dark"
        ctk.set_appearance_mode(self._appearance)
        self._update_theme_btn()
        self._save_settings()

    def _tab_files(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(top, text="Вихідні відео", font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(side="left")
        ctk.CTkButton(top, text="Очистити", width=90, fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT,
                      command=self._clear_sources).pack(side="right", padx=4)
        ctk.CTkButton(top, text="+ Додати відео…", width=140, command=self._pick_sources
                      ).pack(side="right", padx=4)
        self.src_list = ctk.CTkScrollableFrame(tab, height=150)
        self.src_list.grid(row=1, column=0, sticky="nsew")
        self.src_list.grid_columnconfigure(0, weight=1)
        self.src_empty = ctk.CTkLabel(self.src_list, text="Список порожній — додайте одне або кілька відео",
                                      text_color=HINT)
        self.src_empty.grid(row=0, column=0, pady=20)

        form = ctk.CTkFrame(tab, fg_color="transparent")
        form.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        form.grid_columnconfigure(1, weight=1)
        self._path_row(form, 0, "Папка збереження:", self.out_var, self._pick_out)
        ctk.CTkButton(form, text="⟲", width=32, fg_color=SECONDARY, hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT,
                      command=lambda: self.out_var.set(str(DEFAULT_OUT_DIR))).grid(row=0, column=3, padx=(6, 0))
        self._path_row(form, 1, "FFmpeg:", self.ffmpeg_var, self._pick_ffmpeg)
        row = ctk.CTkFrame(form, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ctk.CTkLabel(row, text="Варіацій на кожне відео (N):").pack(side="left")
        ctk.CTkEntry(row, textvariable=self.count_var, width=70).pack(side="left", padx=(8, 24))
        ctk.CTkLabel(row, text="Seed:").pack(side="left")
        ctk.CTkEntry(row, textvariable=self.seed_var, width=120,
                     placeholder_text="випадковий").pack(side="left", padx=6)
        ctk.CTkButton(row, text="🎲", width=36, command=self._new_seed).pack(side="left")
        ctk.CTkLabel(row, text="  той самий seed = ті самі варіації", text_color=HINT
                     ).pack(side="left")

    @staticmethod
    def _scrollable(tab):
        sf = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        sf.pack(fill="both", expand=True)
        return sf

    def _tab_effects(self, tab):
        tab = self._scrollable(tab)
        tab.grid_columnconfigure((0, 1), weight=1)
        items = [
            ("strip_metadata", "Очищення метаданих (-map_metadata -1)"),
            ("color", "Колір: яскравість / контраст / насиченість / відтінок"),
            ("zoom_border", "Мікрозум-кроп або тонка рамка"),
            ("grain", "Плівкове зерно"),
            ("tempo", "Темп відео + аудіо"),
            ("hflip", "Горизонтальне віддзеркалення (~50% варіацій)"),
        ]
        for n, (key, text) in enumerate(items):
            ctk.CTkCheckBox(tab, text=text, variable=self.bool_vars[key]).grid(
                row=n // 2, column=n % 2, sticky="w", padx=12, pady=8)

        rc = ctk.CTkFrame(tab, fg_color="transparent")
        rc.grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))
        ctk.CTkSwitch(rc, text="Випадкова комбінація ефектів, шанс кожного:",
                      variable=self.bool_vars["randomize_set"]).pack(side="left")
        ctk.CTkSlider(rc, from_=0.1, to=1.0, number_of_steps=18, variable=self.chance_var, width=160,
                      command=lambda v: self.chance_label.configure(text=f"{v:.0%}")).pack(side="left", padx=8)
        self.chance_label = ctk.CTkLabel(rc, text=f"{self.chance_var.get():.0%}", width=44)
        self.chance_label.pack(side="left")

        zb = ctk.CTkFrame(tab)
        zb.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        ctk.CTkLabel(zb, text="Зум / рамка:").pack(side="left", padx=(12, 6), pady=10)
        ctk.CTkOptionMenu(zb, values=ZOOM_MODES, variable=self.zoom_mode_var, width=140
                          ).pack(side="left", padx=(0, 24))
        ctk.CTkLabel(zb, text="Колір рамки:").pack(side="left", padx=(0, 6))
        ctk.CTkOptionMenu(zb, values=BORDER_COLOR_MODES, variable=self.border_mode_var, width=120
                          ).pack(side="left")
        self.color_btn = ctk.CTkButton(zb, text="Обрати колір", width=120, command=self._pick_color,
                                       fg_color="#" + self.border_color[2:],
                                       text_color=self._contrast_text(self.border_color))
        self.color_btn.pack(side="left", padx=10)

        rg = ctk.CTkFrame(tab)
        rg.grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        ctk.CTkLabel(rg, text="Діапазони (кожна варіація отримує випадкове значення в цих межах)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=6, sticky="w",
                                                           padx=10, pady=(8, 2))
        rows = [
            ("Контраст / насиченість, ±%", "color_min", "color_max"),
            ("Яскравість, ±%", "bright_min", "bright_max"),
            ("Мікрозум / кроп, %", "zoom_min", "zoom_max"),
            ("Зерно (сила 1–25)", "grain_min", "grain_max"),
            ("Темп, % (−10…+10)", "tempo_min", "tempo_max"),
            ("Зсув відтінку, до ±°", None, "hue_max"),
        ]
        for i, (label, k_from, k_to) in enumerate(rows):
            r, c = 1 + i // 2, (i % 2) * 3
            ctk.CTkLabel(rg, text=label, anchor="w").grid(row=r, column=c, sticky="w", padx=(10, 6), pady=4)
            box = ctk.CTkFrame(rg, fg_color="transparent")
            box.grid(row=r, column=c + 1, sticky="w", padx=(0, 18))
            if k_from:
                ctk.CTkLabel(box, text="від").pack(side="left")
                ctk.CTkEntry(box, textvariable=self.range_vars[k_from], width=52).pack(side="left", padx=4)
                ctk.CTkLabel(box, text="до").pack(side="left")
            ctk.CTkEntry(box, textvariable=self.range_vars[k_to], width=52).pack(side="left", padx=4)
        ctk.CTkLabel(rg, text="Відтінок 0 = вимкнено. Невеликі значення дають помітно різні, але природні варіації.",
                     text_color=HINT).grid(row=4, column=0, columnspan=6, sticky="w", padx=10, pady=(2, 8))

    def _tab_styles(self, tab):
        tab.grid_columnconfigure((0, 1, 2, 3), weight=1)
        ctk.CTkSwitch(tab, text="Використовувати стильові пресети",
                      variable=self.bool_vars["use_styles"],
                      font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(6, 4))
        ctk.CTkLabel(tab, text="Обрані стилі розподіляються між варіаціями порівну — "
                               "отримуєте готові групи для A/B-тесту. Легкі ефекти з вкладки "
                               "«Ефекти» додаються зверху, щоб кожен файл був неповторним.",
                     text_color=HINT, wraplength=780, justify="left").grid(
            row=1, column=0, columnspan=4, sticky="w", padx=12, pady=(0, 10))
        for n, name in enumerate(STYLE_PRESETS):
            ctk.CTkCheckBox(tab, text=name, variable=self.style_vars[name]).grid(
                row=2 + n // 4, column=n % 4, sticky="w", padx=12, pady=8)
        sf = ctk.CTkFrame(tab, fg_color="transparent")
        sf.grid(row=5, column=0, columnspan=4, sticky="w", padx=12, pady=(16, 0))
        ctk.CTkLabel(sf, text="Сила стилю:").pack(side="left")
        self.strength_label = ctk.CTkLabel(sf, text=f"{self.strength_var.get():.0%}", width=44)
        ctk.CTkSlider(sf, from_=0.2, to=1.0, number_of_steps=16, variable=self.strength_var,
                      width=260, command=lambda v: self.strength_label.configure(text=f"{v:.0%}")
                      ).pack(side="left", padx=8)
        self.strength_label.pack(side="left")
        ctk.CTkLabel(sf, text="  Порада: натисніть «👁 Превʼю», щоб побачити стилі до рендеру",
                     text_color=HINT).pack(side="left")

    def _tab_export(self, tab):
        tab = self._scrollable(tab)
        tab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tab, text="Кодер:").grid(row=0, column=0, sticky="w", padx=12, pady=10)
        ef = ctk.CTkFrame(tab, fg_color="transparent")
        ef.grid(row=0, column=1, sticky="w")
        self.encoder_menu = ctk.CTkOptionMenu(ef, values=list(ENCODERS), variable=self.encoder_var,
                                              width=190)
        self.encoder_menu.pack(side="left")
        self.detect_btn = ctk.CTkButton(ef, text="Визначити відеокарту", width=170,
                                        command=self._detect, fg_color=SECONDARY,
                                        hover_color=SECONDARY_HOVER, text_color=SECONDARY_TEXT)
        self.detect_btn.pack(side="left", padx=10)
        self.detect_label = ctk.CTkLabel(ef, text="", text_color=HINT)
        self.detect_label.pack(side="left")

        ctk.CTkLabel(tab, text="Якість (CRF/CQ):").grid(row=1, column=0, sticky="w", padx=12, pady=10)
        qf = ctk.CTkFrame(tab, fg_color="transparent")
        qf.grid(row=1, column=1, sticky="w")
        self.crf_label = ctk.CTkLabel(qf, text=str(self.crf_var.get()), width=30)
        ctk.CTkSlider(qf, from_=14, to=30, number_of_steps=16, variable=self.crf_var, width=220,
                      command=lambda v: self.crf_label.configure(text=str(int(v)))
                      ).pack(side="left")
        self.crf_label.pack(side="left", padx=6)
        ctk.CTkLabel(qf, text="менше = краща якість і більший файл (18–22 — оптимально)",
                     text_color=HINT).pack(side="left", padx=8)

        ctk.CTkLabel(tab, text="Пресет x264 (CPU):").grid(row=2, column=0, sticky="w", padx=12, pady=10)
        ctk.CTkOptionMenu(tab, values=X264_PRESETS, variable=self.x264_var, width=140
                          ).grid(row=2, column=1, sticky="w")

        ctk.CTkLabel(tab, text="Паралельно файлів:").grid(row=3, column=0, sticky="w", padx=12, pady=10)
        pf = ctk.CTkFrame(tab, fg_color="transparent")
        pf.grid(row=3, column=1, sticky="w")
        self.par_label = ctk.CTkLabel(pf, text=str(self.parallel_var.get()), width=30)
        ctk.CTkSlider(pf, from_=1, to=6, number_of_steps=5, variable=self.parallel_var, width=220,
                      command=lambda v: self.par_label.configure(text=str(int(v)))
                      ).pack(side="left")
        self.par_label.pack(side="left", padx=6)
        ctk.CTkLabel(pf, text=f"ядер процесора: {os.cpu_count() or '?'} • для CPU раджу 2–3",
                     text_color=HINT).pack(side="left", padx=8)

        ctk.CTkLabel(tab, text="Роздільність:").grid(row=4, column=0, sticky="w", padx=12, pady=10)
        rf = ctk.CTkFrame(tab, fg_color="transparent")
        rf.grid(row=4, column=1, sticky="w")
        ctk.CTkOptionMenu(rf, values=list(RES_OPTIONS), variable=self.res_var, width=160).pack(side="left")
        ctk.CTkLabel(rf, text="Частота кадрів:").pack(side="left", padx=(24, 8))
        ctk.CTkOptionMenu(rf, values=FPS_OPTIONS, variable=self.fps_var, width=150).pack(side="left")

        ctk.CTkCheckBox(tab, text="Легке підвищення чіткості (компенсує мʼякість після зуму/масштабування)",
                        variable=self.sharpen_var).grid(row=5, column=0, columnspan=2, sticky="w",
                                                        padx=12, pady=8)
        ctk.CTkCheckBox(tab, text="Обмежити бітрейт — файли не роздуваються від зерна (у режимі CRF)",
                        variable=self.cap_var).grid(row=6, column=0, columnspan=2, sticky="w",
                                                    padx=12, pady=8)

        ctk.CTkLabel(tab, text="Бітрейт відео:").grid(row=7, column=0, sticky="w", padx=12, pady=10)
        bf = ctk.CTkFrame(tab, fg_color="transparent")
        bf.grid(row=7, column=1, sticky="w")
        ctk.CTkOptionMenu(bf, values=BITRATE_MODES, variable=self.br_mode_var, width=190).pack(side="left")
        ctk.CTkEntry(bf, textvariable=self.mbps_var, width=60).pack(side="left", padx=(10, 4))
        ctk.CTkLabel(bf, text="Мбіт/с   (для 1080p зазвичай 6–12)", text_color=HINT).pack(side="left")
        ctk.CTkLabel(tab, text="Бітрейт звуку:").grid(row=8, column=0, sticky="w", padx=12, pady=10)
        ctk.CTkOptionMenu(tab, values=AUDIO_BITRATES, variable=self.abr_var, width=110).grid(
            row=8, column=1, sticky="w")

        tf = ctk.CTkFrame(tab)
        tf.grid(row=9, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 6))
        ctk.CTkSwitch(tf, text="Обрізка", variable=self.trim_var,
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=10, pady=10)
        ctk.CTkLabel(tf, text="прибрати з початку, с:").pack(side="left", padx=(10, 4))
        ctk.CTkEntry(tf, textvariable=self.trim_start_var, width=60).pack(side="left")
        ctk.CTkLabel(tf, text="з кінця, с:").pack(side="left", padx=(14, 4))
        ctk.CTkEntry(tf, textvariable=self.trim_end_var, width=60).pack(side="left")
        ctk.CTkLabel(tf, text="  однаково для всіх файлів, напр. 0.25", text_color=HINT).pack(side="left")

    def _tab_design(self, tab):
        tab = self._scrollable(tab)
        tab.grid_columnconfigure(1, weight=1)
        r = 0
        ctk.CTkLabel(tab, text="Формат відео:").grid(row=r, column=0, sticky="w", padx=12, pady=8)
        af = ctk.CTkFrame(tab, fg_color="transparent")
        af.grid(row=r, column=1, sticky="w")
        ctk.CTkOptionMenu(af, values=list(ASPECTS), variable=self.aspect_var, width=210).pack(side="left")
        ctk.CTkLabel(af, text="  інший формат → відео по центру, по краях розмитий фон",
                     text_color=HINT).pack(side="left")

        r += 1
        wm = ctk.CTkFrame(tab)
        wm.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))
        wm.grid_columnconfigure(2, weight=1)
        ctk.CTkSwitch(wm, text="Водяний знак", variable=self.wm_enabled_var,
                      font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=8)
        ctk.CTkSegmentedButton(wm, values=WM_TYPES, variable=self.wm_type_var).grid(
            row=0, column=1, sticky="w", padx=8)
        ctk.CTkOptionMenu(wm, values=WM_POSITIONS, variable=self.wm_pos_var, width=160).grid(
            row=0, column=3, sticky="e", padx=10)
        ctk.CTkLabel(wm, text="Логотип (PNG):").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        ctk.CTkEntry(wm, textvariable=self.wm_logo_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        ctk.CTkButton(wm, text="Огляд…", width=80, command=self._pick_logo).grid(row=1, column=3, padx=10, sticky="e")
        ctk.CTkLabel(wm, text="Або текст:").grid(row=2, column=0, sticky="w", padx=10, pady=4)
        ctk.CTkEntry(wm, textvariable=self.wm_text_var, placeholder_text="@my_account").grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=(0, 10), pady=4)
        sl = ctk.CTkFrame(wm, fg_color="transparent")
        sl.grid(row=3, column=0, columnspan=4, sticky="w", padx=10, pady=(4, 10))
        ctk.CTkLabel(sl, text="Прозорість:").pack(side="left")
        ctk.CTkSlider(sl, from_=0.1, to=1.0, number_of_steps=18, variable=self.wm_opacity_var, width=150,
                      command=lambda v: self._refresh_labels()).pack(side="left", padx=6)
        self.wm_op_label = ctk.CTkLabel(sl, text="", width=40)
        self.wm_op_label.pack(side="left")
        ctk.CTkLabel(sl, text="   Розмір:").pack(side="left")
        ctk.CTkSlider(sl, from_=0.05, to=0.4, number_of_steps=35, variable=self.wm_size_var, width=150,
                      command=lambda v: self._refresh_labels()).pack(side="left", padx=6)
        self.wm_size_label = ctk.CTkLabel(sl, text="", width=40)
        self.wm_size_label.pack(side="left")

        r += 1
        hk = ctk.CTkFrame(tab)
        hk.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        hk.grid_columnconfigure(1, weight=1)
        ctk.CTkSwitch(hk, text="Текст-хук на початку", variable=self.hook_enabled_var,
                      font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=8)
        hs = ctk.CTkFrame(hk, fg_color="transparent")
        hs.grid(row=0, column=1, sticky="e", padx=10)
        ctk.CTkLabel(hs, text="показувати, секунд:").pack(side="left")
        ctk.CTkEntry(hs, textvariable=self.hook_secs_var, width=50).pack(side="left", padx=6)
        self.hook_box = ctk.CTkTextbox(hk, height=56, wrap="word")
        self.hook_box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
        self.hook_box.insert("1.0", self.hook_text_init)
        hf = ctk.CTkFrame(hk, fg_color="transparent")
        hf.grid(row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(0, 10))
        ctk.CTkLabel(hf, text="Шрифт:").pack(side="left")
        self.font_menu = ctk.CTkOptionMenu(hf, values=self.font_names, variable=self.hook_font_var, width=170)
        self.font_menu.pack(side="left", padx=(6, 4))
        ctk.CTkButton(hf, text="…", width=30, command=self._pick_font).pack(side="left", padx=(0, 14))
        ctk.CTkOptionMenu(hf, values=HOOK_STYLES, variable=self.hook_style_var, width=180).pack(side="left")
        ctk.CTkOptionMenu(hf, values=HOOK_POSITIONS, variable=self.hook_pos_var, width=110).pack(side="left", padx=8)
        ctk.CTkLabel(hf, text="Розмір:").pack(side="left", padx=(6, 0))
        ctk.CTkSlider(hf, from_=0.035, to=0.12, number_of_steps=17, variable=self.hook_size_var, width=110,
                      command=lambda v: self._refresh_labels()).pack(side="left", padx=4)
        self.hook_size_label = ctk.CTkLabel(hf, text="", width=44)
        self.hook_size_label.pack(side="left")

        r += 1
        ctk.CTkCheckBox(tab, text="Робити обкладинку (JPG-кадр) для кожного відео",
                        variable=self.thumbs_var).grid(row=r, column=0, columnspan=2, sticky="w",
                                                       padx=12, pady=(8, 4))

    def _tab_enhance(self, tab):
        tab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tab, text="Деталізація:").grid(row=0, column=0, sticky="w", padx=12, pady=10)
        df = ctk.CTkFrame(tab, fg_color="transparent")
        df.grid(row=0, column=1, sticky="w")
        ctk.CTkSlider(df, from_=0, to=1, number_of_steps=20, variable=self.detail_var, width=220,
                      command=lambda v: self._refresh_labels()).pack(side="left")
        self.detail_label = ctk.CTkLabel(df, text="", width=50)
        self.detail_label.pack(side="left", padx=6)
        ctk.CTkLabel(df, text="розумне підвищення різкості дрібних деталей (CAS)",
                     text_color=HINT).pack(side="left")
        items = [
            (self.denoise_var, "Шумоподавлення — прибирає «шум» з темних кадрів і нічної зйомки"),
            (self.deshake_var, "Стабілізація — згладжує тремтіння відео з рук (обробка повільніша)"),
            (self.loudnorm_var, "Нормалізація гучності — усі ролики звучать однаково голосно (−14 LUFS)"),
        ]
        for n, (var, text) in enumerate(items, start=1):
            ctk.CTkCheckBox(tab, text=text, variable=var).grid(row=n, column=0, columnspan=2, sticky="w",
                                                              padx=12, pady=8)
        lf = ctk.CTkFrame(tab)
        lf.grid(row=4, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        lf.grid_columnconfigure(1, weight=1)
        ctk.CTkSwitch(lf, text="LUT (кольоровий фільтр .cube)", variable=self.lut_enabled_var).grid(
            row=0, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkEntry(lf, textvariable=self.lut_file_var, placeholder_text="шлях до файлу .cube").grid(
            row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(lf, text="Огляд…", width=80, command=self._pick_lut).grid(row=0, column=2, padx=10)
        ctk.CTkLabel(tab, text="Порада: перевіряйте результат кнопкою «👁 Превʼю» перед рендером.",
                     text_color=HINT).grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=8)
        self._refresh_labels()

    def _pick_logo(self):
        p = filedialog.askopenfilename(title="Логотип", filetypes=[("Зображення", "*.png *.jpg *.jpeg *.webp"),
                                                                   ("Усі файли", "*.*")])
        if p:
            self.wm_logo_var.set(p)
            self.wm_type_var.set("Логотип")
            self.wm_enabled_var.set(True)

    def _pick_font(self):
        p = filedialog.askopenfilename(title="Шрифт", filetypes=[("Шрифти", "*.ttf *.otf"), ("Усі файли", "*.*")])
        if p:
            name = Path(p).stem
            try:  # копіюємо в папку fonts поруч із програмою — шрифт буде у списку й наступного разу
                (APP_DIR / "fonts").mkdir(exist_ok=True)
                dst = APP_DIR / "fonts" / Path(p).name
                if not dst.exists():
                    shutil.copyfile(p, dst)
                p = str(dst)
            except OSError:
                pass
            available_fonts()[name] = p
            if name not in self.font_names:
                self.font_names = [n for n in self.font_names if not n.startswith("(")] + [name]
                self.font_menu.configure(values=self.font_names)
            self.hook_font_var.set(name)

    def _pick_lut(self):
        p = filedialog.askopenfilename(title="LUT-файл", filetypes=[("LUT", "*.cube"), ("Усі файли", "*.*")])
        if p:
            self.lut_file_var.set(p)
            self.lut_enabled_var.set(True)

    def _path_row(self, parent, row, label, var, cmd):
        ctk.CTkLabel(parent, text=label, width=140, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        ctk.CTkEntry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
        ctk.CTkButton(parent, text="Огляд…", width=80, command=cmd).grid(row=row, column=2, padx=(8, 0), pady=4)

    # --- список файлів ----------------------------------------------------
    def _add_source(self, path: str):
        if path in self.sources:
            return
        self.sources.append(path)
        self._render_sources()

    def _render_sources(self):
        for w in self.src_list.winfo_children():
            w.destroy()
        if not self.sources:
            self.src_empty = ctk.CTkLabel(self.src_list, text="Список порожній — додайте одне або кілька відео",
                                          text_color=HINT)
            self.src_empty.grid(row=0, column=0, pady=20)
            return
        for i, p in enumerate(self.sources):
            ctk.CTkLabel(self.src_list, text=f"{i + 1}. {Path(p).name}", anchor="w").grid(
                row=i, column=0, sticky="ew", padx=6, pady=2)
            ctk.CTkLabel(self.src_list, text=str(Path(p).parent), anchor="w", text_color=HINT
                         ).grid(row=i, column=1, sticky="w", padx=6)
            ctk.CTkButton(self.src_list, text="✕", width=28, height=24, fg_color="transparent",
                          hover_color="#5a2a2a", command=lambda x=p: self._remove_source(x)
                          ).grid(row=i, column=2, padx=4)

    def _remove_source(self, path):
        self.sources = [s for s in self.sources if s != path]
        self._render_sources()

    def _clear_sources(self):
        self.sources = []
        self._render_sources()

    # --- діалоги ----------------------------------------------------------
    def _pick_sources(self):
        paths = filedialog.askopenfilenames(title="Оберіть відео", filetypes=VIDEO_TYPES)
        for p in paths:
            self._add_source(p)
        if paths and not self.out_var.get():
            self.out_var.set(str(DEFAULT_OUT_DIR))

    def _pick_out(self):
        p = filedialog.askdirectory(title="Оберіть папку збереження")
        if p:
            self.out_var.set(p)

    def _pick_ffmpeg(self):
        p = filedialog.askopenfilename(title="Шлях до ffmpeg")
        if p:
            self.ffmpeg_var.set(p)

    @staticmethod
    def _contrast_text(hex0x: str) -> str:
        r, g, b = (int(hex0x[i:i + 2], 16) for i in (2, 4, 6))
        return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 140 else "#FFFFFF"

    def _pick_color(self):
        res = colorchooser.askcolor(color="#" + self.border_color[2:], title="Колір рамки")
        if res and res[1]:
            self.border_color = "0x" + res[1][1:].upper()
            self.border_mode_var.set("Свій")
            self.color_btn.configure(fg_color=res[1], hover_color=res[1],
                                     text_color=self._contrast_text(self.border_color))

    def _new_seed(self):
        self.seed_var.set(str(random.randint(1, 999_999)))

    def _open_out(self):
        p = self.out_var.get().strip() or str(DEFAULT_OUT_DIR)
        try:
            os.makedirs(p, exist_ok=True)
        except OSError:
            messagebox.showinfo(APP_TITLE, "Не вдалося відкрити папку збереження.")
            return
        if sys.platform == "win32":
            os.startfile(p)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", p])

    # --- валідація --------------------------------------------------------
    def _validate(self, need_out: bool = True) -> tuple[str, int, int] | None:
        ffmpeg = self.ffmpeg_var.get().strip() or "ffmpeg"
        if not self.sources:
            messagebox.showerror(APP_TITLE, "Додайте хоча б одне відео (вкладка «Файли»).")
            return None
        if need_out and not self.out_var.get().strip():
            messagebox.showerror(APP_TITLE, "Оберіть папку збереження.")
            return None
        try:
            count = int(self.count_var.get())
            if not 1 <= count <= 1000:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE, "N має бути цілим числом від 1 до 1000.")
            return None
        if not (shutil.which(ffmpeg) or os.path.isfile(ffmpeg)):
            messagebox.showerror(APP_TITLE, "FFmpeg не знайдено. Вкажіть шлях до ffmpeg.exe.")
            return None
        opt = self._collect_options()
        if opt.use_styles and not opt.styles:
            messagebox.showerror(APP_TITLE, "Пресети увімкнено, але жоден стиль не обрано.")
            return None
        raw = self.seed_var.get().strip()
        if not raw:
            self._new_seed()
            raw = self.seed_var.get()
        try:
            seed = int(raw)
        except ValueError:
            messagebox.showerror(APP_TITLE, "Seed має бути цілим числом.")
            return None
        return ffmpeg, count, seed

    def _set_busy(self, busy: bool):
        st = "disabled" if busy else "normal"
        self.start_btn.configure(state=st)
        self.preview_btn.configure(state=st)
        self.stop_btn.configure(state="normal" if busy and self.worker else "disabled")

    # --- дії --------------------------------------------------------------
    def _start(self):
        v = self._validate()
        if not v:
            return
        ffmpeg, count, seed = v
        self._save_settings()
        self._clear_log()
        self._had_error = False
        self.progress.set(0)
        self.status.configure(text="Аналіз відео…")
        self.worker = BatchWorker(ffmpeg, list(self.sources), self.out_var.get().strip(), count,
                                  self._collect_options(), seed, self.events)
        self._set_busy(True)
        self.worker.start()

    def _preview(self):
        v = self._validate(need_out=False)
        if not v:
            return
        ffmpeg, count, seed = v
        self.progress.set(0)
        self.status.configure(text="Готую превʼю…")
        self.preview_worker = PreviewWorker(ffmpeg, self.sources[0], count,
                                            self._collect_options(), seed, self.events)
        self._set_busy(True)
        self.preview_worker.start()

    def _stop(self):
        if self.worker:
            self.status.configure(text="Зупинка…")
            self.worker.stop()

    def _detect(self):
        ffmpeg = self.ffmpeg_var.get().strip() or "ffmpeg"
        self.detect_btn.configure(state="disabled")
        self.detect_label.configure(text="Перевіряю…")

        def job():
            found = detect_encoders(ffmpeg)
            self.events.put(("detected", {"found": found}))
        threading.Thread(target=job, daemon=True).start()

    def _show_preview(self, items: list[tuple[str, str]], total: int):
        try:
            from PIL import Image
        except ImportError:
            messagebox.showerror(APP_TITLE, "Для превʼю потрібна бібліотека Pillow:\npip install pillow")
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Превʼю — {Path(self.sources[0]).name} (seed {self.seed_var.get()})")
        win.geometry("1080x760")
        frame = ctk.CTkScrollableFrame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        cols = 3
        for c in range(cols):
            frame.grid_columnconfigure(c, weight=1)
        self._preview_images = []
        for n, (path, caption) in enumerate(items):
            img = Image.open(path)
            img.load()
            w = 330
            h = max(1, int(img.height * w / img.width))
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(w, h))
            self._preview_images.append(cimg)
            cell = ctk.CTkFrame(frame)
            cell.grid(row=n // cols, column=n % cols, padx=6, pady=6, sticky="n")
            ctk.CTkLabel(cell, image=cimg, text="").pack(padx=6, pady=(6, 2))
            ctk.CTkLabel(cell, text=caption, wraplength=w, justify="left",
                         font=ctk.CTkFont(size=11, weight="bold" if n == 0 else "normal")
                         ).pack(padx=6, pady=(0, 6), anchor="w")
        note = (f"Показано {len(items) - 1} з {total} варіацій. "
                "Натисніть «▶ Старт» з тим самим seed — отримаєте саме ці варіації.")
        ctk.CTkLabel(win, text=note, text_color=HINT).pack(pady=(0, 10))
        win.after(150, win.lift)
        win.focus()

    # --- обробка подій ----------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self._append_log(data["text"])
                elif kind == "progress":
                    self.progress.set(data["value"])
                    self.status.configure(text=data["label"])
                elif kind == "error":
                    self._had_error = True
                    self._append_log(f"ПОМИЛКА: {data['message']}")
                    messagebox.showerror(APP_TITLE, data["message"])
                elif kind == "update_info":
                    self._on_update_info(data["info"], data["manual"])
                elif kind == "update_done":
                    messagebox.showinfo(APP_TITLE, "Оновлення встановлено. Програма перезапуститься.")
                    self._restart()
                    return
                elif kind == "update_failed":
                    self.update_btn.configure(state="normal", text="⟳ Оновлення")
                    messagebox.showerror(APP_TITLE, "Не вдалося оновитися: " + data["message"] +
                                         "\nСтара версія залишилась без змін.")
                elif kind == "preview":
                    self.status.configure(text="Превʼю готове")
                    self._show_preview(data["items"], data["total"])
                elif kind == "preview_done":
                    self.preview_worker = None
                    self._set_busy(False)
                elif kind == "detected":
                    found = data["found"]
                    self.detect_btn.configure(state="normal")
                    gpu = [f for f in found if f != "CPU (libx264)"]
                    if gpu:
                        self.encoder_var.set(gpu[0])
                        self.detect_label.configure(text="Працює: " + ", ".join(gpu))
                    else:
                        self.detect_label.configure(text="Відеокарта недоступна — лишаю CPU")
                elif kind == "done":
                    self.worker = None
                    self._set_busy(False)
                    if data["stopped"]:
                        self.status.configure(text="Зупинено користувачем")
                        self._append_log("— Зупинено —")
                    elif not self._had_error:
                        self.progress.set(1)
                        failed = data.get("failed", 0)
                        msg = "Усі варіації готові ✔" if not failed else f"Готово, помилок: {failed}"
                        self.status.configure(text=msg)
                        self._append_log(f"{msg}  Файли у: {self.out_var.get()}")
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _append_log(self, text: str):
        self.log.configure(state="normal")
        t = text.lstrip()
        tag = ("ok" if t.startswith("✔") or "готові" in t else "err" if (t.startswith("✖") or "ПОМИЛКА" in t)
               else "warn" if t.startswith("⚠") else "head" if t.startswith("■") else None)
        if tag:
            self.log.insert("end", text + "\n", tag)
        else:
            self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Обробка триває. Зупинити й вийти?"):
                return
            self.worker.stop()
        self._save_settings()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
