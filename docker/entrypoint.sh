#!/bin/sh
# Checks that catch the usual Docker setup mistakes with a clear message, then starts wanna.sh.
set -e

if ! mkdir -p "$WANNA_HOME" 2>/dev/null || [ ! -w "$WANNA_HOME" ]; then
  echo "wanna.sh can't write to its data folder ($WANNA_HOME) as user $(id -u):$(id -g)." >&2
  echo "Create the folder on the host before starting (mkdir -p ~/.wanna), and make sure WANNA_UID and" >&2
  echo "WANNA_GID match its owner (id -u, id -g)." >&2
  exit 1
fi

if [ -n "$WANNA_DOCKER_NETWORK" ]; then
  if ! docker version >/dev/null 2>&1; then
    echo "Code is turned on, but wanna.sh can't use Docker through /var/run/docker.sock." >&2
    echo "Check the socket is mounted and DOCKER_GID is its group (stat -c %g /var/run/docker.sock)." >&2
    echo "Starting anyway; Code and its web search won't work until this is fixed." >&2
  fi
  if [ -z "$WANNA_HOST_HOME" ]; then
    echo "WANNA_HOST_HOME isn't set, so Code's sandbox can't find project folders. See docker-compose.code.yml." >&2
  fi
fi

exec "$@"
