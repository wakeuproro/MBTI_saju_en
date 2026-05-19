import os
import json
import uuid
import base64
import httpx
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv
from korean_lunar_calendar import KoreanLunarCalendar
import sxtwl

load_dotenv()

# 천간/지지 한글 인덱스 (sxtwl 정수 → 한자)
_GAN_KR = ['갑','을','병','정','무','기','경','신','임','계']
_JI_KR  = ['자','축','인','묘','진','사','오','미','신','유','술','해']


def convert_lunar_to_solar(lunar_date: str, is_leap_month: bool = False) -> str:
    """음력 YYYY-MM-DD → 양력 YYYY-MM-DD 변환"""
    try:
        y, m, d = map(int, lunar_date.split('-'))
        cal = KoreanLunarCalendar()
        cal.setLunarDate(y, m, d, bool(is_leap_month))
        solar = cal.SolarIsoFormat()  # "YYYY-MM-DD"
        if not solar or solar == "0000-00-00":
            raise ValueError("변환 실패")
        return solar
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"음력→양력 변환 실패: {str(e)[:120]}")


def resolve_birth_date(birth_date: str, calendar_type: str = 'solar', is_leap_month: bool = False) -> tuple:
    """입력된 날짜를 항상 양력 기준으로 보정. (solar_date, original_lunar_or_none)"""
    if calendar_type == 'lunar':
        solar = convert_lunar_to_solar(birth_date, is_leap_month)
        return solar, birth_date
    return birth_date, None


def calc_pillars_accurate(year: int, month: int, day: int, hour: int,
                          calendar_type: str = 'solar', is_leap_month: bool = False):
    """
    📿 sxtwl(수신통일력) 기반 정확한 사주 4기둥
    - 24절기 기반 월주 (입춘, 경칩, 청명, 입하 등 정확)
    - 입춘 기준 연주
    - 자시(23:00+) → 다음 날 일주
    - 음력→양력 변환 자동 (korean-lunar-calendar 활용)
    """
    from datetime import date as _date, timedelta as _td

    # 1) 입력을 양력으로 정규화
    if calendar_type == 'lunar':
        cal_conv = KoreanLunarCalendar()
        cal_conv.setLunarDate(year, month, day, bool(is_leap_month))
        solar_str = cal_conv.SolarIsoFormat()
        if not solar_str or solar_str == '0000-00-00':
            raise ValueError(f"음력 변환 실패: {year}-{month}-{day} (윤달={is_leap_month})")
        sy, sm, sd = map(int, solar_str.split('-'))
    else:
        sy, sm, sd = year, month, day

    # 2) 자시 처리: 23시 출생은 양력 +1일
    if hour == 23:
        d = _date(sy, sm, sd) + _td(days=1)
        sy, sm, sd = d.year, d.month, d.day

    # 3) sxtwl로 사주 갑자 계산 (절기 기반 정확)
    day_obj = sxtwl.fromSolar(sy, sm, sd)
    year_gz  = day_obj.getYearGZ()
    month_gz = day_obj.getMonthGZ()
    day_gz   = day_obj.getDayGZ()
    year_p  = (_GAN_KR[year_gz.tg],  _JI_KR[year_gz.dz])
    month_p = (_GAN_KR[month_gz.tg], _JI_KR[month_gz.dz])
    day_p   = (_GAN_KR[day_gz.tg],   _JI_KR[day_gz.dz])

    # 4) 시주: 일간 + 시간 기반 (5호둔)
    time_p = calc_time_pillar(day_p[0], hour)

    return year_p, month_p, day_p, time_p

# Gemini API 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini_model = None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')

# ─────────────────────────────────────────────
# 💳 토스페이먼츠 결제 설정
# 테스트 키 (Toss Payments 공식 문서 공개): 990원 결제 가능, 실제 청구 X
# 실서비스 전환 시 환경변수로 실제 키 주입
# ─────────────────────────────────────────────
TOSS_CLIENT_KEY = os.getenv("TOSS_CLIENT_KEY", "test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq")
TOSS_SECRET_KEY = os.getenv("TOSS_SECRET_KEY", "test_sk_zXLkKEypNArWmo50nX3lmeaxYG5R")
TOSS_PREMIUM_AMOUNT = int(os.getenv("TOSS_PREMIUM_AMOUNT", "990"))
TOSS_IS_TEST = TOSS_SECRET_KEY.startswith("test_")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def read_index():
    return FileResponse("index.html")

@app.get("/privacy")
async def read_privacy():
    return FileResponse("privacy.html")

@app.get("/payment-config")
async def payment_config():
    """프론트에서 토스 결제창 띄울 때 필요한 공개 정보"""
    return {
        "client_key": TOSS_CLIENT_KEY,
        "amount": TOSS_PREMIUM_AMOUNT,
        "is_test": TOSS_IS_TEST,
        "order_name": "사주 × MBTI 프리미엄 분석",
    }

# ═══════════════════════════════════════════════
# 🔮 고퀄리티 정적 기초 데이터 (LLM 프롬프트 보조용)
# ═══════════════════════════════════════════════

ILGAN_NAMES = {
    'ko': {
        '갑': '갑목(甲木)', '을': '을목(乙木)', '병': '병화(丙火)', '정': '정화(丁火)',
        '무': '무토(戊토)', '기': '기토(己土)', '경': '경금(庚金)', '신': '신금(辛金)',
        '임': '임수(壬水)', '계': '계수(癸水)'
    },
    'en': {
        '갑': 'Gap-mok (Yang Wood)', '을': 'Eul-mok (Yin Wood)', '병': 'Byeong-hwa (Yang Fire)', '정': 'Jeong-hwa (Yin Fire)',
        '무': 'Mu-to (Yang Earth)', '기': 'Gi-to (Yin Earth)', '경': 'Gyeong-geum (Yang Metal)', '신': 'Sin-geum (Yin Metal)',
        '임': 'Im-su (Yang Water)', '계': 'Gye-su (Yin Water)'
    }
}

LUCKY_MAP = {
    'ko': {
        '木': {'color': '초록, 에메랄드', 'num': '3, 8', 'dir': '동쪽', 'food': '나물, 샐러드, 녹차'},
        '火': {'color': '빨강, 보라', 'num': '2, 7', 'dir': '남쪽', 'food': '매운 음식, 초콜릿'},
        '土': {'color': '노랑, 베이지', 'num': '5, 10', 'dir': '중앙', 'food': '곡물, 꿀, 고구마'},
        '金': {'color': '흰색, 골드', 'num': '4, 9', 'dir': '서쪽', 'food': '배, 무, 은행'},
        '水': {'color': '검정, 파랑', 'num': '1, 6', 'dir': '북쪽', 'food': '해산물, 수분 많은 과일'},
    },
    'en': {
        '木': {'color': 'Green, Emerald', 'num': '3, 8', 'dir': 'East', 'food': 'Greens, Salad, Green tea'},
        '火': {'color': 'Red, Purple', 'num': '2, 7', 'dir': 'South', 'food': 'Spicy food, Chocolate'},
        '土': {'color': 'Yellow, Beige', 'num': '5, 10', 'dir': 'Center', 'food': 'Grains, Honey, Sweet potato'},
        '金': {'color': 'White, Gold', 'num': '4, 9', 'dir': 'West', 'food': 'Pear, Radish, Ginkgo nuts'},
        '水': {'color': 'Black, Blue', 'num': '1, 6', 'dir': 'North', 'food': 'Seafood, Juicy fruits'},
    }
}

CHEONGAN_OHENG = {'갑': '木', '을': '木', '병': '火', '정': '火', '무': '土', '기': '土', '경': '金', '신': '金', '임': '水', '계': '水'}
JIJI_OHENG = {'자': '水', '축': '土', '인': '木', '묘': '木', '진': '土', '사': '火', '오': '火', '미': '土', '신': '金', '유': '金', '술': '土', '해': '水'}

def calc_year_pillar(year: int):
    CHEONGAN = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
    JIJI = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']
    idx = (year - 4) % 60
    return CHEONGAN[idx % 10], JIJI[idx % 12]

def calc_month_pillar(year: int, month: int):
    CHEONGAN = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
    JIJI = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']
    month_jiji_idx = (month + 1) % 12
    month_jiji = JIJI[month_jiji_idx]
    year_gan_idx = (year - 4) % 10
    base_map = [2, 4, 6, 8, 0]
    group = year_gan_idx % 5
    month_gan_idx = (base_map[group] + month - 1) % 10
    return CHEONGAN[month_gan_idx], month_jiji

def calc_day_pillar(year: int, month: int, day: int):
    CHEONGAN = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
    JIJI = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']
    reference = date(2000, 1, 7)
    target = date(year, month, day)
    diff = (target - reference).days
    idx = diff % 60
    return CHEONGAN[idx % 10], JIJI[idx % 12]

