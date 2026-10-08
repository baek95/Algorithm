# 경량화된 파이썬 3.11 슬림 이미지 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 파이썬 버퍼링 해제 (로그 실시간 출력)
ENV PYTHONUNBUFFERED=1

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# Cloud Run에서 사용할 멀티프로세스 WSGI 서버 Gunicorn 실행
# PORT 환경변수는 Cloud Run에서 자동 주입됨
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app
