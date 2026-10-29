#!/usr/bin/env bash
# Install or update wanna.sh on Linux, macOS or Windows (inside WSL2).
#
#   curl -fsSL https://raw.githubusercontent.com/wanna-sh/wanna/main/install.sh | bash
#
# Or, from a copy of the repository:  ./install.sh
#
# Options:
#   --dir PATH   where to put wanna.sh (default: ~/wanna.sh)
#   --chat-only  skip the AI libraries for pictures, video, voices and music (saves several GB)
#   --help       show this help
#
# Environment overrides: WANNA_DIR, WANNA_REPO, WANNA_BRANCH (a branch, or a version such as v0.1.0), WANNA_BIN_DIR.
# Running it again updates an existing install.

set -euo pipefail

REPO="${WANNA_REPO:-https://github.com/wanna-sh/wanna.git}"
BRANCH="${WANNA_BRANCH:-main}"
DIR="${WANNA_DIR:-$HOME/wanna.sh}"
BIN_DIR="${WANNA_BIN_DIR:-$HOME/.local/bin}"
PYTHON_VERSION="3.13"
NODE_MIN="20.9.0"  # what the Next.js version the UI uses needs
WITH_ML=1

bold=$'\033[1m'; dim=$'\033[2m'; red=$'\033[31m'; green=$'\033[32m'; yellow=$'\033[33m'; reset=$'\033[0m'
if [ ! -t 1 ]; then bold=""; dim=""; red=""; green=""; yellow=""; reset=""; fi

step() { printf '\n%s==>%s %s%s%s\n' "$green" "$reset" "$bold" "$*" "$reset"; }
note() { printf '    %s\n' "$*"; }
warn() { printf '%s    ! %s%s\n' "$yellow" "$*" "$reset"; }
fail() { printf '\n%sError:%s %s\n' "$red" "$reset" "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) [ $# -ge 2 ] || fail "--dir needs a path"; DIR="$2"; shift 2 ;;
    --dir=*) DIR="${1#--dir=}"; shift ;;
    --chat-only) WITH_ML=0; shift ;;
    -h|--help) sed -n '2,15p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "Unknown option: $1 (try --help)" ;;
  esac
done

# Version a >= version b, for dotted numbers like 20.9.0.
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

# --- 1. Check this computer ------------------------------------------------------------------------------

step "Checking this computer"
case "$(uname -s)" in
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then note "Windows (WSL2)"; else note "Linux"; fi ;;
  Darwin)
    if [ "$(uname -m)" = x86_64 ]; then
      note "macOS (Intel). PyTorch isn't made for Intel Macs any more, so this installs chat and Code only."
      WITH_ML=0
    else
      note "macOS"
    fi ;;
  *) fail "This installer runs on Linux, macOS or Windows inside WSL2. On Windows, open a WSL terminal and run it there." ;;
esac

for cmd in git curl; do
  command -v "$cmd" >/dev/null || fail "$cmd is needed. Install it with your package manager and run this again."
done

if ! command -v node >/dev/null || ! command -v npm >/dev/null; then
  fail "Node.js $NODE_MIN or newer is needed to build the app's interface. Get it from https://nodejs.org (or with nvm) and run this again."
fi
NODE_VERSION="$(node -p 'process.versions.node')"
version_ge "$NODE_VERSION" "$NODE_MIN" || fail "Node.js $NODE_VERSION is too old; $NODE_MIN or newer is needed. Update it from https://nodejs.org and run this again."
note "Node.js $NODE_VERSION"

if ! command -v uv >/dev/null; then
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [ -x "$candidate" ] && PATH="$(dirname "$candidate"):$PATH" && break
  done
fi
if ! command -v uv >/dev/null; then
  step "Installing uv (sets up Python for wanna.sh)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null || fail "uv didn't install. See https://docs.astral.sh/uv/ and run this again."
fi
note "$(uv --version)"

