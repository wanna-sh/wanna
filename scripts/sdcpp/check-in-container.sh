#!/usr/bin/env bash
# Runs check-linux-build.py inside nvidia/cuda:12.8.1-devel-ubuntu22.04, the image the build is made in:
# - Ubuntu 22.04 is the oldest system the build is for, so its dependencies are checked there;
# - the image has NVIDIA's driver stub, which loading the library needs on a computer without a graphics driver.
#
#   check-in-container.sh <build folder> <commit>      (paths inside the container)
set -euo pipefail

build="$1"
commit="$2"
here="$(cd "$(dirname "$0")" && pwd)"

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 ca-certificates > /dev/null

stub=/tmp/driver-stub
mkdir -p "$stub"
ln -sf /usr/local/cuda/lib64/stubs/libcuda.so "$stub/libcuda.so.1"
SDCPP_DRIVER_STUB="$stub" python3 "$here/check-linux-build.py" "$build" "$commit"
