FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# GPU용 compose 파일이 CUDA 휠 주소로 바꿈. torch를 넣을 때 아래 줄을 살린다
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
# RUN pip install torch torchvision --index-url $TORCH_INDEX

COPY c3_sam2/requirements.txt /app/c3_sam2/requirements.txt
RUN pip install -r /app/c3_sam2/requirements.txt

COPY common/ /app/common/
COPY c3_sam2/ /app/c3_sam2/

EXPOSE 8000
CMD ["uvicorn", "c3_sam2.main:app", "--host", "0.0.0.0", "--port", "8000"]
