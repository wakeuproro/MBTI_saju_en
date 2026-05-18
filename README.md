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

`.env` 파일 생성:

```
GOOGLE_API_KEY=your_gemini_api_key_here
```

## 배포

Railway / Render 등 PaaS에 GitHub 연동하여 자동 배포.

`PORT` 환경변수는 플랫폼에서 자동 제공.
