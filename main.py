import os
import json
import uuid
import base64
import httpx
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv
from korean_lunar_calendar import KoreanLunarCalendar
import sxtwl

load_dotenv()

KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

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


# ─────────────────────────────────────────────
# 📜 대운(大運) 계산 — 인생 10년 단위 흐름
# 양년+남자/음년+여자 → 순행 / 양년+여자/음년+남자 → 역행
# 첫 대운 시작 나이 = (가까운 절기까지 일수) / 3
# ─────────────────────────────────────────────
_CHEONGAN = ['갑','을','병','정','무','기','경','신','임','계']
_JIJI = ['자','축','인','묘','진','사','오','미','신','유','술','해']
_YANG_GAN = {'갑', '병', '무', '경', '임'}

# 대운 시기별 키워드 (오행 흐름 기반)
_DAEWOON_THEMES = {
    '木': '성장·도전·새 출발의 시기. 적극적으로 뻗어나가는 운',
    '火': '확장·인기·표현의 시기. 빛을 발하고 사람이 모이는 운',
    '土': '안정·축적·신뢰의 시기. 결실을 다지는 운',
    '金': '결단·정리·완성의 시기. 단단해지고 정제되는 운',
    '水': '내면·지혜·휴식의 시기. 깊어지고 흐르는 운',
}

# ─────────────────────────────────────────────
# 🌟 십성(十星) — 일간과 다른 천간의 관계
# ─────────────────────────────────────────────
_GAN_YIN_YANG = {
    '갑':'양','을':'음','병':'양','정':'음','무':'양',
    '기':'음','경':'양','신':'음','임':'양','계':'음'
}
_OHENG_SAENG_CYCLE = {'木':'火', '火':'土', '土':'金', '金':'水', '水':'木'}
_OHENG_GEUK_CYCLE  = {'木':'土', '土':'水', '水':'火', '火':'金', '金':'木'}

# ─────────────────────────────────────────────
# ✍️ 음향오행 — 이름의 발음 오행 분석
# 훈민정음 원리 기반 한글 자모 → 오행 매핑
# ─────────────────────────────────────────────
# 초성(자음) 오행 (훈민정음 해례 기준)
_CHOSEONG_OHENG = {
    'ㄱ': '木', 'ㅋ': '木', 'ㄲ': '木',                          # 아음(牙音) = 목
    'ㄴ': '火', 'ㄷ': '火', 'ㄹ': '火', 'ㅌ': '火', 'ㄸ': '火',    # 설음(舌音) = 화
    'ㅁ': '水', 'ㅂ': '水', 'ㅍ': '水', 'ㅃ': '水',                # 순음(脣音) = 수
    'ㅅ': '金', 'ㅈ': '金', 'ㅊ': '金', 'ㅆ': '金', 'ㅉ': '金',    # 치음(齒音) = 금
    'ㅇ': '土', 'ㅎ': '土',                                      # 후음(喉音) = 토
}
# 중성(모음) 오행 (음양 + 천지인)
_JUNGSEONG_OHENG = {
    'ㅏ': '木', 'ㅑ': '木',           # 양 + 천 = 목
    'ㅓ': '木', 'ㅕ': '木',           # 음 + 천 = 목 (단순화)
    'ㅗ': '火', 'ㅛ': '火',           # 양 + 지 = 화
    'ㅜ': '水', 'ㅠ': '水',           # 음 + 지 = 수
    'ㅡ': '土',                      # 인 = 토
    'ㅣ': '金',                      # 인 + 천 = 금
    'ㅐ': '木', 'ㅒ': '木', 'ㅔ': '木', 'ㅖ': '木',
    'ㅘ': '火', 'ㅙ': '火', 'ㅚ': '火',
    'ㅝ': '水', 'ㅞ': '水', 'ㅟ': '水',
    'ㅢ': '土',
}
# 종성도 초성과 동일 룰

_CHOSEONG_LIST = ['ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ','ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']
_JUNGSEONG_LIST = ['ㅏ','ㅐ','ㅑ','ㅒ','ㅓ','ㅔ','ㅕ','ㅖ','ㅗ','ㅘ','ㅙ','ㅚ','ㅛ','ㅜ','ㅝ','ㅞ','ㅟ','ㅠ','ㅡ','ㅢ','ㅣ']
_JONGSEONG_LIST = [None,'ㄱ','ㄲ','ㄳ','ㄴ','ㄵ','ㄶ','ㄷ','ㄹ','ㄺ','ㄻ','ㄼ','ㄽ','ㄾ','ㄿ','ㅀ','ㅁ','ㅂ','ㅄ','ㅅ','ㅆ','ㅇ','ㅈ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ']


def _decompose_hangul(ch: str):
    """한 글자 한글 → (초성, 중성, 종성) 튜플"""
    code = ord(ch)
    if not (0xAC00 <= code <= 0xD7A3):
        return None
    idx = code - 0xAC00
    cho = idx // 588
    jung = (idx % 588) // 28
    jong = idx % 28
    return (_CHOSEONG_LIST[cho], _JUNGSEONG_LIST[jung], _JONGSEONG_LIST[jong])


def analyze_phonetic_oheng(name: str, sajus_oheng_pct: dict = None):
    """
    이름의 음향오행 분석.
    Returns: {
        'name': str,
        'syllables': [{char, onset, vowel, coda, onset_oh, vowel_oh, coda_oh}],
        'distribution': {'木':2,'火':1,...},
        'strongest': str,
        'compatibility': {'score':82, 'level':'보완형'|'중립'|'충돌형', 'desc':'...'}
    }
    """
    if not name:
        return None

    syllables = []
    distribution = {'木':0, '火':0, '土':0, '金':0, '水':0}
    for ch in name:
        d = _decompose_hangul(ch)
        if not d:
            continue
        cho, jung, jong = d
        cho_oh = _CHOSEONG_OHENG.get(cho)
        jung_oh = _JUNGSEONG_OHENG.get(jung)
        jong_oh = _CHOSEONG_OHENG.get(jong) if jong else None

        syllables.append({
            'char': ch,
            'onset': cho, 'vowel': jung, 'coda': jong,
            'onset_oh': cho_oh,
            'vowel_oh': jung_oh,
            'coda_oh': jong_oh,
        })
        if cho_oh: distribution[cho_oh] += 1.0   # 초성 가중치 1
        if jung_oh: distribution[jung_oh] += 0.7 # 중성 가중치 0.7
        if jong_oh: distribution[jong_oh] += 0.5 # 종성 가중치 0.5

    strongest = max(distribution, key=distribution.get) if any(distribution.values()) else '土'

    # 사주와의 보완 점수 계산
    compatibility = {'score': 70, 'level': '중립', 'desc': '평이한 조합이에요.'}
    if sajus_oheng_pct:
        # 사주에서 부족한 오행을 이름이 채워주면 점수 ↑
        sorted_saju = sorted(sajus_oheng_pct.items(), key=lambda x: x[1])
        weakest_saju = sorted_saju[0][0]
        strongest_saju = sorted_saju[-1][0]

        # 이름의 주된 오행
        name_total = sum(distribution.values()) or 1
        name_pct = {k: round(v * 100 / name_total, 1) for k, v in distribution.items()}
        name_top = max(name_pct, key=name_pct.get)

        # 평가
        if name_top == weakest_saju:
            score = 90
            level = '보완형 ✨'
            desc = f'사주에 부족한 {weakest_saju}을(를) 이름이 채워줘요. 균형 잡힌 매우 좋은 조합!'
        elif name_top == strongest_saju:
            score = 50
            level = '강조형'
            desc = f'이미 강한 {strongest_saju}을(를) 이름이 더 강조해요. 캐릭터는 명확하지만 균형은 부족.'
        elif _OHENG_SAENG_CYCLE.get(name_top) == weakest_saju:
            score = 80
            level = '간접보완형'
            desc = f'이름의 {name_top}이(가) 부족한 {weakest_saju}을(를) 생해줘요. 좋은 흐름.'
        elif _OHENG_GEUK_CYCLE.get(name_top) == strongest_saju:
            score = 75
            level = '제어형'
            desc = f'이름이 과한 {strongest_saju}을(를) 제어해줘요. 안정감 있는 조합.'
        else:
            score = 65
            level = '중립'
            desc = '특별한 시너지는 없지만 무난한 조합이에요.'
        compatibility = {'score': score, 'level': level, 'desc': desc, 'name_top': name_top}

    return {
        'name': name,
        'syllables': syllables,
        'distribution': {k: round(v, 1) for k, v in distribution.items()},
        'strongest': strongest,
        'compatibility': compatibility,
    }


def calc_sipsung(ilgan: str, target_gan: str) -> str:
    """일간 → 대상 천간의 십성 반환"""
    if ilgan == target_gan:
        return '비견'  # 같은 글자
    ig_oh = CHEONGAN_OHENG[ilgan]
    tg_oh = CHEONGAN_OHENG[target_gan]
    same_yy = (_GAN_YIN_YANG[ilgan] == _GAN_YIN_YANG[target_gan])

    if ig_oh == tg_oh:
        return '비견' if same_yy else '겁재'
    if _OHENG_SAENG_CYCLE[ig_oh] == tg_oh:        # 내가 낳음 → 식상
        return '식신' if same_yy else '상관'
    if _OHENG_SAENG_CYCLE[tg_oh] == ig_oh:        # 나를 낳음 → 인성
        return '편인' if same_yy else '정인'
    if _OHENG_GEUK_CYCLE[ig_oh] == tg_oh:         # 내가 극함 → 재성
        return '편재' if same_yy else '정재'
    if _OHENG_GEUK_CYCLE[tg_oh] == ig_oh:         # 나를 극함 → 관성
        return '편관' if same_yy else '정관'
    return '미정'

