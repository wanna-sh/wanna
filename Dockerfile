# syntax=docker/dockerfile:1
# wanna.sh in a container. See docs/start/docker on the website, or docker-compose.yml.
#
#   docker build -t wanna.sh .                       # everything
#   docker build -t wanna.sh:chat --build-arg WITH_ML=0 .   # chat and Code only, several GB smaller

# --- The interface (Next.js static export) --------------------------------------------------------------
FROM node:24-bookworm-slim AS ui
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# --- The app ----------------------------------------------------------------------------------------------
# Ubuntu 24.04: the prebuilt llama.cpp engine needs glibc 2.38 or newer. CUDA comes from the PyTorch wheels and
# from llama.cpp's own download; the NVIDIA Container Toolkit adds the driver when run with GPUs.
FROM ubuntu:24.04
ARG WITH_ML=1
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libgomp1 libssl3t64 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
# Only used when Code is turned on (docker-compose.code.yml), to start the sandbox and search containers.
COPY --from=docker:29.8.2-cli /usr/local/bin/docker /usr/local/bin/docker

ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app/backend
RUN uv venv --python 3.13 .venv

# Dependencies first, so code changes don't reinstall PyTorch.
COPY backend/pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$WITH_ML" = 1 ]; then uv pip install --python .venv/bin/python -r pyproject.toml --extra ml; \
    else uv pip install --python .venv/bin/python -r pyproject.toml; fi

COPY backend/ ./
RUN uv pip install --python .venv/bin/python --no-deps -e . && chmod -R a+rX /app /opt/python
COPY --from=ui /app/frontend/out /app/frontend/out
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/wanna-entrypoint

ENV PATH=/app/backend/.venv/bin:$PATH \
    WANNA_HOME=/data \
    WANNA_IN_DOCKER=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/data/cache \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

LABEL org.opencontainers.image.title="wanna.sh" \
      org.opencontainers.image.description="Run AI models on your own computer: chat, pictures, video, voices, transcription, music and code." \
      org.opencontainers.image.source="https://github.com/wanna-sh/wanna" \
      org.opencontainers.image.licenses="MIT"

EXPOSE 7860
VOLUME /data
ENTRYPOINT ["wanna-entrypoint"]
CMD ["wanna", "--host", "0.0.0.0", "--port", "7860"]
