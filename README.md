# Yocto Build Automation: Docker and Native Host Setup

This document describes how to use the `yocto_automate_docker.py` script to set up a reproducible Yocto Linux image build environment, either using Docker or a native Linux installation.

---


![Yocto Build Automation](images/image.png)


**IMPORTANT NOTES:**
- Be Patient!
- Have as many cores as you can have.
- Be PATIENT!!!
- Check always the logs generated, and the time.
- BE PATIENT!!!!!!!

## System Requirements

| Resource   | Minimum Requirement                            |
| ---------- | ---------------------------------------------- |
| CPU        | 8 cores                                        |
| RAM        | 16 GB                                          |
| Disk Space | 100 GB free                                    |
| OS         | Ubuntu / Debian / Fedora / macOS (with Docker) |
| Internet   | Optional (can build offline with cached repos) |

For compatible distributions, refer to the [Yocto Quick Start Guide](https://docs.yoctoproject.org/brief-yoctoprojectqs/index.html#compatible-linux-distribution).

---

## Required Tools

These tools are expected to be present either in the host or inside the Docker container:

| Tool      | Minimum Version |
| --------- | --------------- |
| `git`     | 1.8.3           |
| `tar`     | 1.28            |
| `python3` | 3.8             |
| `gcc`     | 8.0             |
| `make`    | 4.0             |

The script automatically checks these versions. If `--auto-install` is used, missing tools will be installed inside the container.

---

## Yocto Recommended Host Packages (Linux only)

If you use the `--install-yocto-deps` flag, these packages are installed:

```text
build-essential chrpath cpio debianutils diffstat file gawk gcc git iputils-ping 
libacl1 liblz4-tool locales python3 python3-git python3-jinja2 python3-pexpect 
python3-pip python3-subunit socat texinfo unzip wget xz-utils zstd
```

These ensure compatibility with Yocto Project builds in containerized or native environments.

---

## Option 1: Docker-Based Environment

### Advantages

* Isolated build environment
* Reproducible and portable
* Works on macOS and Linux
* No contamination of host system

### Example Execution

```bash
python3 yocto_automate_docker.py \
  --container yocto_builder \
  --image ubuntu:22.04 \
  --auto-install \
  --install-yocto-deps \
  --clone-poky \
  --clone-poky-location container \
  --poky-dir /home/yocto/poky \
  --poky-branch styhead \
  --poky-local my-styhead \
  --build-image \
  --target-image core-image-sato \
  --enable-hashserve
```

This command initializes the full workflow inside a Docker container.

---

## Option 2: Native Host Setup

### Advantages

* Better performance (no Docker overhead)
* Direct access to system tools

### Requirements

* Linux host (Ubuntu/Debian/Fedora)
* Root privileges to install packages
* Manual management of required tools

### Example Execution

```bash
python3 yocto_automate_docker.py \
  --clone-poky \
  --clone-poky-location host \
  --poky-dir ./poky \
  --poky-branch styhead \
  --poky-local my-styhead
```

This only prepares the Poky repository on your local machine.

---

## Script Features Summary

| Feature         | Description                                          |
| --------------- | ---------------------------------------------------- |
| System Info     | Logs OS, CPU, RAM, and disk usage                    |
| Tool Checker    | Verifies versions of required tools                  |
| Docker Manager  | Starts or creates containers as needed               |
| Poky Handler    | Clones and checks out specific Yocto branches        |
| Locale Fixes    | Ensures en\_US.UTF-8 inside container                |
| Bitbake Builder | Launches builds with bitbake inside container        |
| Output Checker  | Verifies generated `.ext4`, `.wic`, `.tar.bz2` files |
| Logging System  | All actions logged with timestamps                   |

---

## Generated Directory Structure

Each build generates a structured folder like the following:

```bash
yocto_project/
└── 20250503_112055/
    ├── setup.log
    ├── poky/ (if built on host)
    └── build/ (inside Docker)
```

---

## Best Practices

* Use Docker if portability, isolation, or macOS compatibility is needed
* Use native host mode for higher performance on powerful Linux systems
* Always enable `--enable-hashserve` for faster incremental builds
* Use SSD-based storage to reduce build times

---

## Full Example: Kria KV260 with Hashserve

For more details about Kria support in Yocto, refer to the [official Xilinx guide](https://xilinx.github.io/kria-apps-docs/yocto/build/html/docs/yocto_kria_support.html).

```bash
python3 yocto_automate_docker.py \
  --container kria_dev \
  --image ubuntu:22.04 \
  --auto-install \
  --install-yocto-deps \
  --clone-poky \
  --clone-poky-location container \
  --poky-dir /home/yocto/poky \
  --poky-branch nanbield \
  --poky-local kria-nanbield \
  --build-image \
  --target-image core-image-minimal \
  --enable-hashserve
```

This builds a `core-image-minimal` Yocto image for Kria KV260, using Docker and hash equivalence features.

---

# Reference: yocto\_automate\_docker.py

This section provides a technical reference for the Python script `yocto_automate_docker.py`. It details the purpose, parameters, and behavior of each function.

---

## 1. `setup_logging()`

**Description**: Initializes a timestamped logging directory and returns a logging function and path.

**Returns**:

* `log (function)`: Logs messages to stdout and to a file.
* `log_dir (str)`: Path to the created log directory.

---

## 2. `get_system_info(log)`

**Description**: Collects and logs system information like OS, architecture, disk usage, CPU cores, and RAM.

**Parameters**:

* `log (function)`: Logger function returned from `setup_logging()`.

---

## 3. `run_cmd(cmd, capture_output=True)`

**Description**: Executes a shell command and optionally captures its output.

**Returns**: Command output as a string if `capture_output` is `True`, otherwise `None`.

---

## 4. `run_cmd_live(cmd)`

**Description**: Executes a shell command and prints live output line by line.

**Returns**: Exit code of the command.

---

## 5. `container_exists(name)`

**Description**: Checks whether a Docker container with the given name exists.

**Returns**: Boolean.

---

## 6. `container_running(name)`

**Description**: Checks whether a Docker container with the given name is currently running.

**Returns**: Boolean.

---

## 7. `create_container(log, name, image)`

**Description**: Creates a new detached Docker container from a given image.

**Parameters**:

* `log`: Logger function.
* `name (str)`: Container name.
* `image (str)`: Docker image to use.

---

## 8. `ensure_container_running(log, name, image, force=False)`

**Description**: Starts or recreates a container as needed.

**Parameters**:

* `force (bool)`: If `True`, removes existing container and recreates.

---

## 9. `parse_version(output)`

**Description**: Extracts a semantic version (e.g. `1.2.3`) from a string.

**Returns**: Parsed version string or "0.0".

---

## 10. `version_ge(v1, v2)`

**Description**: Compares two version strings.

**Returns**: `True` if `v1 >= v2`.

---

## 11. `check_tool(log, container_name, tool, min_version)`

**Description**: Checks if a tool inside a container meets the minimum version requirement.

**Returns**: Boolean.

---

## 12. `install_dependencies(log, container_name)`

**Description**: Installs basic required build tools using APT in the container.

---

## 13. `install_yocto_host_packages(log, container_name)`

**Description**: Installs all Yocto-recommended host packages inside the container.

---

## 14. `clone_and_checkout_poky(log, poky_dir, branch_remote, branch_local)`

**Description**: Clones the Poky repository on the host and checks out a branch.

---

## 15. `clone_poky_inside_container(log, container_name, poky_dir, branch_remote, branch_local)`

**Description**: Clones Poky and checks out a branch inside a container.

---

## 16. `patch_local_conf_for_wic(log, container_name, build_dir="/home/yocto/poky/build")`

**Description**: Appends `.wic.bz2` output format to `local.conf` in the build directory.

---

## 17. `fix_poky_permissions(log, container_name, poky_dir="/home/yocto/poky", username="yocto")`

**Description**: Sets ownership of Poky directory to a specific user.

---

## 18. `ensure_locale_utf8(log, container_name)`

**Description**: Ensures the en\_US.UTF-8 locale is generated and configured.

---

## 19. `prepare_non_root_user_and_websockets(log, container_name, username="yocto")`

**Description**: Creates a non-root user and installs the Python `websockets` module.

---

## 20. `patch_local_conf_for_hashserve(log, container_name, build_dir="/home/yocto/poky/build")`

**Description**: Appends hash equivalence and shared-state mirror configuration to `local.conf`.

---

## 21. `build_image_in_container(log, container_name, poky_dir, target_image, enable_hashserve=False, run_qemu=False, username="yocto")`

**Description**: Executes `bitbake` inside the container to build the specified Yocto image.

---

## 22. `verify_build_success(log, container_name, poky_dir, target_image)`

**Description**: Searches for expected output image files in the deployment directory.

---

## 23. `patch_local_conf_machine(log, container_name, machine)`

**Description**: Sets the target `MACHINE` variable in `local.conf`.

---

## 24. `clone_required_layers(log, container_name, base_dir="/home/yocto/poky/sources", release="langdale")`

**Description**: Clones commonly used meta-layers for Xilinx boards if not already present.

---

## 25. `add_meta_layers(log, container_name, layers, poky_dir="/home/yocto/poky")`

**Description**: Adds specified meta-layers to the BitBake build environment.

---

## 26. `parse_args()`

**Description**: Configures and parses command-line arguments using argparse.

**Returns**: `argparse.Namespace`

---

## 27. `main()`

**Description**: Entry point for the script. Controls overall execution flow based on parsed arguments.

---

Future notes:

- Send Json instead of hardcoding the dependencies and requiered tools.

---

## License

This project is licensed under the MIT License.

---

## Acknowledgments

Special thanks to the authors and maintainers of the [Yocto Project documentation](https://docs.yoctoproject.org/) and the [Xilinx Kria Yocto guides](https://xilinx.github.io/kria-apps-docs/) for providing comprehensive and reliable references that helped shape and validate this automation workflow.
