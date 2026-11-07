# RAHBAR API image. Build context: api/  (docker build -t rahbar-api:<tag> api)
# Reads the index; never writes it (section 4.2). Runs as a non-root user with a
# read-only root filesystem (section 4.7); mount an emptyDir at /tmp in the Deployment.
FROM python:3.12-slim

RUN groupadd -r rahbar --gid=1000 \
    && useradd -r -g rahbar --uid=1000 --home-dir=/app --shell=/sbin/nologin rahbar

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ /app/app/

RUN chown -R rahbar:rahbar /app
USER rahbar

EXPOSE 8000

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
