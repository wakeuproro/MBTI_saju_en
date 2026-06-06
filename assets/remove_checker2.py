"""Remove checkerboard background - aggressive version"""
import numpy as np
from PIL import Image
import os

DIR = os.path.dirname(os.path.abspath(__file__))
FILES = ["메인.png", "에러.png", "사주결과용.png", "사주보는중.png"]

# Typical checkerboard colors
CHECKER_COLORS = [
    (204, 204, 204),  # light gray
    (238, 238, 238),  # lighter gray
    (255, 255, 255),  # white
    (231, 231, 231),  # another gray
    (243, 243, 243),  # near white
    (248, 248, 248),  # near white
    (192, 192, 192),  # gray
    (224, 224, 224),  # gray
    (240, 240, 240),  # gray
    (216, 216, 216),  # gray
    (200, 200, 200),  # gray
    (220, 220, 220),  # gray
    (245, 245, 245),  # near white
    (250, 250, 250),  # near white
    (235, 235, 235),  # gray
    (210, 210, 210),  # gray
    (230, 230, 230),  # gray
    (225, 225, 225),  # gray
]

TOLERANCE = 12  # color matching tolerance

for fname in FILES:
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        print(f"[MISS] {fname}")
        continue

    img = Image.open(path).convert("RGBA")
    data = np.array(img, dtype=np.int16)
    r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]

    # Method 1: Any pixel where R==G==B (neutral gray) and bright enough
    is_neutral = (np.abs(r - g) <= 5) & (np.abs(g - b) <= 5) & (np.abs(r - b) <= 5)
    is_bright = r >= 185
    bg_mask = is_neutral & is_bright

    # Method 2: Also check specific checker colors
    for cr, cg, cb in CHECKER_COLORS:
        color_match = (np.abs(r - cr) <= TOLERANCE) & \
                      (np.abs(g - cg) <= TOLERANCE) & \
                      (np.abs(b - cb) <= TOLERANCE)
        bg_mask = bg_mask | color_match

    # Don't remove pixels that are already semi-transparent
    bg_mask = bg_mask & (a > 200)

    # Use flood fill from corners to only remove connected background
    from scipy.ndimage import label
    labeled, num_features = label(bg_mask)

    # Find labels that touch any edge
    h, w = bg_mask.shape
    edge_labels = set()
    edge_labels.update(labeled[0, :].flatten())      # top
    edge_labels.update(labeled[h-1, :].flatten())     # bottom
    edge_labels.update(labeled[:, 0].flatten())       # left
    edge_labels.update(labeled[:, w-1].flatten())     # right
    edge_labels.discard(0)  # 0 = not background

    # Only remove background regions connected to edges
    final_mask = np.zeros_like(bg_mask)
    for lbl in edge_labels:
        final_mask = final_mask | (labeled == lbl)

    # Apply transparency
    out = data.astype(np.uint8).copy()
    out[final_mask, 3] = 0

    # Anti-alias: soften edges near the boundary
    from scipy.ndimage import binary_dilation
    dilated = binary_dilation(final_mask, iterations=2)
    border = dilated & ~final_mask

    for y, x in zip(*np.where(border)):
        px = out[y, x]
        pr, pg, pb = int(px[0]), int(px[1]), int(px[2])
        diff_r = abs(pr - pg)
        diff_g = abs(pg - pb)
        if diff_r < 10 and diff_g < 10 and pr > 180:
            # This border pixel is still grayish - make semi-transparent
            brightness = (pr + pg + pb) / 3
            new_alpha = max(0, min(255, int((255 - brightness) * 4)))
            out[y, x, 3] = min(out[y, x, 3], new_alpha)

    result = Image.fromarray(out)
    result.save(path, "PNG", optimize=True)
    print(f"[OK] {fname} -> {os.path.getsize(path):,} bytes")

print("Done!")