_SIPSUNG_INFO = {
    '비견': {'icon':'🤝', 'theme':'동료·자립·경쟁', 'desc':'동료·형제의 도움이 늘어요. 자기 주도성과 협업이 핵심.'},
    '겁재': {'icon':'⚔️', 'theme':'경쟁·소비·도전', 'desc':'경쟁자가 많아지고 큰 지출이 따라요. 도전 정신은 폭발.'},
    '식신': {'icon':'🍀', 'theme':'표현·여유·즐거움', 'desc':'여유와 풍요의 시기. 취미·자식·창작 운이 좋아져요.'},
    '상관': {'icon':'💡', 'theme':'창의·반항·변화', 'desc':'창의력이 폭발하고 기존 틀을 깨는 시기. 표현 자유.'},
    '편재': {'icon':'💰', 'theme':'큰돈·사업·이동', 'desc':'큰 재물 기회와 사업 운. 활동 반경이 확장돼요.'},
    '정재': {'icon':'💴', 'theme':'안정·저축·결실', 'desc':'꾸준한 수입과 가정 안정. 결혼·재산 운이 좋아요.'},
    '편관': {'icon':'⚡', 'theme':'권위·변화·위기', 'desc':'권력·명예 기회와 함께 큰 변화. 도전과 시련의 시기.'},
    '정관': {'icon':'👑', 'theme':'명예·승진·안정', 'desc':'명예와 직장 운이 빛나요. 사회적 지위가 상승합니다.'},
    '편인': {'icon':'📿', 'theme':'학문·종교·고독', 'desc':'깊은 사색과 학문, 영적 성장의 시기. 혼자 시간 필요.'},
    '정인': {'icon':'📚', 'theme':'학문·보호·인덕', 'desc':'귀인을 만나고 학업·자격 성취. 정신적 풍요로움.'},
    '미정': {'icon':'❓', 'theme':'중립', 'desc':'특별한 강조 없는 평이한 시기.'},
}


def _daewoon_score(ilgan: str, gan: str, ji: str) -> int:
    """대운의 일간 보완도 점수 (0~100). 단순화: 일간을 생하거나 같으면 높음"""
    ig_oh = CHEONGAN_OHENG[ilgan]
    gan_oh = CHEONGAN_OHENG[gan]
    ji_oh  = JIJI_OHENG[ji]
    score = 50
    # 천간 영향
    if gan_oh == ig_oh:
        score += 15   # 같은 오행 = 비겁
    elif _OHENG_SAENG_CYCLE[gan_oh] == ig_oh:
        score += 20   # 나를 낳음 = 인성
    elif _OHENG_SAENG_CYCLE[ig_oh] == gan_oh:
        score += 5    # 내가 낳음 = 식상
    elif _OHENG_GEUK_CYCLE[ig_oh] == gan_oh:
        score -= 5    # 내가 극함 = 재성
    elif _OHENG_GEUK_CYCLE[gan_oh] == ig_oh:
        score -= 15   # 나를 극함 = 관성 (도전)
    # 지지 영향 (절반)
    if ji_oh == ig_oh:
        score += 8
    elif _OHENG_SAENG_CYCLE[ji_oh] == ig_oh:
        score += 10
    elif _OHENG_GEUK_CYCLE[ji_oh] == ig_oh:
        score -= 8
    return max(15, min(95, score))


def _days_to_nearest_jieqi(year: int, month: int, day: int, forward: bool) -> int:
    """기준일에서 가까운 절기까지의 일수 (절기 기반 대운 시작 나이 계산용)"""
    import sxtwl as _sx
    base = _sx.fromSolar(year, month, day)
    cur = base
    for i in range(1, 90):
        cur = cur.after(1) if forward else cur.before(1)
        if cur.hasJieQi():
            return i
    return 15  # 기본값


def calc_daewoon(year: int, month: int, day: int, hour: int, gender: str = 'F',
                 calendar_type: str = 'solar', is_leap_month: bool = False, count: int = 10):
    """
    📜 대운 분석
    Returns:
        {
            'direction': 'forward'|'backward',
            'direction_kr': '순행'|'역행',
            'start_age': float,         # 첫 대운 시작 나이 (소수점)
            'gender': 'M'|'F',
            'policy': str,              # 계산 정책 (절기 기반)
            'pillars': [               # 10개 대운
                {'gan': '갑', 'ji': '인', 'label': '갑인',
                 'age_start': 5.3, 'age_end': 14.3,
                 'oheng_gan': '木', 'oheng_ji': '木',
                 'theme': '성장·도전...'}
            ],
            'current_idx': int,         # 오늘 기준 현재 대운 인덱스
            'current_age': float,
            'current_pillar': dict,     # 현재 대운 정보
        }
    """
    from datetime import date as _date

    # 1) 양력 정규화
    if calendar_type == 'lunar':
        cal_conv = KoreanLunarCalendar()
        cal_conv.setLunarDate(year, month, day, bool(is_leap_month))
        solar_str = cal_conv.SolarIsoFormat()
        sy, sm, sd = map(int, solar_str.split('-'))
    else:
        sy, sm, sd = year, month, day

    # 2) 사주 계산 (월주 사용)
    yp, mp, dp, tp = calc_pillars_accurate(year, month, day, hour, calendar_type, is_leap_month)

    # 3) 대운 방향 결정 (양년+남자, 음년+여자 → 순행)
    is_yang_year = yp[0] in _YANG_GAN
    is_male = (gender == 'M')
    forward = (is_yang_year and is_male) or (not is_yang_year and not is_male)
    direction = 'forward' if forward else 'backward'

    # 4) 첫 대운 시작 나이 (절기까지 일수 / 3)
    days = _days_to_nearest_jieqi(sy, sm, sd, forward)
    start_age = round(days / 3.0, 1)

    # 5) 대운 시퀀스 (월주 ± 1씩)
    ilgan = dp[0]
    mg_idx = _CHEONGAN.index(mp[0])
    mj_idx = _JIJI.index(mp[1])
    pillars = []
    for i in range(1, count + 1):
        if forward:
            gan_idx = (mg_idx + i) % 10
            ji_idx = (mj_idx + i) % 12
        else:
            gan_idx = (mg_idx - i) % 10
            ji_idx = (mj_idx - i) % 12
        gan = _CHEONGAN[gan_idx]
        ji = _JIJI[ji_idx]
        oheng_gan = CHEONGAN_OHENG[gan]
        oheng_ji = JIJI_OHENG[ji]
        theme = _DAEWOON_THEMES.get(oheng_gan, '변화의 시기')

        # 십성 (일간 → 대운 천간)
        sipsung_name = calc_sipsung(ilgan, gan)
        sipsung_info = _SIPSUNG_INFO[sipsung_name]

        # 대운 점수
        score = _daewoon_score(ilgan, gan, ji)
        grade = '🌟매우 좋음' if score >= 75 else '✨좋음' if score >= 60 else '➖평이' if score >= 45 else '⚠️주의' if score >= 35 else '🔥큰 도전'

        a_start = round(start_age + (i - 1) * 10, 1)
        a_end = round(start_age + i * 10, 1)
        pillars.append({
            'gan': gan, 'ji': ji, 'label': f'{gan}{ji}',
            'age_start': a_start, 'age_end': a_end,
            'oheng_gan': oheng_gan, 'oheng_ji': oheng_ji,
            'theme': theme,
            'sipsung': sipsung_name,
            'sipsung_icon': sipsung_info['icon'],
            'sipsung_theme': sipsung_info['theme'],
            'sipsung_desc': sipsung_info['desc'],
            'score': score,
            'grade': grade,
        })

    # 6) 현재 대운 찾기
    today = _date.today()
    birth = _date(sy, sm, sd)
    current_age = round((today - birth).days / 365.25, 1)
    current_idx = -1
    for i, p in enumerate(pillars):
        if p['age_start'] <= current_age < p['age_end']:
            current_idx = i
            break

    return {
        'direction': direction,
        'direction_kr': '순행' if forward else '역행',
        'start_age': start_age,
        'gender': gender,
        'policy': '절기 기반 (입춘/경칩/청명...)',
        'pillars': pillars,
        'current_idx': current_idx,
        'current_age': current_age,
        'current_pillar': pillars[current_idx] if current_idx >= 0 else None,
    }


# ─────────────────────────────────────────────
# ⏰ 시간 보정 — 서머타임 + 1954~1961 GMT+8:30 + 시태양시(경도)
# ─────────────────────────────────────────────
# 한국 서머타임 시행 이력 (KST → 시계 시간 -1시간 = 실제 시간)
_KOREAN_DST_PERIODS = [
    ((1948, 6, 1),  (1948, 9, 13)),
    ((1949, 4, 3),  (1949, 9, 11)),
    ((1950, 4, 1),  (1950, 9, 10)),
    ((1951, 5, 6),  (1951, 9, 9)),
    ((1955, 5, 5),  (1955, 9, 9)),
    ((1956, 5, 20), (1956, 9, 30)),
    ((1957, 5, 5),  (1957, 9, 22)),
    ((1958, 5, 4),  (1958, 9, 21)),
    ((1959, 5, 3),  (1959, 9, 20)),
    ((1960, 5, 1),  (1960, 9, 18)),
    ((1987, 5, 10), (1987, 10, 11)),
    ((1988, 5, 8),  (1988, 10, 9)),
]
# 한국 표준시 GMT+8:30 시기 (시계가 30분 늦음 → 실제 시간 +30분)
_KST_830_RANGE = ((1954, 3, 21), (1961, 8, 9))

# 주요 도시 동경 (시태양시 보정용)
_CITY_LONGITUDES = {
    'Seoul':    126.978,  # 서울
    'Busan':    129.075,  # 부산
    'Incheon':  126.706,  # 인천
    'Daegu':    128.602,
    'Daejeon':  127.385,
    'Gwangju':  126.853,
    'Jeju':     126.531,
}
_KST_BASE_LONGITUDE = 135.0  # 한국 표준시 기준 경도

