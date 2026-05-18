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

load_dotenv()

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

class PremiumReportInput(BaseModel):
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False

class PaidPremiumInput(BaseModel):
    # 분석에 필요한 입력
    birth_date: str
    birth_time: str
    mbti: str
    lang: str = 'ko'
    name: str = ''
    gender: str = 'F'
    time_unknown: bool = False
    # 토스 결제 정보
    paymentKey: str
    orderId: str
    amount: int

@app.post("/get-report")
async def get_report(input_data: ReportInput):
    try:
        report = await get_report_analysis(input_data.birth_date, input_data.birth_time, input_data.mbti, input_data.lang)
        return report
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

def _build_premium_payload(birth_date: str, birth_time: str, mbti: str):
    """프리미엄 분석 콘텐츠 생성 (라이프스타일 + Gemini 심층)"""
    year, month, day = map(int, birth_date.split('-'))
    hour = int(birth_time.split(':')[0])

    year_p = calc_year_pillar(year)
    month_p = calc_month_pillar(year, month)
    day_p = calc_day_pillar(year, month, day)
    time_p = calc_time_pillar(day_p[0], hour)

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
        return _build_premium_payload(input_data.birth_date, input_data.birth_time, input_data.mbti)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/confirm-and-get-premium")
async def confirm_and_get_premium(data: PaidPremiumInput):
    """토스 결제 검증 → 통과 시 프리미엄 콘텐츠 반환"""
    # 1) 금액 사전 검증 (위/변조 방어)
    if data.amount != TOSS_PREMIUM_AMOUNT:
        raise HTTPException(status_code=400, detail=f"잘못된 결제 금액입니다. (요청: {data.amount}원, 정가: {TOSS_PREMIUM_AMOUNT}원)")

    # 2) 토스페이먼츠 결제 승인 호출
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
                    "paymentKey": data.paymentKey,
                    "orderId": data.orderId,
                    "amount": data.amount,
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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"결제 검증 중 오류: {str(e)[:200]}")

    # 3) 검증 통과 → 프리미엄 콘텐츠 생성
    try:
        payload = _build_premium_payload(data.birth_date, data.birth_time, data.mbti)
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