def calc_time_pillar(day_gan: str, hour: int):
    CHEONGAN = ['갑', '을', '병', '정', '무', '기', '경', '신', '임', '계']
    JIJI = ['자', '축', '인', '묘', '진', '사', '오', '미', '신', '유', '술', '해']
    if hour == 23 or hour == 0: jiji_idx = 0
    else: jiji_idx = ((hour + 1) // 2) % 12
    day_gan_idx = CHEONGAN.index(day_gan)
    base_map = [0, 2, 4, 6, 8]
    group = day_gan_idx % 5
    time_gan_idx = (base_map[group] + jiji_idx) % 10
    return CHEONGAN[time_gan_idx], JIJI[jiji_idx]

def analyze_oheng(pillars):
    count = {'木': 0, '火': 0, '土': 0, '金': 0, '水': 0}
    for gan, ji in pillars:
        count[CHEONGAN_OHENG[gan]] += 1
        count[JIJI_OHENG[ji]] += 1
    return count

# ─────────────────────────────────────────────
# ✨ 신살(神煞) 분석
# 도화살/역마살/화개살/장성살 — 일지(또는 년지) 삼합 기준
# 천을귀인 — 일간 기준
# ─────────────────────────────────────────────
SAMHAP_OF = {
    '신': '신자진', '자': '신자진', '진': '신자진',
    '인': '인오술', '오': '인오술', '술': '인오술',
    '사': '사유축', '유': '사유축', '축': '사유축',
    '해': '해묘미', '묘': '해묘미', '미': '해묘미',
}

# 각 삼합 그룹별 신살이 자리하는 지지
DOHWA_MAP    = {'신자진': '유', '인오술': '묘', '사유축': '오', '해묘미': '자'}
YEOKMA_MAP   = {'신자진': '인', '인오술': '신', '사유축': '해', '해묘미': '사'}
HWAGAE_MAP   = {'신자진': '진', '인오술': '술', '사유축': '축', '해묘미': '미'}
JANGSEONG_MAP= {'신자진': '자', '인오술': '오', '사유축': '유', '해묘미': '묘'}

# 천을귀인 (일간 → 해당 지지가 있으면 작동)
CHEONULGWIIN_MAP = {
    '갑': ['축', '미'], '무': ['축', '미'], '경': ['축', '미'],
    '을': ['자', '신'], '기': ['자', '신'],
    '병': ['해', '유'], '정': ['해', '유'],
    '신': ['인', '오'],
    '임': ['묘', '사'], '계': ['묘', '사'],
}

# 백호대살 — 특정 (일간, 일지) 조합. 다른 기둥에 와도 인정
BAEKHO_PAIRS = {('갑','진'), ('을','미'), ('병','술'), ('정','축'),
                ('무','진'), ('임','술'), ('계','축')}

# 양인살 — 일간 → 해당 지지가 사주에 있으면 작동
YANGIN_MAP = {
    '갑': '묘', '을': '진', '병': '오', '정': '미', '무': '오',
    '기': '미', '경': '유', '신': '술', '임': '자', '계': '축'
}

# 재고(財庫) — 일간 → 재성이 들어가는 묘(墓)고 지지
JAEGO_MAP = {
    '갑': '축', '을': '술', '병': '축', '정': '축',
    '무': '진', '기': '진', '경': '미', '신': '미',
    '임': '술', '계': '술',
}

# 문창귀인 — 일간 → 지지
MUNCHANG_MAP = {
    '갑': '사', '을': '오', '병': '신', '정': '유', '무': '신',
    '기': '유', '경': '해', '신': '자', '임': '인', '계': '묘'
}

# 공망 — 일주가 속한 旬(순) 기준 비어있는 2개 지지
GONGMANG_BY_SUN = {
    0: ['술', '해'], 1: ['신', '유'], 2: ['오', '미'],
    3: ['진', '사'], 4: ['인', '묘'], 5: ['자', '축'],
}

def _calc_day_idx_in_60(day_gan, day_ji):
    """일주의 60갑자 인덱스 (0=갑자, 59=계해)"""
    CHEONGAN = ['갑','을','병','정','무','기','경','신','임','계']
    JIJI = ['자','축','인','묘','진','사','오','미','신','유','술','해']
    g_idx = CHEONGAN.index(day_gan)
    j_idx = JIJI.index(day_ji)
    for idx in range(60):
        if idx % 10 == g_idx and idx % 12 == j_idx:
            return idx
    return 0


def calc_gongmang(day_gan, day_ji):
    """일주 기준 공망 지지 2개 반환"""
    day_idx = _calc_day_idx_in_60(day_gan, day_ji)
    sun = day_idx // 10
    return GONGMANG_BY_SUN.get(sun, [])


# ─────────────────────────────────────────────
# 🐉 12지신 띠 분석
# 년지(年支)를 기준으로 띠 결정
# ─────────────────────────────────────────────
ZODIAC_DATA = {
    '자': {
        'icon': '🐭', 'name': '쥐띠', 'hanja': '子',
        'tagline': '영리한 통찰력의 작은 거인',
        'desc': '작은 체구지만 놀라운 통찰력과 재치를 가진 띠. 작은 기회도 놓치지 않는 영민함이 무기예요. 위기 상황에서 누구보다 빠르게 판단하고 움직입니다.',
        'traits': ['영리함', '재치', '적응력'],
        'love': '센스 있는 매력으로 사람을 끌어당겨요. 다만 너무 계산적으로 보일 수 있으니 진심을 표현하는 연습이 필요해요.',
        'career': '기획·마케팅·금융·컨설팅 — 머리 쓰는 일에서 두각',
        'best_match': ['용띠', '원숭이띠'],
        'avoid_match': ['말띠'],
    },
    '축': {
        'icon': '🐂', 'name': '소띠', 'hanja': '丑',
        'tagline': '묵묵히 일하는 성실의 화신',
        'desc': '뚝심 있게 자기 길을 가는 우직한 띠. 화려하진 않아도 시간이 지나면 누구보다 든든한 사람이라는 평을 받아요. 노력한 만큼 결실을 얻는 정직한 사주.',
        'traits': ['성실함', '인내심', '신뢰감'],
        'love': '느리지만 깊게 사랑해요. 화려한 이벤트보다 한결같은 마음으로 신뢰를 쌓아갑니다.',
        'career': '연구·전문직·공무원·농축산업 — 꾸준함이 자산인 분야',
        'best_match': ['뱀띠', '닭띠'],
        'avoid_match': ['양띠'],
    },
    '인': {
        'icon': '🐯', 'name': '호랑이띠', 'hanja': '寅',
        'tagline': '카리스마 넘치는 타고난 리더',
        'desc': '강한 카리스마와 정의감을 타고난 띠. 한번 결심하면 거침없이 밀고 나가는 추진력이 있어요. 주변 사람을 이끄는 자리에서 빛을 발합니다.',
        'traits': ['카리스마', '용기', '정의감'],
        'love': '직진형 연애 스타일. 마음에 들면 망설임 없이 표현해요. 다만 상대의 페이스도 존중해주세요.',
        'career': '경영·리더십·정치·군경 — 권위 있는 자리',
        'best_match': ['말띠', '개띠'],
        'avoid_match': ['원숭이띠'],
    },
    '묘': {
        'icon': '🐰', 'name': '토끼띠', 'hanja': '卯',
        'tagline': '섬세한 감성의 평화주의자',
        'desc': '부드럽고 섬세한 감수성을 타고난 띠. 예술적 감각과 미적 안목이 뛰어나며 사람들과의 조화를 중시합니다. 평화로운 환경에서 더 빛나요.',
        'traits': ['섬세함', '예술성', '온화함'],
        'love': '따뜻하고 다정한 연애를 해요. 갈등을 싫어해서 양보를 많이 하지만, 자기 마음도 챙기세요.',
        'career': '디자인·예술·교육·서비스 — 감성과 미적 감각이 필요한 분야',
        'best_match': ['양띠', '돼지띠'],
        'avoid_match': ['닭띠'],
    },
    '진': {
        'icon': '🐲', 'name': '용띠', 'hanja': '辰',
        'tagline': '하늘을 날아오르는 야망가',
        'desc': '큰 스케일의 야망과 카리스마를 타고난 띠. 평범함을 거부하고 자기만의 길을 개척해요. 위기를 기회로 바꾸는 능력이 탁월합니다.',
        'traits': ['야망', '카리스마', '운'],
        'love': '강렬하고 드라마틱한 연애. 상대를 압도하는 매력이 있지만 가끔 부드러움도 필요해요.',
        'career': '경영·창업·연예·정치 — 큰 무대가 필요한 분야',
        'best_match': ['쥐띠', '원숭이띠'],
        'avoid_match': ['개띠'],
    },
    '사': {
        'icon': '🐍', 'name': '뱀띠', 'hanja': '巳',
        'tagline': '신비로운 직관의 현자',
        'desc': '깊은 직관력과 통찰력을 타고난 띠. 말은 적지만 핵심을 정확히 짚어내는 지혜로움이 있어요. 신비한 매력으로 사람들을 끌어들입니다.',
        'traits': ['직관력', '지혜', '신비로움'],
        'love': '쉽게 마음을 열지 않지만 한번 열면 깊고 강렬해요. 신비로운 매력으로 상대를 매혹시킵니다.',
        'career': '연구·철학·심리·재무 분석 — 깊은 사고가 필요한 분야',
        'best_match': ['소띠', '닭띠'],
        'avoid_match': ['돼지띠'],
    },
    '오': {
        'icon': '🐴', 'name': '말띠', 'hanja': '午',
        'tagline': '자유롭게 달리는 열정가',
        'desc': '에너지가 넘치고 자유로움을 사랑하는 띠. 새로운 도전과 모험을 즐기며 어디서든 활력을 불어넣어요. 한곳에 머물지 못하는 자유로운 영혼.',
        'traits': ['열정', '자유', '활동성'],
        'love': '뜨겁게 시작하지만 빠르게 식기도. 같은 속도로 달릴 수 있는 파트너가 필요해요.',
        'career': '영업·여행·스포츠·미디어 — 움직임이 많고 변화 있는 분야',
        'best_match': ['호랑이띠', '개띠'],
        'avoid_match': ['쥐띠'],
    },
    '미': {
        'icon': '🐑', 'name': '양띠', 'hanja': '未',
        'tagline': '따뜻한 마음의 평화 사절',
        'desc': '온순하고 정이 많은 띠. 사람들과의 조화를 중시하며 갈등을 싫어해요. 예술적 감각과 미적 센스도 뛰어납니다.',
        'traits': ['온순함', '배려심', '예술성'],
        'love': '헌신적이고 다정한 연애 스타일. 너무 양보만 하지 말고 자기 욕구도 표현하세요.',
        'career': '예술·디자인·요리·상담 — 섬세함과 감성이 필요한 분야',
        'best_match': ['토끼띠', '돼지띠'],
        'avoid_match': ['소띠'],
    },
    '신': {
        'icon': '🐒', 'name': '원숭이띠', 'hanja': '申',
        'tagline': '기발한 아이디어의 천재',
        'desc': '재치 있고 영리하며 끝없는 호기심을 가진 띠. 문제를 창의적으로 해결하는 능력이 탁월해요. 사교적이고 어디서든 분위기 메이커가 됩니다.',
        'traits': ['창의성', '재치', '사교성'],
        'love': '재미있고 다채로운 연애. 지루함을 못 견디니 함께 새로운 경험을 만들어가는 파트너가 좋아요.',
        'career': 'IT·창작·엔터테인먼트·기획 — 아이디어가 무기인 분야',
        'best_match': ['쥐띠', '용띠'],
        'avoid_match': ['호랑이띠'],
    },
    '유': {
        'icon': '🐓', 'name': '닭띠', 'hanja': '酉',
        'tagline': '꼼꼼함과 미적 감각의 완벽주의자',
        'desc': '정확하고 꼼꼼한 성격에 미적 감각이 뛰어난 띠. 자기 관리가 철저하고 디테일에 강해요. 책임감 있고 약속을 잘 지킵니다.',
        'traits': ['꼼꼼함', '미적 감각', '책임감'],
        'love': '깔끔하고 정돈된 연애를 추구해요. 상대에게 높은 기준을 요구하니 너그러움도 필요해요.',
        'career': '회계·법률·디자인·요리 — 정확함과 디테일이 중요한 분야',
        'best_match': ['소띠', '뱀띠'],
        'avoid_match': ['토끼띠'],
    },
    '술': {
        'icon': '🐶', 'name': '개띠', 'hanja': '戌',
        'tagline': '의리 있는 충직한 수호자',
        'desc': '의리와 정직함이 트레이드마크인 띠. 한번 친구라고 인정하면 끝까지 함께해요. 정의감이 강하고 약자를 돕는 따뜻한 마음을 가졌습니다.',
        'traits': ['의리', '정직함', '충직함'],
        'love': '진실되고 헌신적인 연애. 한 사람만 깊게 사랑하는 일편단심 스타일이에요.',
        'career': '법률·교육·복지·경찰 — 정의와 신뢰가 필요한 분야',
        'best_match': ['호랑이띠', '말띠'],
        'avoid_match': ['용띠'],
    },
    '해': {
        'icon': '🐷', 'name': '돼지띠', 'hanja': '亥',
        'tagline': '순수하고 풍요로운 복덩이',
        'desc': '순수하고 정이 많으며 사람을 좋아하는 띠. 복이 많고 풍요로운 사주로 알려져 있어요. 솔직하고 꾸밈없는 매력으로 사람들에게 사랑받습니다.',
        'traits': ['순수함', '관대함', '복'],
        'love': '진심으로 사랑하고 표현도 솔직해요. 다만 너무 잘해주다 보면 호구가 될 수 있으니 균형 필요.',
        'career': '요식업·자영업·복지·금융 — 사람을 상대하고 풍요와 연결된 분야',
        'best_match': ['토끼띠', '양띠'],
        'avoid_match': ['뱀띠'],
    },
}


def analyze_zodiac(year_jiji):
    """년지로 띠 정보 반환"""
    data = ZODIAC_DATA.get(year_jiji)
    if not data:
        return None
    return {'key': year_jiji, **data}

SINSAL_DATA = {
    '도화살': {
        'icon': '🌸',
        'name': '도화살 (桃花殺)',
        'type': '매력 · 인기',
        'desc': '복숭아꽃처럼 빛나는 매력의 별. 이성에게 인기가 많고 사람을 끄는 분위기가 있어요. 예술적 감각과 패션 센스도 뛰어나 어디서든 눈에 띕니다.',
        'tip': '매력이 무기지만 한편으론 구설수의 원인이 될 수 있어요. 진짜 인연을 알아보는 안목을 키우세요.'
    },
    '역마살': {
        'icon': '🐎',
        'name': '역마살 (驛馬殺)',
        'type': '이동 · 변화',
        'desc': '한 자리에 머물지 못하는 자유로운 별. 여행·이직·이사가 잦고 새로운 환경에서 더 빛납니다. 글로벌 무대나 출장 잦은 일과 잘 맞아요.',
        'tip': '안정보다 변화에서 기회를 잡는 타입. 한 곳에 갇히기보다 흐름을 따라가세요.'
    },
    '천을귀인': {
        'icon': '⭐',
        'name': '천을귀인 (天乙貴人)',
        'type': '귀인 · 보호',
        'desc': '하늘이 내린 최고의 길성. 위기 때마다 도와주는 귀인을 만나고, 어려운 순간에도 좋은 결과로 이어집니다. 인복을 타고난 사주예요.',
        'tip': '주변 사람을 소중히 하세요. 가장 큰 자산은 사람입니다.'
    },
    '화개살': {
        'icon': '🪷',
        'name': '화개살 (華蓋殺)',
        'type': '예술 · 영성',
        'desc': '연꽃처럼 고고한 정신의 별. 예술·종교·학문·영성에 끌립니다. 깊이 있는 사색과 창작에 능하며 평범함을 거부하는 독특한 매력이 있어요.',
        'tip': '내면이 풍부한 만큼 외로움도 깊을 수 있어요. 자기만의 세계를 가꾸되 고립되지 마세요.'
    },
    '장성살': {
        'icon': '⚔️',
        'name': '장성살 (將星殺)',
        'type': '리더십 · 권위',
        'desc': '장군별. 타고난 리더십과 카리스마의 별입니다. 조직을 이끄는 능력이 뛰어나고 권위 있는 자리에서 빛을 발합니다.',
        'tip': '책임감이 강한 만큼 부담도 클 수 있어요. 가끔은 어깨의 짐을 내려놓고 쉬어가세요.'
    },
    '백호살': {
        'icon': '🐅',
        'name': '백호살 (白虎殺)',
        'type': '추진력 · 카리스마',
        'desc': '백호의 별. 강력한 추진력과 결단력을 타고난 신살입니다. 한번 결심하면 끝까지 밀고 나가는 폭발적 에너지가 있어요. 다만 갑작스러운 변화나 사건사고와도 인연이 있을 수 있어요.',
        'tip': '강한 에너지를 좋은 방향으로 쓰세요. 운전·운동 시 안전 주의, 무리한 추진은 잠시 멈춰가며.'
    },
    '양인살': {
        'icon': '🗡️',
        'name': '양인살 (羊刃殺)',
        'type': '결단력 · 강한 의지',
        'desc': '날카로운 칼날의 별. 의지가 강하고 한번 결정하면 흔들리지 않는 단호함이 있어요. 전문직·기술직·운동선수에게서 자주 발견되며, 경쟁에서 강한 모습을 보입니다.',
        'tip': '칼은 잘 쓰면 명검, 못 쓰면 흉기예요. 강한 자기주장 뒤에는 부드러운 마무리를 잊지 마세요.'
    },
    '공망': {
        'icon': '🕳️',
        'name': '공망 (空亡)',
        'type': '비움 · 정신적 자유',
        'desc': '비어있는 자리의 별. 해당 영역에서 집착을 내려놓아야 오히려 잘 풀려요. 물질보다 정신, 소유보다 경험에 끌리는 자유로운 영혼입니다. 종교·예술·연구 분야와 인연이 깊어요.',
        'tip': '집착하면 더 멀어지고, 놓으면 다가옵니다. 비움의 미학을 즐기세요.'
    },
    '재고': {
        'icon': '💰',
        'name': '재고 (財庫)',
        'type': '재물 창고 · 축적',
        'desc': '재물을 모으는 창고의 별. 큰 돈을 한번에 벌기보다 꾸준히 모아 부를 쌓는 타입이에요. 부동산·저축·자산 관리에 재능이 있고, 노후에 더 풍요로워지는 사주입니다.',
        'tip': '한 방을 노리지 마세요. 작은 돈도 잘 굴리면 큰 자산이 됩니다. 적금·연금이 당신의 친구.'
    },
    '문창귀인': {
        'icon': '📚',
        'name': '문창귀인 (文昌貴人)',
        'type': '학문 · 시험 · 창작',
        'desc': '학문과 글쓰기의 별. 머리가 명석하고 공부·시험에 강한 운을 타고났어요. 작가·교수·연구원·강사에게서 자주 발견되며, 자격증 취득과 시험 합격 운이 좋습니다.',
        'tip': '시험·자격증·자기개발에 적극 도전하세요. 글쓰기·강의·콘텐츠 제작도 잘 어울려요.'
    },
}


def analyze_sinsal(pillars, ilgan):
    """가진 신살만 추출해서 상세 데이터로 반환 (한국 명리 표준)"""
    year_p, month_p, day_p, time_p = pillars
    all_jiji = [p[1] for p in pillars]
    day_jiji = day_p[1]
    other_jiji_no_day = [year_p[1], month_p[1], time_p[1]]

    found = []

    # ────────────────────────────────────────
    # 1) 삼합 기준 — 일지 우선 (도화/역마/화개/장성)
    #    본인 일지가 신살 자리거나, 사주에 그 글자가 있으면 작동
    # ────────────────────────────────────────
    base_group = SAMHAP_OF.get(day_jiji)
    if base_group:
        for name, mp in [
            ('도화살',   DOHWA_MAP),
            ('역마살',   YEOKMA_MAP),
            ('화개살',   HWAGAE_MAP),
            ('장성살',   JANGSEONG_MAP),
        ]:
            target = mp[base_group]
            # 사주 어느 자리든 해당 지지가 있으면 작동 (일지 포함)
            if target in all_jiji:
                found.append(name)

    # ────────────────────────────────────────
    # 2) 천을귀인 — 일간 기준
    # ────────────────────────────────────────
    for t in CHEONULGWIIN_MAP.get(ilgan, []):
        if t in all_jiji:
            found.append('천을귀인')
            break

    # ────────────────────────────────────────
    # 3) 문창귀인 — 일간 기준
    # ────────────────────────────────────────
    munchang_target = MUNCHANG_MAP.get(ilgan)
    if munchang_target and munchang_target in all_jiji:
        found.append('문창귀인')

    # ────────────────────────────────────────
    # 4) 양인살 — 양일간(갑·병·무·경·임)만 적용
    #    음일간은 양인 적용 X (전통 명리 표준)
    # ────────────────────────────────────────
    YANG_GAN = {'갑', '병', '무', '경', '임'}
    if ilgan in YANG_GAN:
        yangin_target = YANGIN_MAP.get(ilgan)
        if yangin_target and yangin_target in all_jiji:
            found.append('양인살')

    # ────────────────────────────────────────
    # 5) 재고(財庫) — 일간 기준
    # ────────────────────────────────────────
    jaego_target = JAEGO_MAP.get(ilgan)
    if jaego_target and jaego_target in all_jiji:
        found.append('재고')

    # ────────────────────────────────────────
    # 6) 백호살 — 일주 한정 (전통 명리는 일주만, 시주는 약하게)
    # ────────────────────────────────────────
    if (day_p[0], day_p[1]) in BAEKHO_PAIRS:
        found.append('백호살')

    # ────────────────────────────────────────
    # 7) 공망 — 일주 旬(순) 기준 지지가 다른 기둥에 있으면 작동
    # ────────────────────────────────────────
    gongmang_jiji = calc_gongmang(day_p[0], day_p[1])
    if any(j in gongmang_jiji for j in other_jiji_no_day):
        found.append('공망')

    return [{'key': k, **SINSAL_DATA[k]} for k in found]

# ═══════════════════════════════════════════════
# 🔮 정적 분석 데이터 로드 (LLM 대체용)
# ═══════════════════════════════════════════════

def load_analysis_data():
    try:
        with open("saju_mbti_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Data Load Error: {e}")
        return None

ANALYSIS_DATA = load_analysis_data()

async def get_report_analysis(birth_date: str, birth_time: str, mbti: str, lang: str = 'ko',
                              calendar_type: str = 'solar', is_leap_month: bool = False):
    # 음력 입력 시 양력 변환 (응답 메타용)
    solar_date, lunar_original = resolve_birth_date(birth_date, calendar_type, is_leap_month)
    # 원본 입력 그대로 라이브러리에 넣어 계산 (음력은 음력대로)
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    year, month, day = map(int, solar_date.split('-'))
    hour = int(birth_time.split(':')[0])

    # 📿 정확한 사주 (24절기 + 자시 + 라이브러리 기반)
    year_p, month_p, day_p, time_p = calc_pillars_accurate(
        raw_y, raw_m, raw_d, hour, calendar_type, is_leap_month
    )

    pillars = [year_p, month_p, day_p, time_p]
    oheng = analyze_oheng(pillars)
    ilgan = day_p[0]
    ilgan_name_lang = ILGAN_NAMES.get(lang, ILGAN_NAMES['ko'])[ilgan]

    # ✨ 신살 분석
    sinsal = analyze_sinsal(pillars, ilgan)

    # 🐉 12지신 띠 분석 (년지 기준)
    zodiac = analyze_zodiac(year_p[1])

    weakest_oheng = min(oheng, key=oheng.get)
    current_lucky_map = LUCKY_MAP.get(lang, LUCKY_MAP['ko'])
    lucky = current_lucky_map[weakest_oheng]

    # 정적 데이터를 이용한 분석 생성
    if ANALYSIS_DATA:
        # 1. 핵심 기운 분석
        ilgan_data = ANALYSIS_DATA["ilgan_analysis"].get(ilgan, {"title": ilgan_name_lang, "desc": f"{ilgan_name_lang}의 기운을 타고나셨군요."})

        # 2. 사주 & MBTI 시너지 (일간+MBTI 조합 데이터 우선, 없으면 글자별 조합)
        combo_key = f"{ilgan}_{mbti}"
        combo_data = ANALYSIS_DATA.get("ilgan_mbti_combinations", {}).get(combo_key)
        if combo_data:
            synergy_title = combo_data["title"]
            synergy_desc = combo_data["desc"]
        else:
            synergy_desc = f"{ilgan_name_lang}의 기운과 {mbti} 성향이 조화롭게 어우러집니다. "
            for char in mbti:
                synergy_desc += ANALYSIS_DATA["synergy_base"].get(char, "") + " "
            synergy_title = f"{ilgan_name_lang} x {mbti} 시너지"
            synergy_desc = synergy_desc.strip()

        # 3. 최고의 궁합
        comp_data = ANALYSIS_DATA["compatibility_data"].get(ilgan, {"types": ["특정 유형"], "desc": "당신과 잘 맞는 인연이 기다리고 있습니다."})
        comp_types = ", ".join(comp_data["types"])

        # 4. 상세 섹션 데이터 (ilgan_detailed)
        detailed = ANALYSIS_DATA.get("ilgan_detailed", {}).get(ilgan, {})

        # 5. MBTI 연애 스타일
        mbti_love = ANALYSIS_DATA.get("mbti_love_style", {}).get(mbti, {})

        # 6. 일간+MBTI 조합 상세 (강점, 약점, 커리어, 성장팁)
        combo_detail = {}
        if combo_data:
            combo_detail = {
                "strength": combo_data.get("strength", ""),
                "weakness": combo_data.get("weakness", ""),
                "career": combo_data.get("career", ""),
                "growth_tip": combo_data.get("growth_tip", "")
            }

        # 7. 계절 운세
        ilgan_oheng = CHEONGAN_OHENG[ilgan]
        fortune = ANALYSIS_DATA.get("monthly_fortune_base", {}).get(ilgan_oheng, {})

        analysis = {
            "ilgan_title": ilgan_data["title"],
            "ilgan_desc": ilgan_data["desc"],
            "synergy_title": synergy_title,
            "synergy_desc": synergy_desc,
            "compatibility_title": f"최고의 궁합: {comp_types}",
            "compatibility_desc": comp_data["desc"]
        }
    else:
        detailed = {}
        mbti_love = {}
        combo_detail = {}
        fortune = {}
        analysis = {
            "ilgan_title": ilgan_name_lang,
            "ilgan_desc": f"{ilgan_name_lang}의 기운을 타고나셨군요. (데이터 로드 실패)",
            "synergy_title": f"{ilgan_name_lang} x {mbti}",
            "synergy_desc": "두 기운이 조화롭게 어우러져 당신만의 독특한 매력을 만들어냅니다.",
            "compatibility_title": "추천 궁합",
            "compatibility_desc": "당신의 포용력을 이해해줄 수 있는 유형과 좋은 인연이 될 것입니다."
        }

    # 결과 섹션 설정
    result_sections = ANALYSIS_DATA.get("result_sections", []) if ANALYSIS_DATA else []
    payment_config = ANALYSIS_DATA.get("payment_config", {}) if ANALYSIS_DATA else {}

    return {
        'pillars': {
            'year': {'gan': year_p[0], 'ji': year_p[1], 'label': f'{year_p[0]}{year_p[1]}'},
            'month': {'gan': month_p[0], 'ji': month_p[1], 'label': f'{month_p[0]}{month_p[1]}'},
            'day': {'gan': day_p[0], 'ji': day_p[1], 'label': f'{day_p[0]}{day_p[1]}'},
            'time': {'gan': time_p[0], 'ji': time_p[1], 'label': f'{time_p[0]}{time_p[1]}'},
        },
        'ilgan': {'name': ilgan_name_lang, 'title': analysis['ilgan_title'], 'desc': analysis['ilgan_desc']},
        'oheng': oheng,
        'mbti': mbti,
        'synergy': {'title': analysis['synergy_title'], 'desc': analysis['synergy_desc']},
        'compatibility': {'title': analysis['compatibility_title'], 'desc': analysis['compatibility_desc']},
        'lucky': lucky,
        'sinsal': sinsal,
        'zodiac': zodiac,
        'calendar_info': {
            'type': calendar_type,
            'solar_date': solar_date,
            'lunar_date': lunar_original,
            'is_leap_month': is_leap_month if calendar_type == 'lunar' else False,
        },
        'detailed': detailed,
        'mbti_love': mbti_love,
        'combo_detail': combo_detail,
        'fortune': fortune,
        'result_sections': result_sections,
        'payment_config': payment_config
    }

class ReportInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'
    name: str = ''
    gender: str = 'F'  # 'F' or 'M'
    time_unknown: bool = False
    calendar_type: str = 'solar'   # 'solar' | 'lunar'
    is_leap_month: bool = False    # 음력 윤달 여부

class PremiumReportInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False

class PaidPremiumInput(BaseModel):
    # 분석에 필요한 입력
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False
    # 토스 결제 정보
    paymentKey: str
    orderId: str
    amount: int

class PaymentCreditInput(BaseModel):
    paymentKey: str
    orderId: str
    amount: int
    product: str  # 'additional' | 'compatibility' | 'yearly'

class PersonInput(BaseModel):
    name: str = ''
    gender: str = 'F'
    birth_date: str
    birth_time: str = '12:00'
    mbti: str
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False

class CompatibilityInput(BaseModel):
    person_a: PersonInput
    person_b: PersonInput
    # 결제 정보 (옵셔널 — 결제 검증 후 호출 시)
    paymentKey: str = ''
    orderId: str = ''
    amount: int = 0

class YearlyFortuneInput(BaseModel):
    birth_date: str
    birth_time: str = '12:00'
    mbti: str
    name: str = ''
    gender: str = 'F'
    target_year: int = 2026
    calendar_type: str = 'solar'
    is_leap_month: bool = False
    # 결제 정보
    paymentKey: str = ''
    orderId: str = ''
    amount: int = 0

@app.post("/get-report")
async def get_report(input_data: ReportInput):
    try:
        report = await get_report_analysis(
            input_data.birth_date, input_data.birth_time, input_data.mbti, input_data.lang,
            calendar_type=input_data.calendar_type, is_leap_month=input_data.is_leap_month
        )
        return report
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ═══════════════════════════════════════════════
# 💎 프리미엄 LLM 분석 (유료)
# ═══════════════════════════════════════════════

PREMIUM_PROMPT_TEMPLATE = """당신은 30년 경력의 명리학 전문가이자 MBTI 전문 상담사입니다.
아래 사주 정보와 MBTI를 바탕으로, 이 사람만을 위한 깊이 있는 사주 해석을 작성해주세요.

[사주 정보]
- 생년월일: {birth_date}
- 태어난 시간: {birth_time}
- 사주 팔자: 년주({year_p}) 월주({month_p}) 일주({day_p}) 시주({time_p})
- 일간: {ilgan_name}
- 오행 분포: 木={oh_wood} 火={oh_fire} 土={oh_earth} 金={oh_metal} 水={oh_water}
- MBTI: {mbti}

[작성 규칙]
1. 반드시 사주 원국 8글자의 관계(충, 합, 형, 파, 생, 극)를 분석하세요
2. MBTI 성향과 사주 기운이 어떻게 시너지/충돌하는지 연결하세요
3. 존댓말로, 따뜻하지만 솔직하게 말하세요
4. 비유와 은유를 풍부하게 사용하되 과장은 금지
5. 각 섹션은 3~5문장으로 작성하세요

[출력 형식 - 반드시 아래 JSON 형식으로만 응답]
{{
  "deep_personality": {{
    "title": "이 사람의 본질을 한 문장으로",
    "desc": "사주 원국 전체를 읽은 성격 분석 (팔자 8글자 관계 포함)"
  }},
  "hidden_pattern": {{
    "title": "숨겨진 패턴 제목",
    "desc": "일반 분석에서는 보이지 않는, 충/합/형 등 특수 관계 해석"
  }},
  "life_turning_point": {{
    "title": "인생 전환점 제목",
    "desc": "대운/세운 흐름에서 주목할 시기와 조언"
  }},
  "deep_love": {{
    "title": "깊은 연애/인연 분석 제목",
    "desc": "사주 원국 기반의 연애 패턴과 배우자운 분석"
  }},
  "deep_wealth": {{
    "title": "재물/사업운 심층 분석 제목",
    "desc": "재성의 위치와 상태에 따른 재물 흐름 분석"
  }},
  "advice": {{
    "title": "명리학자가 전하는 한마디",
    "desc": "이 사주를 가진 사람에게 꼭 해주고 싶은 핵심 조언"
  }}
}}"""

def _build_premium_payload(birth_date: str, birth_time: str, mbti: str,
                           calendar_type: str = 'solar', is_leap_month: bool = False):
    """프리미엄 분석 콘텐츠 생성 (라이프스타일 + Gemini 심층)"""
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    hour = int(birth_time.split(':')[0])

    # 📿 정확한 사주
    year_p, month_p, day_p, time_p = calc_pillars_accurate(
        raw_y, raw_m, raw_d, hour, calendar_type, is_leap_month
    )

    pillars = [year_p, month_p, day_p, time_p]
    oheng = analyze_oheng(pillars)
    ilgan = day_p[0]
    ilgan_name = ILGAN_NAMES['ko'][ilgan]

    # 1) JSON 기반 라이프스타일
    ilgan_detailed = ANALYSIS_DATA.get("ilgan_detailed", {}).get(ilgan, {}) if ANALYSIS_DATA else {}
    lifestyle = {
        "fengshui": ilgan_detailed.get("fengshui"),
        "accessory": ilgan_detailed.get("accessory"),
        "scent": ilgan_detailed.get("scent"),
    }

    # 2) Gemini 심층 분석 (옵셔널)
    premium_data = None
    ai_error = None
    if gemini_model:
        try:
            prompt = PREMIUM_PROMPT_TEMPLATE.format(
                birth_date=birth_date,
                birth_time=birth_time,
                year_p=f"{year_p[0]}{year_p[1]}",
                month_p=f"{month_p[0]}{month_p[1]}",
                day_p=f"{day_p[0]}{day_p[1]}",
                time_p=f"{time_p[0]}{time_p[1]}",
                ilgan_name=ilgan_name,
                oh_wood=oheng['木'], oh_fire=oheng['火'], oh_earth=oheng['土'],
                oh_metal=oheng['金'], oh_water=oheng['水'],
                mbti=mbti
            )
            response = gemini_model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
            premium_data = json.loads(text)
        except Exception as e:
            ai_error = f"AI 심층 분석은 일시적으로 사용할 수 없어요. (사유: {str(e)[:80]}…)"
    else:
        ai_error = "AI 심층 분석 키가 아직 연결되지 않았어요. 라이프스타일 추천은 정상 제공됩니다."

    return {
        "status": "ok",
        "premium": premium_data,
        "lifestyle": lifestyle,
        "ai_error": ai_error,
    }


@app.post("/get-premium-report")
async def get_premium_report(input_data: PremiumReportInput):
    """결제 검증 없이 프리미엄 콘텐츠 반환 (개발/내부용)"""
    try:
        return _build_premium_payload(input_data.birth_date, input_data.birth_time, input_data.mbti,
                                       calendar_type=input_data.calendar_type, is_leap_month=input_data.is_leap_month)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _verify_toss_payment(payment_key: str, order_id: str, amount: int) -> dict:
    """토스페이먼츠 결제 승인 호출 후 검증된 결제 정보 반환"""
    auth = base64.b64encode(f"{TOSS_SECRET_KEY}:".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tosspayments.com/v1/payments/confirm",
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
                json={
                    "paymentKey": payment_key,
                    "orderId": order_id,
                    "amount": amount,
                },
            )
        if resp.status_code != 200:
            err = {}
            try:
                err = resp.json()
            except Exception:
                pass
            msg = err.get("message", resp.text[:200])
            raise HTTPException(status_code=400, detail=f"결제 검증 실패: {msg}")

        toss_result = resp.json()
        if toss_result.get("status") not in ("DONE", "WAITING_FOR_DEPOSIT"):
            raise HTTPException(status_code=400, detail=f"결제 상태 비정상: {toss_result.get('status')}")
        return toss_result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"결제 검증 중 오류: {str(e)[:200]}")


