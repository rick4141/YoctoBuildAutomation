#!/bin/bash
# setup_host.sh - For native Linux environments (Ubuntu/Debian/Fedora)

python3 yocto_automate_docker.py \
  --clone-poky \
  --clone-poky-location host \
  --poky-dir ./poky \
  --poky-branch styhead \
  --poky-local my-styhead
