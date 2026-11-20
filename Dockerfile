FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fontconfig \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY fonts fonts
RUN mkdir -p /usr/share/fonts/truetype/clipauto && cp fonts/*.ttf /usr/share/fonts/truetype/clipauto/ && fc-cache -f
COPY clipauto clipauto
COPY web web
COPY sfx sfx
ENV DATA_DIR=/app/data HF_HOME=/app/data/models PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "-m", "clipauto", "web", "--port", "8000"]