# 상품별 정가 (위/변조 방어용)
PRODUCT_PRICES = {
    "premium": TOSS_PREMIUM_AMOUNT,  # 990
    "additional": 990,
    "compatibility": 1900,
    "yearly": 2900,
}


@app.post("/confirm-and-get-premium")
async def confirm_and_get_premium(data: PaidPremiumInput):
    """토스 결제 검증 → 통과 시 프리미엄 콘텐츠 반환"""
    if data.amount != TOSS_PREMIUM_AMOUNT:
        raise HTTPException(status_code=400, detail=f"잘못된 결제 금액입니다. (요청: {data.amount}원, 정가: {TOSS_PREMIUM_AMOUNT}원)")

    toss_result = await _verify_toss_payment(data.paymentKey, data.orderId, data.amount)

    try:
        payload = _build_premium_payload(data.birth_date, data.birth_time, data.mbti,
                                          calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
        payload["payment"] = {
            "approved_at": toss_result.get("approvedAt"),
            "order_id": data.orderId,
            "amount": data.amount,
            "method": toss_result.get("method"),
            "is_test": TOSS_IS_TEST,
        }
        return payload
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"분석 생성 실패: {str(e)[:200]}")


# ─────────────────────────────────────────────
# 💑 두 사람 궁합 분석 (1,900원)
# ─────────────────────────────────────────────

