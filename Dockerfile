# Use the official lightweight Python image.
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Run the app (adjust as needed for gunicorn, etc.)
CMD ["flask", "run", "--host=0.0.0.0", "--port=5004"]
