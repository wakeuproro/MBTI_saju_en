---
title: 사주 x MBTI 운명 분석
emoji: 🔮
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: 동양 명리학(사주) + 서양 성격유형(MBTI) AI 분석
---

# 사주 × MBTI 운명 분석

동양 명리학(사주)과 서양 성격유형(MBTI)을 결합한 AI 분석 서비스

## 기능

- 사주 팔자 자동 계산 (년/월/일/시주)
- 오행 밸런스 차트
- 일간 × MBTI 시너지 분석
- 인생 전환점 & 대운 흐름 (연령대별 카드)
- 풍수 인테리어 / 행운 악세사리 / 시그니처 향기 추천 (프리미엄)
- AI 기반 심층 사주 해석 (Gemini)

## 로컬 실행

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

`http://localhost:8000` 접속

## 환경 변수

- `GOOGLE_API_KEY`: Gemini API 키 (선택, AI 심층 분석용)

## 배포

- **Hugging Face Spaces**: Docker SDK, README 프론트매터 자동 인식
- **Railway / Render**: `Procfile` + `requirements.txt` 사용
