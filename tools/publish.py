"""Готує version.json для автооновлення.

Використання (з кореня репозиторію):
    python tools/publish.py "Що нового в цій версії"
Перед цим підніміть APP_VERSION у video_variator.py (наприклад 3.0.0 -> 3.1.0),
потім закомітьте й запуште зміни разом із version.json.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
src = (root / "video_variator.py").read_text(encoding="utf-8")
m = re.search(r'^APP_VERSION = "([^"]+)"', src, re.M)
if not m:
    sys.exit("Не знайдено APP_VERSION у video_variator.py")
compile(src, "video_variator.py", "exec")  # битий код не публікуємо
files = {}
for name in ("video_variator.py", "vv_ai.py"):
    compile((root / name).read_text(encoding="utf-8"), name, "exec")
    files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
info = {"version": m.group(1), "notes": " ".join(sys.argv[1:]).strip(), "files": files}
(root / "version.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("version.json →", info["version"])
