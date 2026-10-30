FROM python:3.12-slim
RUN pip install --no-cache-dir paho-mqtt==2.1.0
WORKDIR /app
COPY *.py .
CMD ["python", "-u", "app.py"]
