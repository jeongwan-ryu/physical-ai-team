FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# CUDA가 포함된 torch(수 GB)를 피하려고 CPU 전용 torch를 먼저 설치
RUN pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

COPY rag/requirements.txt /app/rag/requirements.txt
RUN pip install -r /app/rag/requirements.txt

COPY shared/ /app/shared/
COPY demo/ /app/demo/
COPY rag/ /app/rag/

CMD ["uvicorn", "rag.main:app", "--host", "0.0.0.0", "--port", "8001"]
