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
RUN chmod +x /app/docker-entrypoint.sh

# Run the web app and the AI worker in one container.
CMD ["/app/docker-entrypoint.sh"]
