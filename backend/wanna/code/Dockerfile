# The sandbox Code projects run their commands in: Node 24 + Python 3 + git + common build tools.
# Commands run as the host user, so HOME must be writable for any uid.
FROM node:24-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip python3-venv python-is-python3 ripgrep less \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /home/wanna && chmod 1777 /home/wanna
ENV HOME=/home/wanna \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    npm_config_cache=/home/wanna/.npm \
    PYTHONUNBUFFERED=1
WORKDIR /workspace
CMD ["sleep", "infinity"]
