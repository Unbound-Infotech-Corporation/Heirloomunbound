# Optional Chatterbox TTS. The engine is MIT.
# This image does not install XTTS-v2, F5-TTS weights, or LivePortrait face models.
FROM python:3.11-slim-bookworm

WORKDIR /app
COPY box/chatterbox/server.py /app/server.py
RUN pip install --no-cache-dir fastapi uvicorn chatterbox-tts

EXPOSE 8010
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
