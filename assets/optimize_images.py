"""Resize and optimize ddoddo PNG images for web"""
from PIL import Image
import os

DIR = os.path.dirname(os.path.abspath(__file__))

# (filename, max_size_px) - 2x for retina
FILES = {
    "메인.png": 440,        # used at 220px, need 440 for retina
    "에러.png": 320,        # used at 160px
    "사주결과용.png": 200,   # used at 100px
    "사주보는중.png": 360,   # used at 180px
}

for fname, max_size in FILES.items():
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        print(f"[MISS] {fname}")
        continue

    before = os.path.getsize(path)
    img = Image.open(path).convert("RGBA")
    w, h = img.size

    # Resize keeping aspect ratio
    if w > max_size or h > max_size:
        ratio = min(max_size / w, max_size / h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Save with max compression
    img.save(path, "PNG", optimize=True)
    after = os.path.getsize(path)
    pct = int((1 - after / before) * 100)
    print(f"[OK] {fname}: {before:,} -> {after:,} bytes (-{pct}%) [{img.size[0]}x{img.size[1]}]")

print("Done!")
