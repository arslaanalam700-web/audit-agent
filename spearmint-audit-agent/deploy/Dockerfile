FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY engine ./engine
COPY mcp_server ./mcp_server

ENV AUDIT_HOST=0.0.0.0
ENV AUDIT_PORT=8800
ENV PYTHONUNBUFFERED=1

EXPOSE 8800

CMD ["python", "-m", "mcp_server.server"]
