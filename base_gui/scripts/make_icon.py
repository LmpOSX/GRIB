#!/usr/bin/env python3
"""Generate app icon (PNG → ICNS) for Presupuestador Pro."""
import os
import struct
import zlib

RESOURCES = os.path.join(os.path.dirname(__file__), "..", "resources")


def create_png(size: int) -> bytes:
    """Create a simple budget-app icon as raw PNG bytes."""
    # Colors
    BG = (74, 144, 217, 255)       # accent blue
    DARK = (30, 60, 100, 255)      # dark blue
    WHITE = (255, 255, 255, 255)
    GOLD = (220, 180, 50, 255)

    pixels = [[BG] * size for _ in range(size)]

    def fill_rect(x1, y1, x2, y2, color):
        for y in range(max(0, y1), min(size, y2)):
            for x in range(max(0, x1), min(size, x2)):
                pixels[y][x] = color

    def fill_circle(cx, cy, r, color):
        for y in range(max(0, int(cy - r)), min(size, int(cy + r) + 1)):
            for x in range(max(0, int(cx - r)), min(size, int(cx + r) + 1)):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2:
                    pixels[y][x] = color

    s = size
    pad = s // 8

    # Rounded-ish background (fill corners with transparent)
    r = s // 6
    for y in range(s):
        for x in range(s):
            # corner check
            corners = [
                (r, r), (s - r - 1, r), (r, s - r - 1), (s - r - 1, s - r - 1)
            ]
            in_corner = False
            for cx, cy in corners:
                if ((x < r or x >= s - r) and (y < r or y >= s - r)):
                    if (x - cx) ** 2 + (y - cy) ** 2 > r ** 2:
                        pixels[y][x] = (0, 0, 0, 0)
                        in_corner = True
            if not in_corner:
                pixels[y][x] = BG

    # Document shape (white rectangle with fold)
    dx1, dy1 = pad + s // 10, pad + s // 8
    dx2, dy2 = s - pad - s // 10, s - pad - s // 8
    fill_rect(dx1, dy1, dx2, dy2, WHITE)
    # Corner fold
    fold = s // 6
    for fy in range(dy1, dy1 + fold):
        for fx in range(dx2 - fold, dx2):
            if (fx - (dx2 - fold)) + (fy - dy1) < fold:
                pixels[fy][fx] = WHITE
            else:
                pixels[fy][fx] = (200, 210, 230, 255)

    # Horizontal lines (budget rows)
    line_h = max(1, s // 40)
    for i in range(4):
        ly = dy1 + s // 5 + i * (s // 8)
        fill_rect(dx1 + s // 12, ly, dx2 - s // 6, ly + line_h, DARK)

    # Dollar sign circle
    cr = s // 7
    cx, cy = s - pad - s // 6, s - pad - s // 5
    fill_circle(cx, cy, cr, GOLD)
    # $ sign (simple vertical lines)
    bar_w = max(1, cr // 4)
    fill_rect(cx - bar_w // 2, cy - cr + cr // 3, cx + bar_w // 2 + 1, cy + cr - cr // 3, DARK)

    # Encode as PNG
    raw = b""
    for row in pixels:
        raw += b"\x00"  # filter byte
        for r, g, b, a in row:
            raw += struct.pack("BBBB", r, g, b, a)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    compressed = zlib.compress(raw, 9)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"IDAT", compressed)
    png += chunk(b"IEND", b"")
    return png


def png_to_icns(png_path: str, icns_path: str):
    """Convert PNG to ICNS using macOS sips + iconutil."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        iconset = os.path.join(tmpdir, "app.iconset")
        os.makedirs(iconset)

        sizes = [16, 32, 64, 128, 256, 512]
        for sz in sizes:
            out = os.path.join(iconset, f"icon_{sz}x{sz}.png")
            subprocess.run([
                "sips", "-z", str(sz), str(sz), png_path, "--out", out
            ], capture_output=True)
            # @2x
            if sz <= 256:
                out2x = os.path.join(iconset, f"icon_{sz}x{sz}@2x.png")
                sz2 = sz * 2
                subprocess.run([
                    "sips", "-z", str(sz2), str(sz2), png_path, "--out", out2x
                ], capture_output=True)

        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns_path],
                       check=True)


def main():
    os.makedirs(RESOURCES, exist_ok=True)

    # Generate 1024x1024 PNG
    png_path = os.path.join(RESOURCES, "app_icon.png")
    with open(png_path, "wb") as f:
        f.write(create_png(1024))
    print(f"Created {png_path}")

    # Convert to ICNS
    icns_path = os.path.join(RESOURCES, "PresupuestadorPro.icns")
    try:
        png_to_icns(png_path, icns_path)
        print(f"Created {icns_path}")
    except Exception as e:
        print(f"Could not create .icns (need macOS): {e}")

    # Also create a document icon (same but with .ppto label feel)
    doc_png = os.path.join(RESOURCES, "doc_icon.png")
    with open(doc_png, "wb") as f:
        f.write(create_png(512))
    doc_icns = os.path.join(RESOURCES, "PptoDocument.icns")
    try:
        png_to_icns(doc_png, doc_icns)
        print(f"Created {doc_icns}")
    except Exception as e:
        print(f"Could not create doc .icns: {e}")


if __name__ == "__main__":
    main()
