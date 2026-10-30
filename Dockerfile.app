FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir "fastapi>=0.110" "uvicorn>=0.29" "httpx>=0.27"
COPY demo_app ./demo_app
RUN useradd --create-home app && mkdir -p /logs && chown app /logs
USER app
ENV LOG_FILE=/logs/app.jsonl
EXPOSE 8000
CMD ["uvicorn", "demo_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
