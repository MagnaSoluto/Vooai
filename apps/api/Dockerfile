FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api/app ./app
COPY data/gold/sample ./app/sample
ENV VOOAI_GOLD_DIR=/data/gold
ENV VOOAI_GOLD_SAMPLE=/app/app/sample
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