# 오행 상생/상극 관계 (생: +2, 극: -1, 같음: +1)
OHENG_SAENG = {'木':'火', '火':'土', '土':'金', '金':'水', '水':'木'}  # 생
OHENG_GEUK  = {'木':'土', '土':'水', '水':'火', '火':'金', '金':'木'}  # 극

def oheng_relation_score(a_oheng, b_oheng):
    """일간 오행 기준 관계 점수"""
    if a_oheng == b_oheng:
        return 70, "비슷한 결, 편안한 사이"
    if OHENG_SAENG.get(a_oheng) == b_oheng:
        return 90, f"{a_oheng}이(가) {b_oheng}을(를) 키워주는 사이"
    if OHENG_SAENG.get(b_oheng) == a_oheng:
        return 90, f"{b_oheng}이(가) {a_oheng}을(를) 키워주는 사이"
    if OHENG_GEUK.get(a_oheng) == b_oheng:
        return 50, f"{a_oheng}이(가) {b_oheng}을(를) 제어하는 긴장 관계"
    if OHENG_GEUK.get(b_oheng) == a_oheng:
        return 50, f"{b_oheng}이(가) {a_oheng}을(를) 제어하는 긴장 관계"
    return 75, "조화롭게 어우러지는 관계"


# 띠 궁합 (간단 매핑 — 삼합/육합/육충 기반)
SAMHAP_GROUPS_LIST = [
    ['신','자','진'], ['인','오','술'], ['사','유','축'], ['해','묘','미']
]
YUKCHUNG = {'자':'오','오':'자', '축':'미','미':'축', '인':'신','신':'인',
            '묘':'유','유':'묘', '진':'술','술':'진', '사':'해','해':'사'}

