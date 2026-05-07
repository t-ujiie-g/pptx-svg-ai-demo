FROM python:3.13-slim

WORKDIR /app

# Install system dependencies:
# - curl: health checks + node setup script
# - Node.js: PptxGenJS / pptx-svg
# - fonts-noto-cjk: Japanese font glyphs for sharp/librsvg PNG rendering.
#   Without this, pptx_inspect.js produces tofu (□) for Japanese text and
#   the Critic LLM cannot evaluate content.
# - fontconfig: keeps the font cache fresh (sharp uses librsvg → fontconfig)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fontconfig \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Install PptxGenJS and icon rendering dependencies globally
RUN npm install -g pptxgenjs react react-dom react-icons sharp pptx-svg jsdom

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
