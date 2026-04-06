import os
import json
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Gemini API 설정
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

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

async def get_report_analysis(birth_date: str, birth_time: str, mbti: str, lang: str = 'ko'):
    year, month, day = map(int, birth_date.split('-'))
    hour = int(birth_time.split(':')[0])

    year_p = calc_year_pillar(year)
    month_p = calc_month_pillar(year, month)
    day_p = calc_day_pillar(year, month, day)
    time_p = calc_time_pillar(day_p[0], hour)

    pillars = [year_p, month_p, day_p, time_p]
    oheng = analyze_oheng(pillars)
    ilgan = day_p[0]
    ilgan_name_lang = ILGAN_NAMES.get(lang, ILGAN_NAMES['ko'])[ilgan]
    
    weakest_oheng = min(oheng, key=oheng.get)
    current_lucky_map = LUCKY_MAP.get(lang, LUCKY_MAP['ko'])
    lucky = current_lucky_map[weakest_oheng]

    # 정적 데이터를 이용한 분석 생성
    if ANALYSIS_DATA:
        # 1. 핵심 기운 분석
        ilgan_data = ANALYSIS_DATA["ilgan_analysis"].get(ilgan, {"title": ilgan_name_lang, "desc": f"{ilgan_name_lang}의 기운을 타고나셨군요."})
        
        # 2. 사주 & MBTI 시너지 (MBTI 각 글자별 설명 조합)
        synergy_desc = f"{ilgan_name_lang}의 기운과 {mbti} 성향이 조화롭게 어우러집니다. "
        for char in mbti:
            synergy_desc += ANALYSIS_DATA["synergy_base"].get(char, "") + " "
        
        # 3. 최고의 궁합
        comp_data = ANALYSIS_DATA["compatibility_data"].get(ilgan, {"types": ["특정 유형"], "desc": "당신과 잘 맞는 인연이 기다리고 있습니다."})
        comp_types = ", ".join(comp_data["types"])
        
        analysis = {
            "ilgan_title": ilgan_data["title"],
            "ilgan_desc": ilgan_data["desc"],
            "synergy_title": f"{ilgan_name_lang} x {mbti} 시너지",
            "synergy_desc": synergy_desc.strip(),
            "compatibility_title": f"최고의 궁합: {comp_types}",
            "compatibility_desc": comp_data["desc"]
        }
    else:
        # 폴백 데이터
        analysis = {
            "ilgan_title": ilgan_name_lang,
            "ilgan_desc": f"{ilgan_name_lang}의 기운을 타고나셨군요. (데이터 로드 실패)",
            "synergy_title": f"{ilgan_name_lang} x {mbti}",
            "synergy_desc": "두 기운이 조화롭게 어우러져 당신만의 독특한 매력을 만들어냅니다.",
            "compatibility_title": "추천 궁합",
            "compatibility_desc": "당신의 포용력을 이해해줄 수 있는 유형과 좋은 인연이 될 것입니다."
        }

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
        'lucky': lucky
    }

class ReportInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'

@app.post("/get-report")
async def get_report(input_data: ReportInput):
    try:
        report = await get_report_analysis(input_data.birth_date, input_data.birth_time, input_data.mbti, input_data.lang)
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
