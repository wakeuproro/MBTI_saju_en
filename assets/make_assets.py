"""앱인토스 등록용 에셋 생성 — 로고(라이트/다크) + 썸네일"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.dirname(__file__)
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
FONT_REG = "C:/Windows/Fonts/malgun.ttf"


def gradient_bg(size, c1, c2, vertical=True):
    """간단한 선형 그라데이션 배경 생성"""
    img = Image.new('RGB', size, c1)
    draw = ImageDraw.Draw(img)
    w, h = size
    if vertical:
        for y in range(h):
            t = y / max(h - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            draw.line([(0, y), (w, y)], fill=(r, g, b))
    else:
        for x in range(w):
            t = x / max(w - 1, 1)
            r = int(c1[0] + (c2[0] - c1[0]) * t)
            g = int(c1[1] + (c2[1] - c1[1]) * t)
            b = int(c1[2] + (c2[2] - c1[2]) * t)
            draw.line([(x, 0), (x, h)], fill=(r, g, b))
    return img


def rounded_rect(size, radius, color):
    """라운드 사각형 마스크"""
    mask = Image.new('L', size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([(0, 0), (size[0] - 1, size[1] - 1)], radius=radius, fill=255)
    layer = Image.new('RGBA', size, color)
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    out.paste(layer, (0, 0), mask)
    return out


def draw_yin_yang(draw, cx, cy, radius, fg, bg):
    """태극 (음양) 그리기"""
    # 큰 원
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=fg, outline=fg)
    # 위 반원 (밝은쪽)
    draw.pieslice([cx - radius, cy - radius, cx + radius, cy + radius], 270, 90, fill=bg)
    # 작은 원 두 개
    r2 = radius // 2
    draw.ellipse([cx - r2, cy - radius, cx + r2, cy], fill=fg)
    draw.ellipse([cx - r2, cy, cx + r2, cy + radius], fill=bg)
    # 핵심 점
    r3 = radius // 6
    draw.ellipse([cx - r3, cy - radius // 2 - r3, cx + r3, cy - radius // 2 + r3], fill=bg)
    draw.ellipse([cx - r3, cy + radius // 2 - r3, cx + r3, cy + radius // 2 + r3], fill=fg)


def make_logo(path, light=True):
    size = (600, 600)
    if light:
        bg1, bg2 = (255, 243, 224), (255, 204, 128)   # 크림→오렌지
        fg = (191, 54, 12)                            # 진오렌지
        text_color = (191, 54, 12)
        accent = (255, 109, 0)
        sym_bg = (255, 255, 255)
    else:
        bg1, bg2 = (45, 30, 25), (90, 50, 30)         # 다크 + 따뜻한 갈색
        fg = (255, 171, 64)                           # 밝은 오렌지
        text_color = (255, 224, 178)
        accent = (255, 138, 101)
        sym_bg = (60, 40, 30)

    img = gradient_bg(size, bg1, bg2, vertical=False).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # 라운드 영역(아이콘 백판)
    card_size = 360
    card_x = (size[0] - card_size) // 2
    card_y = 90
    card = rounded_rect((card_size, card_size), 90, sym_bg + (235,))
    img.alpha_composite(card, (card_x, card_y))

    # 태극 심볼
    draw_yin_yang(draw, size[0] // 2, card_y + card_size // 2, 110, fg, accent)

    # 텍스트: "사주 × MBTI"
    try:
        f_main = ImageFont.truetype(FONT_BOLD, 72)
        f_sub = ImageFont.truetype(FONT_REG, 32)
    except OSError:
        f_main = ImageFont.load_default()
        f_sub = ImageFont.load_default()

    draw.text((size[0] // 2, 510), "사주 × MBTI", font=f_main, anchor='mm', fill=text_color)
    img.convert('RGB').save(path, 'PNG', optimize=True)
    print(f"saved: {path}")


def make_thumbnail(path):
    """1932x828 가로 썸네일 (앱인토스 피드 배너)"""
    size = (1932, 828)
    img = gradient_bg(size, (255, 243, 224), (255, 204, 128), vertical=False).convert('RGBA')
    draw = ImageDraw.Draw(img)

    # 우측에 반투명 텍스트 카드 효과 (안 씀, 깔끔 유지)

    # 좌측: 큰 태극 심볼
    sym_card = rounded_rect((520, 520), 130, (255, 255, 255, 235))
    sym_x, sym_y = 120, 154
    img.alpha_composite(sym_card, (sym_x, sym_y))
    draw_yin_yang(draw, sym_x + 260, sym_y + 260, 170, (191, 54, 12), (255, 109, 0))

    # 우측 텍스트 영역
    try:
        f_title = ImageFont.truetype(FONT_BOLD, 124)
        f_sub = ImageFont.truetype(FONT_BOLD, 56)
        f_tag = ImageFont.truetype(FONT_REG, 42)
        f_chip = ImageFont.truetype(FONT_BOLD, 32)
    except OSError:
        f_title = ImageFont.load_default()
        f_sub = ImageFont.load_default()
        f_tag = ImageFont.load_default()
        f_chip = ImageFont.load_default()

    text_x = 760
    draw.text((text_x, 220), "사주 × MBTI", font=f_title, anchor='lm', fill=(191, 54, 12))
    draw.text((text_x, 340), "AI가 풀어주는 나만의 운명카드", font=f_sub, anchor='lm', fill=(93, 64, 55))
    draw.text((text_x, 425), "동양 명리학 + 서양 성격유형의 완벽한 결합", font=f_tag, anchor='lm', fill=(141, 110, 99))

    # 칩 4개 (이모지 X, 텍스트만)
    chips = [
        ("사주 팔자", (255, 243, 224, 255), (191, 54, 12)),
        ("오행 분석", (232, 245, 233, 255), (46, 125, 50)),
        ("풍수 인테리어", (252, 228, 236, 255), (198, 40, 40)),
        ("AI 심층 해석", (243, 229, 245, 255), (106, 27, 154)),
    ]
    cx_start = text_x
    cy = 540
    for label, bg_color, fg_color in chips:
        bbox = draw.textbbox((0, 0), label, font=f_chip)
        tw = bbox[2] - bbox[0]
        chip_w = tw + 56
        chip = rounded_rect((chip_w, 80), 40, bg_color)
        img.alpha_composite(chip, (cx_start, cy))
        draw.text((cx_start + chip_w // 2, cy + 40), label, font=f_chip, anchor='mm', fill=fg_color)
        cx_start += chip_w + 18

    # 우상단 배지: "첫 분석 무료"
    try:
        f_badge = ImageFont.truetype(FONT_BOLD, 36)
    except OSError:
        f_badge = ImageFont.load_default()
    badge_text = "첫 분석 무료"
    bbox = draw.textbbox((0, 0), badge_text, font=f_badge)
    bw = bbox[2] - bbox[0] + 60
    badge = rounded_rect((bw, 72), 36, (76, 175, 80, 255))
    img.alpha_composite(badge, (size[0] - bw - 60, 60))
    draw.text((size[0] - bw // 2 - 60, 96), badge_text, font=f_badge, anchor='mm', fill=(255, 255, 255))

    img.convert('RGB').save(path, 'PNG', optimize=True)
    print(f"saved: {path}")


if __name__ == "__main__":
    make_logo(os.path.join(OUT, "logo_light_600.png"), light=True)
    make_logo(os.path.join(OUT, "logo_dark_600.png"), light=False)
    make_thumbnail(os.path.join(OUT, "thumbnail_1932x828.png"))
    print("\n[DONE] all assets generated.")