def adjust_birth_time(year, month, day, hour, minute=0,
                       apply_dst=True, apply_solar_time=False, city='Seoul'):
    """
    출생 시계 시간을 사주 계산용 '실제 천문 시간'으로 보정.
    Returns: (year, month, day, hour, minute, adjustments)
    """
    from datetime import datetime as _dt, timedelta as _td
    dt = _dt(year, month, day, hour, minute)
    adjustments = []

    # 1) 서머타임: 시계가 1시간 빨랐으므로 빼기
    if apply_dst:
        for (sy, sm, sd), (ey, em, ed) in _KOREAN_DST_PERIODS:
            start = _dt(sy, sm, sd, 0, 0)
            end = _dt(ey, em, ed, 23, 59)
            if start <= dt <= end:
                dt -= _td(hours=1)
                adjustments.append({'type': 'summertime', 'minutes': -60})
                break

    # 2) 1954-1961 GMT+8:30: 표준시 30분 늦었으므로 더하기
    (s1y, s1m, s1d), (e1y, e1m, e1d) = _KST_830_RANGE
    s1 = _dt(s1y, s1m, s1d)
    e1 = _dt(e1y, e1m, e1d, 23, 59)
    if s1 <= dt <= e1:
        dt += _td(minutes=30)
        adjustments.append({'type': 'kst_830_offset', 'minutes': 30})

    # 3) 시태양시 (경도 보정)
    if apply_solar_time:
        lon = _CITY_LONGITUDES.get(city, 126.978)
        diff = (lon - _KST_BASE_LONGITUDE) * 4  # 1도 = 4분
        dt += _td(minutes=diff)
        adjustments.append({'type': 'solar_time', 'minutes': round(diff, 1), 'city': city, 'longitude': lon})

    return dt.year, dt.month, dt.day, dt.hour, dt.minute, adjustments


def calc_pillars_accurate(year: int, month: int, day: int, hour: int,
                          calendar_type: str = 'solar', is_leap_month: bool = False,
                          apply_dst: bool = True, apply_solar_time: bool = False, city: str = 'Seoul'):
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

    # 1.5) 시간 보정 (서머타임 + GMT+8:30 + 시태양시)
    sy, sm, sd, hour, _min, _adjs = adjust_birth_time(
        sy, sm, sd, hour, 0,
        apply_dst=apply_dst, apply_solar_time=apply_solar_time, city=city
    )

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

    # 메타데이터를 함수 속성에 저장 (호출자가 필요 시 접근)
    calc_pillars_accurate.last_adjustments = _adjs
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

app.mount("/assets", StaticFiles(directory="assets"), name="assets")

@app.get("/")
async def read_index():
    return FileResponse("index.html")


@app.get("/app-config")
async def app_config(request: Request):
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return {
        "kakao_javascript_key": KAKAO_JAVASCRIPT_KEY,
        "public_base_url": base_url,
    }

@app.get("/privacy")
async def read_privacy():
    return FileResponse("privacy.html")

@app.get("/terms")
async def read_terms():
    return FileResponse("terms.html")

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
    """단순 카운트 (지장간 미반영, 호환용)"""
    count = {'木': 0, '火': 0, '土': 0, '金': 0, '水': 0}
    for gan, ji in pillars:
        count[CHEONGAN_OHENG[gan]] += 1
        count[JIJI_OHENG[ji]] += 1
    return count


# ─────────────────────────────────────────────
# 📿 지장간(支藏干) — 지지 안에 숨은 천간들
# 본기/중기/여기 + 비율 (전통 명리 표준)
# ─────────────────────────────────────────────
JIJI_JANGGAN = {
    '자': [('계', 1.0)],
    '축': [('기', 0.6), ('계', 0.3), ('신', 0.1)],
    '인': [('갑', 0.6), ('병', 0.3), ('무', 0.1)],
    '묘': [('을', 1.0)],
    '진': [('무', 0.6), ('을', 0.3), ('계', 0.1)],
    '사': [('병', 0.6), ('경', 0.3), ('무', 0.1)],
    '오': [('정', 0.7), ('기', 0.3)],
    '미': [('기', 0.6), ('정', 0.3), ('을', 0.1)],
    '신': [('경', 0.6), ('임', 0.3), ('무', 0.1)],
    '유': [('신', 1.0)],
    '술': [('무', 0.6), ('신', 0.3), ('정', 0.1)],
    '해': [('임', 0.7), ('갑', 0.3)],
}

# 자리별 가중치 (월지가 가장 영향력 큼)
PILLAR_WEIGHTS = {'year': 1.0, 'month': 2.5, 'day': 1.8, 'time': 1.0}
JIJI_WEIGHT = 1.2   # 지지가 천간보다 약간 무겁게


def analyze_oheng_advanced(pillars):
    """
    📿 정밀 오행 분석 (지장간 + 자리별 가중치)
    pillars: [(year_gan, year_ji), (month_gan, month_ji), (day_gan, day_ji), (time_gan, time_ji)]

    Returns:
        {
            'score': {오행→실수 점수},
            'pct':   {오행→백분율},
            'count': {오행→정수 막대 (시각화용)},
            'strongest': 가장 강한 오행,
            'weakest':   가장 약한 오행,
        }
    """
    score = {'木': 0.0, '火': 0.0, '土': 0.0, '金': 0.0, '水': 0.0}
    pillar_names = ['year', 'month', 'day', 'time']

    for i, (gan, ji) in enumerate(pillars):
        pn = pillar_names[i]
        w = PILLAR_WEIGHTS[pn]

        # 1) 천간 (드러난 오행)
        score[CHEONGAN_OHENG[gan]] += w * 1.0

        # 2) 지장간 (지지 안 숨은 오행, 본기·중기·여기)
        for hidden_gan, ratio in JIJI_JANGGAN[ji]:
            score[CHEONGAN_OHENG[hidden_gan]] += w * ratio * JIJI_WEIGHT

    # 백분율 계산
    total = sum(score.values()) or 1.0
    pct = {k: round(v * 100 / total, 1) for k, v in score.items()}

    # 시각화용 정수 막대 (0~10 정규화)
    max_score = max(score.values()) or 1.0
    count_viz = {k: max(1, round(v * 10 / max_score)) if v > 0.05 else 0 for k, v in score.items()}

    sorted_items = sorted(score.items(), key=lambda x: x[1], reverse=True)
    strongest = sorted_items[0][0]
    weakest = sorted_items[-1][0]

    return {
        'score': {k: round(v, 2) for k, v in score.items()},
        'pct': pct,
        'count': count_viz,
        'strongest': strongest,
        'weakest': weakest,
    }

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