def zodiac_relation(a_jiji, b_jiji):
    if a_jiji == b_jiji:
        return 75, "같은 띠 — 닮은 점이 많아 공감대 형성에 좋음"
    if YUKCHUNG.get(a_jiji) == b_jiji:
        return 45, "육충(六冲) — 정반대 성향이 부딪힐 수 있지만 자극이 큼"
    for group in SAMHAP_GROUPS_LIST:
        if a_jiji in group and b_jiji in group:
            return 95, "삼합(三合) — 천생연분급 환상의 조합"
    return 70, "무난한 띠 조합"


# MBTI 궁합 매핑 (간단)
MBTI_BEST = {
    'INTJ':['ENFP','ENTP'], 'INTP':['ENTJ','ENFJ'],
    'ENTJ':['INTP','INFP'], 'ENTP':['INTJ','INFJ'],
    'INFJ':['ENTP','ENFP'], 'INFP':['ENTJ','ENFJ'],
    'ENFJ':['INTP','INFP'], 'ENFP':['INTJ','INFJ'],
    'ISTJ':['ESFP','ESTP'], 'ISFJ':['ESFP','ESTP'],
    'ESTJ':['ISFP','ISTP'], 'ESFJ':['ISFP','ISTP'],
    'ISTP':['ESFJ','ESTJ'], 'ISFP':['ESFJ','ENFJ'],
    'ESTP':['ISFJ','ISTJ'], 'ESFP':['ISFJ','ISTJ'],
}

