FROM python:3.11-slim

WORKDIR /app

# 시스템 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 의존성 먼저 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY . .

# 포트 (Railway: $PORT 환경변수, HF Spaces: 7860)
EXPOSE ${PORT:-7860}

# 실행 — Railway는 $PORT를 동적 할당하므로 shell form 사용
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}
