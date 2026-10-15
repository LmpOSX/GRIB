#!/usr/bin/env python3
"""Genera el icono de la app (PNG → ICNS) para Visor GRIB.

Dibuja, sin dependencias externas, una barba de viento sobre un fondo
azul oscuro con esquinas redondeadas; el icono de documento lleva además
una hoja blanca detrás.
"""
import math
import os
import struct
import zlib

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "resources")

BG = (18, 40, 72, 255)         # azul oscuro (fondo de mapa)
GRID = (40, 70, 110, 255)      # líneas de grilla
WHITE = (255, 255, 255, 255)
YELLOW = (255, 230, 0, 255)    # barba (30–39 kt en la escala del visor)
CYAN = (0, 229, 255, 255)
PAPER = (236, 240, 246, 255)


def create_png(size: int, document: bool = False) -> bytes:
    pixels = [[(0, 0, 0, 0)] * size for _ in range(size)]
    s = size
    r = s // 6

    def put(x, y, color):
        if 0 <= x < s and 0 <= y < s:
            pixels[y][x] = color

    def fill_rounded_rect(x1, y1, x2, y2, rad, color):
        for y in range(max(0, y1), min(s, y2)):
            for x in range(max(0, x1), min(s, x2)):
                cx = min(max(x, x1 + rad), x2 - 1 - rad)
                cy = min(max(y, y1 + rad), y2 - 1 - rad)
                if (x - cx) ** 2 + (y - cy) ** 2 <= rad ** 2:
                    put(x, y, color)

    def line(x1, y1, x2, y2, width, color):
        """Segmento grueso: pinta un disco por cada punto del trazo."""
        length = max(1, int(math.hypot(x2 - x1, y2 - y1)))
        rad = max(1, width // 2)
        # Un disco cada rad/2 píxeles alcanza para un trazo continuo y es
        # ~20× más rápido que uno por píxel (en CI tardaba minutos)
        step = max(1, rad // 2)
        for i in list(range(0, length + 1, step)) + [length]:
            t = i / length
            cx = x1 + (x2 - x1) * t
            cy = y1 + (y2 - y1) * t
            for dy in range(-rad, rad + 1):
                for dx in range(-rad, rad + 1):
                    if dx * dx + dy * dy <= rad * rad:
                        put(int(cx + dx), int(cy + dy), color)

    if document:
        # Hoja blanca con la esquina doblada detrás del mapa
        fill_rounded_rect(s // 8, s // 14, s - s // 8, s - s // 14, s // 20, PAPER)
        fill_rounded_rect(s // 5, s // 4, s - s // 5, s - s // 6, r // 2, BG)
        x0, y0, x1, y1 = s // 5, s // 4, s - s // 5, s - s // 6
    else:
        fill_rounded_rect(0, 0, s, s, r, BG)
        x0, y0, x1, y1 = 0, 0, s, s

    # Grilla tenue
    w = max(1, s // 160)
    step = (x1 - x0) // 4
    for k in range(1, 4):
        line(x0 + k * step, y0, x0 + k * step, y1, w, GRID)
        line(x0, y0 + k * step, x1, y0 + k * step, w, GRID)

    # Barba de viento (asta inclinada + bandera + dos plumas), como en el mapa
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    L = (x1 - x0) * 0.36
    ang = math.radians(-55)
    ux, uy = math.cos(ang), math.sin(ang)        # dirección del asta
    px, py = -uy, ux                              # perpendicular (lado de las plumas)
    tail = (cx - ux * L * 0.55, cy - uy * L * 0.55)
    head = (cx + ux * L * 0.75, cy + uy * L * 0.75)
    thick = max(2, s // 26)
    line(int(tail[0]), int(tail[1]), int(head[0]), int(head[1]), thick, YELLOW)
    # Bandera (50 kt): triángulo relleno en la punta
    f_len = L * 0.38
    fx, fy = head[0] - ux * f_len, head[1] - uy * f_len
    tip = (head[0] + px * f_len * 0.9, head[1] + py * f_len * 0.9)
    steps = int(f_len)
    for i in range(steps + 1):
        t = i / steps
        ax_, ay_ = head[0] - ux * f_len * t, head[1] - uy * f_len * t
        bx_, by_ = tip[0] - (tip[0] - fx) * t, tip[1] - (tip[1] - fy) * t
        line(int(ax_), int(ay_), int(bx_), int(by_), max(1, thick // 2), YELLOW)
    # Plumas (10 kt): dos trazos hacia el mismo lado
    for k in (1, 2):
        bx = head[0] - ux * (f_len + k * L * 0.22)
        by = head[1] - uy * (f_len + k * L * 0.22)
        line(int(bx), int(by), int(bx + px * L * 0.38), int(by + py * L * 0.38),
             thick, YELLOW)
    # Punto de la estación
    line(int(tail[0]), int(tail[1]), int(tail[0]), int(tail[1]), thick * 2, CYAN)

    # Codificar PNG
    raw = b""
    for row in pixels:
        raw += b"\x00"
        for r_, g, b, a in row:
            raw += struct.pack("BBBB", r_, g, b, a)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    return png


def png_to_icns(png_path: str, icns_path: str):
    """PNG → ICNS con sips + iconutil (macOS)."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = os.path.join(tmpdir, "app.iconset")
        os.makedirs(iconset)
        for sz in (16, 32, 64, 128, 256, 512):
            out = os.path.join(iconset, f"icon_{sz}x{sz}.png")
            subprocess.run(["sips", "-z", str(sz), str(sz), png_path, "--out", out],
                           capture_output=True)
            if sz <= 256:
                out2x = os.path.join(iconset, f"icon_{sz}x{sz}@2x.png")
                subprocess.run(["sips", "-z", str(sz * 2), str(sz * 2), png_path,
                                "--out", out2x], capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path], check=True)


def png_to_ico(ico_path: str, sizes=(256, 128, 64, 48, 32, 16), document: bool = False):
    """ICO con una entrada PNG por tamaño (Windows Vista o posterior)."""
    entries = [(sz, create_png(sz, document=document)) for sz in sizes]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory = b""
    payload = b""
    for sz, png in entries:
        directory += struct.pack("<BBBBHHII", sz % 256, sz % 256, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    with open(ico_path, "wb") as f:
        f.write(header + directory + payload)


def main():
    os.makedirs(RESOURCES, exist_ok=True)

    png_path = os.path.join(RESOURCES, "app_icon.png")
    with open(png_path, "wb") as f:
        f.write(create_png(1024))
    print(f"Creado {png_path}")
    icns_path = os.path.join(RESOURCES, "VisorGRIB.icns")
    try:
        png_to_icns(png_path, icns_path)
        print(f"Creado {icns_path}")
    except Exception as e:
        print(f"No se pudo crear el .icns (hace falta macOS): {e}")

    ico_path = os.path.join(RESOURCES, "VisorGRIB.ico")
    png_to_ico(ico_path)
    print(f"Creado {ico_path}")
    png256 = os.path.join(RESOURCES, "app_icon_256.png")
    with open(png256, "wb") as f:
        f.write(create_png(256))
    print(f"Creado {png256}")

    doc_png = os.path.join(RESOURCES, "doc_icon.png")
    with open(doc_png, "wb") as f:
        f.write(create_png(512, document=True))
    doc_icns = os.path.join(RESOURCES, "GribDocument.icns")
    try:
        png_to_icns(doc_png, doc_icns)
        print(f"Creado {doc_icns}")
    except Exception as e:
        print(f"No se pudo crear el .icns de documento: {e}")


if __name__ == "__main__":
    main()
