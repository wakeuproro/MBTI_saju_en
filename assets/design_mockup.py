"""현재 배포 디자인 + 대안 시안 목업"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.dirname(__file__)
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
FONT_REG = "C:/Windows/Fonts/malgun.ttf"


def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def rounded(draw, box, r, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


# 보라 테마 컬러
PURPLE_MAIN = "#7B1FA2"
PURPLE_DARK = "#4A148C"
PURPLE_LIGHT = "#BA68C8"
BG_MAIN = "#FAF7FF"
BG_SOFT = "#F3E5F5"
BORDER = "#E1BEE7"
PINK = "#F8BBD0"
GOLD = "#FFC107"


def draw_wizard_cat(draw, cx, cy, size=80, mood="happy"):
    """마법사 고양이 SVG를 PIL로 재현"""
    s = size / 100
    # Wizard hat (보라색)
    hat_pts = [(cx - 22*s, cy - 25*s), (cx, cy - 60*s), (cx + 22*s, cy - 25*s)]
    draw.polygon(hat_pts, fill=PURPLE_MAIN)
    # Hat brim
    draw.ellipse([cx - 25*s, cy - 27*s, cx + 25*s, cy - 22*s], fill=PURPLE_DARK)
    # Star on hat
    draw.ellipse([cx - 2*s, cy - 55*s, cx + 2*s, cy - 51*s], fill=GOLD)

    # Ears
    draw.polygon([(cx - 18*s, cy - 18*s), (cx - 14*s, cy - 28*s), (cx - 10*s, cy - 15*s)], fill="#FFFFFF", outline=BORDER)
    draw.polygon([(cx + 18*s, cy - 18*s), (cx + 14*s, cy - 28*s), (cx + 10*s, cy - 15*s)], fill="#FFFFFF", outline=BORDER)
    # Inner ears (pink)
    draw.polygon([(cx - 16*s, cy - 17*s), (cx - 14*s, cy - 24*s), (cx - 12*s, cy - 16*s)], fill=PINK)
    draw.polygon([(cx + 16*s, cy - 17*s), (cx + 14*s, cy - 24*s), (cx + 12*s, cy - 16*s)], fill=PINK)

    # Head
    draw.ellipse([cx - 25*s, cy - 18*s, cx + 25*s, cy + 22*s], fill="#FFFFFF", outline=BORDER, width=int(max(1, 2*s)))

    # Eyes
    if mood == "happy":
        draw.arc([cx - 14*s, cy - 8*s, cx - 6*s, cy + 2*s], 0, 180, fill="#2D2D2D", width=int(max(2, 3*s)))
        draw.arc([cx + 6*s, cy - 8*s, cx + 14*s, cy + 2*s], 0, 180, fill="#2D2D2D", width=int(max(2, 3*s)))
    elif mood == "worried":
        draw.ellipse([cx - 13*s, cy - 8*s, cx - 7*s, cy + 2*s], fill="#2D2D2D")
        draw.ellipse([cx + 7*s, cy - 8*s, cx + 13*s, cy + 2*s], fill="#2D2D2D")
    elif mood == "focused":
        draw.line([cx - 14*s, cy - 4*s, cx - 7*s, cy - 4*s], fill="#2D2D2D", width=int(max(2, 3*s)))
        draw.line([cx + 7*s, cy - 4*s, cx + 14*s, cy - 4*s], fill="#2D2D2D", width=int(max(2, 3*s)))
    else:  # normal
        draw.ellipse([cx - 13*s, cy - 8*s, cx - 7*s, cy + 2*s], fill="#2D2D2D")
        draw.ellipse([cx + 7*s, cy - 8*s, cx + 13*s, cy + 2*s], fill="#2D2D2D")
        draw.ellipse([cx - 11*s, cy - 7*s, cx - 9*s, cy - 5*s], fill="#FFFFFF")
        draw.ellipse([cx + 9*s, cy - 7*s, cx + 11*s, cy - 5*s], fill="#FFFFFF")

    # Cheeks (pink)
    draw.ellipse([cx - 22*s, cy + 4*s, cx - 14*s, cy + 9*s], fill=PINK, outline=None)
    draw.ellipse([cx + 14*s, cy + 4*s, cx + 22*s, cy + 9*s], fill=PINK, outline=None)

    # Nose
    draw.polygon([(cx - 2*s, cy + 5*s), (cx + 2*s, cy + 5*s), (cx, cy + 8*s)], fill="#FFB6C1")

    # Mouth
    if mood == "worried":
        draw.arc([cx - 5*s, cy + 10*s, cx + 5*s, cy + 18*s], 180, 360, fill="#2D2D2D", width=int(max(1, 2*s)))
    else:
        draw.arc([cx - 5*s, cy + 8*s, cx + 5*s, cy + 14*s], 0, 180, fill="#2D2D2D", width=int(max(1, 2*s)))


def make_mockup_intro():
    """인트로 화면 목업"""
    W, H = 636, 1048
    img = Image.new('RGB', (W, H), BG_MAIN)
    d = ImageDraw.Draw(img)

    # 헤더
    d.rectangle([0, 0, W, 80], fill=BG_MAIN)
    d.line([0, 80, W, 80], fill="#EDE7F6", width=2)
    # 미니 고양이 로고
    draw_wizard_cat(d, 50, 40, size=40, mood="normal")
    d.text((90, 40), "사주 x MBTI", font=font(20, bold=True), anchor='lm', fill=PURPLE_MAIN)
    # KO/EN
    rounded(d, [W-130, 22, W-22, 58], 14, BG_SOFT, "#EDE7F6", 1)
    rounded(d, [W-128, 24, W-78, 56], 12, PURPLE_MAIN, None, 0)
    d.text((W-103, 40), "KO", font=font(16, bold=True), anchor='mm', fill="#FFFFFF")
    d.text((W-53, 40), "EN", font=font(16, bold=True), anchor='mm', fill=PURPLE_MAIN)

    # 큰 마법사 고양이 + 수정구슬
    cy = 230
    draw_wizard_cat(d, W//2, cy, size=180, mood="normal")
    # 수정구슬 below
    bcy = cy + 120
    d.ellipse([W//2 - 38, bcy - 30, W//2 + 38, bcy + 30], fill=PURPLE_LIGHT, outline=PURPLE_MAIN, width=2)
    d.ellipse([W//2 - 30, bcy - 22, W//2 + 30, bcy + 22], fill="#F3E5F5")
    d.ellipse([W//2 - 12, bcy - 18, W//2 - 4, bcy - 12], fill="#FFFFFF")
    d.text((W//2, bcy), "✦", font=font(16, bold=True), anchor='mm', fill=GOLD)
    # 반짝
    d.text((90, 200), "✦", font=font(28), anchor='mm', fill=GOLD)
    d.text((W-90, 250), "✧", font=font(24), anchor='mm', fill=PURPLE_LIGHT)
    d.text((100, 320), "·", font=font(16), anchor='mm', fill=PURPLE_MAIN)
    d.text((W-100, 360), "✦", font=font(20), anchor='mm', fill=GOLD)

    # 타이틀
    d.text((W//2, 460), "사주와 MBTI가 만나면", font=font(28, bold=True), anchor='mm', fill=PURPLE_DARK)
    d.text((W//2, 498), "운명이 보입니다", font=font(28, bold=True), anchor='mm', fill=PURPLE_DARK)
    d.text((W//2, 540), "🐱 운명을 풀어주는 마법사 고양이가 도와드려요", font=font(16), anchor='mm', fill="#8E7E94")

    # 무료 배지
    rounded(d, [W//2 - 60, 568, W//2 + 60, 600], 16, "#E8F5E9", None)
    d.text((W//2, 584), "첫 분석 무료", font=font(14, bold=True), anchor='mm', fill="#2E7D32")

    # 입력 폼 (간략화)
    y = 640
    d.text((40, y), "이름 또는 닉네임", font=font(14, bold=True), anchor='lm', fill="#6D4C41")
    rounded(d, [32, y+14, W-32, y+62], 12, "#FFFFFF", BORDER, 2)
    d.text((50, y+38), "예: 김지수", font=font(15), anchor='lm', fill="#9E9E9E")

    y += 90
    d.text((40, y), "성별", font=font(14, bold=True), anchor='lm', fill="#6D4C41")
    rounded(d, [32, y+14, W//2 - 6, y+62], 12, PURPLE_MAIN, None)
    d.text(((32+W//2-6)//2, y+38), "여자", font=font(16, bold=True), anchor='mm', fill="#FFFFFF")
    rounded(d, [W//2 + 6, y+14, W-32, y+62], 12, "#FFFFFF", BORDER, 2)
    d.text(((W//2+6+W-32)//2, y+38), "남자", font=font(16, bold=True), anchor='mm', fill="#8E7E94")

    # 시작 버튼
    rounded(d, [32, H-100, W-32, H-44], 18, PURPLE_MAIN, None)
    d.text((W//2, H-72), "✨ 무료 분석 시작하기", font=font(18, bold=True), anchor='mm', fill="#FFFFFF")

    img.save(os.path.join(OUT, "mockup_intro.png"))
    print("saved: mockup_intro.png")


def make_mockup_loading():
    """로딩 화면 목업"""
    W, H = 636, 1048
    img = Image.new('RGB', (W, H), BG_MAIN)
    d = ImageDraw.Draw(img)

    # 반투명 오버레이 효과 (밝게)
    # 노트북 두드리는 고양이
    cy = H // 2 - 60
    draw_wizard_cat(d, W//2, cy, size=140, mood="focused")
    # 노트북
    lap_y = cy + 85
    rounded(d, [W//2 - 70, lap_y, W//2 + 70, lap_y + 30], 4, PURPLE_MAIN)
    d.rectangle([W//2 - 64, lap_y + 5, W//2 + 64, lap_y + 26], fill="#1A1A2E")
    d.rectangle([W//2 - 76, lap_y + 28, W//2 + 76, lap_y + 36], fill=PURPLE_DARK)
    # 파우 마크
    d.ellipse([W//2 - 3, lap_y + 13, W//2 + 3, lap_y + 19], fill=GOLD)

    # 타닥타닥
    d.text((W//2 - 130, cy - 40), "타닥", font=font(18, bold=True), anchor='mm', fill=PURPLE_LIGHT)
    d.text((W//2 + 130, cy - 60), "타닥", font=font(18, bold=True), anchor='mm', fill=PURPLE_LIGHT)
    d.text((W//2 + 100, cy + 20), "타닥", font=font(16, bold=True), anchor='mm', fill=PURPLE_LIGHT)

    # 메시지
    rounded(d, [W//2 - 140, H//2 + 100, W//2 + 140, H//2 + 160], 30, "#FFFFFF", BORDER, 2)
    d.text((W//2, H//2 + 130), "운명을 해석하고 있어요...", font=font(16, bold=True), anchor='mm', fill=PURPLE_DARK)

    img.save(os.path.join(OUT, "mockup_loading.png"))
    print("saved: mockup_loading.png")


def make_mockup_result():
    """결과 화면 목업 (헤더 카드)"""
    W, H = 636, 1048
    img = Image.new('RGB', (W, H), BG_MAIN)
    d = ImageDraw.Draw(img)

    # 헤더
    d.rectangle([0, 0, W, 80], fill=BG_MAIN)
    d.line([0, 80, W, 80], fill="#EDE7F6", width=2)
    draw_wizard_cat(d, 50, 40, size=40, mood="normal")
    d.text((90, 40), "사주 x MBTI", font=font(20, bold=True), anchor='lm', fill=PURPLE_MAIN)

    # 헤더 카드 (그라데이션 라벤더)
    rounded(d, [24, 100, W-24, 480], 22, BG_SOFT, BORDER, 2)
    # 두루마리 든 고양이
    draw_wizard_cat(d, W//2, 165, size=90, mood="happy")
    # 두루마리
    rounded(d, [W//2 - 60, 195, W//2 - 18, 220], 4, "#FFF8E1", GOLD, 1)
    d.line([W//2 - 55, 200, W//2 - 23, 200], fill=PURPLE_MAIN, width=1)
    d.line([W//2 - 55, 207, W//2 - 28, 207], fill=PURPLE_MAIN, width=1)
    d.line([W//2 - 55, 214, W//2 - 25, 214], fill=PURPLE_MAIN, width=1)

    # 이름
    d.text((W//2, 260), "로로님의 사주", font=font(22, bold=True), anchor='mm', fill=PURPLE_DARK)
    d.text((W//2, 288), "병화(丙火) × ENFP", font=font(26, bold=True), anchor='mm', fill=PURPLE_DARK)

    # 정보 칩
    chip_y = 320
    cx = 70
    for label in ["♀ 여자", "ENFP", "일간: 병화"]:
        bbox = d.textbbox((0, 0), label, font=font(13, bold=True))
        cw = bbox[2] - bbox[0] + 24
        rounded(d, [cx, chip_y, cx + cw, chip_y + 28], 14, "#FFFFFF", BORDER, 1)
        d.text((cx + cw // 2, chip_y + 14), label, font=font(13, bold=True), anchor='mm', fill="#8E7E94")
        cx += cw + 8

    # 사주팔자 4기둥
    pillar_data = [
        ("시주", "갑", "오", "#E8F5E9", "#2E7D32"),
        ("일주", "병", "오", "#FCE4EC", "#C62828"),
        ("월주", "임", "오", "#E3F2FD", "#1565C0"),
        ("년주", "을", "해", "#E8F5E9", "#2E7D32"),
    ]
    py = 370
    pw = (W - 80) // 4
    for i, (label, gan, ji, bg, fg) in enumerate(pillar_data):
        x = 40 + i * pw
        rounded(d, [x + 4, py, x + pw - 4, py + 110], 12, bg)
        d.text((x + pw // 2, py + 14), label, font=font(13, bold=True), anchor='mm', fill="#8E7E94")
        d.text((x + pw // 2, py + 50), gan, font=font(40, bold=True), anchor='mm', fill=fg)
        d.text((x + pw // 2, py + 92), ji, font=font(32, bold=True), anchor='mm', fill=fg)

    # 띠 카드 미리보기
    rounded(d, [24, 510, W-24, 720], 18, "#FFF8E1", "#FFCC80", 2)
    d.text((W//2, 540), "🐷", font=font(50), anchor='mm', fill="#000")
    d.text((W//2, 595), "돼지띠 (亥)", font=font(20, bold=True), anchor='mm', fill=PURPLE_DARK)
    d.text((W//2, 622), "순수하고 풍요로운 복덩이", font=font(13, bold=True), anchor='mm', fill="#6D4C41")
    d.text((W//2, 660), "순수하고 정이 많으며 사람을 좋아하는 띠.", font=font(12), anchor='mm', fill="#5D4037")
    d.text((W//2, 680), "복이 많고 풍요로운 사주로 알려져 있어요.", font=font(12), anchor='mm', fill="#5D4037")

    # 신살 미리보기
    rounded(d, [24, 750, W-24, 990], 18, BG_SOFT, BORDER, 2)
    d.text((54, 780), "✨ 내 사주의 특수 신살", font=font(16, bold=True), anchor='lm', fill=PURPLE_DARK)
    # 신살 미니
    items = [("🌸", "도화살"), ("⭐", "천을귀인"), ("🪷", "화개살")]
    iy = 820
    for emoji, name in items:
        rounded(d, [44, iy, W - 44, iy + 50], 12, "#FFFFFF", BORDER, 1)
        d.text((70, iy + 25), emoji, font=font(20), anchor='mm', fill="#000")
        d.text((110, iy + 25), name, font=font(14, bold=True), anchor='lm', fill=PURPLE_DARK)
        iy += 56

    img.save(os.path.join(OUT, "mockup_result.png"))
    print("saved: mockup_result.png")


def make_mockup_error():
    """에러 모달 목업"""
    W, H = 636, 1048
    img = Image.new('RGB', (W, H), BG_MAIN)
    d = ImageDraw.Draw(img)

    # 배경 (어두운 보라 오버레이)
    overlay = Image.new('RGBA', (W, H), (74, 20, 140, 140))
    img.paste(overlay, (0, 0), overlay)
    d = ImageDraw.Draw(img)

    # 에러 모달 카드
    mx, my, mw, mh = 60, H//2 - 280, W - 120, 560
    rounded(d, [mx, my, mx+mw, my+mh], 24, "#FFFFFF")

    # 당황한 고양이
    cy = my + 140
    draw_wizard_cat(d, W//2, cy, size=130, mood="worried")
    # 식은땀
    d.ellipse([W//2 - 60, cy - 35, W//2 - 54, cy - 25], fill="#42A5F5")
    d.ellipse([W//2 + 54, cy - 35, W//2 + 60, cy - 25], fill="#42A5F5")
    # 꼬인 실타래
    d.text((W//2 - 100, cy - 80), "〰️", font=font(28), anchor='mm', fill=PURPLE_LIGHT)
    d.text((W//2 + 100, cy - 80), "〰️", font=font(28), anchor='mm', fill=PURPLE_LIGHT)

    # 메시지
    d.text((W//2, my + 320), "앗, 운명의 실이 꼬였어요!", font=font(20, bold=True), anchor='mm', fill=PURPLE_DARK)
    d.text((W//2, my + 360), "잠시 후 다시 시도해주세요 🐾", font=font(14), anchor='mm', fill="#6D4C41")

    # 확인 버튼
    rounded(d, [mx + 30, my + mh - 90, mx + mw - 30, my + mh - 30], 16, PURPLE_MAIN)
    d.text((W//2, my + mh - 60), "알겠어요!", font=font(18, bold=True), anchor='mm', fill="#FFFFFF")

    img.save(os.path.join(OUT, "mockup_error.png"))
    print("saved: mockup_error.png")


if __name__ == "__main__":
    make_mockup_intro()
    make_mockup_loading()
    make_mockup_result()
    make_mockup_error()
    print("\n[DONE] 4 design mockups generated.")
