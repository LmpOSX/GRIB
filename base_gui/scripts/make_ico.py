"""Genera los iconos .ico de Windows a partir de los PNG de resources/.

    pip install pillow
    python scripts/make_ico.py
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "resources")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

for src, dst in (("app_icon.png", "PresupuestadorPro.ico"),
                 ("doc_icon.png", "PptoDocument.ico")):
    img = Image.open(os.path.join(RES, src)).convert("RGBA")
    out = os.path.join(RES, dst)
    img.save(out, format="ICO", sizes=SIZES)
    print("ok", out)
