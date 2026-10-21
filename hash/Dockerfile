# =====================================================================
#  해시 검색 서버 - Google Cloud Run 배포용 Dockerfile
# =====================================================================
# 가벼운 공식 Python 이미지 사용
FROM python:3.12-slim

# 파이썬 로그가 버퍼링 없이 바로 출력되도록 (Cloud Run 로그에서 확인 용이)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 의존성 먼저 설치 → 소스만 바뀔 때 도커 캐시 재사용
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY . .

# Cloud Run 은 PORT 환경변수(기본 8080)로 요청을 전달한다.
ENV PORT=8080

# gunicorn 실행
#  --workers 1 : 해시 테이블이 프로세스 메모리에 있으므로 워커는 반드시 1개
#  --threads 8 : 동시 요청은 스레드로 처리 (서버 코드에서 Lock 으로 보호)
#  --timeout 0 : Cloud Run 이 자체적으로 요청 타임아웃을 관리
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 main:app

# ---------------------------------------------------------------------
# 배포 예시 (Cloud Shell 또는 gcloud CLI, 이 파일이 있는 폴더에서):
#
#   gcloud run deploy hash-search \
#       --source . \
#       --region asia-northeast3 \
#       --allow-unauthenticated \
#       --max-instances 1
#
#   (선택) CORS 허용 출처 제한:
#       --set-env-vars ALLOWED_ORIGINS=https://script.google.com
# ---------------------------------------------------------------------
