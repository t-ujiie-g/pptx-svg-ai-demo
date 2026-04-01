FROM python:3.13-slim

WORKDIR /app

# Install system dependencies (curl for health checks, Node.js for PptxGenJS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install PptxGenJS and icon rendering dependencies globally
RUN npm install -g pptxgenjs react react-dom react-icons sharp

# Copy project files
COPY pyproject.toml ./
COPY src ./src
COPY skills ./skills

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
