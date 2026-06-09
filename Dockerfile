FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Create data directory for SQLite
RUN mkdir -p backend/data

EXPOSE 5000

CMD ["python", "wsgi.py"]
