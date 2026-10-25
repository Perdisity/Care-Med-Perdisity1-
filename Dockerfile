FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN apt-get update && apt-get install -y default-mysql-client

COPY . .

# Strip Windows CRLF line endings from the entrypoint and make it executable.
# dos2unix is the clean way; sed -i 's/\r//' is the fallback.
RUN apt-get update && apt-get install -y --no-install-recommends dos2unix \
    && dos2unix entrypoint.sh \
    && chmod +x entrypoint.sh \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 5000

# entrypoint.sh: waits for MySQL, creates/upgrades schema, then starts gunicorn
CMD ["sh", "entrypoint.sh"]