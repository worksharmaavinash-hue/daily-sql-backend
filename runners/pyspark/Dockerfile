FROM python:3.11-slim
# Install Java required for Spark and clean up apt cache
RUN apt-get update && apt-get install -y default-jre-headless --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN pip install pyspark pandas fastapi uvicorn --no-cache-dir
COPY server.py /server.py
RUN useradd -m runner
USER runner
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5002"]
