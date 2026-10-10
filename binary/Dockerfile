# 파이썬 경량 베이스 이미지 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 파이썬 의존성 설치 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY main.py .

# Gunicorn 웹 서버를 사용하여 Flask 앱 실행 (Cloud Run 표준)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
