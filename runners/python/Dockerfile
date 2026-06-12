FROM python:3.11-slim
RUN pip install pandas numpy fastapi uvicorn --no-cache-dir
COPY server.py /server.py
COPY entrypoint.py /entrypoint.py
RUN useradd -m runner
USER runner
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "5001"]
