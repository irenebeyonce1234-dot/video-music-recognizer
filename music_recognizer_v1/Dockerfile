FROM python:3.9-slim

# Install system dependencies (ffmpeg is required for audio processing)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose the port
EXPOSE 8000

# Run the application using Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "120", "webapp.app:app"]
