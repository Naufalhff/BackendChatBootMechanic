# Gunakan image Python 3.11-slim sebagai base image yang ringan
FROM python:3.11-slim

# Set environment variables untuk Python & buffering log
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory di dalam container
WORKDIR /app

# Install dependensi sistem yang dibutuhkan untuk kompilasi psycopg2 (PostgreSQL adapter)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt dan install dependensi Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode program backend ke dalam container
COPY . .

# Expose port default (FastAPI)
EXPOSE 8000

# Jalankan Uvicorn dengan shell format agar variabel PORT dari GCP Cloud Run bisa dibaca dinamis
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
