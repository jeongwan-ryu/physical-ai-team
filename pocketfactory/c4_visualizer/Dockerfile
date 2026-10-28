FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY c4_visualizer/requirements.txt /app/c4_visualizer/requirements.txt
RUN pip install -r /app/c4_visualizer/requirements.txt

COPY common/ /app/common/
COPY c4_visualizer/ /app/c4_visualizer/

EXPOSE 8000
CMD ["uvicorn", "c4_visualizer.main:app", "--host", "0.0.0.0", "--port", "8000"]
