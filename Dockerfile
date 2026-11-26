FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-captions.txt ./
RUN pip install --no-cache-dir -r requirements-captions.txt
COPY . .
RUN useradd --create-home --uid 10001 clip && mkdir /data && chown clip:clip /data
USER clip
ENV HF_HOME=/data/models
WORKDIR /data
ENTRYPOINT ["python","/app/supervisor.py"]
CMD ["--daily","30"]