def mbti_relation(a_mbti, b_mbti):
    if a_mbti == b_mbti:
        return 70, "같은 MBTI — 서로의 패턴을 본능적으로 이해"
    if b_mbti in MBTI_BEST.get(a_mbti, []):
        return 95, "MBTI 황금 궁합 — 서로를 보완하는 환상 짝"
    # 같은 NF/NT/SF/ST 가족
    if a_mbti[1:3] == b_mbti[1:3]:
        return 80, "비슷한 사고·가치관 — 대화가 잘 통하는 사이"
    if a_mbti[2:] == b_mbti[2:]:
        return 75, "공감 코드 일치 — 감정선이 비슷한 편"
    return 65, "다른 색깔이 만나 서로를 배우는 관계"


def calc_compatibility(person_a: dict, person_b: dict) -> dict:
    """두 사람 사주 + MBTI 궁합 분석"""
    def make_profile(p):
        raw_y, raw_m, raw_d = map(int, p['birth_date'].split('-'))
        h = int(p['birth_time'].split(':')[0])
        cal_type = p.get('calendar_type', 'solar')
        leap = p.get('is_leap_month', False)
        # 📿 정확한 사주
        yp, mp, dp, tp = calc_pillars_accurate(raw_y, raw_m, raw_d, h, cal_type, leap)
        # 양력 변환 (메타용)
        y, m, dd = map(int, resolve_birth_date(p['birth_date'], cal_type, leap)[0].split('-'))
        ilgan = dp[0]
        return {
            'name': p.get('name') or '익명',
            'gender': p.get('gender','F'),
            'ilgan': ilgan,
            'ilgan_name': ILGAN_NAMES['ko'][ilgan],
            'ilgan_oheng': CHEONGAN_OHENG[ilgan],
            'year_jiji': yp[1],
            'pillars': {'year':yp,'month':mp,'day':dp,'time':tp},
            'mbti': p['mbti'],
        }

    a = make_profile(person_a)
    b = make_profile(person_b)

    # 1) 오행 궁합
    oh_score, oh_desc = oheng_relation_score(a['ilgan_oheng'], b['ilgan_oheng'])
    # 2) 띠 궁합
    z_score, z_desc = zodiac_relation(a['year_jiji'], b['year_jiji'])
    # 3) MBTI 궁합
    m_score, m_desc = mbti_relation(a['mbti'], b['mbti'])

    total = round(oh_score * 0.4 + z_score * 0.3 + m_score * 0.3)

    # 종합 등급
    if total >= 90: grade, grade_emoji, grade_desc = 'S', '💎', '천생연분급 — 평생 함께해도 좋을 환상의 케미'
    elif total >= 80: grade, grade_emoji, grade_desc = 'A', '⭐', '환상적 — 서로를 빛나게 해주는 관계'
    elif total >= 70: grade, grade_emoji, grade_desc = 'B', '🌟', '좋아요 — 노력으로 더 깊어질 사이'
    elif total >= 60: grade, grade_emoji, grade_desc = 'C', '✨', '평범 — 노력과 이해가 필요한 관계'
    else: grade, grade_emoji, grade_desc = 'D', '⚡', '도전적 — 차이를 인정하고 배워가는 사이'

    return {
        'person_a': a,
        'person_b': b,
        'total_score': total,
        'grade': grade,
        'grade_emoji': grade_emoji,
        'grade_desc': grade_desc,
        'details': [
            {'label': '오행 궁합 (일간 기준)', 'score': oh_score, 'desc': oh_desc, 'weight': '40%'},
            {'label': '띠 궁합 (년지 기준)', 'score': z_score, 'desc': z_desc, 'weight': '30%'},
            {'label': 'MBTI 궁합', 'score': m_score, 'desc': m_desc, 'weight': '30%'},
        ],
        'advice': _build_compatibility_advice(a, b, total),
    }


