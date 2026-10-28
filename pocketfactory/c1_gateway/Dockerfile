FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY c1_gateway/requirements.txt /app/c1_gateway/requirements.txt
RUN pip install -r /app/c1_gateway/requirements.txt

COPY common/ /app/common/
COPY c1_gateway/ /app/c1_gateway/

EXPOSE 8000
CMD ["uvicorn", "c1_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
