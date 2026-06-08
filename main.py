import os
import json
import uuid
import base64
import httpx
import time
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

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")

# Heavenly Stems / Earthly Branches — sxtwl integer index → English key
_GAN = ['yang_wood','yin_wood','yang_fire','yin_fire','yang_earth','yin_earth','yang_metal','yin_metal','yang_water','yin_water']
_JI  = ['rat','ox','tiger','rabbit','dragon','snake','horse','goat','monkey','rooster','dog','pig']


def convert_lunar_to_solar(lunar_date: str, is_leap_month: bool = False) -> str:
    """Lunar YYYY-MM-DD → Solar YYYY-MM-DD conversion"""
    try:
        y, m, d = map(int, lunar_date.split('-'))
        cal = KoreanLunarCalendar()
        cal.setLunarDate(y, m, d, bool(is_leap_month))
        solar = cal.SolarIsoFormat()
        if not solar or solar == "0000-00-00":
            raise ValueError("Conversion failed")
        return solar
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Lunar to solar conversion failed: {str(e)[:120]}")


def resolve_birth_date(birth_date: str, calendar_type: str = 'solar', is_leap_month: bool = False) -> tuple:
    """Normalize input date to solar. Returns (solar_date, original_lunar_or_none)."""
    if calendar_type == 'lunar':
        solar = convert_lunar_to_solar(birth_date, is_leap_month)
        return solar, birth_date
    return birth_date, None


# ─────────────────────────────────────────────
# Grand Cycle (大運) — 10-year life phases
# ─────────────────────────────────────────────
_YANG_GAN_SET = {'yang_wood', 'yang_fire', 'yang_earth', 'yang_metal', 'yang_water'}

_DAEWOON_THEMES = {
    'wood': 'A season of growth, challenges, and fresh starts. Energy pushes outward.',
    'fire': 'A season of expansion, charisma, and spotlight moments. People gather around you.',
    'earth': 'A season of stability, harvest, and trust-building. Laying solid foundations.',
    'metal': 'A season of decisiveness, refinement, and completion. Becoming sharper and stronger.',
    'water': 'A season of inner wisdom, reflection, and flow. Deepening from within.',
}

# ─────────────────────────────────────────────
# Ten Gods — relationship between Day Master and other stems
# ─────────────────────────────────────────────
_GAN_YIN_YANG = {
    'yang_wood':'yang','yin_wood':'yin','yang_fire':'yang','yin_fire':'yin','yang_earth':'yang',
    'yin_earth':'yin','yang_metal':'yang','yin_metal':'yin','yang_water':'yang','yin_water':'yin'
}
_OHENG_SAENG_CYCLE = {'wood':'fire', 'fire':'earth', 'earth':'metal', 'metal':'water', 'water':'wood'}
_OHENG_GEUK_CYCLE  = {'wood':'earth', 'earth':'water', 'water':'fire', 'fire':'metal', 'metal':'wood'}

# ─────────────────────────────────────────────
# Sound Element Analysis — English alphabet → Five Elements
# Based on Eastern phonetic philosophy: articulation position determines element
# ─────────────────────────────────────────────
_ALPHA_ELEMENT = {
    'G': 'wood', 'K': 'wood', 'C': 'wood',
    'N': 'fire', 'D': 'fire', 'L': 'fire', 'R': 'fire', 'T': 'fire',
    'M': 'water', 'B': 'water', 'P': 'water', 'F': 'water', 'V': 'water', 'W': 'water',
    'S': 'metal', 'Z': 'metal', 'J': 'metal', 'X': 'metal',
    'H': 'earth', 'Q': 'earth',
    'A': 'earth', 'E': 'earth', 'I': 'earth', 'O': 'earth', 'U': 'earth', 'Y': 'earth',
}

# Consonants get full weight (1.0), vowels get reduced weight (0.5)
_VOWELS = set('AEIOU')


def analyze_phonetic_oheng(name: str, sajus_oheng_pct: dict = None):
    """
    Sound Element analysis for an English name.
    Maps each letter to a Five Element based on its articulation position.
    """
    if not name:
        return None

    letters = []
    distribution = {'wood': 0.0, 'fire': 0.0, 'earth': 0.0, 'metal': 0.0, 'water': 0.0}
    for ch in name.upper():
        elem = _ALPHA_ELEMENT.get(ch)
        if not elem:
            continue
        weight = 0.5 if ch in _VOWELS else 1.0
        letters.append({'char': ch, 'element': elem, 'weight': weight})
        distribution[elem] += weight

    if not letters:
        return None

    strongest = max(distribution, key=distribution.get) if any(distribution.values()) else 'earth'

    compatibility = {'score': 70, 'level': 'Neutral', 'desc': 'A balanced combination.'}
    if sajus_oheng_pct:
        sorted_saju = sorted(sajus_oheng_pct.items(), key=lambda x: x[1])
        weakest_saju = sorted_saju[0][0]
        strongest_saju = sorted_saju[-1][0]

        name_total = sum(distribution.values()) or 1
        name_pct = {k: round(v * 100 / name_total, 1) for k, v in distribution.items()}
        name_top = max(name_pct, key=name_pct.get)

        element_labels = {'wood': 'Wood', 'fire': 'Fire', 'earth': 'Earth', 'metal': 'Metal', 'water': 'Water'}
        if name_top == weakest_saju:
            score = 90
            level = 'Complementary ✨'
            desc = f'Your name fills the {element_labels[weakest_saju]} energy your chart lacks. A beautifully balanced pairing!'
        elif name_top == strongest_saju:
            score = 50
            level = 'Amplifying'
            desc = f'Your name doubles down on {element_labels[strongest_saju]} energy. Strong identity, but less balance.'
        elif _OHENG_SAENG_CYCLE.get(name_top) == weakest_saju:
            score = 80
            level = 'Indirect Complement'
            desc = f'Your name\'s {element_labels[name_top]} nurtures the {element_labels[weakest_saju]} you need. Good flow.'
        elif _OHENG_GEUK_CYCLE.get(name_top) == strongest_saju:
            score = 75
            level = 'Balancing'
            desc = f'Your name tempers your excess {element_labels[strongest_saju]}. A stabilizing combination.'
        else:
            score = 65
            level = 'Neutral'
            desc = 'No special synergy, but a smooth and easygoing combination.'
        compatibility = {'score': score, 'level': level, 'desc': desc, 'name_top': name_top}

    return {
        'name': name,
        'letters': letters,
        'distribution': {k: round(v, 1) for k, v in distribution.items()},
        'strongest': strongest,
        'compatibility': compatibility,
    }


CHEONGAN_OHENG = {
    'yang_wood': 'wood', 'yin_wood': 'wood',
    'yang_fire': 'fire', 'yin_fire': 'fire',
    'yang_earth': 'earth', 'yin_earth': 'earth',
    'yang_metal': 'metal', 'yin_metal': 'metal',
    'yang_water': 'water', 'yin_water': 'water',
}
JIJI_OHENG = {
    'rat': 'water', 'ox': 'earth', 'tiger': 'wood', 'rabbit': 'wood',
    'dragon': 'earth', 'snake': 'fire', 'horse': 'fire', 'goat': 'earth',
    'monkey': 'metal', 'rooster': 'metal', 'dog': 'earth', 'pig': 'water',
}


def calc_sipsung(ilgan: str, target_gan: str) -> str:
    """Ten Gods: relationship from Day Master to target stem"""
    if ilgan == target_gan:
        return 'companion'
    ig_oh = CHEONGAN_OHENG[ilgan]
    tg_oh = CHEONGAN_OHENG[target_gan]
    same_yy = (_GAN_YIN_YANG[ilgan] == _GAN_YIN_YANG[target_gan])

    if ig_oh == tg_oh:
        return 'companion' if same_yy else 'rival'
    if _OHENG_SAENG_CYCLE[ig_oh] == tg_oh:
        return 'epicure' if same_yy else 'maverick'
    if _OHENG_SAENG_CYCLE[tg_oh] == ig_oh:
        return 'mystic' if same_yy else 'mentor'
    if _OHENG_GEUK_CYCLE[ig_oh] == tg_oh:
        return 'windfall' if same_yy else 'prosperity'
    if _OHENG_GEUK_CYCLE[tg_oh] == ig_oh:
        return 'challenger' if same_yy else 'guardian'
    return 'neutral'

_SIPSUNG_INFO = {
    'companion': {'icon':'🤝', 'theme':'Allies · Independence · Drive', 'desc':'A time of camaraderie and self-reliance. Allies appear, and collaboration is key.'},
    'rival':     {'icon':'⚔️', 'theme':'Competition · Spending · Ambition', 'desc':'Rivals emerge and expenses rise. Your fighting spirit ignites.'},
    'epicure':   {'icon':'🍀', 'theme':'Expression · Leisure · Joy', 'desc':'A period of ease and abundance. Creativity, hobbies, and joy flourish.'},
    'maverick':  {'icon':'💡', 'theme':'Innovation · Rebellion · Change', 'desc':'Creativity explodes as you break the mold. A time of bold self-expression.'},
    'windfall':  {'icon':'💰', 'theme':'Big Money · Ventures · Movement', 'desc':'Major financial opportunities and business ventures. Your world expands.'},
    'prosperity':{'icon':'💵', 'theme':'Stability · Savings · Harvest', 'desc':'Steady income and domestic peace. Marriage and property luck are strong.'},
    'challenger':{'icon':'⚡', 'theme':'Power · Upheaval · Crisis', 'desc':'Opportunities for authority come with major changes. A test of courage.'},
    'guardian':  {'icon':'👑', 'theme':'Honor · Promotion · Order', 'desc':'Recognition and career advancement. Your social standing rises.'},
    'mystic':    {'icon':'📿', 'theme':'Study · Spirituality · Solitude', 'desc':'Deep contemplation and spiritual growth. You need time alone to recharge.'},
    'mentor':    {'icon':'📚', 'theme':'Wisdom · Protection · Grace', 'desc':'Mentors appear and academic success follows. A time of inner richness.'},
    'neutral':   {'icon':'❓', 'theme':'Neutral', 'desc':'An uneventful period of quiet equilibrium.'},
}


def _daewoon_score(ilgan: str, gan: str, ji: str) -> int:
    """Grand Cycle affinity score (0~100)"""
    ig_oh = CHEONGAN_OHENG[ilgan]
    gan_oh = CHEONGAN_OHENG[gan]
    ji_oh  = JIJI_OHENG[ji]
    score = 50
    if gan_oh == ig_oh:
        score += 15
    elif _OHENG_SAENG_CYCLE[gan_oh] == ig_oh:
        score += 20
    elif _OHENG_SAENG_CYCLE[ig_oh] == gan_oh:
        score += 5
    elif _OHENG_GEUK_CYCLE[ig_oh] == gan_oh:
        score -= 5
    elif _OHENG_GEUK_CYCLE[gan_oh] == ig_oh:
        score -= 15
    if ji_oh == ig_oh:
        score += 8
    elif _OHENG_SAENG_CYCLE[ji_oh] == ig_oh:
        score += 10
    elif _OHENG_GEUK_CYCLE[ji_oh] == ig_oh:
        score -= 8
    return max(15, min(95, score))


def _days_to_nearest_jieqi(year: int, month: int, day: int, forward: bool) -> int:
    """Days from birth to the nearest solar term (for Grand Cycle start age)"""
    import sxtwl as _sx
    base = _sx.fromSolar(year, month, day)
    cur = base
    for i in range(1, 90):
        cur = cur.after(1) if forward else cur.before(1)
        if cur.hasJieQi():
            return i
    return 15


