FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host ${AUDIT_HOST:-0.0.0.0} --port ${AUDIT_PORT:-8080}"]
