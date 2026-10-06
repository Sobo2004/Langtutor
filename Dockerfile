# LangTutor: FastAPI backend + static frontend in one small image.
#   docker build -t langtutor .
#   docker run -p 8000:8000 --env-file .env -v langtutor-data:/data langtutor
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANGTUTOR_DB=/data/app.db

WORKDIR /app

# Install dependencies first so this layer is cached when only the code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py course.json ./
COPY frontend ./frontend

# Run as a non-root user; the database lives on a volume so it survives restarts
RUN useradd --create-home appuser \
    && mkdir -p /data /app/tts_cache \
    && chown -R appuser /data /app/tts_cache
USER appuser

EXPOSE 8000
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/version')"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
