# syntax=docker/dockerfile:1
ARG DESKTOP_IMAGE=ghcr.io/linuxserver/baseimage-selkies:debiantrixie@sha256:5b3f10459933740554081efbca9c8d5e006faf5116b54ab40b7bfad7c8111849
FROM python:3.10-slim-trixie@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d AS python-runtime
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS node-runtime
FROM ${DESKTOP_IMAGE}
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
LABEL org.opencontainers.image.title="2ByteASR Docker" \
      org.opencontainers.image.version="0.8.1-docker.1" \
      org.opencontainers.image.source="https://github.com/NOTBAD314/2ByteASR" \
      io.2byteasr.base-revision="83f928c1aa445fd17312ffbfb30c88cf5d5027b1" \
      org.opencontainers.image.licenses="GPL-3.0-only"
ENV TITLE="兔白字幕 0.8.1" \
    PIXELFLUX_WAYLAND=false \
    SELKIES_MANUAL_WIDTH=1600 \
    SELKIES_MANUAL_HEIGHT=900 \
    NO_GAMEPAD=true \
    NO_STEAM=true \
    START_DOCKER=false \
    DISABLE_SUDO=true \
    TWOBYTEASR_CONTAINER=1 \
    TWOBYTEASR_MAIN_PYTHON=/opt/venv/bin/python \
    TWOBYTEASR_RENDERER_CHROME=/usr/bin/chromium \
    QT_QPA_PLATFORM=xcb \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PATH="/opt/venv/bin:/opt/node/bin:${PATH}"
COPY --from=python-runtime /usr/local/ /usr/local/
COPY --from=node-runtime /usr/local/ /opt/node/
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg mpv chromium libsndfile1 libxcb-cursor0 libxkbcommon-x11-0 \
    libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 \
    libegl1 libopengl0 fonts-noto-cjk fonts-noto-core fonts-noto-color-emoji \
    espeak-ng xdotool && rm -rf /var/lib/apt/lists/*
COPY packaging/docker/requirements.txt /tmp/2byteasr-requirements.txt
COPY packaging/docker/constraints.txt /tmp/2byteasr-constraints.txt
RUN /usr/local/bin/python3 -m venv /opt/venv && \
    /opt/venv/bin/python -m pip install --no-cache-dir torch==2.11.0 torchaudio==2.11.0 --index-url ${TORCH_INDEX} --extra-index-url https://pypi.org/simple -c /tmp/2byteasr-constraints.txt && \
    /opt/venv/bin/python -m pip install --no-cache-dir -r /tmp/2byteasr-requirements.txt -c /tmp/2byteasr-constraints.txt && \
    /opt/venv/bin/python -m pip check
WORKDIR /app
COPY . /app/
RUN cd renderer && npm ci --no-audit --no-fund && npm cache clean --force
RUN mkdir -p /app/tools/ffmpeg/bin /app/tools/mpv /models /media && \
    ln -s /usr/bin/ffmpeg /app/tools/ffmpeg/bin/ffmpeg && \
    ln -s /usr/bin/ffprobe /app/tools/ffmpeg/bin/ffprobe && \
    ln -s /usr/bin/mpv /app/tools/mpv/mpv && \
    ln -s /opt/venv /app/.venv-main && \
    chmod +x /app/packaging/docker/root/defaults/autostart && \
    chown -R abc:abc /app /models /media
COPY packaging/docker/root/ /
RUN chmod +x /defaults/autostart /custom-cont-init.d/50-2byteasr
ARG VCS_REF=docker-local
RUN VCS_REF=$VCS_REF /opt/venv/bin/python /app/packaging/docker/build_metadata.py
LABEL org.opencontainers.image.revision=$VCS_REF
EXPOSE 3000
VOLUME ["/config", "/models", "/media"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD /opt/venv/bin/python /app/packaging/docker/healthcheck.py
