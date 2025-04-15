# Dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install git+https://github.com/openai/whisper.git

COPY . .

CMD ["python", "main.py"]