if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | while read -r gpu; do note "Graphics card: $gpu"; done
else
  warn "No NVIDIA graphics card found. wanna.sh still works, but models run on the processor and are much slower."
fi

# --- 2. Get the code --------------------------------------------------------------------------------------

# Run from inside a copy of the repository? Use that copy instead of cloning.
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/backend/pyproject.toml" ] && [ -z "${WANNA_DIR:-}" ]; then
  DIR="$SCRIPT_DIR"
  step "Using the copy of wanna.sh in $DIR"
elif [ -d "$DIR/.git" ] && [ -n "${WANNA_BRANCH:-}" ]; then
  # A specific version (a tag such as v0.1.0) or branch was asked for: switch to it.
  step "Switching wanna.sh in $DIR to $BRANCH"
  if git -C "$DIR" ls-remote --exit-code --heads origin "$BRANCH" >/dev/null 2>&1; then
    # A branch: follow it, so running the installer again keeps it up to date.
    switched=$(git -C "$DIR" fetch --quiet --depth 1 origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" \
      && git -C "$DIR" checkout --quiet -B "$BRANCH" "origin/$BRANCH" && echo yes)
  else
    # A version tag: stay on exactly that version.
    switched=$(git -C "$DIR" fetch --quiet --depth 1 origin "+refs/tags/$BRANCH:refs/tags/$BRANCH" \
      && git -C "$DIR" checkout --quiet "refs/tags/$BRANCH" && echo yes)
  fi
  [ "$switched" = yes ] || fail "Couldn't switch $DIR to $BRANCH. Check the version exists, and commit or undo any changes there."
elif [ -d "$DIR/.git" ]; then
  step "Updating wanna.sh in $DIR"
  git -C "$DIR" pull --ff-only \
    || fail "Couldn't update $DIR. If you changed files there, commit or undo them first. If you installed a specific version, run this again with WANNA_BRANCH=main (or another version)."
elif [ -e "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null)" ]; then
  fail "$DIR already exists and isn't a wanna.sh install. Choose another place with --dir."
else
  step "Downloading wanna.sh to $DIR"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi

# --- 3. The app (Python) ------------------------------------------------------------------------------------

step "Setting up the app"
cd "$DIR/backend"
[ -x .venv/bin/python ] || uv venv --python "$PYTHON_VERSION" .venv
if [ "$WITH_ML" = 1 ]; then
  note "Installing the AI libraries for pictures, video, voices and music. The first time this downloads several GB."
  uv pip install --python .venv/bin/python -e ".[ml]"
else
  note "Chat only: skipping the AI libraries for pictures, video, voices and music (run without --chat-only to add them)."
  uv pip install --python .venv/bin/python -e .
fi

# --- 4. The interface (Node.js) -----------------------------------------------------------------------------

step "Building the interface"
cd "$DIR/frontend"
npm ci --no-fund --no-audit --loglevel=error
npm run build --silent >/dev/null
[ -f out/index.html ] || fail "The interface didn't build. Run 'npm run build' in $DIR/frontend to see why."

# --- 5. The wanna command -----------------------------------------------------------------------------------

step "Adding the wanna command"
mkdir -p "$BIN_DIR"
ln -sf "$DIR/backend/.venv/bin/wanna" "$BIN_DIR/wanna"
note "$BIN_DIR/wanna"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR isn't on your PATH yet. Add this line to ~/.bashrc or ~/.zshrc, then open a new terminal:"
     note "export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac

if ! command -v docker >/dev/null || ! docker version >/dev/null 2>&1; then
  warn "Docker isn't running. Everything works without it except Code, which runs commands inside Docker."
fi

printf '\n%swanna.sh is installed.%s\n\n' "$bold" "$reset"
printf '  Start it:   %swanna%s\n' "$bold" "$reset"
printf '  Then open:  %shttp://localhost:7860%s\n\n' "$bold" "$reset"
printf '%s  Run this installer again any time to update.%s\n' "$dim" "$reset"
