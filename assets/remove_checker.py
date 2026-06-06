"""격자무늬(체커보드) 배경을 투명으로 변환"""
import numpy as np
from PIL import Image
import os

DIR = os.path.dirname(os.path.abspath(__file__))
FILES = ["메인.png", "에러.png", "사주결과용.png", "사주보는중.png"]

for fname in FILES:
    path = os.path.join(DIR, fname)
    if not os.path.exists(path):
        print(f"[MISS] {fname} not found")
        continue

    img = Image.open(path).convert("RGBA")
    data = np.array(img)

    # 체커보드 패턴의 두 색상 감지 (일반적으로 흰색 + 연회색)
    # 일반적인 체커보드: (204,204,204) + (255,255,255) 또는 (238,238,238) + (255,255,255)
    # 허용 범위를 넓게 잡아서 처리
    r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]

    # 회색 계열 (R≈G≈B) 이면서 밝은 색상인 픽셀 = 배경
    is_gray = (np.abs(r.astype(int) - g.astype(int)) < 8) & \
              (np.abs(g.astype(int) - b.astype(int)) < 8) & \
              (np.abs(r.astype(int) - b.astype(int)) < 8)
    is_bright = r > 190  # 밝은 회색~흰색

    # 배경으로 판단되는 픽셀을 투명으로
    bg_mask = is_gray & is_bright
    data[bg_mask, 3] = 0  # alpha = 0

    # 경계 부분 안티앨리어싱 처리: 배경과 인접한 반투명 영역
    from scipy import ndimage
    bg_float = bg_mask.astype(float)
    dilated = ndimage.binary_dilation(bg_mask, iterations=1)
    border = dilated & ~bg_mask

    # 경계 픽셀의 알파를 배경색 비율로 조정
    for y, x in zip(*np.where(border)):
        pixel = data[y, x]
        pr, pg, pb = int(pixel[0]), int(pixel[1]), int(pixel[2])
        # 얼마나 배경색(밝은회색)에 가까운지 계산
        gray_avg = (pr + pg + pb) / 3
        if gray_avg > 200:
            # 배경에 가까울수록 더 투명하게
            alpha_ratio = max(0, min(255, int((255 - gray_avg) * 255 / 55)))
            data[y, x, 3] = min(pixel[3], alpha_ratio)

    result = Image.fromarray(data)
    result.save(path, "PNG")
    print(f"[OK] {fname} done ({os.path.getsize(path):,} bytes)")
