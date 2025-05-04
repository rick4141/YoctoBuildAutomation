#!/bin/bash

# setup_docker.sh - Full automated Yocto build with Docker container

python3 yocto_automate_docker.py \
    --build-image \
    --clone-poky \
    --install-yocto-deps \
    --machine k26-smk \
    --target-image core-image-sato \
    --container kria_builder \
    --image ubuntu:22.04 \
    --poky-branch langdale \
    --poky-local my-kria \
    --yocto-release langdale \
    --meta-layers sources/meta-xilinx sources/meta-kria