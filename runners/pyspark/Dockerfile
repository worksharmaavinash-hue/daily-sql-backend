FROM python:3.11-slim
# Install Java required for Spark and clean up apt cache
RUN apt-get update && apt-get install -y default-jre-headless --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN pip install pyspark pandas --no-cache-dir
COPY entrypoint.py /entrypoint.py
RUN useradd -m runner
USER runner
CMD ["python", "/entrypoint.py"]