def _build_compatibility_advice(a, b, score):
    """간단한 관계 조언"""
    a_oh = a['ilgan_oheng']
    b_oh = b['ilgan_oheng']
    oh_names = {'木':'목(나무)', '火':'화(불)', '土':'토(흙)', '金':'금(금속)', '水':'수(물)'}
    base = f"{a['name']}님({oh_names[a_oh]} 일간)과 {b['name']}님({oh_names[b_oh]} 일간)은 "
    if score >= 80:
        return base + "오행 흐름과 성향이 자연스럽게 맞아 큰 노력 없이도 편안한 관계를 유지할 수 있어요. 다만 익숙함에 안주하지 말고 작은 이벤트로 신선함을 유지하세요."
    elif score >= 70:
        return base + "기본 케미는 좋은 편이에요. 서로의 다른 점을 흥미롭게 봐주고, 가끔 작은 갈등이 와도 대화로 풀면 더 깊어집니다."
    elif score >= 60:
        return base + "성향 차이가 있어 처음엔 어색할 수 있어요. 서로의 다름을 인정하면 오히려 보완하는 관계가 됩니다. 인내심이 필요해요."
    else:
        return base + "기질적으로 도전적인 조합이에요. 하지만 어려운 관계가 깊은 관계가 되기도 합니다. 서로의 차이를 강점으로 바꿀 수 있는 대화가 핵심."


@app.post("/get-compatibility-preview")
async def get_compatibility_preview(data: CompatibilityInput):
    """미리보기 (점수만, 무료) — 결제 유도용"""
    result = calc_compatibility(data.person_a.dict(), data.person_b.dict())
    # 상세 항목 가리고 점수+등급만 노출
    return {
        'total_score': result['total_score'],
        'grade': result['grade'],
        'grade_emoji': result['grade_emoji'],
        'grade_desc': result['grade_desc'],
        'person_a_summary': {'name': result['person_a']['name'], 'ilgan': result['person_a']['ilgan_name'], 'mbti': result['person_a']['mbti']},
        'person_b_summary': {'name': result['person_b']['name'], 'ilgan': result['person_b']['ilgan_name'], 'mbti': result['person_b']['mbti']},
        'locked': True,
        'unlock_price': PRODUCT_PRICES['compatibility'],
    }


@app.post("/confirm-and-get-compatibility")
async def confirm_and_get_compatibility(data: CompatibilityInput):
    """토스 결제 검증 → 통과 시 궁합 상세 반환"""
    expected = PRODUCT_PRICES['compatibility']
    if data.amount != expected:
        raise HTTPException(status_code=400, detail=f"잘못된 결제 금액 (요청: {data.amount}원, 정가: {expected}원)")

    await _verify_toss_payment(data.paymentKey, data.orderId, data.amount)

    result = calc_compatibility(data.person_a.dict(), data.person_b.dict())
    result['unlocked'] = True
    return result


# ─────────────────────────────────────────────
# 📅 월별 운세 (2,900원)
# ─────────────────────────────────────────────

MONTH_THEMES_BY_OHENG = {
    '木': {  # 일간이 목
        1: ('새싹의 결심', '한 해 목표를 세우기 좋은 달. 너무 욕심내지 말고 한 가지 핵심에 집중하세요.'),
        2: ('뿌리 다지기', '기반을 다지는 시기. 새로운 인맥보다 기존 관계 관리에 집중하면 좋습니다.'),
        3: ('성장의 봄', '본격적인 도약기. 미뤄둔 계획을 실행에 옮길 최적의 시기예요.'),
        4: ('가지를 뻗다', '활동 반경을 넓힐 때. 출장·교류·이직 검토에 우호적입니다.'),
        5: ('꽃 피우다', '결실의 전조가 보이는 달. 협업과 파트너십에서 행운이 따릅니다.'),
        6: ('잎이 무성', '에너지 충만한 달. 단, 과로 주의. 휴식과 운동 병행 필수.'),
        7: ('태양 아래', '재능을 알리고 인정받을 기회. 적극적인 자기 홍보를 추천.'),
        8: ('열매 익다', '그간의 노력이 보상으로 돌아오는 달. 금전 운 양호.'),
        9: ('가을의 정돈', '계획을 점검하고 군더더기 정리. 인간관계도 슬림화하세요.'),
        10: ('단풍의 결실', '한 분야의 마무리를 짓고 새로운 도전 준비.'),
        11: ('낙엽의 휴식', '안으로 들어가 회복하는 달. 무리한 결정 보류.'),
        12: ('겨울의 저장', '내년을 위한 학습·휴식. 큰 지출은 자제하세요.'),
    },
    '火': {
        1: ('불꽃의 시작', '의욕 폭발하는 달. 새 도전이 좋지만 사람과 부딪힘 주의.'),
        2: ('열기 모으기', '하나에 집중하기 좋은 시기. 다중 작업은 피하세요.'),
        3: ('활활 타오름', '인기와 주목이 따르는 달. 사교 활동에 우호적.'),
        4: ('태양 정점', '리더십 발휘의 최적기. 발표·면접·승부에 강함.'),
        5: ('축제의 달', '연애·사교·창작 모두 좋은 시기. 표현력 최고.'),
        6: ('과열 주의', '에너지가 너무 강해 충돌 가능. 한 박자 쉬어가세요.'),
        7: ('빛이 깊어짐', '진정성 있는 관계가 깊어지는 달.'),
        8: ('석양의 따뜻함', '나누고 베푸는 활동에서 보람을 얻어요.'),
        9: ('등불의 시기', '집중·연구에 좋은 달. 자기 계발 추천.'),
        10: ('숯의 안정', '드러나지 않게 실력을 쌓는 시기.'),
        11: ('잿불의 휴식', '깊은 사색과 명상이 도움. 결정은 보류.'),
        12: ('등불 켜기', '내면의 빛을 다시 켜는 달. 가족과의 시간 ↑.'),
    },
    '土': {
        1: ('대지의 봄 준비', '기초를 다지는 시기. 부동산·자산 점검에 우호적.'),
        2: ('씨앗 심기', '장기 계획을 세우기 좋은 달. 신중한 결정을.'),
        3: ('토양 정비', '환경 정리·이사·인테리어에 좋은 시기.'),
        4: ('새싹 돕기', '주변을 챙기는 행동이 복으로 돌아오는 달.'),
        5: ('풍요의 시작', '재물·인덕이 함께 들어오는 시기.'),
        6: ('수확 준비', '결과물을 정리하고 평가받는 달.'),
        7: ('황금 들판', '재물운 최고조. 부동산·투자 검토 OK.'),
        8: ('곡식 거두기', '구체적 성과가 손에 잡히는 달.'),
        9: ('창고 채우기', '저축·자산 관리에 우호적. 큰 지출 자제.'),
        10: ('대지의 휴식', '내실 다지기. 인간관계 정리도 좋은 시기.'),
        11: ('얼어붙는 땅', '활동 자제하고 내면 충전. 건강 관리 ↑.'),
        12: ('봄을 기다림', '내년 큰 그림을 그리는 사색의 시기.'),
    },
    '金': {
        1: ('칼날의 점검', '체계와 원칙을 세우기 좋은 시기. 정리정돈에 우호적.'),
        2: ('단련의 달', '실력 연마·자격증 도전에 유리.'),
        3: ('결단의 시기', '중요한 결정을 내리기 좋은 달. 우유부단 X.'),
        4: ('연마된 빛', '실력이 인정받기 시작하는 시기.'),
        5: ('투쟁의 봄', '경쟁 상황에서 강함. 승부 기회 적극 활용.'),
        6: ('차분한 정돈', '시끄러움에서 거리두기. 혼자만의 시간 필요.'),
        7: ('수확의 가을', '오래 준비한 일의 결실이 보이는 달.'),
        8: ('명검의 시기', '금(金)의 최절정. 권위·승진·계약에 강함.'),
        9: ('마무리의 달', '한 사이클을 깔끔히 닫고 정산하는 시기.'),
        10: ('서리 내림', '날카로움 ↑. 인간관계 갈등 주의.'),
        11: ('얼음의 강함', '결정력 최고지만 차갑게 보일 수 있음. 부드러움 필요.'),
        12: ('재단의 시기', '내년 계획을 정밀하게 짜는 달.'),
    },
    '水': {
        1: ('얼음 아래 흐름', '드러나지 않게 준비하는 시기. 학습·연구 우호적.'),
        2: ('해빙의 시작', '얼었던 일들이 풀리기 시작. 인간관계 회복 ↑.'),
        3: ('샘물이 솟다', '직관과 영감이 강해지는 달. 창작·기획에 강함.'),
        4: ('시냇물 흐름', '새로운 사람과의 인연. 네트워킹 적극 권장.'),
        5: ('강이 넓어짐', '활동 반경 확대. 여행·이동에 우호적.'),
        6: ('수원지 충만', '에너지가 가장 풍부한 시기. 큰 일 도전 OK.'),
        7: ('호수의 깊이', '내면이 깊어지는 달. 통찰과 지혜가 빛남.'),
        8: ('파도의 변화', '갑작스러운 변화 가능. 유연하게 대응.'),
        9: ('가을 비', '감정이 풍부해지는 시기. 예술·문학과의 인연.'),
        10: ('서리의 결정', '재정 정리·관계 정리에 좋은 달.'),
        11: ('겨울 강', '내면 깊이 침잠. 명상·휴식 권장.'),
        12: ('얼음의 결정', '한 해를 정리하고 응축하는 시기.'),
    },
}

