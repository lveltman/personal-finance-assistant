FROM python:3.11-slim

WORKDIR /app

# System deps for pandas/openpyxl
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create sessions directory
RUN mkdir -p /app/data/sessions

CMD ["python", "-m", "src.bot.main"]
