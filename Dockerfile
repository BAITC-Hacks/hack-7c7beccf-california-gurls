FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# пайплайн пересчитывается при каждом старте (≈15 с), затем поднимается API + фронтенд
CMD python run.py && uvicorn api.main:app --host 0.0.0.0 --port 8000
