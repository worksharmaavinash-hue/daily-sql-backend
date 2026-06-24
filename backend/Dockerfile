# Stage 1: pull the docker CLI binary
FROM docker:cli AS docker-cli

# Stage 2: main API image
FROM python:3.11-slim

WORKDIR /app

# Copy docker CLI binary from the docker:cli image
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
