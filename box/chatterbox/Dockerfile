# Optional Chatterbox TTS. The engine is MIT.
# Pinned so a fresh pip resolve does not pull a torch build that fails to install.
# This image does not install XTTS-v2, F5-TTS weights, or LivePortrait face models.
FROM python:3.11-slim-bookworm

WORKDIR /app
RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ffmpeg git libsndfile1 \
  && rm -rf /var/lib/apt/lists/*

# chatterbox-tts 0.1.1 pins torch==2.6.0 and does not pull spacy-pkuseg.
# The CUDA 12.4 wheel is installed first. The server uses CPU when the GPU is hidden.
RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124 \
  && pip install --no-cache-dir 'chatterbox-tts==0.1.1' fastapi 'uvicorn[standard]' --extra-index-url https://download.pytorch.org/whl/cu124

# Copied after the pip layers, so a server.py change does not re-download torch.
COPY box/chatterbox/server.py /app/server.py

ENV NVIDIA_VISIBLE_DEVICES=all
EXPOSE 8010
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
