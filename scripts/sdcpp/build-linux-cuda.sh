#!/usr/bin/env bash
# Builds stable-diffusion.cpp's library for Linux with CUDA, the way its own Windows CUDA release is built (same
# CUDA version and graphics card generations), for wanna.sh to download instead of building on each computer.
# Runs inside nvidia/cuda:12.8.1-devel-ubuntu22.04 (glibc 2.35: Ubuntu 22.04+, Debian 12+).
#
#   build-linux-cuda.sh <commit> <output folder>
#
# The output folder gets the library, ggml and its plugins (CUDA, and the processor variants), side by side.
# NVIDIA's CUDA runtime and cuBLAS aren't included: wanna.sh downloads them from NVIDIA's packages on PyPI.
set -euo pipefail

commit="$1"
out="$2"
# GTX 10 series (61) to RTX 50 series (120). The same list as stable-diffusion.cpp's Windows cuda12 release.
# SDCPP_CUDA_ARCHS overrides it for a quicker local test build (e.g. "86"); published builds use the full list.
archs="${SDCPP_CUDA_ARCHS:-61;70;75;80;86;89;90;100;120}"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends git ccache cmake ca-certificates > /dev/null

src=/tmp/sdcpp-src
git clone --quiet --filter=blob:none https://github.com/leejet/stable-diffusion.cpp.git "$src"
git -C "$src" checkout --quiet "$commit"
git -C "$src" submodule update --quiet --init --recursive

# GGML_CUDA_NCCL=OFF: the CUDA image has NCCL, which ggml links when it finds it, but people's computers don't have it
# (Windows builds go without it too). It only speeds up splitting one model across several cards.
cmake -S "$src" -B "$src/build" -DCMAKE_BUILD_TYPE=Release \
  -DSD_CUDA=ON -DSD_BUILD_SHARED_LIBS=ON -DSD_BUILD_SHARED_GGML_LIB=ON -DSD_BUILD_EXAMPLES=OFF \
  -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON -DGGML_CUDA_NCCL=OFF \
  -DCMAKE_CUDA_ARCHITECTURES="$archs" \
  -DCMAKE_CUDA_FLAGS='-Xcudafe "--diag_suppress=177" -Xcudafe "--diag_suppress=550"' \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DCMAKE_CUDA_COMPILER_LAUNCHER=ccache
cmake --build "$src/build" --config Release -j "$(nproc)"

mkdir -p "$out"
# Every shared library the build made, under each of its names (as real files: the download is unpacked flat).
find "$src/build" -name '*.so*' \( -type f -o -type l \) -print0 | while IFS= read -r -d '' f; do
  cp -L "$f" "$out/$(basename "$f")"
done
test -f "$out/libstable-diffusion.so"
ls "$out"/libggml-cuda*.so > /dev/null
echo "$commit" > "$out/commit.txt"
ls -la "$out"
