FROM node:22-alpine AS web
WORKDIR /w
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
# Links the GHCR package to this repo so the Actions token may push it.
LABEL org.opencontainers.image.source="https://github.com/Ugur22/lumio"
# The root filesystem is read-only at runtime: no .pyc files, and HOME must exist for libraries that call Path.home().
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY app/ app/
COPY --from=web /w/dist frontend/dist
# docker-compose.yml overrides this with the host's lumio UID/GID so the existing 0600 files in /var/lib/lumio stay readable.
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
