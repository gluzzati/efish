FROM python:3.11-slim

# Install system dependencies including Docker CLI
RUN apt-get update && apt-get install -y \
    curl \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Install Tailscale CLI
RUN curl -fsSL https://tailscale.com/install.sh | sh

WORKDIR /app

# Copy requirements and install Python dependencies
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/*.py ./

# Create static directory for future use
RUN mkdir -p ./static

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"] 