FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY c2_preprocess/requirements.txt /app/c2_preprocess/requirements.txt
RUN pip install -r /app/c2_preprocess/requirements.txt

COPY common/ /app/common/
COPY c2_preprocess/ /app/c2_preprocess/

EXPOSE 8000
CMD ["uvicorn", "c2_preprocess.main:app", "--host", "0.0.0.0", "--port", "8000"]