# 천덕귀인 — 월지 → 해당 글자
CHEONDEOK_MAP = {
    '인': '정', '묘': '신', '진': '임', '사': '신',
    '오': '해', '미': '갑', '신': '계', '유': '인',
    '술': '병', '해': '을', '자': '사', '축': '경',
}
# 월덕귀인 — 월지 → 해당 천간
WEOLDEOK_MAP = {
    '인': '병', '오': '병', '술': '병',
    '신': '임', '자': '임', '진': '임',
    '사': '경', '유': '경', '축': '경',
    '해': '갑', '묘': '갑', '미': '갑',
}
# 홍염살 — 일간 → 해당 지지
HONGYEOM_MAP = {
    '갑': '오', '을': '오', '병': '인', '정': '미',
    '무': '진', '기': '진', '경': '술', '신': '유',
    '임': '자', '계': '신',
}
# 괴강살 — 일주 한정 (특정 조합)
GOEGANG_PAIRS = {('경', '진'), ('경', '술'), ('임', '진'), ('임', '술'), ('무', '술'), ('무', '진')}
# 금여록 — 일간 → 해당 지지
KEUMYEO_MAP = {
    '갑': '진', '을': '사', '병': '미', '정': '신',
    '무': '미', '기': '신', '경': '술', '신': '해',
    '임': '축', '계': '인',
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

# ═══════════════════════════════════════════════
# ⭐ 별자리 (서양 점성술)
# ═══════════════════════════════════════════════
CONSTELLATION_DATA = {
    'aries': {
        'icon': '♈', 'name': '양자리', 'date': '3/21~4/19', 'element': '불',
        'ruling_planet': '화성 (Mars)', 'modality': '활동궁',
        'traits': ['열정적', '도전적', '솔직함', '독립적', '용감함'],
        'desc': '불같은 에너지로 앞장서는 개척자. 누구보다 빠르게 행동하고 도전을 즐기는 타고난 리더예요.',
        'strength': '결단력이 빠르고 어떤 상황에서든 먼저 나서는 용기가 있어요. 새로운 일을 시작하는 능력이 탁월하며, 주변 사람들에게 에너지를 불어넣어줍니다.',
        'weakness': '인내심이 부족하고 급한 성격 때문에 실수할 수 있어요. 다른 사람의 의견을 경청하는 연습이 필요합니다. 시작은 잘하지만 마무리가 약할 수 있어요.',
        'love_style': '직진형 연애 스타일! 좋으면 바로 표현하고, 밀당을 싫어해요. 상대를 리드하려는 경향이 있지만, 진심을 다하는 뜨거운 사랑을 해요.',
        'career_hint': '창업, 스포츠, 군인/경찰, 영업, 프로젝트 매니저 등 도전적이고 주도적인 역할에서 빛나요.',
        'lucky_day': '화요일', 'lucky_color': '빨강',
        'best_match': ['사자자리', '사수자리', '쌍둥이자리'], 'worst_match': ['게자리', '염소자리'],
        'advice': '때로는 멈춰서 주변을 돌아보세요. 당신의 열정에 인내를 더하면 세상을 바꿀 수 있어요.',
        'synergy_fire': '사주의 화(火) 기운과 만나면 열정이 폭발! 추진력이 극대화되지만, 과도한 불의 기운으로 감정 조절에 유의하세요. 리더십과 카리스마가 최고조에 달합니다.',
        'synergy_water': '사주의 수(水) 기운이 양자리의 불을 적절히 중화시켜 감정 조절력을 높여줘요. 직관력과 행동력이 균형을 이루는 이상적인 조합입니다.',
        'synergy_earth': '사주의 토(土) 기운이 양자리의 급한 성격에 안정감을 더해줘요. 현실적인 판단력이 생겨 시작한 일을 끝까지 마무리하는 힘이 생깁니다.',
        'synergy_wood': '사주의 목(木) 기운이 양자리의 성장 에너지를 배가시켜요. 새로운 분야 개척과 자기계발에서 놀라운 성과를 거둘 수 있습니다.',
        'synergy_metal': '사주의 금(金) 기운이 양자리에 날카로운 판단력과 집중력을 선물해요. 흩어지기 쉬운 에너지를 하나로 모아 큰 성취를 이끌어냅니다.',
        'synergy_default': '양자리의 리더십이 사주의 기운과 어우러져 독보적인 존재감을 만들어요.',
    },
    'taurus': {
        'icon': '♉', 'name': '황소자리', 'date': '4/20~5/20', 'element': '흙',
        'ruling_planet': '금성 (Venus)', 'modality': '고정궁',
        'traits': ['안정적', '감각적', '인내심', '현실적', '충실함'],
        'desc': '흔들림 없는 안정감의 소유자. 오감이 발달해 미식, 예술, 자연을 사랑하며 한번 시작하면 끝까지 해내요.',
        'strength': '끈기와 인내심이 남다르며, 한번 정한 목표는 반드시 이뤄내요. 감각적인 능력이 뛰어나 예술이나 요리, 패션 등에서 탁월한 재능을 보입니다.',
        'weakness': '변화를 꺼리고 고집이 셀 수 있어요. 소유욕이 강해 집착으로 이어질 수 있으니 유연한 사고가 필요합니다. 새로운 시도를 두려워하지 마세요.',
        'love_style': '한번 사랑하면 끝까지 가는 충실한 타입! 안정적이고 헌신적인 연애를 하며, 물질적 표현(선물, 맛집)으로 사랑을 보여줘요.',
        'career_hint': '금융, 부동산, 셰프, 디자이너, 음악가 등 안정적이면서 감각을 살릴 수 있는 분야에서 성공해요.',
        'lucky_day': '금요일', 'lucky_color': '초록',
        'best_match': ['처녀자리', '염소자리', '게자리'], 'worst_match': ['물병자리', '사자자리'],
        'advice': '가끔은 익숙한 것에서 벗어나 새로운 경험을 해보세요. 당신의 탄탄한 기반 위에 변화를 더하면 더 큰 세계가 열려요.',
        'synergy_earth': '사주의 토(土) 기운과 만나면 안정감이 배가! 재물운이 탄탄해지고 현실적인 성공을 착실히 쌓아갑니다.',
        'synergy_wood': '사주의 목(木) 기운이 황소자리에 성장 에너지를 더해줘요. 고집스러운 면을 유연하게 바꿔주고 새로운 가능성을 열어줍니다.',
        'synergy_fire': '사주의 화(火) 기운이 황소자리의 느긋함에 열정을 불어넣어요. 행동력이 빨라지고 적극적인 변화를 이끌 수 있게 됩니다.',
        'synergy_water': '사주의 수(水) 기운이 황소자리에 감수성과 직관력을 더해줘요. 예술적 감각이 극대화되어 창작 활동에서 빛을 발합니다.',
        'synergy_metal': '사주의 금(金) 기운이 황소자리의 감각을 더욱 날카롭게 다듬어요. 비즈니스 판단력이 탁월해져 재물 축적에 유리합니다.',
        'synergy_default': '황소자리의 끈기가 사주의 기운과 합쳐져 꾸준한 성공을 만들어냅니다.',
    },
    'gemini': {
        'icon': '♊', 'name': '쌍둥이자리', 'date': '5/21~6/21', 'element': '바람',
        'ruling_planet': '수성 (Mercury)', 'modality': '변동궁',
        'traits': ['다재다능', '호기심', '소통력', '재치있음', '적응력'],
        'desc': '끝없는 호기심의 소통 천재. 어떤 주제든 빠르게 이해하고 재미있게 풀어내는 재능이 있어요.',
        'strength': '머리 회전이 빠르고 어떤 상황에든 적응을 잘해요. 대화 능력이 뛰어나 사람들을 즐겁게 하고, 여러 가지를 동시에 해내는 멀티태스킹 능력이 있어요.',
        'weakness': '관심사가 자주 바뀌어 한 가지에 깊이 파고들기 어려울 수 있어요. 가볍게 보일 수 있으니 진정성을 보여주는 노력이 필요합니다.',
        'love_style': '대화가 통하는 상대에게 끌려요! 지적인 자극이 있는 연애를 원하며, 자유로움을 존중해주는 관계를 선호해요. 유머 감각이 연애의 핵심!',
        'career_hint': '작가, 기자, 마케터, 프로그래머, 통역사, MC 등 소통과 다양성이 요구되는 분야에서 빛나요.',
        'lucky_day': '수요일', 'lucky_color': '노랑',
        'best_match': ['천칭자리', '물병자리', '양자리'], 'worst_match': ['처녀자리', '물고기자리'],
        'advice': '하나에 집중하는 시간을 의도적으로 만들어보세요. 당신의 넓은 관심사에 깊이를 더하면 전문가로 인정받게 돼요.',
        'synergy_wood': '사주의 목(木) 기운과 만나면 지적 호기심이 더 활발해져요. 배움의 속도가 빨라지고 여러 분야를 넘나드는 융합적 사고가 가능해집니다.',
        'synergy_metal': '사주의 금(金) 기운이 쌍둥이자리에 집중력과 결단력을 더해줍니다. 흩어지기 쉬운 재능을 하나로 모아 큰 성과를 만들어내요.',
        'synergy_fire': '사주의 화(火) 기운이 쌍둥이자리에 열정과 추진력을 불어넣어요. 아이디어를 실행으로 옮기는 힘이 강해집니다.',
        'synergy_water': '사주의 수(水) 기운이 쌍둥이자리에 감성적 깊이를 더해줘요. 표면적 소통을 넘어 마음을 울리는 대화가 가능해집니다.',
        'synergy_earth': '사주의 토(土) 기운이 쌍둥이자리에 현실 감각과 끈기를 선물해요. 시작한 일을 끝까지 해내는 완성력이 생겨요.',
        'synergy_default': '쌍둥이자리의 다재다능함이 사주의 기운과 만나 여러 분야에서 빛납니다.',
    },
    'cancer': {
        'icon': '♋', 'name': '게자리', 'date': '6/22~7/22', 'element': '물',
        'ruling_planet': '달 (Moon)', 'modality': '활동궁',
        'traits': ['감성적', '보호본능', '직감력', '가정적', '배려심'],
        'desc': '따뜻한 마음의 감성 수호자. 사랑하는 사람을 위해서라면 무엇이든 하는 헌신적인 마음의 소유자예요.',
        'strength': '공감 능력이 뛰어나고 상대방의 감정을 잘 읽어요. 가족과 친구에 대한 헌신이 깊으며, 직감으로 위험을 미리 감지하는 능력이 있어요.',
        'weakness': '감정 기복이 있고, 과거에 집착할 수 있어요. 거절을 잘 못하고 남의 감정을 너무 많이 떠안으면 지칠 수 있으니 자기 보호도 중요해요.',
        'love_style': '헌신적이고 보살피는 연애를 해요. 가정적인 분위기를 중시하며, 요리해주기·편지쓰기 등 따뜻한 표현을 좋아해요. 안정감을 주는 상대에게 끌려요.',
        'career_hint': '간호사, 상담사, 교사, 요리사, 인테리어, 사회복지 등 사람을 돌보고 편안한 환경을 만드는 분야에서 빛나요.',
        'lucky_day': '월요일', 'lucky_color': '은색',
        'best_match': ['전갈자리', '물고기자리', '황소자리'], 'worst_match': ['양자리', '천칭자리'],
        'advice': '자신의 감정도 소중히 여기세요. 남을 위해 헌신하는 만큼 자기 자신을 위한 시간도 꼭 가져야 오래갈 수 있어요.',
        'synergy_water': '사주의 수(水) 기운과 만나면 감성과 직관력이 극대화됩니다. 예술적 재능이 폭발하고 사람의 마음을 움직이는 힘이 커져요.',
        'synergy_fire': '사주의 화(火) 기운이 게자리에 자신감과 적극성을 더해줘요. 소극적인 면을 극복하고 자기 의견을 당당히 표현할 수 있게 됩니다.',
        'synergy_earth': '사주의 토(土) 기운이 게자리에 현실적 안정감을 줘요. 감정에 휩쓸리지 않고 단단한 기반을 다지는 힘이 생깁니다.',
        'synergy_wood': '사주의 목(木) 기운이 게자리에 성장 동력을 불어넣어요. 안전지대를 벗어나 새로운 도전을 시작하는 용기가 생깁니다.',
        'synergy_metal': '사주의 금(金) 기운이 게자리에 논리적 판단력을 더해줘요. 감정과 이성의 균형을 맞춰 더 현명한 선택을 할 수 있어요.',
        'synergy_default': '게자리의 따뜻함이 사주의 기운과 어우러져 깊은 유대감을 만들어냅니다.',
    },
    'leo': {
        'icon': '♌', 'name': '사자자리', 'date': '7/23~8/22', 'element': '불',
        'ruling_planet': '태양 (Sun)', 'modality': '고정궁',
        'traits': ['당당함', '창의력', '리더십', '관대함', '자신감'],
        'desc': '무대 위의 왕, 타고난 스타. 어디서든 주목받고 사람들에게 영감을 주는 카리스마가 있어요.',
        'strength': '자신감이 넘치고 사람들을 이끄는 리더십이 탁월해요. 창의적인 아이디어가 풍부하며, 관대한 마음으로 주변을 챙기는 따뜻함도 있어요.',
        'weakness': '인정욕구가 강하고 자존심이 세서 비판에 예민할 수 있어요. 모든 것을 컨트롤하려는 성향을 줄이고, 겸손함을 배우면 더 큰 사람이 돼요.',
        'love_style': '로맨틱하고 드라마틱한 연애를 즐겨요! 화려한 이벤트와 애정 표현을 좋아하며, 상대를 왕처럼 대접하지만 자신도 인정받길 원해요.',
        'career_hint': '연예인, CEO, 디자이너, 이벤트 기획, 교육자 등 무대 위에서 빛나거나 사람을 이끄는 역할에서 최고의 성과를 내요.',
        'lucky_day': '일요일', 'lucky_color': '금색',
        'best_match': ['양자리', '사수자리', '쌍둥이자리'], 'worst_match': ['황소자리', '전갈자리'],
        'advice': '빛나는 것만큼 그림자도 인정하세요. 완벽하지 않아도 사랑받을 수 있다는 걸 알면, 진짜 왕의 여유가 생겨요.',
        'synergy_fire': '사주의 화(火) 기운과 만나면 카리스마가 최고조! 주변을 이끄는 힘이 강해지지만, 자기 과시에 주의하세요.',
        'synergy_earth': '사주의 토(土) 기운이 사자자리에 안정감과 현실감각을 더해줍니다. 화려함에 내실을 더해 진정한 리더로 성장해요.',
        'synergy_water': '사주의 수(水) 기운이 사자자리에 감수성과 공감력을 더해줘요. 카리스마에 따뜻함이 더해져 사람들이 진심으로 따르게 됩니다.',
        'synergy_wood': '사주의 목(木) 기운이 사자자리의 창의력을 배가시켜요. 예술적 재능이 꽃피우며 독창적인 작품을 만들어낼 수 있어요.',
        'synergy_metal': '사주의 금(金) 기운이 사자자리에 전략적 사고를 더해줘요. 감정적 판단을 줄이고 냉철한 리더십을 발휘할 수 있습니다.',
        'synergy_default': '사자자리의 당당함이 사주의 기운과 합쳐져 빛나는 존재감을 만들어요.',
    },
    'virgo': {
        'icon': '♍', 'name': '처녀자리', 'date': '8/23~9/22', 'element': '흙',
        'ruling_planet': '수성 (Mercury)', 'modality': '변동궁',
        'traits': ['분석적', '완벽주의', '실용적', '성실함', '세심함'],
        'desc': '디테일의 달인, 완벽을 추구하는 분석가. 꼼꼼하고 체계적이며 실용적인 해결책을 잘 찾아요.',
        'strength': '분석력이 뛰어나고 체계적으로 일을 처리해요. 실수가 적고 효율적인 방법을 잘 찾으며, 건강과 생활 관리 능력이 탁월합니다.',
        'weakness': '너무 완벽을 추구해 스트레스를 받을 수 있어요. 남에게도 높은 기준을 적용하면 관계가 피곤해질 수 있으니, 때로는 "이 정도면 충분해"를 배우세요.',
        'love_style': '말보다 행동으로 사랑을 표현해요. 상대의 건강을 챙기고, 생활을 도와주는 실질적인 사랑을 해요. 겉으론 차가워 보이지만 속은 따뜻해요.',
        'career_hint': '데이터 분석, 회계사, 의사, 편집자, 연구원, 품질관리 등 정확성과 분석력이 요구되는 분야에서 빛나요.',
        'lucky_day': '수요일', 'lucky_color': '네이비',
        'best_match': ['황소자리', '염소자리', '전갈자리'], 'worst_match': ['사수자리', '쌍둥이자리'],
        'advice': '완벽하지 않아도 괜찮아요. 80%로도 충분히 잘하고 있다는 걸 기억하세요. 자신에게 더 너그러워지면 행복이 가까워져요.',
        'synergy_earth': '사주의 토(土) 기운과 만나면 분석력과 실행력이 배가됩니다. 계획을 세우고 실천하는 능력이 극대화되어 목표 달성률이 높아져요.',
        'synergy_water': '사주의 수(水) 기운이 처녀자리에 유연성과 감수성을 더해줘요. 논리적인 사고에 감성을 더해 더 따뜻한 사람이 될 수 있어요.',
        'synergy_fire': '사주의 화(火) 기운이 처녀자리에 자신감과 결단력을 불어넣어요. 분석만 하지 않고 과감하게 실행하는 힘이 생깁니다.',
        'synergy_wood': '사주의 목(木) 기운이 처녀자리에 창의적 사고를 더해줘요. 틀에 박힌 사고를 넘어 혁신적인 아이디어를 낼 수 있어요.',
        'synergy_metal': '사주의 금(金) 기운이 처녀자리의 분석력을 더욱 날카롭게 만들어요. 전문성이 극대화되어 해당 분야의 최고가 될 수 있습니다.',
        'synergy_default': '처녀자리의 꼼꼼함이 사주의 기운과 만나 실수 없는 완벽함을 만들어냅니다.',
    },
    'libra': {
        'icon': '♎', 'name': '천칭자리', 'date': '9/23~10/22', 'element': '바람',
        'ruling_planet': '금성 (Venus)', 'modality': '활동궁',
        'traits': ['균형감각', '사교적', '미적감각', '공정함', '매력적'],
        'desc': '조화와 아름다움의 외교관. 갈등을 중재하고 사람들 사이에서 균형을 잡는 데 탁월해요.',
        'strength': '사람들과의 관계를 잘 맺고 분위기를 편안하게 만들어요. 미적 감각이 뛰어나고, 공정한 판단력으로 갈등 상황을 잘 해결합니다.',
        'weakness': '결정을 내리기 어려워하고, 갈등을 피하려다 본심을 숨길 수 있어요. 남의 눈치를 보느라 자기 의견을 못 말하는 경우가 있으니 자기주장 연습이 필요해요.',
        'love_style': '로맨틱하고 세련된 연애를 추구해요. 데이트 분위기와 미적 요소를 중시하며, 평등하고 존중받는 관계를 원해요. 상대의 외모와 센스도 중요하게 봐요.',
        'career_hint': '디자이너, 외교관, 변호사, 상담사, 큐레이터, 이벤트 플래너 등 미적 감각과 대인관계가 중요한 분야에서 빛나요.',
        'lucky_day': '금요일', 'lucky_color': '파스텔 핑크',
        'best_match': ['쌍둥이자리', '물병자리', '사자자리'], 'worst_match': ['게자리', '염소자리'],
        'advice': '모든 사람을 만족시킬 수는 없어요. 때로는 누군가를 실망시키더라도 자신의 진짜 마음을 표현하는 것이 진정한 균형이에요.',
        'synergy_metal': '사주의 금(金) 기운과 만나면 미적 감각과 판단력이 극대화됩니다. 예술적 안목이 높아지고 올바른 선택을 하는 힘이 커져요.',
        'synergy_fire': '사주의 화(火) 기운이 천칭자리에 결단력과 추진력을 더해줘요. 우유부단함을 극복하고 빠른 결정을 내릴 수 있게 됩니다.',
        'synergy_water': '사주의 수(水) 기운이 천칭자리에 감성적 깊이를 더해줘요. 표면적 관계를 넘어 깊은 유대감을 형성할 수 있어요.',
        'synergy_earth': '사주의 토(土) 기운이 천칭자리에 현실 감각을 선물해요. 이상과 현실의 균형을 맞추는 능력이 생깁니다.',
        'synergy_wood': '사주의 목(木) 기운이 천칭자리의 성장 욕구를 자극해요. 자기주장을 키우고 독립적인 결정을 내리는 힘이 길러져요.',
        'synergy_default': '천칭자리의 균형감각이 사주의 기운과 어우러져 완벽한 하모니를 만들어요.',
    },
    'scorpio': {
        'icon': '♏', 'name': '전갈자리', 'date': '10/23~11/21', 'element': '물',
        'ruling_planet': '명왕성 (Pluto)', 'modality': '고정궁',
        'traits': ['강렬함', '통찰력', '집중력', '신비로움', '충성심'],
        'desc': '깊고 강렬한 감정의 탐구자. 한번 집중하면 끝을 보는 집요함과 날카로운 통찰력의 소유자예요.',
        'strength': '어떤 것이든 깊이 파고드는 집중력과, 사람의 본심을 꿰뚫어 보는 통찰력이 있어요. 충성심이 강해 한번 신뢰한 사람은 끝까지 지켜요.',
        'weakness': '의심이 많고 질투심이 강할 수 있어요. 상처를 받으면 오래 기억하고, 복수심을 품기도 해요. 용서하고 놓아주는 연습이 필요합니다.',
        'love_style': '전부 아니면 전무! 깊고 강렬한 사랑을 해요. 상대의 모든 것을 알고 싶어하며, 일단 사랑에 빠지면 영혼까지 주는 타입. 가벼운 연애는 못해요.',
        'career_hint': '심리학자, 수사관, 외과의사, 연구원, 투자 분석가 등 깊이와 집중력이 요구되는 분야에서 최고가 될 수 있어요.',
        'lucky_day': '화요일', 'lucky_color': '와인색',
        'best_match': ['게자리', '물고기자리', '처녀자리'], 'worst_match': ['사자자리', '물병자리'],
        'advice': '모든 것을 통제하려 하지 마세요. 놓아줄 때 오히려 더 많은 것이 돌아오는 법이에요. 당신의 깊이는 이미 충분히 특별해요.',
        'synergy_water': '사주의 수(水) 기운과 만나면 직관력과 통찰력이 극강해집니다. 숨겨진 진실을 꿰뚫어 보는 눈이 더욱 날카로워져요.',
        'synergy_earth': '사주의 토(土) 기운이 전갈자리에 안정감과 인내심을 더해줘요. 감정의 폭풍을 잘 다스리고 현실적인 성과를 낼 수 있게 됩니다.',
        'synergy_fire': '사주의 화(火) 기운이 전갈자리에 행동력을 불어넣어요. 머릿속 계획을 실행으로 옮기는 추진력이 강해져요.',
        'synergy_wood': '사주의 목(木) 기운이 전갈자리에 재생과 성장의 에너지를 줘요. 과거의 상처를 치유하고 새롭게 시작하는 힘이 생겨요.',
        'synergy_metal': '사주의 금(金) 기운이 전갈자리의 집중력을 더욱 예리하게 만들어요. 목표를 향한 레이저 같은 집중력으로 대단한 성취를 이뤄냅니다.',
        'synergy_default': '전갈자리의 집중력이 사주의 기운과 합쳐져 어떤 것이든 꿰뚫어 보는 눈을 줍니다.',
    },
    'sagittarius': {
        'icon': '♐', 'name': '사수자리', 'date': '11/22~12/21', 'element': '불',
        'ruling_planet': '목성 (Jupiter)', 'modality': '변동궁',
        'traits': ['자유로움', '낙관적', '모험심', '철학적', '유머감각'],
        'desc': '끝없는 탐험을 꿈꾸는 자유로운 영혼. 새로운 경험과 지식에 대한 갈증이 끊이지 않아요.',
        'strength': '긍정적인 에너지가 넘치고 어떤 상황에서도 희망을 잃지 않아요. 다양한 문화와 사상에 열린 마음을 가지고 있으며, 유머로 사람들을 행복하게 해요.',
        'weakness': '책임감이 부족하다는 소리를 들을 수 있어요. 약속을 가볍게 여기거나, 깊이 없이 넘어가는 경향이 있으니 신중함을 기르세요.',
        'love_style': '자유를 존중해주는 상대를 원해요! 함께 여행하고 새로운 경험을 나눌 수 있는 파트너가 이상적. 속박을 느끼면 도망가고 싶어지는 타입.',
        'career_hint': '여행작가, 교수, 철학자, 국제 비즈니스, 스포츠, 방송인 등 자유롭고 다양한 경험이 가능한 분야에서 빛나요.',
        'lucky_day': '목요일', 'lucky_color': '보라',
        'best_match': ['양자리', '사자자리', '물병자리'], 'worst_match': ['처녀자리', '물고기자리'],
        'advice': '자유는 책임감 위에 세워지는 거예요. 깊이 있는 관계와 끝까지 해내는 경험이 당신을 진짜 자유롭게 만들어줄 거예요.',
        'synergy_fire': '사주의 화(火) 기운과 만나면 모험심과 낙관이 극대화! 어디서든 빛나고, 새로운 도전이 성공으로 이어져요.',
        'synergy_metal': '사주의 금(金) 기운이 사수자리에 집중력과 마무리 능력을 더해줍니다. 시작한 모험을 완벽히 마무리하는 힘이 생겨요.',
        'synergy_earth': '사주의 토(土) 기운이 사수자리에 현실감각을 더해줘요. 꿈을 현실로 만드는 구체적인 계획 능력이 생깁니다.',
        'synergy_water': '사주의 수(水) 기운이 사수자리에 감성적 깊이를 줘요. 표면적 경험을 넘어 내면의 성장을 이루는 여행을 하게 돼요.',
        'synergy_wood': '사주의 목(木) 기운이 사수자리의 성장 에너지를 배가시켜요. 배움의 폭이 넓어지고 지적 성장이 가속화됩니다.',
        'synergy_default': '사수자리의 자유로움이 사주의 기운과 만나 넓은 세계를 향한 발걸음을 이끌어요.',
    },
    'capricorn': {
        'icon': '♑', 'name': '염소자리', 'date': '12/22~1/19', 'element': '흙',
        'ruling_planet': '토성 (Saturn)', 'modality': '활동궁',
        'traits': ['책임감', '야망', '끈기', '현실적', '자기관리'],
        'desc': '정상을 향해 묵묵히 오르는 야심가. 책임감이 강하고 장기적인 목표를 위해 꾸준히 노력하는 사람이에요.',
        'strength': '자기관리와 계획 능력이 뛰어나요. 장기적 목표를 세우고 묵묵히 실행하는 인내심이 있으며, 나이가 들수록 빛나는 대기만성형이에요.',
        'weakness': '일 중독에 빠지기 쉽고, 감정 표현이 서툴러요. 너무 현실적이라 꿈을 포기하거나, 즐거움을 뒤로 미루는 경향이 있어요. 가끔은 놀 줄도 알아야 해요.',
        'love_style': '진지하고 책임감 있는 연애를 해요. 가볍게 시작하지 않지만, 한번 시작하면 끝까지 함께해요. 안정적인 미래를 함께 계획할 수 있는 상대를 원해요.',
        'career_hint': 'CEO, 공무원, 건축가, 변호사, 경영 컨설턴트 등 장기적 비전과 체계적 관리가 필요한 분야에서 정상에 올라요.',
        'lucky_day': '토요일', 'lucky_color': '브라운',
        'best_match': ['황소자리', '처녀자리', '전갈자리'], 'worst_match': ['양자리', '천칭자리'],
        'advice': '성공도 중요하지만 과정에서의 행복도 놓치지 마세요. 가끔은 계획을 내려놓고 즐기는 시간이 오히려 더 큰 에너지를 줄 거예요.',
        'synergy_earth': '사주의 토(土) 기운과 만나면 현실적 성공 확률이 극대화됩니다. 탄탄한 기반 위에 차곡차곡 성과를 쌓아가요.',
        'synergy_wood': '사주의 목(木) 기운이 염소자리에 유연성과 창의성을 더해줘요. 딱딱한 사고를 부드럽게 바꿔 새로운 기회를 잡을 수 있어요.',
        'synergy_fire': '사주의 화(火) 기운이 염소자리에 열정과 따뜻함을 불어넣어요. 냉철한 판단에 감성을 더해 더 매력적인 리더가 됩니다.',
        'synergy_water': '사주의 수(水) 기운이 염소자리에 직관력과 유연성을 줘요. 계획에 없던 기회를 포착하는 눈이 생겨요.',
        'synergy_metal': '사주의 금(金) 기운이 염소자리의 야망을 현실로 만드는 실행력을 극대화해요. 목표 달성 능력이 최강이 됩니다.',
        'synergy_default': '염소자리의 끈기가 사주의 기운과 합쳐져 시간이 갈수록 빛나는 인생을 만들어요.',
    },
    'aquarius': {
        'icon': '♒', 'name': '물병자리', 'date': '1/20~2/18', 'element': '바람',
        'ruling_planet': '천왕성 (Uranus)', 'modality': '고정궁',
        'traits': ['독창적', '혁신적', '박애정신', '자유로움', '지적'],
        'desc': '시대를 앞서가는 혁신가. 독창적인 생각과 인류애로 세상을 바꾸고 싶어하는 이상주의자예요.',
        'strength': '남들과 다른 시각으로 세상을 보는 독창성이 있어요. 편견 없이 다양한 사람을 받아들이며, 사회적 문제에 관심이 많고 혁신적 해결책을 찾아내요.',
        'weakness': '감정 표현이 서툴고 너무 머리로만 생각하려 해요. 개인적 친밀감보다 인류 전체를 생각하는 경향이 있어서, 가까운 사람이 소외감을 느낄 수 있어요.',
        'love_style': '친구같은 연애를 선호해요! 지적 교류가 중요하고, 서로의 자유를 존중하는 관계를 원해요. 독특하고 남다른 사람에게 끌리며, 평범한 연애는 지루해해요.',
        'career_hint': 'IT 개발자, 사회운동가, 발명가, 우주공학, 스타트업 창업가 등 혁신적이고 미래지향적인 분야에서 세상을 바꿔요.',
        'lucky_day': '토요일', 'lucky_color': '전기 블루',
        'best_match': ['쌍둥이자리', '천칭자리', '사수자리'], 'worst_match': ['황소자리', '전갈자리'],
        'advice': '머리뿐 아니라 가슴으로도 느껴보세요. 가까운 사람에게 마음을 열면 당신의 혁신이 더 따뜻한 세상을 만들 수 있어요.',
        'synergy_metal': '사주의 금(金) 기운과 만나면 혁신적 사고가 현실화되는 힘이 생겨요. 아이디어를 구체적인 결과물로 만들어내는 능력이 극대화됩니다.',
        'synergy_fire': '사주의 화(火) 기운이 물병자리에 열정과 실행력을 더해줍니다. 머릿속 계획을 즉시 행동으로 옮기는 추진력이 생겨요.',
        'synergy_water': '사주의 수(水) 기운이 물병자리에 감성과 공감력을 더해줘요. 차가운 논리에 따뜻한 마음을 더해 사람들의 진심을 얻을 수 있어요.',
        'synergy_earth': '사주의 토(土) 기운이 물병자리에 현실 감각을 선물해요. 이상주의적 꿈을 실현 가능한 계획으로 바꾸는 힘이 생깁니다.',
        'synergy_wood': '사주의 목(木) 기운이 물병자리의 성장을 촉진해요. 사회적 영향력이 커지고 더 많은 사람에게 영감을 줄 수 있어요.',
        'synergy_default': '물병자리의 독창성이 사주의 기운과 어우러져 남들과 다른 길에서 성공해요.',
    },
    'pisces': {
        'icon': '♓', 'name': '물고기자리', 'date': '2/19~3/20', 'element': '물',
        'ruling_planet': '해왕성 (Neptune)', 'modality': '변동궁',
        'traits': ['상상력', '공감능력', '예술성', '직관력', '온유함'],
        'desc': '꿈과 현실의 경계를 넘나드는 몽상가. 풍부한 상상력과 깊은 공감 능력으로 예술적 영감이 넘쳐요.',
        'strength': '상상력과 창의력이 무한하며, 다른 사람의 감정을 깊이 이해하는 공감 능력이 있어요. 예술적 재능이 뛰어나고, 영적인 직관이 발달했어요.',
        'weakness': '현실감각이 부족하고 몽상에 빠지기 쉬워요. 남의 감정에 너무 동화되어 자신을 잃을 수 있고, 결정을 회피하는 경향이 있어요.',
        'love_style': '동화 같은 로맨틱한 사랑을 꿈꿔요. 영혼의 짝을 찾고 싶어하며, 상대를 이상화하는 경향이 있어요. 헌신적이지만 경계를 설정하는 것도 중요해요.',
        'career_hint': '예술가, 음악가, 사진작가, 심리상담사, 간호사, 영화감독 등 감성과 창의력을 발휘할 수 있는 분야에서 빛나요.',
        'lucky_day': '목요일', 'lucky_color': '연보라',
        'best_match': ['전갈자리', '게자리', '황소자리'], 'worst_match': ['쌍둥이자리', '사수자리'],
        'advice': '꿈을 꾸되, 두 발은 땅에 딛고 있으세요. 당신의 상상력에 현실적 행동을 더하면 정말로 마법 같은 일이 일어날 수 있어요.',
        'synergy_water': '사주의 수(水) 기운과 만나면 예술적 감성과 영적 직관이 극대화됩니다. 초자연적인 감각이 깊어지고 예술 작품에 영혼을 불어넣을 수 있어요.',
        'synergy_wood': '사주의 목(木) 기운이 물고기자리에 현실적 실행력을 더해줘요. 꿈을 현실로 만드는 구체적인 행동력이 생겨요.',
        'synergy_fire': '사주의 화(火) 기운이 물고기자리에 자신감과 에너지를 불어넣어요. 소극적인 면을 극복하고 적극적으로 자신을 표현할 수 있어요.',
        'synergy_earth': '사주의 토(土) 기운이 물고기자리에 현실 감각과 안정감을 줘요. 몽상을 현실의 성과로 바꾸는 힘이 생깁니다.',
        'synergy_metal': '사주의 금(金) 기운이 물고기자리에 논리적 사고를 더해줘요. 감성과 이성의 균형으로 더 완성도 높은 작품을 만들어낼 수 있어요.',
        'synergy_default': '물고기자리의 상상력이 사주의 기운과 만나 창의적인 인생을 펼쳐냅니다.',
    },
}

def analyze_constellation(month: int, day: int, strongest_oheng: str = ''):
    """생월/생일로 별자리 분석 반환"""
    # 별자리 판별
    signs = [
        (1, 20, 'aquarius'), (2, 19, 'pisces'), (3, 21, 'aries'), (4, 20, 'taurus'),
        (5, 21, 'gemini'), (6, 22, 'cancer'), (7, 23, 'leo'), (8, 23, 'virgo'),
        (9, 23, 'libra'), (10, 23, 'scorpio'), (11, 22, 'sagittarius'), (12, 22, 'capricorn'),
    ]
    sign_key = 'capricorn'  # default (12/22~1/19)
    for i, (m, d, key) in enumerate(signs):
        if month == m and day >= d:
            sign_key = key
        elif month == m and day < d:
            # 이전 별자리
            sign_key = signs[i - 1][2] if i > 0 else 'capricorn'
            break

    data = CONSTELLATION_DATA[sign_key]

    # 사주 오행과 별자리 시너지 매칭
    oheng_to_element = {'목': 'wood', '화': 'fire', '토': 'earth', '금': 'metal', '수': 'water'}
    element_key = oheng_to_element.get(strongest_oheng, '')
    synergy = data.get(f'synergy_{element_key}', data['synergy_default'])

    return {
        'key': sign_key,
        'icon': data['icon'],
        'name': data['name'],
        'date': data['date'],
        'element': data['element'],
        'ruling_planet': data['ruling_planet'],
        'modality': data['modality'],
        'traits': data['traits'],
        'desc': data['desc'],
        'strength': data['strength'],
        'weakness': data['weakness'],
        'love_style': data['love_style'],
        'career_hint': data['career_hint'],
        'lucky_day': data['lucky_day'],
        'lucky_color': data['lucky_color'],
        'best_match': data['best_match'],
        'worst_match': data['worst_match'],
        'advice': data['advice'],
        'synergy': synergy,
    }


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
    '천덕귀인': {
        'icon': '🌟', 'name': '천덕귀인 (天德貴人)', 'type': '하늘의 보호',
        'desc': '하늘이 내린 덕의 별. 큰 위기 속에서도 보이지 않는 손길의 도움을 받아 무사히 넘어갑니다. 인덕이 두텁고 베푼 만큼 돌아오는 사주예요.',
        'tip': '주변에 베푸세요. 당신의 선행이 위기 때 보호막이 됩니다.'
    },
    '월덕귀인': {
        'icon': '🌙', 'name': '월덕귀인 (月德貴人)', 'type': '안정의 별',
        'desc': '달처럼 부드럽고 안정적인 보호의 별. 가정과 인간관계에서 따뜻한 인복이 있어요. 어머니·연인·배우자의 도움이 큰 사주입니다.',
        'tip': '가족과의 시간을 소중히 하세요. 결혼·가정 운이 특히 좋습니다.'
    },
    '홍염살': {
        'icon': '🌹', 'name': '홍염살 (紅艶殺)', 'type': '치명적 매력',
        'desc': '도화살의 강화 버전. 강렬하고 치명적인 매력으로 이성을 끌어당기는 별. 연예·예술·미용 분야에서 두각을 나타냅니다. 다만 구설수와 삼각관계 주의.',
        'tip': '매력을 무기로 쓰되 관계 정리는 분명하게. 진정성 있는 인연을 찾으세요.'
    },
    '괴강살': {
        'icon': '⚒️', 'name': '괴강살 (魁罡殺)', 'type': '극단의 카리스마',
        'desc': '극과 극을 오가는 강력한 별. 큰 성공 또는 큰 실패의 양극단. 리더십과 카리스마는 압도적이지만, 한번 무너지면 크게 다칩니다. 군경·법조·의학·정치에 강한 사주.',
        'tip': '극단을 피하고 중도를 유지. 자만하지 말고 겸손하면 평생 강력한 영향력.'
    },
    '금여록': {
        'icon': '🏆', 'name': '금여록 (金輿祿)', 'type': '풍요의 별',
        'desc': '황금 마차의 별. 부부 인연이 좋고 배우자가 부와 명예를 가져오는 사주. 또한 본인도 풍요로운 삶을 누리는 복록이 큰 별입니다.',
        'tip': '인연을 소중히. 결혼 후 더 큰 운이 열립니다. 배우자 선택이 인생 좌우.'
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

    # ────────────────────────────────────────
    # 8) 천덕귀인 — 월지 기준 해당 천간이 사주에 있으면 작동
    # ────────────────────────────────────────
    cheondeok_target = CHEONDEOK_MAP.get(month_p[1])
    all_gan = [year_p[0], month_p[0], day_p[0], time_p[0]]
    if cheondeok_target and cheondeok_target in all_gan:
        found.append('천덕귀인')

    # ────────────────────────────────────────
    # 9) 월덕귀인 — 월지 기준 해당 천간이 사주에 있으면 작동
    # ────────────────────────────────────────
    weoldeok_target = WEOLDEOK_MAP.get(month_p[1])
    if weoldeok_target and weoldeok_target in all_gan:
        found.append('월덕귀인')

    # ────────────────────────────────────────
    # 10) 홍염살 — 일간 기준 해당 지지가 사주에 있으면 작동
    # ────────────────────────────────────────
    hongyeom_target = HONGYEOM_MAP.get(ilgan)
    if hongyeom_target and hongyeom_target in all_jiji:
        found.append('홍염살')

    # ────────────────────────────────────────
    # 11) 괴강살 — 일주 한정
    # ────────────────────────────────────────
    if (day_p[0], day_p[1]) in GOEGANG_PAIRS:
        found.append('괴강살')

    # ────────────────────────────────────────
    # 12) 금여록 — 일간 기준 해당 지지가 사주에 있으면 작동
    # ────────────────────────────────────────
    keumyeo_target = KEUMYEO_MAP.get(ilgan)
    if keumyeo_target and keumyeo_target in all_jiji:
        found.append('금여록')

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
                              calendar_type: str = 'solar', is_leap_month: bool = False,
                              gender: str = 'F',
                              apply_dst: bool = True, apply_solar_time: bool = False,
                              birth_city: str = 'Seoul',
                              name: str = ''):
    # 음력 입력 시 양력 변환 (응답 메타용)
    solar_date, lunar_original = resolve_birth_date(birth_date, calendar_type, is_leap_month)
    # 원본 입력 그대로 라이브러리에 넣어 계산 (음력은 음력대로)
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    year, month, day = map(int, solar_date.split('-'))
    # birth_time 방어: 'unknown' 등 비정상 값 → 정오(12시) 처리
    try:
        hour = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        hour = 12

    # 📿 정확한 사주 (24절기 + 자시 + 시간보정)
    year_p, month_p, day_p, time_p = calc_pillars_accurate(
        raw_y, raw_m, raw_d, hour, calendar_type, is_leap_month,
        apply_dst=apply_dst, apply_solar_time=apply_solar_time, city=birth_city
    )
    time_adjustments = getattr(calc_pillars_accurate, 'last_adjustments', [])

    pillars = [year_p, month_p, day_p, time_p]
    oheng_simple = analyze_oheng(pillars)              # 기본 카운트 (호환)
    oheng_adv = analyze_oheng_advanced(pillars)        # 정밀 점수 (지장간+가중치)
    # 시각화용 — 정밀 점수 기반 정수 막대를 oheng으로 사용
    oheng = oheng_adv['count']
    ilgan = day_p[0]
    ilgan_name_lang = ILGAN_NAMES.get(lang, ILGAN_NAMES['ko'])[ilgan]

    # ✨ 신살 분석
    sinsal = analyze_sinsal(pillars, ilgan)

    # 🐉 12지신 띠 분석 (년지 기준)
    zodiac = analyze_zodiac(year_p[1])

    # ⭐ 별자리 분석 (양력 생월/일 기준)
    constellation = analyze_constellation(
        int(solar_date.split('-')[1]),
        int(solar_date.split('-')[2]),
        oheng_adv.get('strongest', '')
    )

    # 📜 대운 분석 (10년 단위 인생 흐름)
    daewoon = calc_daewoon(raw_y, raw_m, raw_d, hour, gender, calendar_type, is_leap_month, count=10)

    # ✍️ 음향오행 분석 (이름이 있을 때만)
    phonetic = None
    if name and name != '당신':
        phonetic = analyze_phonetic_oheng(name, oheng_adv.get('pct'))

    # ⏰ 시간 보정 정보 (응답용)
    time_correction = {
        'applied': len(time_adjustments) > 0,
        'adjustments': time_adjustments,
        'apply_dst': apply_dst,
        'apply_solar_time': apply_solar_time,
        'birth_city': birth_city if apply_solar_time else None,
    }

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
        'oheng_advanced': oheng_adv,    # 정밀 점수 (지장간+가중치)
        'mbti': mbti,
        'synergy': {'title': analysis['synergy_title'], 'desc': analysis['synergy_desc']},
        'compatibility': {'title': analysis['compatibility_title'], 'desc': analysis['compatibility_desc']},
        'lucky': lucky,
        'sinsal': sinsal,
        'zodiac': zodiac,
        'constellation': constellation,
        'daewoon': daewoon,
        'phonetic_oheng': phonetic,
        'time_correction': time_correction,
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
    # ⏰ 시간 보정 옵션
    apply_dst: bool = True              # 서머타임 자동 보정 (1948-1988)
    apply_solar_time: bool = False      # 시태양시 (경도) 보정
    birth_city: str = 'Seoul'           # 시태양시 보정용 도시

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
            calendar_type=input_data.calendar_type, is_leap_month=input_data.is_leap_month,
            gender=input_data.gender,
            apply_dst=input_data.apply_dst, apply_solar_time=input_data.apply_solar_time,
            birth_city=input_data.birth_city,
            name=input_data.name
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
    try:
        hour = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        hour = 12

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


def _get_chemi_type(total_score, oh_rel, mbti_a, mbti_b):
    """케미 유형 이름 + 한줄 명대사 반환"""
    # 오행 관계 기반
    if oh_rel == 'saeng':  # 상생
        if total_score >= 85:
            return ('🔥 운명의 소울메이트', '"만나자마자 느꼈어, 이 사람이다"')
        return ('🌿 키워주는 힐러 케미', '"네 옆에 있으면 왜 이렇게 편하지?"')
    elif oh_rel == 'geuk':  # 상극
        if total_score >= 70:
            return ('⚡ 밀당 스파크 케미', '"싸우면서 더 가까워지는 우리"')
        return ('🌊 도전적 성장 케미', '"너 때문에 매일 성장하는 기분이야"')
    elif oh_rel == 'same':  # 동일 오행
        return ('🪞 거울 소울 케미', '"너랑 나, 왜 이렇게 닮았어?"')
    else:  # 조화
        if total_score >= 80:
            return ('🌈 자연스러운 하모니 케미', '"우리 사이엔 말이 필요 없어"')
        return ('🎵 리듬이 맞는 듀엣 케미', '"같이 있으면 어색하지 않은 사이"')


def _get_oheng_relation_type(a_oheng, b_oheng):
    """오행 관계 타입 반환 (saeng/geuk/same/harmony)"""
    if a_oheng == b_oheng:
        return 'same'
    if OHENG_SAENG.get(a_oheng) == b_oheng or OHENG_SAENG.get(b_oheng) == a_oheng:
        return 'saeng'
    if OHENG_GEUK.get(a_oheng) == b_oheng or OHENG_GEUK.get(b_oheng) == a_oheng:
        return 'geuk'
    return 'harmony'


def _get_ddoddo_comment(total_score):
    """또또의 궁합 코멘트 (점수별 표정 + 대사)"""
    if total_score >= 90:
        return {
            'expression': '😻',
            'comment': '이 조합은 또또도 감동이야! 우주가 점찍어준 사이라냥~✨',
            'sub': '둘이 만난 건 우연이 아니라 운명이다냥!'
        }
    elif total_score >= 80:
        return {
            'expression': '😸',
            'comment': '오오~ 꽤 좋은 궁합이다냥! 서로 빛나게 해주는 사이~⭐',
            'sub': '약간의 노력이면 천생연분이 될 수 있다냥!'
        }
    elif total_score >= 70:
        return {
            'expression': '🐱',
            'comment': '나쁘지 않은 궁합이다냥~ 대화가 핵심이다냥!',
            'sub': '서로의 다름을 즐기면 더 깊어질 수 있다냥~'
        }
    elif total_score >= 60:
        return {
            'expression': '😿',
            'comment': '음... 좀 노력이 필요한 사이다냥~',
            'sub': '하지만 노력하는 사랑이 더 단단하다냥! 포기하지 마라냥!'
        }
    else:
        return {
            'expression': '🙀',
            'comment': '으악... 도전적인 조합이다냥!',
            'sub': '그래도 정반대가 끌리는 법이라냥~ 서로 배우면 최강이다냥!'
        }


def calc_compatibility(person_a: dict, person_b: dict) -> dict:
    """두 사람 사주 + MBTI 궁합 분석"""
    def make_profile(p):
        raw_y, raw_m, raw_d = map(int, p['birth_date'].split('-'))
        try:
            h = int(p['birth_time'].split(':')[0])
        except (ValueError, AttributeError):
            h = 12
        cal_type = p.get('calendar_type', 'solar')
        leap = p.get('is_leap_month', False)
        # 📿 정확한 사주
        yp, mp, dp, tp = calc_pillars_accurate(raw_y, raw_m, raw_d, h, cal_type, leap)
        # 양력 변환 (메타용)
        y, m, dd = map(int, resolve_birth_date(p['birth_date'], cal_type, leap)[0].split('-'))
        ilgan = dp[0]
        pillars_list = [yp, mp, dp, tp]
        oheng_data = analyze_oheng_advanced(pillars_list)
        return {
            'name': p.get('name') or '익명',
            'gender': p.get('gender','F'),
            'ilgan': ilgan,
            'ilgan_name': ILGAN_NAMES['ko'][ilgan],
            'ilgan_oheng': CHEONGAN_OHENG[ilgan],
            'year_jiji': yp[1],
            'pillars': {'year':yp,'month':mp,'day':dp,'time':tp},
            'mbti': p['mbti'],
            'oheng_pct': oheng_data['pct'],
            'oheng_strongest': oheng_data['strongest'],
            'oheng_weakest': oheng_data['weakest'],
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

    # 케미 유형
    oh_rel_type = _get_oheng_relation_type(a['ilgan_oheng'], b['ilgan_oheng'])
    chemi_name, chemi_quote = _get_chemi_type(total, oh_rel_type, a['mbti'], b['mbti'])

    # 또또 코멘트
    ddoddo = _get_ddoddo_comment(total)

    return {
        'person_a': a,
        'person_b': b,
        'total_score': total,
        'grade': grade,
        'grade_emoji': grade_emoji,
        'grade_desc': grade_desc,
        'chemi_name': chemi_name,
        'chemi_quote': chemi_quote,
        'ddoddo': ddoddo,
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


@app.post("/get-compatibility-full")
async def get_compatibility_full(data: CompatibilityInput):
    """광고 시청 후 궁합 상세 반환 (결제 검증 없음)"""
    result = calc_compatibility(data.person_a.dict(), data.person_b.dict())
    result['unlocked'] = True
    return result


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
    try:
        h = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        h = 12
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

    # 월별 럭키 아이템/컬러 (오행별)
    LUCKY_BY_OHENG = {
        '木': {'color': '초록색/연두색', 'item': '식물 화분, 나무 소품', 'food': '녹색 채소, 샐러드'},
        '火': {'color': '빨간색/주황색', 'item': '캔들, 따뜻한 조명', 'food': '매운 음식, 홍삼'},
        '土': {'color': '노란색/베이지', 'item': '도자기, 흙냄새 향초', 'food': '곡물, 고구마'},
        '金': {'color': '흰색/골드', 'item': '금속 악세사리, 시계', 'food': '흰쌀밥, 배'},
        '水': {'color': '파란색/검정', 'item': '수정, 물 관련 소품', 'food': '해산물, 수프'},
    }

    # 월별 한줄 행동 팁 (오행 관계별)
    ACTION_TIPS = {
        'same': '자신만의 루틴을 지키세요. 안정이 곧 힘!',
        'saeng_me': '적극적으로 행동할 때! 기회를 잡으세요.',
        'me_saeng': '배움과 성장에 투자하기 좋은 시기예요.',
        'geuk_me': '무리하지 마세요. 휴식이 전략입니다.',
        'me_geuk': '도전정신이 빛나는 달! 단, 인간관계 조심.',
        'neutral': '흐름에 맡기되, 작은 변화를 시도해보세요.',
    }

    months = []
    for mon in range(1, 13):
        title, desc = base_themes[mon]
        target_p = calc_month_pillar(year, mon)
        mo_oheng = CHEONGAN_OHENG[target_p[0]]

        # 오행 관계 판단
        if ilgan_oheng == mo_oheng:
            rel = 'same'
        elif OHENG_SAENG.get(mo_oheng) == ilgan_oheng:
            rel = 'saeng_me'
        elif OHENG_SAENG.get(ilgan_oheng) == mo_oheng:
            rel = 'me_saeng'
        elif OHENG_GEUK.get(mo_oheng) == ilgan_oheng:
            rel = 'geuk_me'
        elif OHENG_GEUK.get(ilgan_oheng) == mo_oheng:
            rel = 'me_geuk'
        else:
            rel = 'neutral'

        lucky = LUCKY_BY_OHENG.get(mo_oheng, LUCKY_BY_OHENG['木'])

        months.append({
            'month': mon,
            'label': MONTH_LABELS[mon-1],
            'season': season_of(mon),
            'pillar': f'{target_p[0]}{target_p[1]}',
            'pillar_oheng': mo_oheng,
            'title': title,
            'desc': desc,
            'lucky_color': lucky['color'],
            'lucky_item': lucky['item'],
            'lucky_food': lucky['food'],
            'action_tip': ACTION_TIPS[rel],
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


@app.post("/get-yearly-fortune-full")
async def get_yearly_full(data: YearlyFortuneInput):
    """광고 시청 후 12개월 전체 응답 (결제 검증 없음)"""
    result = build_yearly_fortune(data.birth_date, data.birth_time, data.mbti, data.target_year,
                                   calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    result['unlocked'] = True
    return result


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

# ═══════════════════════════════════════════════
# 🔐 토스 로그인 연결 끊기 콜백
# ═══════════════════════════════════════════════

TOSS_CALLBACK_AUTH = os.getenv("TOSS_CALLBACK_AUTH", "c2FqdS1tYnRpOmM4YzgwOGQ4ZWRhZWZjNWE4YmFjMWM3OTM4NGU1NTcz")

@app.get("/toss/disconnect-callback")
async def toss_disconnect_callback(request: Request):
    """토스 회원 탈퇴/연결 끊기 시 호출되는 콜백"""
    # Basic Auth 검증
    auth_header = request.headers.get("authorization", "")
    expected = f"Basic {TOSS_CALLBACK_AUTH}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    params = dict(request.query_params)
    print(f"[TOSS] 연결 끊기 콜백 수신: {params}")
    # 필요 시 사용자 데이터 정리 로직 추가
    return {"status": "ok", "message": "disconnect callback received"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
