---
title: Graphics card for GGUF picture models on Linux and WSL
description: Install the CUDA toolkit, cmake and git so wanna.sh can build its picture engine for your NVIDIA card.
---

GGUF picture models, such as Qwen-Image 2.1 and Qwen-Image-Edit, run on stable-diffusion.cpp. On **Linux and WSL**
there's no ready-made version of it for NVIDIA cards, so wanna.sh builds one for your card. To do that it needs four
tools: the **CUDA toolkit**, **cmake**, **git** and a **C++ compiler**. Until they're installed, these models run on
the processor, which is very slow.

You only do this once. It takes about 10 minutes to install the tools, then wanna.sh spends 10 to 20 minutes building
the engine the next time you use one of these models.

:::note[Who needs this]
Only Linux and WSL with an NVIDIA graphics card. **Windows** and **Mac** need nothing: wanna.sh downloads a
ready-made engine for them. Other picture models (Stable Diffusion, SDXL, FLUX in diffusers format) don't use this
engine and already use your graphics card.
:::

## Do I need this?

You do if either of these is true:

- The **Pictures** page shows a notice starting *Pictures from this kind of model are made on the processor*.
- **Settings → This computer → Picture engine** ends with **cpu (no CUDA build tools)**.

When it's working, the picture engine shows **cuda (built here)**.

## Step 1: Open a terminal in the right place

Run every command below in the system **wanna.sh runs in**:

- **Linux:** a normal terminal.
- **WSL:** a WSL terminal. In Windows, open **Terminal** and type `wsl` (or `wsl -d Debian`, using the name of the
  distribution wanna.sh is installed in; `wsl -l -v` lists them). Installing the CUDA toolkit on Windows itself does
  not help.

## Step 2: Find your driver's CUDA version

```bash
nvidia-smi
```

Look at the top right of the table for **CUDA Version** (newer drivers say **CUDA UMD Version**), for example `13.3`.
This is the newest CUDA toolkit your driver can run. Write it with a dash: `13.3` becomes `13-3`.

If `nvidia-smi` isn't found, install or update your NVIDIA driver first. In WSL, update the driver on **Windows**:
WSL uses the Windows driver.

## Step 3: Find your system's NVIDIA repository

```bash
grep -E '^(ID|VERSION_ID)=' /etc/os-release
```

Pick the repository name for your system:

| Your system | Repository name | Newest toolkit available |
| --- | --- | --- |
| Ubuntu 24.04 in **WSL** | `wsl-ubuntu` | 13-3 |
| Ubuntu 22.04 in **WSL** | `wsl-ubuntu` | 13-3 |
| Ubuntu 24.04 | `ubuntu2404` | 13-4 |
| Ubuntu 22.04 | `ubuntu2204` | 13-4 |
| Debian 13, also in WSL | `debian13` | 13-4 |
| Debian 12, also in WSL | `debian12` | 13-4 |

Choose the toolkit version: the **CUDA version from step 2**, or the newest one in the table if that's lower. For
example, a driver showing `13.3` on Debian 13 uses `cuda-toolkit-13-3`.

## Step 4: Install the tools

Replace `REPO` with the repository name and `X-Y` with the toolkit version, then run these lines one at a time. The
`sudo` lines ask for your password.

```bash
cd /tmp
wget https://developer.download.nvidia.com/compute/cuda/repos/REPO/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda-toolkit-X-Y build-essential cmake git
```

For example, Debian 13 in WSL with a driver showing CUDA 13.3:

```bash
cd /tmp
wget https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda-toolkit-13-3 build-essential cmake git
```

:::caution[In WSL, install the toolkit only]
Install `cuda-toolkit-X-Y` and nothing else from NVIDIA. **Never** install `cuda`, `cuda-drivers` or any
`nvidia-driver` package in WSL: they replace the link to the Windows driver and your graphics card stops working in
WSL.
:::

The toolkit is a few gigabytes. You don't need to change your `PATH`: wanna.sh looks for it in `/usr/local/cuda*`.

## Step 5: Check

```bash
ls /usr/local/cuda*/bin/nvcc
cmake --version
git --version
g++ --version
```

Each line should print a path or a version. If one says *not found* or *No such file*, that tool didn't install:
run its part of step 4 again.

## Step 6: Let wanna.sh build the engine

You don't need to restart wanna.sh. Open **Pictures**, choose a GGUF picture model and make a picture. wanna.sh sees
the tools and builds the engine for your card:

- **My models** shows *Setting up the picture engine* with its progress. It takes 10 to 20 minutes, once.
- Your picture request says the engine is still being set up. Try again when the build has finished.
- **Settings → This computer → Picture engine** then shows **cuda (built here)**, and pictures use your card.

## If something goes wrong

**The picture engine still says "no CUDA build tools".**
wanna.sh can't see one of the tools. Run step 5 again in the same system wanna.sh runs in. In WSL, check you installed
them in the distribution wanna.sh uses (`wsl -l -v`), not another one or Windows.

**"The picture engine couldn't be set up: Building the picture engine failed".**
The message ends with the last lines of the build. Two common causes:

- *unsupported GNU version*: your C++ compiler is newer than the toolkit supports. Install the newest toolkit your
  driver allows (step 2 and the table above).
- *No space left on device*: the build needs a few gigabytes free in your home folder.

After fixing it, use the model again: wanna.sh tries the build again.

**My graphics card stopped working in WSL.**
A driver package was installed in WSL. Remove it (`sudo apt-get remove --purge 'nvidia-driver*' cuda-drivers`),
then restart WSL from Windows with `wsl --shutdown`.

**Other Linux distributions (Fedora, Arch and others).**
Install the CUDA toolkit from [NVIDIA's download page](https://developer.nvidia.com/cuda-downloads) or your
distribution's packages, plus cmake, git and a C++ compiler (g++). wanna.sh finds `nvcc` on your `PATH`, in
`/usr/local/cuda*/bin` or in `/opt/cuda/bin`.

**Docker.**
The Docker image doesn't include the build tools yet, so GGUF picture models run on the processor there. Use the
regular install to run them on your graphics card.
