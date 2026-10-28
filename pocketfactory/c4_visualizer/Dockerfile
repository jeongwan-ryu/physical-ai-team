FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 마킹 이미지의 한글 텍스트용 폰트
RUN apt-get update && apt-get install -y --no-install-recommends fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

COPY c4_visualizer/requirements.txt /app/c4_visualizer/requirements.txt
RUN pip install -r /app/c4_visualizer/requirements.txt

COPY common/ /app/common/
COPY c4_visualizer/ /app/c4_visualizer/

EXPOSE 8000
CMD ["uvicorn", "c4_visualizer.main:app", "--host", "0.0.0.0", "--port", "8000"]
