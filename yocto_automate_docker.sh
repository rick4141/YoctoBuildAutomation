#!/bin/bash

# yocto_automate_docker.sh - Full automated Yocto build with Docker container

python3 yocto_automate_docker.py \
  --board k26-smk-kv \
  --container yocto_builder \
  --config config.json \
  --yocto-release kirkstone \
  --poky-branch kirkstone \
  --force \
  --auto-install \
  --install-yocto-deps \
  --clone-poky \
  --clone-poky-location container \
  --meta-layers \
    https://github.com/Xilinx/meta-xilinx.git#rel-2023.1 \
    https://github.com/Xilinx/meta-kria.git#rel-2023.1 \
  --build-image
