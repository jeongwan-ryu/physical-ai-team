FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OpenCV(libgl1, libglib2.0-0)와 Paddle(libgomp1)이 필요로 하는 시스템 라이브러리
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CUDA가 포함된 torch(수 GB)를 피하려고 CPU 전용 torch를 먼저 설치
RUN pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY worker/requirements.txt /app/worker/requirements.txt
RUN pip install -r /app/worker/requirements.txt

COPY shared/ /app/shared/
COPY demo/ /app/demo/
COPY worker/ /app/worker/

CMD ["python", "-m", "worker.worker"]
