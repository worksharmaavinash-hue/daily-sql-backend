FROM python:3.11-slim
RUN pip install pandas numpy --no-cache-dir
COPY entrypoint.py /entrypoint.py
RUN useradd -m runner
USER runner
CMD ["python", "/entrypoint.py"]
