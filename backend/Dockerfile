FROM python:3.11-slim

WORKDIR /backend

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create data dir for SQLite
RUN mkdir -p /data

EXPOSE 5000

ENV FLASK_ENV=production
ENV DATABASE_URL=sqlite:////data/stock.db

CMD ["python", "run.py"]
