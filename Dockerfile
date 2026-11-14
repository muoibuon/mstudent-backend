FROM python:3.12-slim

ARG VCS_REF=unknown
LABEL org.opencontainers.image.revision=$VCS_REF

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/tmp
WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install -r requirements.txt
COPY app ./app
COPY eval ./eval
COPY sample_data ./sample_data
COPY deploy/backup.py ./deploy/backup.py

USER 1000:1000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=4))['ok']"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
