"""앱인토스 등록용 모바일 스크린샷 3장 생성 (636x1048)"""
from PIL import Image, ImageDraw, ImageFont
import os

OUT = os.path.dirname(__file__)
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
FONT_REG = "C:/Windows/Fonts/malgun.ttf"

W, H = 636, 1048
BG = (255, 248, 240)        # FFF8F0 cream
ACCENT = (255, 109, 0)       # FF6D00
ACCENT_DARK = (191, 54, 12)  # BF360C
TEXT = (45, 45, 45)
SUB_TEXT = (141, 110, 99)
BORDER = (255, 224, 178)


def font(size, bold=False):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except OSError:
        return ImageFont.load_default()


def rounded_rect(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_header(draw):
    """공통 헤더"""
    draw.rectangle([0, 0, W, 80], fill=(255, 248, 240))
    draw.line([0, 80, W, 80], fill=BORDER, width=2)
    draw.text((40, 40), "사주 x MBTI", font=font(28, bold=True), anchor='lm', fill=ACCENT_DARK)
    # 우측 KO/EN 토글
    rounded_rect(draw, [W - 130, 24, W - 24, 56], 12, (255, 243, 224), BORDER, 1)
    rounded_rect(draw, [W - 128, 26, W - 78, 54], 10, ACCENT, None, 0)
    draw.text((W - 103, 40), "KO", font=font(18, bold=True), anchor='mm', fill=(255, 255, 255))
    draw.text((W - 53, 40), "EN", font=font(18, bold=True), anchor='mm', fill=ACCENT_DARK)


def yin_yang(draw, cx, cy, r, fg=ACCENT_DARK, bg=ACCENT):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fg)
    draw.pieslice([cx - r, cy - r, cx + r, cy + r], 270, 90, fill=bg)
    r2 = r // 2
    draw.ellipse([cx - r2, cy - r, cx + r2, cy], fill=fg)
    draw.ellipse([cx - r2, cy, cx + r2, cy + r], fill=bg)
    r3 = r // 6
    draw.ellipse([cx - r3, cy - r // 2 - r3, cx + r3, cy - r // 2 + r3], fill=bg)
    draw.ellipse([cx - r3, cy + r // 2 - r3, cx + r3, cy + r // 2 + r3], fill=fg)


# ════════════════════════════════════════════
# 스크린샷 1: 입력 화면 (Intro)
# ════════════════════════════════════════════
def screenshot_1_intro():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_header(draw)

    # 히어로 영역
    yin_yang(draw, W // 2, 180, 50)
    draw.text((W // 2, 282), "사주와 MBTI가 만나면", font=font(34, bold=True), anchor='mm', fill=ACCENT_DARK)
    draw.text((W // 2, 322), "운명이 보입니다", font=font(34, bold=True), anchor='mm', fill=ACCENT_DARK)
    draw.text((W // 2, 365), "동양 명리학 + 서양 성격유형의 운명적 조합", font=font(18), anchor='mm', fill=SUB_TEXT)

    # 무료 배지
    bbox = draw.textbbox((0, 0), "첫 분석 무료", font=font(16, bold=True))
    bw = bbox[2] - bbox[0] + 32
    rounded_rect(draw, [W // 2 - bw // 2, 395, W // 2 + bw // 2, 425], 15, (232, 245, 233))
    draw.text((W // 2, 410), "첫 분석 무료", font=font(16, bold=True), anchor='mm', fill=(46, 125, 50))

    # 입력 폼
    y = 470
    fields = [
        ("이름 또는 닉네임", "예: 김지수"),
        ("성별", "여자  /  남자"),
        ("생년월일 (양력)", "1995-05-15"),
        ("MBTI", "ENFP - 활동가"),
    ]
    for label, placeholder in fields:
        draw.text((40, y), label, font=font(16, bold=True), anchor='lm', fill=(109, 76, 65))
        rounded_rect(draw, [32, y + 16, W - 32, y + 76], 14, (255, 255, 255), BORDER, 2)
        if label == "성별":
            # 여자/남자 두 버튼
            mid = W // 2
            rounded_rect(draw, [40, y + 22, mid - 4, y + 70], 12, ACCENT, None)
            draw.text(((40 + mid - 4) // 2, y + 46), "여자", font=font(20, bold=True), anchor='mm', fill=(255, 255, 255))
            rounded_rect(draw, [mid + 4, y + 22, W - 40, y + 70], 12, (255, 255, 255), BORDER, 2)
            draw.text(((mid + 4 + W - 40) // 2, y + 46), "남자", font=font(20, bold=True), anchor='mm', fill=SUB_TEXT)
        else:
            draw.text((50, y + 46), placeholder, font=font(18), anchor='lm', fill=(160, 160, 160) if "예:" in placeholder else TEXT)
        y += 100

    # CTA 버튼
    rounded_rect(draw, [32, 920, W - 32, 990], 16, ACCENT, None)
    draw.text((W // 2, 955), "무료 분석 시작하기", font=font(22, bold=True), anchor='mm', fill=(255, 255, 255))

    img.save(os.path.join(OUT, "screenshot_1_intro.png"))
    print("saved: screenshot_1_intro.png")


# ════════════════════════════════════════════
# 스크린샷 2: 분석 결과 + 사주팔자 + 오행 차트
# ════════════════════════════════════════════
def screenshot_2_result():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_header(draw)

    # 헤더 카드 (이름+사주)
    rounded_rect(draw, [24, 100, W - 24, 380], 20, (255, 243, 224), (255, 204, 128), 2)
    draw.text((W // 2, 140), "로로님의 사주", font=font(22, bold=True), anchor='mm', fill=ACCENT_DARK)
    draw.text((W // 2, 168), "병화(丙火) × ENFP", font=font(26, bold=True), anchor='mm', fill=ACCENT_DARK)

    # 정보 칩들
    chips_y = 200
    chips = [("여 여자", (255, 252, 248)), ("ENFP", (255, 252, 248)), ("일간: 병화", (255, 252, 248))]
    cx = 50
    for label, color in chips:
        bbox = draw.textbbox((0, 0), label, font=font(13, bold=True))
        cw = bbox[2] - bbox[0] + 24
        rounded_rect(draw, [cx, chips_y, cx + cw, chips_y + 28], 14, (255, 255, 255), (255, 204, 128), 1)
        draw.text((cx + cw // 2, chips_y + 14), label, font=font(13, bold=True), anchor='mm', fill=SUB_TEXT)
        cx += cw + 8

    # 사주팔자 4기둥 (시/일/월/년)
    pillar_data = [
        ("시주", "갑", "오", (232, 245, 233), (46, 125, 50)),
        ("일주", "병", "오", (252, 228, 236), (198, 40, 40)),
        ("월주", "임", "오", (227, 242, 253), (21, 101, 192)),
        ("년주", "을", "해", (232, 245, 233), (46, 125, 50)),
    ]
    py = 250
    pw = (W - 80) // 4
    for i, (label, gan, ji, bg, fg) in enumerate(pillar_data):
        x = 40 + i * pw
        rounded_rect(draw, [x + 4, py, x + pw - 4, py + 110], 12, bg)
        draw.text((x + pw // 2, py + 14), label, font=font(13, bold=True), anchor='mm', fill=SUB_TEXT)
        draw.text((x + pw // 2, py + 50), gan, font=font(40, bold=True), anchor='mm', fill=fg)
        draw.text((x + pw // 2, py + 92), ji, font=font(32, bold=True), anchor='mm', fill=fg)

    # 오행 차트 섹션
    rounded_rect(draw, [24, 410, W - 24, 720], 16, (255, 255, 255), BORDER, 2)
    draw.text((54, 446), "☯", font=font(22, bold=True), anchor='lm', fill=ACCENT_DARK)
    draw.text((90, 446), "오행 밸런스 차트", font=font(20, bold=True), anchor='lm', fill=TEXT)

    # 오행 바 차트
    bar_data = [("목", 1, (102, 187, 106)), ("화", 3, (239, 83, 80)), ("토", 0, (255, 202, 40)), ("금", 0, (171, 71, 188)), ("수", 2, (66, 165, 245))]
    max_h = 130
    by = 600
    bw = (W - 100) // 5
    for i, (name, val, color) in enumerate(bar_data):
        x = 50 + i * bw
        bar_h = max(int(val * 40), 8)
        draw.rectangle([x + 14, by - bar_h, x + bw - 14, by], fill=color)
        draw.text((x + bw // 2, by + 20), f"{name}", font=font(15, bold=True), anchor='mm', fill=color)
        draw.text((x + bw // 2, by + 40), f"{val}개", font=font(12), anchor='mm', fill=SUB_TEXT)

    draw.text((54, 680), "화(火)의 기운이 가장 강해요.", font=font(15), anchor='lm', fill=SUB_TEXT)

    # 첫 분석 섹션 (열린 상태)
    rounded_rect(draw, [24, 740, W - 24, 900], 16, (255, 255, 255), BORDER, 2)
    rounded_rect(draw, [54, 770, 100, 816], 12, (255, 243, 224))
    draw.text((77, 793), "☀", font=font(22, bold=True), anchor='mm', fill=ACCENT)
    draw.text((120, 793), "세상을 밝히는 찬란한 태양", font=font(17, bold=True), anchor='lm', fill=TEXT)
    draw.text((54, 840), "병화(丙火)의 기운을 가진 당신은", font=font(15), anchor='lm', fill=(93, 64, 55))
    draw.text((54, 866), "열정적이고 에너지가 넘칩니다.", font=font(15), anchor='lm', fill=(93, 64, 55))

    # 하단 CTA
    rounded_rect(draw, [0, 950, W, H], 0, (244, 67, 130))
    draw.text((W // 2, 999), "친구 사주도 궁금하다면? 990원에 확인", font=font(17, bold=True), anchor='mm', fill=(255, 255, 255))

    img.save(os.path.join(OUT, "screenshot_2_result.png"))
    print("saved: screenshot_2_result.png")


# ════════════════════════════════════════════
# 스크린샷 3: 프리미엄 티저 (풍수/악세사리/향기)
# ════════════════════════════════════════════
def screenshot_3_premium():
    img = Image.new('RGB', (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw_header(draw)

    # 섹션 타이틀
    draw.text((W // 2, 130), "💎 더 깊은 사주 해석", font=font(24, bold=True), anchor='mm', fill=ACCENT_DARK)
    draw.text((W // 2, 160), "이런 것까지 알려드려요", font=font(15), anchor='mm', fill=SUB_TEXT)

    # 티저 카드 3개
    teasers = [
        ("집", "돈이 새지 않는 우리집 풍수인테리어", "당신의 오행 에너지를 살리는 컬러,\n배치, 소품이 따로 있습니다."),
        ("보석", "부족한 기운을 채워주는 악세사리", "내 사주에 부족한 오행을 보충해주는\n소재와 보석이 있습니다."),
        ("꽃", "나의 기질에 딱 맞는 시그니처 향기", "일간 에너지와 공명하는 향이 자신감과\n매력을 끌어올립니다."),
    ]

    icon_colors = [(255, 224, 178), (252, 228, 236), (243, 229, 245)]
    icon_text_colors = [(191, 54, 12), (198, 40, 40), (106, 27, 154)]

    y = 200
    for i, (icon_label, title, desc) in enumerate(teasers):
        rounded_rect(draw, [24, y, W - 24, y + 170], 18, (255, 255, 255), (224, 224, 224), 2)
        # 아이콘 사각형
        rounded_rect(draw, [44, y + 24, 92, y + 72], 12, icon_colors[i])
        draw.text((68, y + 48), icon_label, font=font(20, bold=True), anchor='mm', fill=icon_text_colors[i])
        # 타이틀 + lock
        draw.text((110, y + 36), title, font=font(17, bold=True), anchor='lm', fill=(120, 120, 120))
        draw.text((W - 50, y + 36), "🔒", font=font(18), anchor='mm', fill=(160, 160, 160))
        draw.text((110, y + 58), "PREMIUM", font=font(12, bold=True), anchor='lm', fill=(123, 31, 162))
        # blurry 설명
        for li, line in enumerate(desc.split('\n')):
            draw.text((44, y + 105 + li * 22), line, font=font(13), anchor='lm', fill=(180, 180, 180))
        y += 186

    # 프리미엄 unlock 배너
    rounded_rect(draw, [24, 760, W - 24, 940], 18, (243, 229, 245), (206, 147, 216), 2)
    draw.text((W // 2, 798), "더 깊은 사주 해석이 준비됐어요", font=font(18, bold=True), anchor='mm', fill=(106, 27, 154))
    draw.text((W // 2, 826), "풍수 · 악세사리 · 향기 + AI 심층 해석", font=font(14), anchor='mm', fill=(123, 31, 162))
    rounded_rect(draw, [80, 858, W - 80, 916], 16, (123, 31, 162))
    draw.text((W // 2, 887), "990원 결제하고 열기", font=font(20, bold=True), anchor='mm', fill=(255, 255, 255))

    # 하단 CTA
    rounded_rect(draw, [0, 970, W, H], 0, (244, 67, 130))
    draw.text((W // 2, 1009), "친구 사주도 궁금하다면? 990원", font=font(17, bold=True), anchor='mm', fill=(255, 255, 255))

    img.save(os.path.join(OUT, "screenshot_3_premium.png"))
    print("saved: screenshot_3_premium.png")


if __name__ == "__main__":
    screenshot_1_intro()
    screenshot_2_result()
    screenshot_3_premium()
    print("\n[DONE] 3 screenshots generated.")
