FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render and Railway inject PORT. One container runs the API and the intake
# loop so they share state/ (SQLite, quote JSON, Telegram offset).
CMD ["sh", "-c", "python automate.py & exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
