FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# GPU용 compose 파일이 CUDA 휠 주소로 바꿈. sam2보다 먼저 설치해야 CUDA 휠이 끌려오지 않음
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install setuptools && pip install torch torchvision --index-url $TORCH_INDEX

# sam2는 설치 중에 torch를 import하므로 빌드 격리를 끔. CUDA 확장은 후처리용이라 빼도 동작함
COPY c3_sam2/requirements.txt /app/c3_sam2/requirements.txt
RUN SAM2_BUILD_CUDA=0 pip install --no-build-isolation -r /app/c3_sam2/requirements.txt

COPY common/ /app/common/
COPY c3_sam2/ /app/c3_sam2/

EXPOSE 8000
CMD ["uvicorn", "c3_sam2.main:app", "--host", "0.0.0.0", "--port", "8000"]