def calc_daewoon(year: int, month: int, day: int, hour: int, gender: str = 'F',
                 calendar_type: str = 'solar', is_leap_month: bool = False, count: int = 10):
    """Grand Cycle analysis — 10-year life phases"""
    from datetime import date as _date

    if calendar_type == 'lunar':
        cal_conv = KoreanLunarCalendar()
        cal_conv.setLunarDate(year, month, day, bool(is_leap_month))
        solar_str = cal_conv.SolarIsoFormat()
        sy, sm, sd = map(int, solar_str.split('-'))
    else:
        sy, sm, sd = year, month, day

    yp, mp, dp, tp = calc_pillars_accurate(year, month, day, hour, calendar_type, is_leap_month)

    is_yang_year = yp[0] in _YANG_GAN_SET
    if gender == 'N':
        # Non-binary: follow the year's natural energy direction (Yang=forward)
        forward = is_yang_year
    else:
        is_male = (gender == 'M')
        forward = (is_yang_year and is_male) or (not is_yang_year and not is_male)
    direction = 'forward' if forward else 'backward'

    days = _days_to_nearest_jieqi(sy, sm, sd, forward)
    start_age = round(days / 3.0, 1)

    ilgan = dp[0]
    mg_idx = _GAN.index(mp[0])
    mj_idx = _JI.index(mp[1])
    pillars = []
    for i in range(1, count + 1):
        if forward:
            gan_idx = (mg_idx + i) % 10
            ji_idx = (mj_idx + i) % 12
        else:
            gan_idx = (mg_idx - i) % 10
            ji_idx = (mj_idx - i) % 12
        gan = _GAN[gan_idx]
        ji = _JI[ji_idx]
        oheng_gan = CHEONGAN_OHENG[gan]
        oheng_ji = JIJI_OHENG[ji]
        theme = _DAEWOON_THEMES.get(oheng_gan, 'A time of transformation')

        sipsung_name = calc_sipsung(ilgan, gan)
        sipsung_info = _SIPSUNG_INFO[sipsung_name]
        score = _daewoon_score(ilgan, gan, ji)
        grade = '🌟 Excellent' if score >= 75 else '✨ Good' if score >= 60 else '➖ Neutral' if score >= 45 else '⚠️ Caution' if score >= 35 else '🔥 Major Challenge'

        a_start = round(start_age + (i - 1) * 10, 1)
        a_end = round(start_age + i * 10, 1)
        pillars.append({
            'gan': gan, 'ji': ji, 'label': f'{gan} {ji}',
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
        'direction_label': 'Forward' if forward else 'Backward',
        'start_age': start_age,
        'gender': gender,
        'policy': 'Solar term based',
        'pillars': pillars,
        'current_idx': current_idx,
        'current_age': current_age,
        'current_pillar': pillars[current_idx] if current_idx >= 0 else None,
    }


# ─────────────────────────────────────────────
# Birth time adjustment (simplified for global)
# ─────────────────────────────────────────────
def adjust_birth_time(year, month, day, hour, minute=0,
                       apply_dst=False, apply_solar_time=False, city=''):
    """Placeholder for birth time correction. For the global version, no automatic adjustments."""
    adjustments = []
    return year, month, day, hour, minute, adjustments


def calc_pillars_accurate(year: int, month: int, day: int, hour: int,
                          calendar_type: str = 'solar', is_leap_month: bool = False,
                          apply_dst: bool = False, apply_solar_time: bool = False, city: str = ''):
    """
    Accurate Four Pillars via sxtwl (24 solar terms based)
    - Solar term based month pillar
    - Lichun based year pillar
    - Zi hour (23:00+) → next day
    - Lunar→Solar auto conversion
    """
    from datetime import date as _date, timedelta as _td

    if calendar_type == 'lunar':
        cal_conv = KoreanLunarCalendar()
        cal_conv.setLunarDate(year, month, day, bool(is_leap_month))
        solar_str = cal_conv.SolarIsoFormat()
        if not solar_str or solar_str == '0000-00-00':
            raise ValueError(f"Lunar conversion failed: {year}-{month}-{day} (leap={is_leap_month})")
        sy, sm, sd = map(int, solar_str.split('-'))
    else:
        sy, sm, sd = year, month, day

    sy, sm, sd, hour, _min, _adjs = adjust_birth_time(
        sy, sm, sd, hour, 0,
        apply_dst=apply_dst, apply_solar_time=apply_solar_time, city=city
    )

    if hour == 23:
        d = _date(sy, sm, sd) + _td(days=1)
        sy, sm, sd = d.year, d.month, d.day

    day_obj = sxtwl.fromSolar(sy, sm, sd)
    year_gz  = day_obj.getYearGZ()
    month_gz = day_obj.getMonthGZ()
    day_gz   = day_obj.getDayGZ()
    year_p  = (_GAN[year_gz.tg],  _JI[year_gz.dz])
    month_p = (_GAN[month_gz.tg], _JI[month_gz.dz])
    day_p   = (_GAN[day_gz.tg],   _JI[day_gz.dz])

    time_p = calc_time_pillar(day_p[0], hour)

    calc_pillars_accurate.last_adjustments = _adjs
    return year_p, month_p, day_p, time_p

# Gemini API setup
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
gemini_model = None
if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-2.5-flash')

# ─────────────────────────────────────────────
# Payment (PayPal Orders API v2)
# ─────────────────────────────────────────────
PAYPAL_CLIENT_ID     = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_MODE          = os.getenv("PAYPAL_MODE", "sandbox")  # "sandbox" or "live"
PAYPAL_BASE_URL      = "https://api-m.sandbox.paypal.com" if PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"

# Captured order IDs — prevents double-use
_captured_orders: set = set()


async def _paypal_token() -> str:
    """Fetch a short-lived OAuth2 access token from PayPal."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{PAYPAL_BASE_URL}/v1/oauth2/token",
            auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="PayPal auth failed")
    return r.json()["access_token"]

app = FastAPI()

from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Allow iframe embedding from WordPress site
from starlette.middleware.base import BaseHTTPMiddleware

class IframeAllowMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Allow embedding from mindwiredai.com and direct access
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self' https://mindwiredai.com https://*.mindwiredai.com"
        response.headers["X-Frame-Options"] = "ALLOW-FROM https://mindwiredai.com"
        return response

app.add_middleware(IframeAllowMiddleware)

from fastapi.responses import Response
from starlette.staticfiles import StaticFiles as _StaticFiles
import mimetypes

class CachedStaticFiles(_StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if hasattr(response, 'headers'):
            content_type = mimetypes.guess_type(path)[0] or ''
            if content_type.startswith('image/'):
                response.headers['Cache-Control'] = 'public, max-age=86400, immutable'
        return response

app.mount("/assets", CachedStaticFiles(directory="assets"), name="assets")

@app.get("/")
async def read_index():
    return FileResponse("index.html", headers={"Cache-Control": "public, max-age=300"})


@app.get("/app-config")
async def app_config(request: Request):
    base_url = PUBLIC_BASE_URL or str(request.base_url).rstrip("/")
    return {
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
    return {
        "provider": "paypal",
        "client_id": PAYPAL_CLIENT_ID,
        "mode": PAYPAL_MODE,
    }

# ═══════════════════════════════════════════════
# Static base data
# ═══════════════════════════════════════════════

ILGAN_NAMES = {
    'yang_wood': 'Yang Wood', 'yin_wood': 'Yin Wood',
    'yang_fire': 'Yang Fire', 'yin_fire': 'Yin Fire',
    'yang_earth': 'Yang Earth', 'yin_earth': 'Yin Earth',
    'yang_metal': 'Yang Metal', 'yin_metal': 'Yin Metal',
    'yang_water': 'Yang Water', 'yin_water': 'Yin Water',
}

LUCKY_MAP = {
    'wood': {'color': 'Green, Emerald', 'num': '3, 8', 'dir': 'East', 'food': 'Greens, Salad, Green tea'},
    'fire': {'color': 'Red, Purple', 'num': '2, 7', 'dir': 'South', 'food': 'Spicy food, Chocolate'},
    'earth': {'color': 'Yellow, Beige', 'num': '5, 10', 'dir': 'Center', 'food': 'Grains, Honey, Sweet potato'},
    'metal': {'color': 'White, Gold', 'num': '4, 9', 'dir': 'West', 'food': 'Pear, Radish, Ginkgo nuts'},
    'water': {'color': 'Black, Blue', 'num': '1, 6', 'dir': 'North', 'food': 'Seafood, Juicy fruits'},
}

def calc_year_pillar(year: int):
    idx = (year - 4) % 60
    return _GAN[idx % 10], _JI[idx % 12]

def calc_month_pillar(year: int, month: int):
    month_jiji_idx = (month + 1) % 12
    month_jiji = _JI[month_jiji_idx]
    year_gan_idx = (year - 4) % 10
    base_map = [2, 4, 6, 8, 0]
    group = year_gan_idx % 5
    month_gan_idx = (base_map[group] + month - 1) % 10
    return _GAN[month_gan_idx], month_jiji

def calc_day_pillar(year: int, month: int, day: int):
    reference = date(2000, 1, 7)
    target = date(year, month, day)
    diff = (target - reference).days
    idx = diff % 60
    return _GAN[idx % 10], _JI[idx % 12]

def calc_time_pillar(day_gan: str, hour: int):
    if hour == 23 or hour == 0: jiji_idx = 0
    else: jiji_idx = ((hour + 1) // 2) % 12
    day_gan_idx = _GAN.index(day_gan)
    base_map = [0, 2, 4, 6, 8]
    group = day_gan_idx % 5
    time_gan_idx = (base_map[group] + jiji_idx) % 10
    return _GAN[time_gan_idx], _JI[jiji_idx]

def analyze_oheng(pillars):
    """Simple element count"""
    count = {'wood': 0, 'fire': 0, 'earth': 0, 'metal': 0, 'water': 0}
    for gan, ji in pillars:
        count[CHEONGAN_OHENG[gan]] += 1
        count[JIJI_OHENG[ji]] += 1
    return count


# ─────────────────────────────────────────────
# Hidden Stems (支藏干) inside Earthly Branches
# ─────────────────────────────────────────────
JIJI_JANGGAN = {
    'rat':     [('yin_water', 1.0)],
    'ox':      [('yin_earth', 0.6), ('yin_water', 0.3), ('yin_metal', 0.1)],
    'tiger':   [('yang_wood', 0.6), ('yang_fire', 0.3), ('yang_earth', 0.1)],
    'rabbit':  [('yin_wood', 1.0)],
    'dragon':  [('yang_earth', 0.6), ('yin_wood', 0.3), ('yin_water', 0.1)],
    'snake':   [('yang_fire', 0.6), ('yang_metal', 0.3), ('yang_earth', 0.1)],
    'horse':   [('yin_fire', 0.7), ('yin_earth', 0.3)],
    'goat':    [('yin_earth', 0.6), ('yin_fire', 0.3), ('yin_wood', 0.1)],
    'monkey':  [('yang_metal', 0.6), ('yang_water', 0.3), ('yang_earth', 0.1)],
    'rooster': [('yin_metal', 1.0)],
    'dog':     [('yang_earth', 0.6), ('yin_metal', 0.3), ('yin_fire', 0.1)],
    'pig':     [('yang_water', 0.7), ('yang_wood', 0.3)],
}

PILLAR_WEIGHTS = {'year': 1.0, 'month': 2.5, 'day': 1.8, 'time': 1.0}
JIJI_WEIGHT = 1.2


def analyze_oheng_advanced(pillars):
    """Advanced Five Element analysis with hidden stems and positional weights"""
    score = {'wood': 0.0, 'fire': 0.0, 'earth': 0.0, 'metal': 0.0, 'water': 0.0}
    pillar_names = ['year', 'month', 'day', 'time']

    for i, (gan, ji) in enumerate(pillars):
        pn = pillar_names[i]
        w = PILLAR_WEIGHTS[pn]
        score[CHEONGAN_OHENG[gan]] += w * 1.0
        for hidden_gan, ratio in JIJI_JANGGAN[ji]:
            score[CHEONGAN_OHENG[hidden_gan]] += w * ratio * JIJI_WEIGHT

    total = sum(score.values()) or 1.0
    pct = {k: round(v * 100 / total, 1) for k, v in score.items()}
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
# Celestial Markers (神煞)
# ─────────────────────────────────────────────
SAMHAP_OF = {
    'monkey': 'monkey_rat_dragon', 'rat': 'monkey_rat_dragon', 'dragon': 'monkey_rat_dragon',
    'tiger': 'tiger_horse_dog', 'horse': 'tiger_horse_dog', 'dog': 'tiger_horse_dog',
    'snake': 'snake_rooster_ox', 'rooster': 'snake_rooster_ox', 'ox': 'snake_rooster_ox',
    'pig': 'pig_rabbit_goat', 'rabbit': 'pig_rabbit_goat', 'goat': 'pig_rabbit_goat',
}

DOHWA_MAP    = {'monkey_rat_dragon': 'rooster', 'tiger_horse_dog': 'rabbit', 'snake_rooster_ox': 'horse', 'pig_rabbit_goat': 'rat'}
YEOKMA_MAP   = {'monkey_rat_dragon': 'tiger', 'tiger_horse_dog': 'monkey', 'snake_rooster_ox': 'pig', 'pig_rabbit_goat': 'snake'}
HWAGAE_MAP   = {'monkey_rat_dragon': 'dragon', 'tiger_horse_dog': 'dog', 'snake_rooster_ox': 'ox', 'pig_rabbit_goat': 'goat'}
JANGSEONG_MAP= {'monkey_rat_dragon': 'rat', 'tiger_horse_dog': 'horse', 'snake_rooster_ox': 'rooster', 'pig_rabbit_goat': 'rabbit'}

CHEONULGWIIN_MAP = {
    'yang_wood': ['ox', 'goat'], 'yang_earth': ['ox', 'goat'], 'yang_metal': ['ox', 'goat'],
    'yin_wood': ['rat', 'monkey'], 'yin_earth': ['rat', 'monkey'],
    'yang_fire': ['pig', 'rooster'], 'yin_fire': ['pig', 'rooster'],
    'yin_metal': ['tiger', 'horse'],
    'yang_water': ['rabbit', 'snake'], 'yin_water': ['rabbit', 'snake'],
}

BAEKHO_PAIRS = {('yang_wood','dragon'), ('yin_wood','goat'), ('yang_fire','dog'), ('yin_fire','ox'),
                ('yang_earth','dragon'), ('yang_water','dog'), ('yin_water','ox')}

YANGIN_MAP = {
    'yang_wood': 'rabbit', 'yin_wood': 'dragon', 'yang_fire': 'horse', 'yin_fire': 'goat', 'yang_earth': 'horse',
    'yin_earth': 'goat', 'yang_metal': 'rooster', 'yin_metal': 'dog', 'yang_water': 'rat', 'yin_water': 'ox'
}

JAEGO_MAP = {
    'yang_wood': 'ox', 'yin_wood': 'dog', 'yang_fire': 'ox', 'yin_fire': 'ox',
    'yang_earth': 'dragon', 'yin_earth': 'dragon', 'yang_metal': 'goat', 'yin_metal': 'goat',
    'yang_water': 'dog', 'yin_water': 'dog',
}

MUNCHANG_MAP = {
    'yang_wood': 'snake', 'yin_wood': 'horse', 'yang_fire': 'monkey', 'yin_fire': 'rooster', 'yang_earth': 'monkey',
    'yin_earth': 'rooster', 'yang_metal': 'pig', 'yin_metal': 'rat', 'yang_water': 'tiger', 'yin_water': 'rabbit'
}

GONGMANG_BY_SUN = {
    0: ['dog', 'pig'], 1: ['monkey', 'rooster'], 2: ['horse', 'goat'],
    3: ['dragon', 'snake'], 4: ['tiger', 'rabbit'], 5: ['rat', 'ox'],
}

CHEONDEOK_MAP = {
    'tiger': 'yin_fire', 'rabbit': 'yin_metal', 'dragon': 'yang_water', 'snake': 'yin_metal',
    'horse': 'pig', 'goat': 'yang_wood', 'monkey': 'yin_water', 'rooster': 'tiger',
    'dog': 'yang_fire', 'pig': 'yin_wood', 'rat': 'snake', 'ox': 'yang_metal',
}

WEOLDEOK_MAP = {
    'tiger': 'yang_fire', 'horse': 'yang_fire', 'dog': 'yang_fire',
    'monkey': 'yang_water', 'rat': 'yang_water', 'dragon': 'yang_water',
    'snake': 'yang_metal', 'rooster': 'yang_metal', 'ox': 'yang_metal',
    'pig': 'yang_wood', 'rabbit': 'yang_wood', 'goat': 'yang_wood',
}

HONGYEOM_MAP = {
    'yang_wood': 'horse', 'yin_wood': 'horse', 'yang_fire': 'tiger', 'yin_fire': 'goat',
    'yang_earth': 'dragon', 'yin_earth': 'dragon', 'yang_metal': 'dog', 'yin_metal': 'rooster',
    'yang_water': 'rat', 'yin_water': 'monkey',
}

GOEGANG_PAIRS = {('yang_metal', 'dragon'), ('yang_metal', 'dog'), ('yang_water', 'dragon'), ('yang_water', 'dog'), ('yang_earth', 'dog'), ('yang_earth', 'dragon')}

KEUMYEO_MAP = {
    'yang_wood': 'dragon', 'yin_wood': 'snake', 'yang_fire': 'goat', 'yin_fire': 'monkey',
    'yang_earth': 'goat', 'yin_earth': 'monkey', 'yang_metal': 'dog', 'yin_metal': 'pig',
    'yang_water': 'ox', 'yin_water': 'tiger',
}

def _calc_day_idx_in_60(day_gan, day_ji):
    g_idx = _GAN.index(day_gan)
    j_idx = _JI.index(day_ji)
    for idx in range(60):
        if idx % 10 == g_idx and idx % 12 == j_idx:
            return idx
    return 0


def calc_gongmang(day_gan, day_ji):
    day_idx = _calc_day_idx_in_60(day_gan, day_ji)
    sun = day_idx // 10
    return GONGMANG_BY_SUN.get(sun, [])


# ─────────────────────────────────────────────
# Chinese Zodiac (12 animals by year branch)
# ─────────────────────────────────────────────
ZODIAC_DATA = {
    'rat': {
        'icon': '🐭', 'name': 'Rat', 'symbol': '子',
        'tagline': 'The Clever Strategist',
        'desc': 'Small but mighty — the Rat possesses extraordinary insight and quick wit. No opportunity slips by unnoticed. In a crisis, you think faster and move smarter than anyone.',
        'traits': ['Cleverness', 'Resourcefulness', 'Adaptability'],
        'love': 'Your charm is magnetic and effortless. Just be careful not to come across as too calculating — let your genuine warmth shine through.',
        'career': 'Marketing, Finance, Consulting, Strategy — anywhere quick thinking wins',
        'best_match': ['Dragon', 'Monkey'],
        'avoid_match': ['Horse'],
    },
    'ox': {
        'icon': '🐂', 'name': 'Ox', 'symbol': '丑',
        'tagline': 'The Steadfast Achiever',
        'desc': 'Unwavering determination defines the Ox. Not flashy, but over time, everyone comes to see you as the most dependable person in the room. Honest effort always pays off.',
        'traits': ['Diligence', 'Patience', 'Reliability'],
        'love': 'Slow to fall, but deeply devoted. You build love on trust, not grand gestures.',
        'career': 'Research, Engineering, Government, Agriculture — fields where consistency is king',
        'best_match': ['Snake', 'Rooster'],
        'avoid_match': ['Goat'],
    },
    'tiger': {
        'icon': '🐯', 'name': 'Tiger', 'symbol': '寅',
        'tagline': 'The Born Leader',
        'desc': 'Charisma and courage run in your blood. Once you make a decision, nothing stands in your way. You light up every room and inspire others to follow.',
        'traits': ['Charisma', 'Courage', 'Justice'],
        'love': 'You go all-in when you fall. Direct and fearless in love — just remember to match your partner\'s pace.',
        'career': 'Management, Law, Military, Politics — positions of authority',
        'best_match': ['Horse', 'Dog'],
        'avoid_match': ['Monkey'],
    },
    'rabbit': {
        'icon': '🐰', 'name': 'Rabbit', 'symbol': '卯',
        'tagline': 'The Gentle Diplomat',
        'desc': 'Soft-spoken with exquisite taste, the Rabbit brings harmony wherever they go. Your artistic eye and emotional intelligence make you a natural peacemaker.',
        'traits': ['Sensitivity', 'Artistry', 'Gentleness'],
        'love': 'Warm and nurturing in relationships. You avoid conflict, but don\'t forget to speak up for yourself too.',
        'career': 'Design, Education, Hospitality, Arts — where beauty and empathy matter',
        'best_match': ['Goat', 'Pig'],
        'avoid_match': ['Rooster'],
    },
    'dragon': {
        'icon': '🐲', 'name': 'Dragon', 'symbol': '辰',
        'tagline': 'The Visionary Trailblazer',
        'desc': 'Grand ambition meets magnetic charisma. You refuse the ordinary and carve your own path. Turning setbacks into comebacks is your superpower.',
        'traits': ['Ambition', 'Charisma', 'Fortune'],
        'love': 'Intense and dramatic love affairs. You can be overwhelming — balance your fire with tenderness.',
        'career': 'Entrepreneurship, Entertainment, Politics — any grand stage',
        'best_match': ['Rat', 'Monkey'],
        'avoid_match': ['Dog'],
    },
    'snake': {
        'icon': '🐍', 'name': 'Snake', 'symbol': '巳',
        'tagline': 'The Mystic Sage',
        'desc': 'Deep intuition and piercing insight define the Snake. Few words, but every one hits the mark. Your mysterious allure draws people in like a spell.',
        'traits': ['Intuition', 'Wisdom', 'Mystery'],
        'love': 'Guarded at first, but once you open up, your love is deep and all-consuming.',
        'career': 'Research, Psychology, Finance, Philosophy — where deep thinking matters',
        'best_match': ['Ox', 'Rooster'],
        'avoid_match': ['Pig'],
    },
    'horse': {
        'icon': '🐴', 'name': 'Horse', 'symbol': '午',
        'tagline': 'The Free Spirit',
        'desc': 'Boundless energy and an unstoppable love of freedom. You thrive on adventure and bring vitality to everything you touch. A restless soul always seeking the next horizon.',
        'traits': ['Passion', 'Freedom', 'Energy'],
        'love': 'Burns hot and fast. You need a partner who can keep up with your pace and share your adventures.',
        'career': 'Sales, Travel, Sports, Media — fast-paced and dynamic fields',
        'best_match': ['Tiger', 'Dog'],
        'avoid_match': ['Rat'],
    },
    'goat': {
        'icon': '🐑', 'name': 'Goat', 'symbol': '未',
        'tagline': 'The Gentle Healer',
        'desc': 'Kind-hearted and deeply caring, the Goat values harmony above all. Your artistic sensibility and compassion make the world a softer place.',
        'traits': ['Gentleness', 'Empathy', 'Artistry'],
        'love': 'Devoted and tender in love. Just remember — giving too much without receiving leads to burnout.',
        'career': 'Art, Design, Culinary, Counseling — where heart and craft intersect',
        'best_match': ['Rabbit', 'Pig'],
        'avoid_match': ['Ox'],
    },
    'monkey': {
        'icon': '🐒', 'name': 'Monkey', 'symbol': '申',
        'tagline': 'The Creative Genius',
        'desc': 'Quick-witted, endlessly curious, and never short on ideas. You solve problems others can\'t even see. Social butterfly and life of every party.',
        'traits': ['Creativity', 'Wit', 'Sociability'],
        'love': 'Fun and unpredictable in love. Boredom is the enemy — you need a partner who keeps things fresh.',
        'career': 'Tech, Creative, Entertainment, Strategy — where ideas are weapons',
        'best_match': ['Rat', 'Dragon'],
        'avoid_match': ['Tiger'],
    },
    'rooster': {
        'icon': '🐓', 'name': 'Rooster', 'symbol': '酉',
        'tagline': 'The Detail Perfectionist',
        'desc': 'Precise, polished, and always put-together. Your eye for detail is unmatched, and you hold yourself to the highest standards. Dependable and true to your word.',
        'traits': ['Precision', 'Aesthetic sense', 'Responsibility'],
        'love': 'You prefer clean, well-ordered relationships. High standards are great — just leave room for imperfection.',
        'career': 'Accounting, Law, Design, Culinary — where precision and beauty converge',
        'best_match': ['Ox', 'Snake'],
        'avoid_match': ['Rabbit'],
    },
    'dog': {
        'icon': '🐶', 'name': 'Dog', 'symbol': '戌',
        'tagline': 'The Loyal Protector',
        'desc': 'Loyalty and honesty are your hallmarks. Once someone earns your trust, you\'re ride-or-die forever. Your strong sense of justice makes you a champion for the underdog.',
        'traits': ['Loyalty', 'Honesty', 'Devotion'],
        'love': 'Faithful and all-in. Once you love, it\'s with your whole heart — a true romantic at the core.',
        'career': 'Law, Education, Social Work, Security — where trust and justice matter',
        'best_match': ['Tiger', 'Horse'],
        'avoid_match': ['Dragon'],
    },
    'pig': {
        'icon': '🐷', 'name': 'Pig', 'symbol': '亥',
        'tagline': 'The Generous Soul',
        'desc': 'Pure-hearted, generous, and a true people person. Known for bringing abundance and warmth wherever you go. Your honest charm wins hearts effortlessly.',
        'traits': ['Generosity', 'Sincerity', 'Fortune'],
        'love': 'Loves with total sincerity and openness. Just make sure you\'re not giving more than you\'re getting back.',
        'career': 'Food Industry, Business, Finance, Social Work — people-centered abundance',
        'best_match': ['Rabbit', 'Goat'],
        'avoid_match': ['Snake'],
    },
}


def analyze_zodiac(year_jiji):
    data = ZODIAC_DATA.get(year_jiji)
    if not data:
        return None
    return {'key': year_jiji, **data}

# ═══════════════════════════════════════════════
# Western Zodiac (Constellations)
# ═══════════════════════════════════════════════
CONSTELLATION_DATA = {
    'aries': {
        'icon': '♈', 'name': 'Aries', 'date': '3/21~4/19', 'element': 'Fire',
        'ruling_planet': 'Mars', 'modality': 'Cardinal',
        'traits': ['Passionate', 'Bold', 'Honest', 'Independent', 'Brave'],
        'desc': 'A trailblazer fueled by pure fire energy. You charge ahead where others hesitate and inspire everyone around you.',
        'strength': 'Lightning-fast decisions, fearless initiative, and infectious energy. You\'re the one who gets things started.',
        'weakness': 'Patience isn\'t your forte. Slow down, listen more, and remember that finishing matters as much as starting.',
        'love_style': 'Direct and passionate. No games, no waiting — when you\'re in, you\'re ALL in.',
        'career_hint': 'Startups, sports, sales, project management — anywhere you can lead the charge.',
        'lucky_day': 'Tuesday', 'lucky_color': 'Red',
        'best_match': ['Leo', 'Sagittarius', 'Gemini'], 'worst_match': ['Cancer', 'Capricorn'],
        'advice': 'Sometimes the bravest thing is to pause and look around. Add patience to your fire, and you can change the world.',
        'synergy_fire': 'When your Aries fire meets Fire in your chart, passion explodes! Leadership peaks, but watch for emotional overload.',
        'synergy_water': 'Water tempers your flames just right — sharpening intuition while keeping your action-hero energy intact.',
        'synergy_earth': 'Earth grounds your impulsiveness. Suddenly you can start AND finish what you begin.',
        'synergy_wood': 'Wood fuels your growth energy. Perfect for pioneering new fields and leveling up fast.',
        'synergy_metal': 'Metal gives you laser focus. All that scattered Aries energy? Now it has a razor edge.',
        'synergy_default': 'Your Aries leadership merges with your chart\'s energy to create an unstoppable presence.',
    },
    'taurus': {
        'icon': '♉', 'name': 'Taurus', 'date': '4/20~5/20', 'element': 'Earth',
        'ruling_planet': 'Venus', 'modality': 'Fixed',
        'traits': ['Steady', 'Sensual', 'Patient', 'Practical', 'Loyal'],
        'desc': 'Unshakeable stability meets refined taste. You appreciate beauty, savor life\'s pleasures, and finish what you start — always.',
        'strength': 'Incredible endurance and an eye for quality. You build things that last, whether careers, homes, or relationships.',
        'weakness': 'Change is hard for you. Stubbornness can become your cage. Try stepping outside your comfort zone more often.',
        'love_style': 'All-in loyalty. You show love through actions — home-cooked meals, thoughtful gifts, steady presence.',
        'career_hint': 'Finance, real estate, culinary arts, design — where taste and tenacity pay off.',
        'lucky_day': 'Friday', 'lucky_color': 'Green',
        'best_match': ['Virgo', 'Capricorn', 'Cancer'], 'worst_match': ['Aquarius', 'Leo'],
        'advice': 'Your foundation is rock-solid. Now dare to build something new on top of it. The world is bigger than your comfort zone.',
        'synergy_earth': 'Double Earth = financial fortress. Wealth accumulates steadily and your practical success is almost guaranteed.',
        'synergy_wood': 'Wood loosens your rigidity. You become more flexible and open to fresh possibilities.',
        'synergy_fire': 'Fire lights a spark under your steady pace. You finally move faster on things that matter.',
        'synergy_water': 'Water deepens your artistic soul. Creative expression hits a whole new level.',
        'synergy_metal': 'Metal sharpens your business instincts. Financial decisions become almost surgically precise.',
        'synergy_default': 'Taurus persistence + your chart\'s energy = slow and steady wins that actually last.',
    },
    'gemini': {
        'icon': '♊', 'name': 'Gemini', 'date': '5/21~6/21', 'element': 'Air',
        'ruling_planet': 'Mercury', 'modality': 'Mutable',
        'traits': ['Versatile', 'Curious', 'Communicative', 'Witty', 'Adaptable'],
        'desc': 'An endlessly curious mind that connects dots nobody else can see. You make any topic fascinating and any room more fun.',
        'strength': 'Quick learner, brilliant conversationalist, natural multitasker. You bridge worlds that others can\'t even see.',
        'weakness': 'Your interests shift fast. Depth requires staying power — pick one thing and go deep sometimes.',
        'love_style': 'Mental connection first, everything else second. You need someone who stimulates your mind and respects your freedom.',
        'career_hint': 'Writing, marketing, tech, media, translation — communication-heavy and diverse roles.',
        'lucky_day': 'Wednesday', 'lucky_color': 'Yellow',
        'best_match': ['Libra', 'Aquarius', 'Aries'], 'worst_match': ['Virgo', 'Pisces'],
        'advice': 'Your breadth is your gift. Now add depth to one area and watch yourself become truly extraordinary.',
        'synergy_wood': 'Wood amplifies your intellectual hunger. Learning speed doubles and cross-disciplinary thinking soars.',
        'synergy_metal': 'Metal gives you the focus you crave. Scattered brilliance becomes concentrated expertise.',
        'synergy_fire': 'Fire turns ideas into action. You stop just talking about things and start doing them.',
        'synergy_water': 'Water adds emotional depth. Your words start touching hearts, not just minds.',
        'synergy_earth': 'Earth gives you follow-through. Start-to-finish completion becomes your new superpower.',
        'synergy_default': 'Gemini versatility + your chart\'s energy = brilliance across multiple domains.',
    },
    'cancer': {
        'icon': '♋', 'name': 'Cancer', 'date': '6/22~7/22', 'element': 'Water',
        'ruling_planet': 'Moon', 'modality': 'Cardinal',
        'traits': ['Nurturing', 'Intuitive', 'Protective', 'Empathetic', 'Devoted'],
        'desc': 'The emotional guardian with a heart of gold. You\'d move mountains for the people you love, and your intuition borders on psychic.',
        'strength': 'Unmatched empathy and a sixth sense for danger. Your devotion creates bonds that last a lifetime.',
        'weakness': 'Mood swings and holding onto the past can weigh you down. Remember to protect your own heart too.',
        'love_style': 'Nurturing and all-encompassing. Home-cooked love with handwritten notes and tender care.',
        'career_hint': 'Healthcare, counseling, teaching, culinary, interior design — caring for others.',
        'lucky_day': 'Monday', 'lucky_color': 'Silver',
        'best_match': ['Scorpio', 'Pisces', 'Taurus'], 'worst_match': ['Aries', 'Libra'],
        'advice': 'Your love for others is beautiful — just make sure you\'re filling your own cup too. Self-care isn\'t selfish.',
        'synergy_water': 'Double Water = emotional superpowers. Your intuition becomes almost supernatural. Art and healing flourish.',
        'synergy_fire': 'Fire gives you confidence to speak up. No more hiding your feelings — you learn to advocate for yourself.',
        'synergy_earth': 'Earth keeps you grounded when emotions surge. Practical stability meets deep feeling.',
        'synergy_wood': 'Wood pushes you out of your shell. New adventures and growth await beyond your comfort zone.',
        'synergy_metal': 'Metal adds logical clarity. Heart and head find balance for wiser decisions.',
        'synergy_default': 'Cancer warmth + your chart\'s energy = bonds so deep they feel like destiny.',
    },
    'leo': {
        'icon': '♌', 'name': 'Leo', 'date': '7/23~8/22', 'element': 'Fire',
        'ruling_planet': 'Sun', 'modality': 'Fixed',
        'traits': ['Confident', 'Creative', 'Generous', 'Dramatic', 'Loyal'],
        'desc': 'Born for the spotlight. Your charisma lights up rooms and your generosity wins hearts. You inspire others just by being you.',
        'strength': 'Natural leadership, creative brilliance, and a warm heart that genuinely cares about the people around you.',
        'weakness': 'Your ego needs feeding. Learn to accept imperfection and criticism — true confidence doesn\'t need constant validation.',
        'love_style': 'Grand romantic gestures, passion, and drama. You treat your partner like royalty — and expect the same.',
        'career_hint': 'Entertainment, leadership, design, event planning — center stage or at the helm.',
        'lucky_day': 'Sunday', 'lucky_color': 'Gold',
        'best_match': ['Aries', 'Sagittarius', 'Gemini'], 'worst_match': ['Taurus', 'Scorpio'],
        'advice': 'You shine brightest when you lift others up too. Real royalty is generous, not just glamorous.',
        'synergy_fire': 'Double Fire = maximum charisma. You become impossible to ignore. Just watch for ego overdrive.',
        'synergy_earth': 'Earth adds substance to your style. Real achievements back up the confident persona.',
        'synergy_water': 'Water softens your edges. People follow you not just from awe, but from genuine love.',
        'synergy_wood': 'Wood feeds your creative fire. Artistic expression reaches breathtaking new heights.',
        'synergy_metal': 'Metal adds strategic thinking. Emotional leadership gains a razor-sharp strategic edge.',
        'synergy_default': 'Leo presence + your chart\'s energy = a star that\'s impossible to miss.',
    },
    'virgo': {
        'icon': '♍', 'name': 'Virgo', 'date': '8/23~9/22', 'element': 'Earth',
        'ruling_planet': 'Mercury', 'modality': 'Mutable',
        'traits': ['Analytical', 'Perfectionist', 'Practical', 'Diligent', 'Meticulous'],
        'desc': 'The detail master who sees what everyone else misses. Methodical, efficient, and always three steps ahead.',
        'strength': 'Laser-sharp analysis and flawless execution. Your organizational skills border on supernatural.',
        'weakness': 'Perfectionism can paralyze you. Sometimes "good enough" really is good enough. Be kinder to yourself.',
        'love_style': 'Actions over words. You show love by fixing things, planning ahead, and quietly making life better for your person.',
        'career_hint': 'Data science, medicine, editing, research, quality control — precision matters.',
        'lucky_day': 'Wednesday', 'lucky_color': 'Navy',
        'best_match': ['Taurus', 'Capricorn', 'Scorpio'], 'worst_match': ['Sagittarius', 'Gemini'],
        'advice': '80% done is still amazing. Give yourself permission to be imperfect sometimes — happiness lives there.',
        'synergy_earth': 'Double Earth = unstoppable execution. Plans become reality with almost mathematical precision.',
        'synergy_water': 'Water adds flexibility and feeling. Your analytical mind gains emotional intelligence.',
        'synergy_fire': 'Fire gives you courage to act boldly. Analysis turns into decisive action.',
        'synergy_wood': 'Wood brings creative thinking. You innovate beyond the usual playbook.',
        'synergy_metal': 'Metal sharpens your already keen edge. You become the absolute expert in your field.',
        'synergy_default': 'Virgo precision + your chart\'s energy = excellence that speaks for itself.',
    },
    'libra': {
        'icon': '♎', 'name': 'Libra', 'date': '9/23~10/22', 'element': 'Air',
        'ruling_planet': 'Venus', 'modality': 'Cardinal',
        'traits': ['Balanced', 'Social', 'Aesthetic', 'Fair', 'Charming'],
        'desc': 'The natural diplomat and beauty connoisseur. You smooth conflicts, curate beauty, and bring people together effortlessly.',
        'strength': 'Social grace, impeccable taste, and a fairness that makes everyone feel heard and valued.',
        'weakness': 'Indecisiveness and people-pleasing can hold you back. It\'s okay to disappoint someone to honor yourself.',
        'love_style': 'Romantic, refined, and equality-focused. Beautiful dates and balanced partnerships are your love language.',
        'career_hint': 'Design, law, diplomacy, counseling, curation — beauty meets balance.',
        'lucky_day': 'Friday', 'lucky_color': 'Pastel Pink',
        'best_match': ['Gemini', 'Aquarius', 'Leo'], 'worst_match': ['Cancer', 'Capricorn'],
        'advice': 'You can\'t please everyone, and that\'s okay. Speaking your truth IS balance.',
        'synergy_metal': 'Metal sharpens your aesthetic judgment and decisiveness. Beauty meets clarity.',
        'synergy_fire': 'Fire gives you backbone. Decisions come faster and you stop second-guessing yourself.',
        'synergy_water': 'Water deepens your connections beyond the surface. Relationships gain real substance.',
        'synergy_earth': 'Earth grounds your idealism. Dreams become actionable plans.',
        'synergy_wood': 'Wood builds your independence. You learn to stand firm in your own opinions.',
        'synergy_default': 'Libra harmony + your chart\'s energy = a life beautifully composed.',
    },
    'scorpio': {
        'icon': '♏', 'name': 'Scorpio', 'date': '10/23~11/21', 'element': 'Water',
        'ruling_planet': 'Pluto', 'modality': 'Fixed',
        'traits': ['Intense', 'Perceptive', 'Focused', 'Mysterious', 'Loyal'],
        'desc': 'The emotional alchemist who sees through everything. When you lock onto something, nothing can stop you.',
        'strength': 'Unmatched focus and X-ray perception into people\'s true motives. Loyalty that runs deeper than the ocean.',
        'weakness': 'Jealousy and grudges can consume you. Learning to forgive and release is your ultimate power move.',
        'love_style': 'All or nothing. Deep, soulful, and consuming. You don\'t do casual — when you love, it\'s total.',
        'career_hint': 'Psychology, investigation, surgery, research, investment — where depth wins.',
        'lucky_day': 'Tuesday', 'lucky_color': 'Wine Red',
        'best_match': ['Cancer', 'Pisces', 'Virgo'], 'worst_match': ['Leo', 'Aquarius'],
        'advice': 'Letting go is not losing — it\'s making room for something better. Your depth is already extraordinary.',
        'synergy_water': 'Double Water = almost telepathic insight. You see what others can\'t even imagine.',
        'synergy_earth': 'Earth stabilizes your emotional storms. Deep feeling meets solid ground.',
        'synergy_fire': 'Fire turns strategy into action. Your plans stop simmering and start blazing.',
        'synergy_wood': 'Wood brings renewal. Old wounds heal and new chapters begin.',
        'synergy_metal': 'Metal makes your focus lethal. Target locked, achievement unlocked.',
        'synergy_default': 'Scorpio intensity + your chart\'s energy = nothing escapes your gaze.',
    },
    'sagittarius': {
        'icon': '♐', 'name': 'Sagittarius', 'date': '11/22~12/21', 'element': 'Fire',
        'ruling_planet': 'Jupiter', 'modality': 'Mutable',
        'traits': ['Adventurous', 'Optimistic', 'Philosophical', 'Humorous', 'Free-spirited'],
        'desc': 'The eternal explorer with an unquenchable thirst for knowledge and experience. You find meaning in every horizon.',
        'strength': 'Infectious optimism, cultural openness, and the ability to find silver linings in any storm.',
        'weakness': 'Commitment can feel like a cage. Depth requires staying — sometimes the best adventure is going deeper, not further.',
        'love_style': 'Freedom-loving and spontaneous. You want a travel buddy for life, not a jailer.',
        'career_hint': 'Travel writing, academia, philosophy, international business — the wider world.',
        'lucky_day': 'Thursday', 'lucky_color': 'Purple',
        'best_match': ['Aries', 'Leo', 'Aquarius'], 'worst_match': ['Virgo', 'Pisces'],
        'advice': 'True freedom comes from commitment, not avoidance. The deepest adventures are in staying.',
        'synergy_fire': 'Double Fire = adventure on turbo. Every risk seems to pay off beautifully.',
        'synergy_metal': 'Metal gives you follow-through. Adventures get proper endings, not just great beginnings.',
        'synergy_earth': 'Earth turns your dreams into itineraries. Big ideas become real plans.',
        'synergy_water': 'Water deepens your journeys. You stop collecting stamps and start collecting wisdom.',
        'synergy_wood': 'Wood accelerates your growth. Learning becomes exponential.',
        'synergy_default': 'Sagittarius freedom + your chart\'s energy = a life that reads like an epic novel.',
    },
    'capricorn': {
        'icon': '♑', 'name': 'Capricorn', 'date': '12/22~1/19', 'element': 'Earth',
        'ruling_planet': 'Saturn', 'modality': 'Cardinal',
        'traits': ['Ambitious', 'Disciplined', 'Responsible', 'Strategic', 'Patient'],
        'desc': 'The quiet climber who always reaches the summit. Discipline, long-term vision, and an iron will — you age like fine wine.',
        'strength': 'Self-mastery, strategic planning, and the patience to play the long game. You get better every single year.',
        'weakness': 'Workaholism and emotional suppression. Remember — success without joy is just productivity.',
        'love_style': 'Serious and committed. You don\'t start relationships lightly, but once in, you\'re in for the long haul.',
        'career_hint': 'Executive leadership, law, architecture, finance — long-term vision required.',
        'lucky_day': 'Saturday', 'lucky_color': 'Brown',
        'best_match': ['Taurus', 'Virgo', 'Scorpio'], 'worst_match': ['Aries', 'Libra'],
        'advice': 'The summit is beautiful, but so is the climb. Don\'t forget to enjoy the view on the way up.',
        'synergy_earth': 'Double Earth = practically guaranteed success. Your foundation is unshakeable.',
        'synergy_wood': 'Wood adds flexibility. Your rigid plans become adaptable strategies.',
        'synergy_fire': 'Fire warms your cool exterior. Leadership gains charisma alongside competence.',
        'synergy_water': 'Water adds intuition. You start sensing opportunities before they appear.',
        'synergy_metal': 'Metal supercharges your execution. Goals don\'t just get met — they get demolished.',
        'synergy_default': 'Capricorn discipline + your chart\'s energy = a legacy built to last.',
    },
    'aquarius': {
        'icon': '♒', 'name': 'Aquarius', 'date': '1/20~2/18', 'element': 'Air',
        'ruling_planet': 'Uranus', 'modality': 'Fixed',
        'traits': ['Innovative', 'Independent', 'Humanitarian', 'Eccentric', 'Intellectual'],
        'desc': 'The visionary who lives five years ahead of everyone else. Your ideas are strange, brilliant, and usually right.',
        'strength': 'Original thinking, open-mindedness, and a genuine desire to make the world better for everyone.',
        'weakness': 'Emotionally distant. Your big heart loves humanity but sometimes forgets about the humans closest to you.',
        'love_style': 'Friends first, lovers second. You need intellectual stimulation and total respect for independence.',
        'career_hint': 'Tech, social innovation, science, startups — where the future is being built.',
        'lucky_day': 'Saturday', 'lucky_color': 'Electric Blue',
        'best_match': ['Gemini', 'Libra', 'Sagittarius'], 'worst_match': ['Taurus', 'Scorpio'],
        'advice': 'Your mind is extraordinary. Now let your heart catch up. The people closest to you need you present, not just brilliant.',
        'synergy_metal': 'Metal turns wild ideas into working prototypes. Innovation meets execution.',
        'synergy_fire': 'Fire gives your plans urgency and passion. Ideas launch instead of languishing.',
        'synergy_water': 'Water adds the empathy your genius needs. Cold logic becomes warm wisdom.',
        'synergy_earth': 'Earth makes your utopian visions practical. Dreams get budgets and timelines.',
        'synergy_wood': 'Wood expands your influence. More people hear your message and join the cause.',
        'synergy_default': 'Aquarius vision + your chart\'s energy = a future only you could imagine.',
    },
    'pisces': {
        'icon': '♓', 'name': 'Pisces', 'date': '2/19~3/20', 'element': 'Water',
        'ruling_planet': 'Neptune', 'modality': 'Mutable',
        'traits': ['Imaginative', 'Empathetic', 'Artistic', 'Intuitive', 'Gentle'],
        'desc': 'The dreamer who walks between worlds. Boundless imagination and deep empathy make you a natural artist and healer.',
        'strength': 'Limitless creativity and the ability to feel what others feel. Your art touches souls.',
        'weakness': 'Reality can feel harsh. Don\'t drift too far into dreams — your magic needs grounding to reach the world.',
        'love_style': 'Fairy-tale romantic seeking a soulmate. Deeply devoted but needs to keep healthy boundaries.',
        'career_hint': 'Arts, music, photography, therapy, film — where imagination creates reality.',
        'lucky_day': 'Thursday', 'lucky_color': 'Lavender',
        'best_match': ['Scorpio', 'Cancer', 'Taurus'], 'worst_match': ['Gemini', 'Sagittarius'],
        'advice': 'Dream big, but keep your feet on the ground. When imagination meets action, that\'s where the real magic happens.',
        'synergy_water': 'Double Water = artistic transcendence. Your creative expression becomes almost otherworldly.',
        'synergy_wood': 'Wood gives your dreams legs. Ideas become books, art becomes business.',
        'synergy_fire': 'Fire gives you courage to share your inner world. No more hiding your gifts.',
        'synergy_earth': 'Earth turns fantasy into reality. Your visions materialize into tangible creations.',
        'synergy_metal': 'Metal adds structure to your flow. Emotion and logic create truly polished work.',
        'synergy_default': 'Pisces imagination + your chart\'s energy = a creative life beyond ordinary limits.',
    },
}

def analyze_constellation(month: int, day: int, strongest_oheng: str = ''):
    signs = [
        (1, 20, 'aquarius'), (2, 19, 'pisces'), (3, 21, 'aries'), (4, 20, 'taurus'),
        (5, 21, 'gemini'), (6, 22, 'cancer'), (7, 23, 'leo'), (8, 23, 'virgo'),
        (9, 23, 'libra'), (10, 23, 'scorpio'), (11, 22, 'sagittarius'), (12, 22, 'capricorn'),
    ]
    sign_key = 'capricorn'
    for i, (m, d, key) in enumerate(signs):
        if month == m and day >= d:
            sign_key = key
        elif month == m and day < d:
            sign_key = signs[i - 1][2] if i > 0 else 'capricorn'
            break

    data = CONSTELLATION_DATA[sign_key]
    synergy = data.get(f'synergy_{strongest_oheng}', data['synergy_default'])

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
    'peach_blossom': {
        'icon': '🌸',
        'name': 'Peach Blossom Star',
        'type': 'Charm · Magnetism',
        'desc': 'A star of irresistible allure. You naturally draw people in with an almost magnetic charm. Artistic taste and social grace come effortlessly.',
        'tip': 'Your magnetism is a gift, but it can attract drama too. Learn to recognize genuine connections from fleeting attractions.'
    },
    'traveling_star': {
        'icon': '🐎',
        'name': 'Traveling Star',
        'type': 'Movement · Change',
        'desc': 'A restless star that thrives in motion. Travel, relocation, and career changes come frequently. You shine brightest in new environments and global settings.',
        'tip': 'Embrace change as your superpower. Stability comes from within, not from staying in one place.'
    },
    'noble_benefactor': {
        'icon': '⭐',
        'name': 'Noble Benefactor Star',
        'type': 'Protection · Grace',
        'desc': 'The most auspicious celestial marker. Helpful mentors and allies appear exactly when you need them. Even in your darkest hour, a guiding light finds you.',
        'tip': 'Cherish the people around you. Your greatest asset has always been your connections.'
    },
    'lotus_crown': {
        'icon': '🪷',
        'name': 'Lotus Crown Star',
        'type': 'Art · Spirituality',
        'desc': 'A star of elevated consciousness. You\'re drawn to art, spirituality, and philosophy. Your inner world is rich and your creative vision is uniquely profound.',
        'tip': 'Your depth is your treasure, but don\'t let it isolate you. Share your inner world with those who deserve it.'
    },
    'general_star': {
        'icon': '⚔️',
        'name': 'General Star',
        'type': 'Leadership · Authority',
        'desc': 'The star of a born commander. Natural leadership and commanding presence define you. You thrive in positions of authority and responsibility.',
        'tip': 'Heavy is the head that wears the crown. Remember to rest and delegate when the weight gets too much.'
    },
    'white_tiger': {
        'icon': '🐅',
        'name': 'White Tiger Star',
        'type': 'Drive · Intensity',
        'desc': 'A star of explosive energy and decisive action. When you commit, you go all-in with unstoppable force. Life may bring sudden changes, but your resilience is extraordinary.',
        'tip': 'Channel your fierce energy wisely. Pause before leaping, and avoid unnecessary risks in physical activities.'
    },
    'blade_of_resolve': {
        'icon': '🗡️',
        'name': 'Blade of Resolve',
        'type': 'Willpower · Determination',
        'desc': 'A sharp star of unyielding will. Once you decide, nothing shakes you. Common among athletes, specialists, and competitive professionals.',
        'tip': 'A blade cuts both ways. Pair your determination with grace, and follow boldness with gentleness.'
    },
    'void_star': {
        'icon': '🕳️',
        'name': 'Void Star',
        'type': 'Release · Spiritual Freedom',
        'desc': 'The star of beautiful emptiness. Letting go is your path to abundance — the less you cling, the more flows to you. A natural affinity for spirituality, art, and research.',
        'tip': 'What you chase runs faster. What you release returns tenfold. Master the art of letting go.'
    },
    'wealth_vault': {
        'icon': '💰',
        'name': 'Wealth Vault',
        'type': 'Accumulation · Assets',
        'desc': 'The star of steady wealth building. Rather than windfall gains, you accumulate through patience and smart management. Real estate and long-term investments are your allies.',
        'tip': 'Forget get-rich-quick schemes. Your path to wealth is paved with consistent, small, smart moves.'
    },
    'scholar_star': {
        'icon': '📚',
        'name': 'Scholar Star',
        'type': 'Intellect · Achievement',
        'desc': 'The star of sharp minds and academic glory. Exams, certifications, and intellectual pursuits come naturally to you. Often found among writers, professors, and researchers.',
        'tip': 'Lean into learning. Certifications, courses, and creative writing are your fast-track to success.'
    },
    'heavens_grace': {
        'icon': '🌟', 'name': 'Heaven\'s Grace Star', 'type': 'Divine Protection',
        'desc': 'An invisible shield from above. Even in the worst situations, unseen forces guide you through safely. Your kindness comes back as protection.',
        'tip': 'Be generous. Your good deeds build a karmic shield that activates when you need it most.'
    },
    'moons_grace': {
        'icon': '🌙', 'name': 'Moon\'s Grace Star', 'type': 'Stability · Warmth',
        'desc': 'A gentle, stabilizing presence like moonlight. Strong blessings in family and close relationships. Partners and loved ones bring meaningful support.',
        'tip': 'Invest in family time. Your marriage and home life hold your greatest fortune.'
    },
    'crimson_flame': {
        'icon': '🌹', 'name': 'Crimson Flame Star', 'type': 'Fatal Attraction',
        'desc': 'The Peach Blossom\'s fiercer sibling. An intense, almost dangerous charisma that draws people helplessly toward you. Powerful in entertainment, arts, and beauty industries.',
        'tip': 'Your allure is undeniable — use it responsibly. Keep your relationships clear and your boundaries firm.'
    },
    'iron_will': {
        'icon': '⚒️', 'name': 'Iron Will Star', 'type': 'Extreme Charisma',
        'desc': 'A star of extremes — spectacular success or dramatic downfall. Your leadership and presence are overwhelming. Common among military leaders, judges, and political figures.',
        'tip': 'Stay centered. Avoid hubris, practice humility, and your influence will last a lifetime.'
    },
    'golden_chariot': {
        'icon': '🏆', 'name': 'Golden Chariot Star', 'type': 'Abundance',
        'desc': 'The star of golden fortune. Blessed unions and prosperous partnerships. Your spouse is likely to bring wealth, status, or both. Life rewards you richly.',
        'tip': 'Choose your partner wisely — it may be the most important decision of your life. After marriage, your fortune multiplies.'
    },
}


def analyze_sinsal(pillars, ilgan):
    """Extract active celestial markers from the chart"""
    year_p, month_p, day_p, time_p = pillars
    all_jiji = [p[1] for p in pillars]
    day_jiji = day_p[1]
    other_jiji_no_day = [year_p[1], month_p[1], time_p[1]]

    found = []

    base_group = SAMHAP_OF.get(day_jiji)
    if base_group:
        for name, mp in [
            ('peach_blossom',   DOHWA_MAP),
            ('traveling_star',  YEOKMA_MAP),
            ('lotus_crown',     HWAGAE_MAP),
            ('general_star',    JANGSEONG_MAP),
        ]:
            target = mp[base_group]
            if target in all_jiji:
                found.append(name)

    for t in CHEONULGWIIN_MAP.get(ilgan, []):
        if t in all_jiji:
            found.append('noble_benefactor')
            break

    munchang_target = MUNCHANG_MAP.get(ilgan)
    if munchang_target and munchang_target in all_jiji:
        found.append('scholar_star')

    if ilgan in _YANG_GAN_SET:
        yangin_target = YANGIN_MAP.get(ilgan)
        if yangin_target and yangin_target in all_jiji:
            found.append('blade_of_resolve')

    jaego_target = JAEGO_MAP.get(ilgan)
    if jaego_target and jaego_target in all_jiji:
        found.append('wealth_vault')

    if (day_p[0], day_p[1]) in BAEKHO_PAIRS:
        found.append('white_tiger')

    gongmang_jiji = calc_gongmang(day_p[0], day_p[1])
    if any(j in gongmang_jiji for j in other_jiji_no_day):
        found.append('void_star')

    cheondeok_target = CHEONDEOK_MAP.get(month_p[1])
    all_gan = [year_p[0], month_p[0], day_p[0], time_p[0]]
    if cheondeok_target and cheondeok_target in all_gan:
        found.append('heavens_grace')

    weoldeok_target = WEOLDEOK_MAP.get(month_p[1])
    if weoldeok_target and weoldeok_target in all_gan:
        found.append('moons_grace')

    hongyeom_target = HONGYEOM_MAP.get(ilgan)
    if hongyeom_target and hongyeom_target in all_jiji:
        found.append('crimson_flame')

    if (day_p[0], day_p[1]) in GOEGANG_PAIRS:
        found.append('iron_will')

    keumyeo_target = KEUMYEO_MAP.get(ilgan)
    if keumyeo_target and keumyeo_target in all_jiji:
        found.append('golden_chariot')

    return [{'key': k, **SINSAL_DATA[k]} for k in found]

# ═══════════════════════════════════════════════
# Static analysis data from JSON
# ═══════════════════════════════════════════════

def load_analysis_data():
    try:
        with open("saju_mbti_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Data Load Error: {e}")
        return None

ANALYSIS_DATA = load_analysis_data()

async def get_report_analysis(birth_date: str, birth_time: str, mbti: str, lang: str = 'en',
                              calendar_type: str = 'solar', is_leap_month: bool = False,
                              gender: str = 'F',
                              apply_dst: bool = False, apply_solar_time: bool = False,
                              birth_city: str = '',
                              name: str = ''):
    solar_date, lunar_original = resolve_birth_date(birth_date, calendar_type, is_leap_month)
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    year, month, day = map(int, solar_date.split('-'))
    try:
        hour = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        hour = 12

    year_p, month_p, day_p, time_p = calc_pillars_accurate(
        raw_y, raw_m, raw_d, hour, calendar_type, is_leap_month,
        apply_dst=apply_dst, apply_solar_time=apply_solar_time, city=birth_city
    )
    time_adjustments = getattr(calc_pillars_accurate, 'last_adjustments', [])

    pillars = [year_p, month_p, day_p, time_p]
    oheng_simple = analyze_oheng(pillars)
    oheng_adv = analyze_oheng_advanced(pillars)
    oheng = oheng_adv['count']
    ilgan = day_p[0]
    ilgan_name = ILGAN_NAMES[ilgan]

    sinsal = analyze_sinsal(pillars, ilgan)
    zodiac = analyze_zodiac(year_p[1])
    constellation = analyze_constellation(
        int(solar_date.split('-')[1]),
        int(solar_date.split('-')[2]),
        oheng_adv.get('strongest', '')
    )
    daewoon = calc_daewoon(raw_y, raw_m, raw_d, hour, gender, calendar_type, is_leap_month, count=10)

    phonetic = None
    if name:
        phonetic = analyze_phonetic_oheng(name, oheng_adv.get('pct'))

    time_correction = {
        'applied': len(time_adjustments) > 0,
        'adjustments': time_adjustments,
        'apply_dst': apply_dst,
        'apply_solar_time': apply_solar_time,
        'birth_city': birth_city if apply_solar_time else None,
    }

    weakest_oheng = min(oheng, key=oheng.get)
    lucky = LUCKY_MAP[weakest_oheng]

    if ANALYSIS_DATA:
        ilgan_data = ANALYSIS_DATA["ilgan_analysis"].get(ilgan, {"title": ilgan_name, "desc": f"You carry the energy of {ilgan_name}."})

        combo_key = f"{ilgan}_{mbti}"
        combo_data = ANALYSIS_DATA.get("ilgan_mbti_combinations", {}).get(combo_key)
        if combo_data:
            synergy_title = combo_data["title"]
            synergy_desc = combo_data["desc"]
        else:
            synergy_desc = f"The energy of {ilgan_name} harmonizes beautifully with your {mbti} personality. "
            for char in mbti:
                synergy_desc += ANALYSIS_DATA["synergy_base"].get(char, "") + " "
            synergy_title = f"{ilgan_name} × {mbti} Synergy"
            synergy_desc = synergy_desc.strip()

        comp_data = ANALYSIS_DATA["compatibility_data"].get(ilgan, {"types": ["certain types"], "desc": "A meaningful connection awaits you."})
        comp_types = ", ".join(comp_data["types"])

        detailed = ANALYSIS_DATA.get("ilgan_detailed", {}).get(ilgan, {})
        mbti_love = ANALYSIS_DATA.get("mbti_love_style", {}).get(mbti, {})

        combo_detail = {}
        if combo_data:
            combo_detail = {
                "strength": combo_data.get("strength", ""),
                "weakness": combo_data.get("weakness", ""),
                "career": combo_data.get("career", ""),
                "growth_tip": combo_data.get("growth_tip", "")
            }

        ilgan_oheng = CHEONGAN_OHENG[ilgan]
        fortune = ANALYSIS_DATA.get("monthly_fortune_base", {}).get(ilgan_oheng, {})

        analysis = {
            "ilgan_title": ilgan_data["title"],
            "ilgan_desc": ilgan_data["desc"],
            "synergy_title": synergy_title,
            "synergy_desc": synergy_desc,
            "compatibility_title": f"Best Match: {comp_types}",
            "compatibility_desc": comp_data["desc"]
        }
    else:
        detailed = {}
        mbti_love = {}
        combo_detail = {}
        fortune = {}
        analysis = {
            "ilgan_title": ilgan_name,
            "ilgan_desc": f"You carry the energy of {ilgan_name}. (Data load failed)",
            "synergy_title": f"{ilgan_name} × {mbti}",
            "synergy_desc": "These two energies weave together to create your uniquely captivating presence.",
            "compatibility_title": "Recommended Match",
            "compatibility_desc": "Someone who appreciates your depth and energy is waiting for you."
        }

    result_sections = ANALYSIS_DATA.get("result_sections", []) if ANALYSIS_DATA else []
    payment_config = ANALYSIS_DATA.get("payment_config", {}) if ANALYSIS_DATA else {}

    return {
        'pillars': {
            'year': {'gan': year_p[0], 'ji': year_p[1], 'label': f'{year_p[0]} {year_p[1]}'},
            'month': {'gan': month_p[0], 'ji': month_p[1], 'label': f'{month_p[0]} {month_p[1]}'},
            'day': {'gan': day_p[0], 'ji': day_p[1], 'label': f'{day_p[0]} {day_p[1]}'},
            'time': {'gan': time_p[0], 'ji': time_p[1], 'label': f'{time_p[0]} {time_p[1]}'},
        },
        'ilgan': {'name': ilgan_name, 'title': analysis['ilgan_title'], 'desc': analysis['ilgan_desc']},
        'oheng': oheng,
        'oheng_advanced': oheng_adv,
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
    lang: str = 'en'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False
    apply_dst: bool = False
    apply_solar_time: bool = False
    birth_city: str = ''

class PremiumReportInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'en'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False

class PaidPremiumInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'en'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    calendar_type: str = 'solar'
    is_leap_month: bool = False
    paymentKey: str  # Polar checkout ID

class PaymentCreditInput(BaseModel):
    paymentKey: str   # Polar checkout ID
    product: str

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
    paymentKey: str = ''  # Stripe PaymentIntent ID

class YearlyFortuneInput(BaseModel):
    birth_date: str
    birth_time: str = '12:00'
    mbti: str
    name: str = ''
    gender: str = 'F'
    target_year: int = 2026
    calendar_type: str = 'solar'
    is_leap_month: bool = False
    paymentKey: str = ''  # Stripe PaymentIntent ID

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
# Premium LLM Analysis
# ═══════════════════════════════════════════════

PREMIUM_PROMPT_TEMPLATE = """You are a master of Eastern Four Pillars astrology with 30 years of experience, combined with deep MBTI expertise.
Based on the birth chart and MBTI below, write a deeply personal and insightful reading for this individual.

[Birth Chart Info]
- Date of Birth: {birth_date}
- Time of Birth: {birth_time}
- Four Pillars: Year({year_p}) Month({month_p}) Day({day_p}) Hour({time_p})
- Day Master: {ilgan_name}
- Five Elements: Wood={oh_wood} Fire={oh_fire} Earth={oh_earth} Metal={oh_metal} Water={oh_water}
- MBTI: {mbti}

[Writing Rules]
1. Analyze the relationships within the 8 characters (clash, harmony, punishment, destruction, generation, control)
2. Connect MBTI traits with the chart's elemental energy — show synergies and tensions
3. Write warmly but honestly, like a wise mentor having an intimate conversation
4. Use vivid metaphors and imagery, but never exaggerate
5. Each section should be 3-5 sentences

[Output Format — respond ONLY with this JSON structure]
{{
  "deep_personality": {{
    "title": "One sentence capturing this person's essence",
    "desc": "Full personality analysis reading the entire birth chart (all 8 characters and their relationships)"
  }},
  "hidden_pattern": {{
    "title": "Hidden pattern title",
    "desc": "Insights invisible in a basic reading — clash/harmony/punishment dynamics and what they reveal"
  }},
  "life_turning_point": {{
    "title": "Life turning point title",
    "desc": "Key periods from Grand Cycle and Annual Cycles worth watching, with advice"
  }},
  "deep_love": {{
    "title": "Deep love analysis title",
    "desc": "Romantic patterns and partner destiny based on the birth chart"
  }},
  "career": {{
    "title": "Career destiny title (e.g., 'Your true calling is...')",
    "desc": "Deep career analysis based on Five Elements and MBTI (3-5 sentences)",
    "work_style": "One-line work style summary",
    "best_fields": ["Field 1", "Field 2", "Field 3", "Field 4", "Field 5"]
  }},
  "wealth": {{
    "title": "Wealth analysis title (e.g., 'Your money has a pattern')",
    "desc": "Deep wealth analysis based on wealth stars position and state (3-5 sentences)",
    "money_style": "One-line money style summary",
    "wealth_tip": "One actionable tip to boost wealth luck"
  }},
  "health": {{
    "title": "Health analysis title",
    "desc": "Health tendencies from Five Element balance (3-5 sentences)",
    "health_tip": "One specific lifestyle tip for health",
    "weak_points": ["Area 1", "Area 2", "Area 3"]
  }},
  "deep_wealth": {{
    "title": "Deep wealth/business analysis title",
    "desc": "Wealth flow analysis based on wealth star positions and elemental dynamics"
  }},
  "advice": {{
    "title": "A word from the master",
    "desc": "The one essential piece of wisdom for someone with this birth chart"
  }}
}}"""

def _build_premium_payload(birth_date: str, birth_time: str, mbti: str,
                           calendar_type: str = 'solar', is_leap_month: bool = False):
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    try:
        hour = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        hour = 12

    year_p, month_p, day_p, time_p = calc_pillars_accurate(
        raw_y, raw_m, raw_d, hour, calendar_type, is_leap_month
    )

    pillars = [year_p, month_p, day_p, time_p]
    oheng = analyze_oheng(pillars)
    ilgan = day_p[0]
    ilgan_name = ILGAN_NAMES[ilgan]

    ilgan_detailed = ANALYSIS_DATA.get("ilgan_detailed", {}).get(ilgan, {}) if ANALYSIS_DATA else {}
    lifestyle = {
        "fengshui": ilgan_detailed.get("fengshui"),
        "accessory": ilgan_detailed.get("accessory"),
        "scent": ilgan_detailed.get("scent"),
    }

    premium_data = None
    ai_error = None
    if gemini_model:
        try:
            prompt = PREMIUM_PROMPT_TEMPLATE.format(
                birth_date=birth_date,
                birth_time=birth_time,
                year_p=f"{year_p[0]} {year_p[1]}",
                month_p=f"{month_p[0]} {month_p[1]}",
                day_p=f"{day_p[0]} {day_p[1]}",
                time_p=f"{time_p[0]} {time_p[1]}",
                ilgan_name=ilgan_name,
                oh_wood=oheng['wood'], oh_fire=oheng['fire'], oh_earth=oheng['earth'],
                oh_metal=oheng['metal'], oh_water=oheng['water'],
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
            ai_error = f"AI deep analysis is temporarily unavailable. ({str(e)[:80]})"
    else:
        ai_error = "AI deep analysis key is not connected yet. Lifestyle recommendations are still available."

    return {
        "status": "ok",
        "premium": premium_data,
        "lifestyle": lifestyle,
        "ai_error": ai_error,
    }


@app.post("/get-premium-report")
async def get_premium_report(input_data: PremiumReportInput):
    raise HTTPException(status_code=403, detail="Payment required. Use /confirm-and-get-premium.")


VALID_PRODUCTS = {"premium", "additional", "compatibility", "yearly", "constellation", "all"}
PRODUCT_PRICES = {"all": "1.99"}  # everything else defaults to $0.99


def _verify_paypal_capture(order_id: str, expected_product: str) -> None:
    """Verify that a PayPal order was captured.
    Accepts either exact product match OR 'all' bundle purchase."""
    if f"{expected_product}:{order_id}" in _captured_orders:
        return
    if f"all:{order_id}" in _captured_orders:
        return  # 'all' bundle unlocks everything
    raise HTTPException(status_code=400, detail="Payment not verified. Complete payment first.")


@app.post("/create-paypal-order")
async def create_paypal_order(data: dict):
    product = data.get("product", "premium")
    if product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="Unknown product")
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Payment not configured")
    token = await _paypal_token()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "amount": {"currency_code": "USD", "value": PRODUCT_PRICES.get(product, "0.99")},
                    "custom_id": product,
                    "description": "Destiny Reading — Unlock All" if product == "all" else f"Destiny Reading Unlock — {product}",
                }],
            },
            timeout=15,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="PayPal order creation failed")
    return {"order_id": r.json()["id"]}


@app.post("/capture-paypal-order")
async def capture_paypal_order(data: dict):
    order_id = data.get("order_id", "")
    product  = data.get("product", "premium")
    if not order_id or product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail="Invalid request")
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Payment not configured")
    token = await _paypal_token()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=15,
        )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="PayPal capture failed")
    body = r.json()
    if body.get("status") != "COMPLETED":
        raise HTTPException(status_code=400, detail=f"Payment not completed: {body.get('status')}")
    # Verify amount (PayPal capture response nests captures under purchase_units[0].payments.captures)
    units = body.get("purchase_units", [{}])
    captures = units[0].get("payments", {}).get("captures", [{}])
    amount = captures[0].get("amount", {}).get("value", "0") if captures else "0"
    expected_min = 1.98 if product == "all" else 0.98
    if float(amount) < expected_min:
        raise HTTPException(status_code=400, detail="Amount mismatch")
    _captured_orders.add(f"{product}:{order_id}")
    return {"status": "ok", "product": product}


@app.post("/confirm-and-get-premium")
async def confirm_and_get_premium(data: PaidPremiumInput):
    _verify_paypal_capture(data.paymentKey, "premium")
    try:
        return _build_premium_payload(data.birth_date, data.birth_time, data.mbti,
                                      calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis generation failed: {str(e)[:200]}")


# ─────────────────────────────────────────────
# Compatibility Analysis
# ─────────────────────────────────────────────
OHENG_SAENG = {'wood':'fire', 'fire':'earth', 'earth':'metal', 'metal':'water', 'water':'wood'}
OHENG_GEUK  = {'wood':'earth', 'earth':'water', 'water':'fire', 'fire':'metal', 'metal':'wood'}

def oheng_relation_score(a_oheng, b_oheng):
    el = {'wood': 'Wood', 'fire': 'Fire', 'earth': 'Earth', 'metal': 'Metal', 'water': 'Water'}
    if a_oheng == b_oheng:
        return 70, "Kindred spirits — naturally comfortable together"
    if OHENG_SAENG.get(a_oheng) == b_oheng:
        return 90, f"{el[a_oheng]} nurtures {el[b_oheng]} — a supportive bond"
    if OHENG_SAENG.get(b_oheng) == a_oheng:
        return 90, f"{el[b_oheng]} nurtures {el[a_oheng]} — a supportive bond"
    if OHENG_GEUK.get(a_oheng) == b_oheng:
        return 50, f"{el[a_oheng]} challenges {el[b_oheng]} — creative tension"
    if OHENG_GEUK.get(b_oheng) == a_oheng:
        return 50, f"{el[b_oheng]} challenges {el[a_oheng]} — creative tension"
    return 75, "A harmonious blend of energies"


SAMHAP_GROUPS_LIST = [
    ['monkey','rat','dragon'], ['tiger','horse','dog'], ['snake','rooster','ox'], ['pig','rabbit','goat']
]
YUKCHUNG = {'rat':'horse','horse':'rat', 'ox':'goat','goat':'ox', 'tiger':'monkey','monkey':'tiger',
            'rabbit':'rooster','rooster':'rabbit', 'dragon':'dog','dog':'dragon', 'snake':'pig','pig':'snake'}

def zodiac_relation(a_jiji, b_jiji):
    if a_jiji == b_jiji:
        return 75, "Same zodiac — deep understanding and natural empathy"
    if YUKCHUNG.get(a_jiji) == b_jiji:
        return 45, "Opposite signs — exciting tension but requires patience"
    for group in SAMHAP_GROUPS_LIST:
        if a_jiji in group and b_jiji in group:
            return 95, "Trinity harmony — a match practically written in the stars"
    return 70, "A balanced and easygoing pairing"


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
        return 70, "Same MBTI — you instinctively get each other"
    if b_mbti in MBTI_BEST.get(a_mbti, []):
        return 95, "Golden MBTI match — you complete each other beautifully"
    if a_mbti[1:3] == b_mbti[1:3]:
        return 80, "Similar worldview — great conversations await"
    if a_mbti[2:] == b_mbti[2:]:
        return 75, "Emotional wavelength match — you just *feel* each other"
    return 65, "Different colors make the most interesting paintings"


def _get_chemi_type(total_score, oh_rel, mbti_a, mbti_b):
    if oh_rel == 'saeng':
        if total_score >= 85:
            return ('🔥 Destined Soulmates', '"I knew the moment we met — it was always you."')
        return ('🌿 Healing Bond', '"Why do I feel so at peace when you\'re around?"')
    elif oh_rel == 'geuk':
        if total_score >= 70:
            return ('⚡ Electric Chemistry', '"We fight, we make up, we grow closer every time."')
        return ('🌊 Growth Through Challenge', '"You make me better every single day."')
    elif oh_rel == 'same':
        return ('🪞 Mirror Souls', '"It\'s like looking at a different version of myself."')
    else:
        if total_score >= 80:
            return ('🌈 Natural Harmony', '"We don\'t need words — we just know."')
        return ('🎵 Rhythm & Flow', '"Being with you just feels... right."')


def _get_oheng_relation_type(a_oheng, b_oheng):
    if a_oheng == b_oheng:
        return 'same'
    if OHENG_SAENG.get(a_oheng) == b_oheng or OHENG_SAENG.get(b_oheng) == a_oheng:
        return 'saeng'
    if OHENG_GEUK.get(a_oheng) == b_oheng or OHENG_GEUK.get(b_oheng) == a_oheng:
        return 'geuk'
    return 'harmony'


def _get_mascot_comment(total_score):
    if total_score >= 90:
        return {
            'expression': '😻',
            'comment': 'This combination is legendary! The universe practically arranged this one~ ✨',
            'sub': 'Meeting each other wasn\'t coincidence — it was destiny!'
        }
    elif total_score >= 80:
        return {
            'expression': '😸',
            'comment': 'Ooh, that\'s a strong match! You two bring out the best in each other~ ⭐',
            'sub': 'With just a little effort, you could be soulmates!'
        }
    elif total_score >= 70:
        return {
            'expression': '🐱',
            'comment': 'Not bad at all! Communication is your secret weapon here~',
            'sub': 'Embrace your differences and watch the magic happen!'
        }
    elif total_score >= 60:
        return {
            'expression': '😿',
            'comment': 'Hmm, this one takes some work...',
            'sub': 'But love that\'s earned is stronger than love that\'s given. Don\'t give up!'
        }
    else:
        return {
            'expression': '🙀',
            'comment': 'Whoa, this is a challenging match!',
            'sub': 'But opposites attract for a reason — if you learn from each other, you\'ll be unstoppable!'
        }


def calc_compatibility(person_a: dict, person_b: dict) -> dict:
    def make_profile(p):
        raw_y, raw_m, raw_d = map(int, p['birth_date'].split('-'))
        try:
            h = int(p['birth_time'].split(':')[0])
        except (ValueError, AttributeError):
            h = 12
        cal_type = p.get('calendar_type', 'solar')
        leap = p.get('is_leap_month', False)
        yp, mp, dp, tp = calc_pillars_accurate(raw_y, raw_m, raw_d, h, cal_type, leap)
        y, m, dd = map(int, resolve_birth_date(p['birth_date'], cal_type, leap)[0].split('-'))
        ilgan = dp[0]
        pillars_list = [yp, mp, dp, tp]
        oheng_data = analyze_oheng_advanced(pillars_list)
        return {
            'name': p.get('name') or 'Anonymous',
            'gender': p.get('gender','F'),
            'ilgan': ilgan,
            'ilgan_name': ILGAN_NAMES[ilgan],
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

    oh_score, oh_desc = oheng_relation_score(a['ilgan_oheng'], b['ilgan_oheng'])
    z_score, z_desc = zodiac_relation(a['year_jiji'], b['year_jiji'])
    m_score, m_desc = mbti_relation(a['mbti'], b['mbti'])

    total = round(oh_score * 0.4 + z_score * 0.3 + m_score * 0.3)

    if total >= 90: grade, grade_emoji, grade_desc = 'S', '💎', 'Soulmates — a cosmic once-in-a-lifetime connection'
    elif total >= 80: grade, grade_emoji, grade_desc = 'A', '⭐', 'Fantastic — you bring out each other\'s best'
    elif total >= 70: grade, grade_emoji, grade_desc = 'B', '🌟', 'Great potential — grows deeper with effort'
    elif total >= 60: grade, grade_emoji, grade_desc = 'C', '✨', 'Average — needs patience and understanding'
    else: grade, grade_emoji, grade_desc = 'D', '⚡', 'Challenging — but differences can become strengths'

    oh_rel_type = _get_oheng_relation_type(a['ilgan_oheng'], b['ilgan_oheng'])
    chemi_name, chemi_quote = _get_chemi_type(total, oh_rel_type, a['mbti'], b['mbti'])
    mascot = _get_mascot_comment(total)

    return {
        'person_a': a,
        'person_b': b,
        'total_score': total,
        'grade': grade,
        'grade_emoji': grade_emoji,
        'grade_desc': grade_desc,
        'chemi_name': chemi_name,
        'chemi_quote': chemi_quote,
        'mascot': mascot,
        'details': [
            {'label': 'Elemental Match (Day Master)', 'score': oh_score, 'desc': oh_desc, 'weight': '40%'},
            {'label': 'Zodiac Match (Year Branch)', 'score': z_score, 'desc': z_desc, 'weight': '30%'},
            {'label': 'MBTI Match', 'score': m_score, 'desc': m_desc, 'weight': '30%'},
        ],
        'advice': _build_compatibility_advice(a, b, total),
    }


def _build_compatibility_advice(a, b, score):
    el = {'wood':'Wood', 'fire':'Fire', 'earth':'Earth', 'metal':'Metal', 'water':'Water'}
    base = f"{a['name']} ({el[a['ilgan_oheng']]} energy) and {b['name']} ({el[b['ilgan_oheng']]} energy) — "
    if score >= 80:
        return base + "your elemental flow and personalities align naturally. You don't need to try hard — just don't let comfort turn into complacency. Keep surprising each other."
    elif score >= 70:
        return base + "you have solid chemistry. Your differences are more interesting than threatening. When small conflicts arise, talk it through — this bond grows deeper with honesty."
    elif score >= 60:
        return base + "your energies are quite different, which might feel awkward at first. But accepting each other's quirks can turn this into a beautifully complementary relationship."
    else:
        return base + "this is a bold combination. It won't always be easy, but the hardest relationships can become the deepest. The secret? Respect what makes the other person different."


@app.post("/get-compatibility-preview")
async def get_compatibility_preview(data: CompatibilityInput):
    result = calc_compatibility(data.person_a.dict(), data.person_b.dict())
    return {
        'total_score': result['total_score'],
        'grade': result['grade'],
        'grade_emoji': result['grade_emoji'],
        'grade_desc': result['grade_desc'],
        'person_a_summary': {'name': result['person_a']['name'], 'ilgan': result['person_a']['ilgan_name'], 'mbti': result['person_a']['mbti']},
        'person_b_summary': {'name': result['person_b']['name'], 'ilgan': result['person_b']['ilgan_name'], 'mbti': result['person_b']['mbti']},
        'locked': True,
        'unlock_price': 99,
    }


@app.post("/get-compatibility-full")
async def get_compatibility_full(data: CompatibilityInput):
    raise HTTPException(status_code=403, detail="Payment required. Use /confirm-and-get-compatibility.")


@app.post("/confirm-and-get-compatibility")
async def confirm_and_get_compatibility(data: CompatibilityInput):
    _verify_paypal_capture(data.paymentKey, "compatibility")
    result = calc_compatibility(data.person_a.dict(), data.person_b.dict())
    result['unlocked'] = True
    return result


# ─────────────────────────────────────────────
# Monthly Fortune Calendar
# ─────────────────────────────────────────────

MONTH_THEMES_BY_OHENG = {
    'wood': {
        1: ('New Beginnings', 'Set your intentions for the year. Don\'t overreach — focus on one core goal.'),
        2: ('Laying Roots', 'Build your foundation. Nurture existing relationships over chasing new ones.'),
        3: ('Spring Growth', 'Time to leap. Execute those plans you\'ve been holding back.'),
        4: ('Branching Out', 'Expand your horizons. Great for travel, networking, and career moves.'),
        5: ('Blossoming', 'Early fruits of your labor appear. Partnerships and collaborations thrive.'),
        6: ('Full Canopy', 'Energy is at its peak — but watch for burnout. Balance work with rest.'),
        7: ('Into the Light', 'Your talents get noticed. Put yourself out there confidently.'),
        8: ('Harvest Time', 'Rewards are coming in. Financial luck is favorable.'),
        9: ('Autumn Pruning', 'Review and refine. Trim what\'s not working — including relationships.'),
        10: ('Closing Chapters', 'Wrap up projects. Prepare mentally for the next big thing.'),
        11: ('Quiet Rest', 'Turn inward. Avoid major decisions and recharge your batteries.'),
        12: ('Winter Storage', 'Study, rest, and plan for next year. Avoid big spending.'),
    },
    'fire': {
        1: ('Ignition', 'Motivation is high. New ventures look promising, but watch for conflict.'),
        2: ('Focused Flame', 'Great for deep work. Avoid multitasking this month.'),
        3: ('Blazing Bright', 'Popularity soars. Social events and networking pay off.'),
        4: ('Peak Heat', 'Leadership moments. Presentations, interviews, and competitions favor you.'),
        5: ('Festival Energy', 'Love, socializing, and creativity all peak. Express yourself fully.'),
        6: ('Cool Down', 'Energy runs too hot. Step back before sparks fly into conflict.'),
        7: ('Deeper Glow', 'Authentic relationships deepen this month.'),
        8: ('Warm Giving', 'Generosity brings unexpected rewards.'),
        9: ('Study Light', 'Perfect for focused learning and self-development.'),
        10: ('Ember Strength', 'Quietly build skills. Let your work speak louder than words.'),
        11: ('Fireplace Rest', 'Contemplation and meditation. Hold off on big decisions.'),
        12: ('Rekindling', 'Reconnect with your inner spark. Prioritize family time.'),
    },
    'earth': {
        1: ('Preparing the Soil', 'Foundation time. Review finances and assets.'),
        2: ('Planting Seeds', 'Long-term planning works best now. Choose wisely.'),
        3: ('Tending Ground', 'Home improvements, organization, and environment changes are favored.'),
        4: ('Nurturing Others', 'Acts of kindness return as blessings.'),
        5: ('Early Abundance', 'Wealth and relationships both strengthen this month.'),
        6: ('Measuring Progress', 'Time to evaluate your results and get feedback.'),
        7: ('Golden Fields', 'Peak financial luck. Real estate and investment decisions are favored.'),
        8: ('Reaping Rewards', 'Concrete results arrive. Your patience pays off.'),
        9: ('Building Reserves', 'Save and consolidate. Avoid unnecessary spending.'),
        10: ('Quiet Strength', 'Strengthen your inner circle. Quality over quantity.'),
        11: ('Winter Stillness', 'Slow down and prioritize health and self-care.'),
        12: ('Dreaming Ahead', 'Reflect on the big picture. Plant seeds for next year.'),
    },
    'metal': {
        1: ('Sharpening the Blade', 'Set systems and standards. Great for organizing your life.'),
        2: ('Training Month', 'Skill development and certifications are highly favored.'),
        3: ('Decision Time', 'Make that important choice you\'ve been delaying. Be decisive.'),
        4: ('Polished Shine', 'Your expertise gets recognized. Opportunities knock.'),
        5: ('Competitive Edge', 'Competitions and challenges favor you. Go for it.'),
        6: ('Quiet Focus', 'Step away from noise. Solitude recharges your edge.'),
        7: ('Autumn Harvest', 'Long-term projects finally show results.'),
        8: ('Peak Precision', 'Metal energy peaks. Authority, promotion, and contracts are favored.'),
        9: ('Clean Finish', 'Close out one cycle cleanly. Settle debts and obligations.'),
        10: ('Frost Warning', 'Your edge is sharp — but watch for relationship friction.'),
        11: ('Ice Strength', 'Maximum decisiveness, but you may seem cold. Add warmth.'),
        12: ('Blueprint Season', 'Plan next year with surgical precision.'),
    },
    'water': {
        1: ('Undercurrent', 'Quiet preparation period. Study and research are favored.'),
        2: ('Spring Thaw', 'Frozen situations start to move. Relationship healing begins.'),
        3: ('Welling Up', 'Intuition is strongest now. Trust your gut for creative and strategic work.'),
        4: ('New Streams', 'New people enter your life. Network actively.'),
        5: ('Widening River', 'Your world expands. Travel and exploration are highly favored.'),
        6: ('Full Reservoir', 'Energy peaks. Take on ambitious projects now.'),
        7: ('Lake Depth', 'Inner wisdom deepens. Insight and clarity are at their best.'),
        8: ('Tidal Change', 'Unexpected shifts are possible. Stay flexible and adaptable.'),
        9: ('Autumn Rain', 'Emotions run deep. Great month for art, writing, and reflection.'),
        10: ('Frost Clarity', 'Financial and relationship review. Clean up loose ends.'),
        11: ('Deep Winter', 'Go within. Meditation and rest are essential.'),
        12: ('Ice Crystal', 'Wrap up the year. Compress and consolidate your gains.'),
    },
}

def build_yearly_fortune(birth_date: str, birth_time: str, mbti: str, year: int,
                          calendar_type: str = 'solar', is_leap_month: bool = False):
    raw_y, raw_m, raw_d = map(int, birth_date.split('-'))
    try:
        h = int(birth_time.split(':')[0])
    except (ValueError, AttributeError):
        h = 12
    _yp, _mp, dp, _tp = calc_pillars_accurate(raw_y, raw_m, raw_d, h, calendar_type, is_leap_month)
    ilgan = dp[0]
    ilgan_oheng = CHEONGAN_OHENG[ilgan]
    ilgan_name = ILGAN_NAMES[ilgan]

    base_themes = MONTH_THEMES_BY_OHENG.get(ilgan_oheng, MONTH_THEMES_BY_OHENG['wood'])

    MONTH_LABELS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    SEASON = {'Spring':[3,4,5],'Summer':[6,7,8],'Autumn':[9,10,11],'Winter':[12,1,2]}
    def season_of(mon):
        for s, ms in SEASON.items():
            if mon in ms: return s
        return ''

    LUCKY_BY_OHENG = {
        'wood':  {'color': 'Green / Sage', 'item': 'Plants, wooden accessories', 'food': 'Green vegetables, salad'},
        'fire':  {'color': 'Red / Orange', 'item': 'Candles, warm lighting', 'food': 'Spicy food, dark chocolate'},
        'earth': {'color': 'Yellow / Beige', 'item': 'Ceramics, earth-tone decor', 'food': 'Whole grains, sweet potato'},
        'metal': {'color': 'White / Gold', 'item': 'Metal jewelry, watches', 'food': 'White rice, pear'},
        'water': {'color': 'Blue / Black', 'item': 'Crystals, water features', 'food': 'Seafood, soups'},
    }

    ACTION_TIPS = {
        'same': 'Stick to your routine. Stability is your strength right now.',
        'saeng_me': 'Go for it! The energy supports bold action.',
        'me_saeng': 'Invest in learning and growth. Perfect time for self-improvement.',
        'geuk_me': 'Take it easy. Rest is a strategy, not a weakness.',
        'me_geuk': 'Your competitive spirit shines! But watch your words with others.',
        'neutral': 'Go with the flow, but add one small new thing to your routine.',
    }

    months = []
    for mon in range(1, 13):
        title, desc = base_themes[mon]
        target_p = calc_month_pillar(year, mon)
        mo_oheng = CHEONGAN_OHENG[target_p[0]]

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

        lucky = LUCKY_BY_OHENG.get(mo_oheng, LUCKY_BY_OHENG['wood'])

        months.append({
            'month': mon,
            'label': MONTH_LABELS[mon-1],
            'season': season_of(mon),
            'pillar': f'{target_p[0]} {target_p[1]}',
            'pillar_oheng': mo_oheng,
            'title': title,
            'desc': desc,
            'lucky_color': lucky['color'],
            'lucky_item': lucky['item'],
            'lucky_food': lucky['food'],
            'action_tip': ACTION_TIPS[rel],
        })

    luck_scores = []
    for mo in months:
        ti = ilgan_oheng
        mo_oh = mo['pillar_oheng']
        if ti == mo_oh: s = 75
        elif OHENG_SAENG.get(mo_oh) == ti: s = 90
        elif OHENG_SAENG.get(ti) == mo_oh: s = 80
        elif OHENG_GEUK.get(mo_oh) == ti: s = 50
        elif OHENG_GEUK.get(ti) == mo_oh: s = 65
        else: s = 70
        luck_scores.append(s)
        mo['luck'] = s

    best = max(range(12), key=lambda i: luck_scores[i])
    worst = min(range(12), key=lambda i: luck_scores[i])

    return {
        'year': year,
        'ilgan': ilgan_name,
        'ilgan_oheng': ilgan_oheng.capitalize(),
        'months': months,
        'best_month': {'label': months[best]['label'], 'reason': f"{months[best]['pillar']} — {months[best]['title']}"},
        'caution_month': {'label': months[worst]['label'], 'reason': f"{months[worst]['pillar']} — {months[worst]['title']}"},
        'summary': f"In {year}, your brightest month is {months[best]['label']} and the one to navigate carefully is {months[worst]['label']}.",
    }


@app.post("/get-yearly-fortune-preview")
async def yearly_preview(data: YearlyFortuneInput):
    result = build_yearly_fortune(data.birth_date, data.birth_time, data.mbti, data.target_year,
                                   calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    return {
        'year': result['year'],
        'ilgan': result['ilgan'],
        'best_month': result['best_month'],
        'caution_month': result['caution_month'],
        'summary': result['summary'],
        'locked': True,
        'unlock_price': 99,
    }


@app.post("/get-yearly-fortune-full")
async def get_yearly_full(data: YearlyFortuneInput):
    raise HTTPException(status_code=403, detail="Payment required. Use /confirm-and-get-yearly-fortune.")


@app.post("/confirm-and-get-yearly-fortune")
async def confirm_and_get_yearly(data: YearlyFortuneInput):
    _verify_paypal_capture(data.paymentKey, "yearly")
    result = build_yearly_fortune(data.birth_date, data.birth_time, data.mbti, data.target_year,
                                   calendar_type=data.calendar_type, is_leap_month=data.is_leap_month)
    result['unlocked'] = True
    return result


@app.post("/confirm-payment-credit")
async def confirm_payment_credit(data: PaymentCreditInput):
    if data.product not in VALID_PRODUCTS:
        raise HTTPException(status_code=400, detail=f"Unknown product: {data.product}")
    _verify_paypal_capture(data.paymentKey, data.product)
    return {"status": "ok", "product": data.product}

# ═══════════════════════════════════════════════
# Referral System
# ═══════════════════════════════════════════════

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
        raise HTTPException(status_code=404, detail="Invalid referral code.")

    ref = referral_store[code]
    ref["uses"] += 1

    bonus_for_sharer = False
    if not ref["bonus_granted"]:
        ref["bonus_granted"] = True
        bonus_for_sharer = True

    return {
        "valid": True,
        "bonus_for_sharer": bonus_for_sharer,
        "message": "Referral code applied! You've unlocked a free analysis."
    }

# ═══════════════════════════════════════════════
# Toss Disconnect Callback
# ═══════════════════════════════════════════════

TOSS_CALLBACK_AUTH = os.getenv("TOSS_CALLBACK_AUTH", "c2FqdS1tYnRpOmM4YzgwOGQ4ZWRhZWZjNWE4YmFjMWM3OTM4NGU1NTcz")

@app.get("/toss/disconnect-callback")
async def toss_disconnect_callback(request: Request):
    auth_header = request.headers.get("authorization", "")
    expected = f"Basic {TOSS_CALLBACK_AUTH}"
    if auth_header != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    params = dict(request.query_params)
    print(f"[TOSS] Disconnect callback received: {params}")
    return {"status": "ok", "message": "disconnect callback received"}


# ═══════════════════════════════════════════════
# Daily Fortune + Monthly Calendar
# ═══════════════════════════════════════════════

_OHENG_SANG_SAENG = {'wood': 'fire', 'fire': 'earth', 'earth': 'metal', 'metal': 'water', 'water': 'wood'}
_OHENG_SANG_GEUK = {'wood': 'earth', 'fire': 'metal', 'earth': 'water', 'metal': 'wood', 'water': 'fire'}
_OHENG_GEUK_ME   = {'wood': 'metal', 'fire': 'water', 'earth': 'wood', 'metal': 'fire', 'water': 'earth'}

def _daily_fortune_score(ilgan: str, target_date: date):
    day_gan, day_ji = calc_day_pillar(target_date.year, target_date.month, target_date.day)
    my_oheng = CHEONGAN_OHENG[ilgan]
    day_gan_oheng = CHEONGAN_OHENG[day_gan]
    day_ji_oheng = JIJI_OHENG[day_ji]

    score = 50

    if day_gan_oheng == my_oheng:
        score += 15
    elif _OHENG_SANG_SAENG[my_oheng] == day_gan_oheng:
        score += 10
    elif _OHENG_SANG_SAENG[day_gan_oheng] == my_oheng:
        score += 20
    elif _OHENG_SANG_GEUK[my_oheng] == day_gan_oheng:
        score += 12
    elif _OHENG_GEUK_ME[my_oheng] == day_gan_oheng:
        score -= 15

    if day_ji_oheng == my_oheng:
        score += 8
    elif _OHENG_SANG_SAENG[day_ji_oheng] == my_oheng:
        score += 12
    elif _OHENG_GEUK_ME[my_oheng] == day_ji_oheng:
        score -= 8

    import hashlib
    seed = hashlib.md5(f"{ilgan}{target_date.isoformat()}".encode()).hexdigest()
    micro = int(seed[:4], 16) % 11 - 5
    score += micro

    score = max(15, min(95, score))
    return score, day_gan, day_ji, day_gan_oheng, day_ji_oheng

_FORTUNE_MESSAGES = {
    'total': {
        (85, 100): ['Your best day yet! Go for it ✨', 'Everything flows in your favor today 🌟', 'Lucky energy is hiding in every corner today 🍀'],
        (70, 85): ['A good day ahead 😊', 'Positive energy surrounds you today 🌈', 'Small blessings will find you today ☘️'],
        (50, 70): ['A steady, peaceful day 🌿', 'Nothing dramatic — just keep going 📚', 'A calm day for focused work 🍃'],
        (30, 50): ['Tread carefully today 🤔', 'Save big decisions for tomorrow 💭', 'Recharge your batteries today 🔋'],
        (0, 30): ['Rest is your best strategy today 🛌', 'Take a step back and regroup 🧘', 'Focus inward — the world can wait 🌙'],
    },
    'love': {
        (85, 100): ['An exciting connection awaits 💕', 'Love energy is strong today 💘'],
        (70, 85): ['Warm conversations deepen bonds 💬', 'Reach out to someone special today 📱'],
        (50, 70): ['Keep things natural and easy 😌', 'Small gestures matter more than words today 🌸'],
        (30, 50): ['Misunderstandings lurk — choose words carefully ⚠️', 'Avoid emotional decisions today 💭'],
        (0, 30): ['Self-care over socializing today 🧘‍♀️', 'Take care of yourself first today 🛁'],
    },
    'money': {
        (85, 100): ['Financial luck is wide open today! 💰', 'Great timing for investments and deals 📈'],
        (70, 85): ['Surprise income might appear 🎁', 'A financially stable day ahead 💵'],
        (50, 70): ['Stick to your budget today 📊', 'Small purchases OK, big ones — think twice 🛒'],
        (30, 50): ['Watch your spending! Impulse buys calling 🚫', 'Unexpected expenses possible today 😥'],
        (0, 30): ['Best not to spend today 🔒', 'Use today for financial review instead 📝'],
    },
    'work': {
        (85, 100): ['Peak productivity! Tackle the big stuff today 🚀', 'Recognition from colleagues and leaders 🏆'],
        (70, 85): ['Great focus today — clear that backlog! 📋', 'Fresh ideas come easily today 💡'],
        (50, 70): ['Routine tasks go smoothly 📁', 'Steady progress builds momentum 🧱'],
        (30, 50): ['Double-check everything today ✅', 'Manage stress proactively today 🧃'],
        (0, 30): ['Do the minimum and conserve energy 🐢', 'Health comes first — don\'t push it 🩺'],
    },
    'health': {
        (85, 100): ['Feeling amazing! Perfect day for exercise 🏃', 'Body and mind are light and energized 🦋'],
        (70, 85): ['A walk or stretch would feel great 🚶', 'Health is good — just don\'t overdo it 👌'],
        (50, 70): ['Stick to your wellness routine 🥗', 'Prioritize good sleep tonight 😴'],
        (30, 50): ['Fatigue is building — rest early 🌛', 'Avoid cold foods and stay warm 🍵'],
        (0, 30): ['Listen to your body today 🩺', 'Resting IS being productive today 🛌'],
    },
}

def _pick_message(category: str, score: int, seed_str: str):
    import hashlib
    msgs_dict = _FORTUNE_MESSAGES[category]
    for (lo, hi), msgs in msgs_dict.items():
        if lo <= score < hi or (hi == 100 and score == 100):
            idx = int(hashlib.md5(f"{category}{seed_str}".encode()).hexdigest()[:4], 16) % len(msgs)
            return msgs[idx]
    return list(list(msgs_dict.values())[2])[0]

def _sub_score(base: int, category: str, seed_str: str):
    import hashlib
    h = int(hashlib.md5(f"{category}{seed_str}".encode()).hexdigest()[:6], 16)
    delta = (h % 21) - 10
    return max(15, min(95, base + delta))


class DailyFortuneInput(BaseModel):
    birth_date: str
    birth_time: str = '12:00'
    mbti: str = ''
    calendar_type: str = 'solar'
    is_leap_month: bool = False


@app.post("/get-daily-fortune")
async def get_daily_fortune(inp: DailyFortuneInput):
    try:
        raw_y, raw_m, raw_d = map(int, inp.birth_date.split('-'))
        hour = int(inp.birth_time.split(':')[0]) if inp.birth_time else 12

        if inp.calendar_type == 'lunar':
            solar = convert_lunar_to_solar(inp.birth_date, inp.is_leap_month)
            raw_y, raw_m, raw_d = map(int, solar.split('-'))

        year_p, month_p, day_p, time_p = calc_pillars_accurate(
            raw_y, raw_m, raw_d, hour, inp.calendar_type, inp.is_leap_month
        )
        ilgan = day_p[0]

        today = date.today()
        seed = f"{ilgan}{today.isoformat()}"
        total_score, day_gan, day_ji, dg_oh, dj_oh = _daily_fortune_score(ilgan, today)

        love_score = _sub_score(total_score, 'love', seed)
        money_score = _sub_score(total_score, 'money', seed)
        work_score = _sub_score(total_score, 'work', seed)
        health_score = _sub_score(total_score, 'health', seed)

        my_oheng = CHEONGAN_OHENG[ilgan]
        lucky = LUCKY_MAP.get(my_oheng, {})

        return {
            "status": "ok",
            "date": today.isoformat(),
            "day_pillar": f"{day_gan} {day_ji}",
            "ilgan": ilgan,
            "ilgan_name": ILGAN_NAMES[ilgan],
            "total": {
                "score": total_score,
                "message": _pick_message('total', total_score, seed),
                "grade": "🔥 Amazing" if total_score >= 85 else "😊 Good" if total_score >= 70 else "🌿 Steady" if total_score >= 50 else "⚠️ Careful" if total_score >= 30 else "🌙 Rest",
            },
            "love": {"score": love_score, "message": _pick_message('love', love_score, seed)},
            "money": {"score": money_score, "message": _pick_message('money', money_score, seed)},
            "work": {"score": work_score, "message": _pick_message('work', work_score, seed)},
            "health": {"score": health_score, "message": _pick_message('health', health_score, seed)},
            "lucky": {
                "color": lucky.get('color', ''),
                "number": lucky.get('num', ''),
                "direction": lucky.get('dir', ''),
                "food": lucky.get('food', ''),
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class MonthlyCalendarInput(BaseModel):
    birth_date: str
    birth_time: str = '12:00'
    mbti: str = ''
    year: int = 2026
    month: int = 1
    calendar_type: str = 'solar'
    is_leap_month: bool = False


@app.post("/get-monthly-calendar")
async def get_monthly_calendar(inp: MonthlyCalendarInput):
    try:
        raw_y, raw_m, raw_d = map(int, inp.birth_date.split('-'))
        hour = int(inp.birth_time.split(':')[0]) if inp.birth_time else 12

        if inp.calendar_type == 'lunar':
            solar = convert_lunar_to_solar(inp.birth_date, inp.is_leap_month)
            raw_y, raw_m, raw_d = map(int, solar.split('-'))

        year_p, month_p, day_p, time_p = calc_pillars_accurate(
            raw_y, raw_m, raw_d, hour, inp.calendar_type, inp.is_leap_month
        )
        ilgan = day_p[0]

        import calendar
        _, last_day = calendar.monthrange(inp.year, inp.month)

        days = []
        for d in range(1, last_day + 1):
            target = date(inp.year, inp.month, d)
            score, dg, dj, _, _ = _daily_fortune_score(ilgan, target)
            grade = "🔥" if score >= 85 else "😊" if score >= 70 else "🌿" if score >= 50 else "⚠️" if score >= 30 else "🌙"
            days.append({
                "day": d,
                "score": score,
                "grade": grade,
                "pillar": f"{dg} {dj}",
            })

        return {
            "status": "ok",
            "year": inp.year,
            "month": inp.month,
            "ilgan": ilgan,
            "ilgan_name": ILGAN_NAMES[ilgan],
            "days": days,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