def build_yearly_fortune(birth_date: str, birth_time: str, mbti: str, year: int,
                          calendar_type: str = 'solar', is_leap_month: bool = False):
    """년주의 오행 흐름과 사용자 일간을 비교한 월별 운세"""
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    h = int(birth_time.split(':')[0])
    # 📿 정확한 사주
    _yp, _mp, dp, _tp = calc_pillars_accurate(raw_y, raw_m, raw_d, h, calendar_type, is_leap_month)
    ilgan = dp[0]
    ilgan_oheng = CHEONGAN_OHENG[ilgan]
    ilgan_name = ILGAN_NAMES['ko'][ilgan]

    base_themes = MONTH_THEMES_BY_OHENG.get(ilgan_oheng, MONTH_THEMES_BY_OHENG['木'])

    # 12개 월별 데이터
    MONTH_LABELS = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']
    SEASON = {'봄':[3,4,5],'여름':[6,7,8],'가을':[9,10,11],'겨울':[12,1,2]}
    def season_of(mon):
        for s, ms in SEASON.items():
            if mon in ms: return s
        return ''

    months = []
    for mon in range(1, 13):
        title, desc = base_themes[mon]
        target_p = calc_month_pillar(year, mon)
        months.append({
            'month': mon,
            'label': MONTH_LABELS[mon-1],
            'season': season_of(mon),
            'pillar': f'{target_p[0]}{target_p[1]}',
            'pillar_oheng': CHEONGAN_OHENG[target_p[0]],
            'title': title,
            'desc': desc,
        })

    # 베스트/주의 월 표시
    luck_scores = []
    for mo in months:
        # 일간 오행과 월주 천간 오행의 관계로 점수
        ti = ilgan_oheng
        mo_oh = mo['pillar_oheng']
        if ti == mo_oh: s = 75
        elif OHENG_SAENG.get(mo_oh) == ti: s = 90  # 월이 나를 생함
        elif OHENG_SAENG.get(ti) == mo_oh: s = 80  # 내가 월을 생함
        elif OHENG_GEUK.get(mo_oh) == ti: s = 50   # 월이 나를 극함
        elif OHENG_GEUK.get(ti) == mo_oh: s = 65
        else: s = 70
        luck_scores.append(s)
        mo['luck'] = s

    best = max(range(12), key=lambda i: luck_scores[i])
    worst = min(range(12), key=lambda i: luck_scores[i])

    return {
        'year': year,
        'ilgan': ilgan_name,
        'ilgan_oheng_korean': {'木':'목','火':'화','土':'토','金':'금','水':'수'}[ilgan_oheng],
        'months': months,
        'best_month': {'label': months[best]['label'], 'reason': f"{months[best]['pillar']} — {months[best]['title']}"},
        'caution_month': {'label': months[worst]['label'], 'reason': f"{months[worst]['pillar']} — {months[worst]['title']}"},
        'summary': f"{year}년 {ilgan_name}에게 가장 빛나는 달은 {months[best]['label']}, 신중해야 할 달은 {months[worst]['label']}이에요.",
    }


@app.post("/get-yearly-fortune-preview")
async def yearly_preview(data: YearlyFortuneInput):
    """미리보기 — 결제 유도용 (요약만)"""
    result = build_yearly_fortune(data.birth_date, data.birth_time, data.mbti, data.target_year,
                                   calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    return {
        'year': result['year'],
        'ilgan': result['ilgan'],
        'best_month': result['best_month'],
        'caution_month': result['caution_month'],
        'summary': result['summary'],
        'locked': True,
        'unlock_price': PRODUCT_PRICES['yearly'],
    }


@app.post("/confirm-and-get-yearly-fortune")
async def confirm_and_get_yearly(data: YearlyFortuneInput):
    """결제 검증 → 12개월 전체 응답"""
    expected = PRODUCT_PRICES['yearly']
    if data.amount != expected:
        raise HTTPException(status_code=400, detail=f"잘못된 결제 금액 (요청: {data.amount}원, 정가: {expected}원)")
    await _verify_toss_payment(data.paymentKey, data.orderId, data.amount)

    result = build_yearly_fortune(data.birth_date, data.birth_time, data.mbti, data.target_year,
                                   calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    result['unlocked'] = True
    return result


@app.post("/confirm-payment-credit")
async def confirm_payment_credit(data: PaymentCreditInput):
    """추가 분석/궁합/운세 등의 권한 구매 결제 검증"""
    expected = PRODUCT_PRICES.get(data.product)
    if not expected:
        raise HTTPException(status_code=400, detail=f"알 수 없는 상품: {data.product}")
    if data.amount != expected:
        raise HTTPException(status_code=400, detail=f"잘못된 결제 금액입니다. (요청: {data.amount}원, 정가: {expected}원)")

    toss_result = await _verify_toss_payment(data.paymentKey, data.orderId, data.amount)

    return {
        "status": "ok",
        "product": data.product,
        "payment": {
            "approved_at": toss_result.get("approvedAt"),
            "order_id": data.orderId,
            "amount": data.amount,
            "method": toss_result.get("method"),
            "is_test": TOSS_IS_TEST,
        },
    }

# ═══════════════════════════════════════════════
# 🔗 리퍼럴 시스템 (공유 보상)
# ═══════════════════════════════════════════════

# 메모리 기반 간단한 리퍼럴 저장소 (프로덕션에서는 DB로 교체)
referral_store = {}

@app.post("/create-referral")
async def create_referral():
    code = str(uuid.uuid4())[:8]
    referral_store[code] = {"uses": 0, "bonus_granted": False}
    return {"code": code}

@app.post("/use-referral")
async def use_referral(data: dict):
    code = data.get("code", "")
    if code not in referral_store:
        raise HTTPException(status_code=404, detail="유효하지 않은 추천 코드입니다.")

    ref = referral_store[code]
    ref["uses"] += 1

    # 공유자에게 보너스 부여 (1회)
    bonus_for_sharer = False
    if not ref["bonus_granted"]:
        ref["bonus_granted"] = True
        bonus_for_sharer = True

    return {
        "valid": True,
        "bonus_for_sharer": bonus_for_sharer,
        "message": "추천 코드가 적용되었습니다! 무료 분석 1회가 제공됩니다."
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
