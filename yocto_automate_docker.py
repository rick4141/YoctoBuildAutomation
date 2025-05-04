import os
import platform
import subprocess
import shutil
import datetime
import re
import argparse

# =============================
# DEFAULT CONFIGURATION
# =============================

REQUIRED_TOOLS = {
    "git": "1.8.3",
    "tar": "1.28",
    "python3": "3.8",
    "gcc": "8.0",
    "make": "4.0"
}

YOCTO_HOST_PACKAGES = [
    "build-essential", "chrpath", "cpio", "debianutils", "diffstat", "file", "gawk",
    "gcc", "git", "iputils-ping", "libacl1", "liblz4-tool", "locales", "python3",
    "python3-git", "python3-jinja2", "python3-pexpect", "python3-pip",
    "python3-subunit", "socat", "texinfo", "unzip", "wget", "xz-utils", "zstd"
]


# =============================
# LOGGER SETUP
# =============================

def setup_logging():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.getcwd(), f"yocto_project/{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "setup.log")

    def log(tag, message):
        time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{tag}] {time_str} - {message}"
        print(line)
        with open(log_file, "a") as f:
            f.write(line + "\n")

    return log, log_dir

# =============================
# SYSTEM INFO
# =============================

def get_system_info(log):
    log("INFO", "Collecting system information...")

    total, used, free = shutil.disk_usage("/")
    cpu_count = os.cpu_count()
    os_info = f"{platform.system()} {platform.release()}"
    arch = platform.machine()

    try:
        if platform.system() == "Darwin":  # macOS
            ram_bytes = int(subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"]).decode().strip())
            ram_gb = ram_bytes // (2**30)
            ram_info = f"{ram_gb} GB (from sysctl)"
        else:  # Linux
            ram_info = subprocess.check_output("free -h", shell=True).decode()
    except Exception as e:
        ram_info = f"Could not retrieve RAM info: {str(e)}"

    log("INFO", f"OS: {os_info}")
    log("INFO", f"Architecture: {arch}")
    log("INFO", f"Disk Total: {total // (2**30)} GB")
    log("INFO", f"Disk Free: {free // (2**30)} GB")
    log("INFO", f"CPU Cores: {cpu_count}")
    log("INFO", f"RAM Info: {ram_info.strip()}")


# =============================
# UTILITIES
# =============================

def run_cmd(cmd, capture_output=True):
    result = subprocess.run(cmd, shell=True, text=True, capture_output=capture_output)
    return result.stdout.strip() if capture_output else None

def run_cmd_live(cmd):
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            print(output.strip())
    return process.returncode


def container_exists(name):
    output = run_cmd(f"docker ps -a --filter name=^{name}$ --format '{{{{.Names}}}}'")
    return name in output.splitlines()

def container_running(name):
    output = run_cmd(f"docker ps --filter name=^{name}$ --format '{{{{.Names}}}}'")
    return name in output.splitlines()

def create_container(log, name, image):
    log("PROCESS", f"Creating container '{name}' from image '{image}'...")
    run_cmd(f"docker run -dit --name {name} {image} bash", capture_output=False)

def ensure_container_running(log, name, image, force=False):
    if container_exists(name) and force:
        log("PROCESS", f"Removing existing container '{name}' (forced)...")
        run_cmd(f"docker rm -f {name}", capture_output=False)

    if not container_exists(name):
        create_container(log, name, image)
    elif not container_running(name):
        log("PROCESS", f"Starting container '{name}'...")
        run_cmd(f"docker start {name}", capture_output=False)
    else:
        log("INFO", f"Container '{name}' is already running.")

def parse_version(output):
    match = re.search(r'(\d+\.\d+(\.\d+)?)', output)
    return match.group(1) if match else "0.0"

def version_ge(v1, v2):
    def normalize(v): return [int(x) for x in v.split(".")]
    return normalize(v1) >= normalize(v2)

def check_tool(log, container_name, tool, min_version):
    try:
        output = run_cmd(f"docker exec {container_name} {tool} --version")
        current_version = parse_version(output)
        if version_ge(current_version, min_version):
            log("INFO", f"{tool}: version {current_version} (OK)")
            return True
        else:
            log("WARN", f"{tool}: version {current_version} < required {min_version}")
            return False
    except Exception as e:
        log("ERROR", f"Failed to check {tool}: {e}")
        return False

def install_dependencies(log, container_name):
    log("PROCESS", "Installing required dependencies using apt...")
    cmds = [
        f"docker exec {container_name} apt-get update",
        f"docker exec {container_name} apt-get install -y git tar python3 gcc make"
    ]
    for cmd in cmds:
        log("PROCESS", f"Running: {cmd}")
        run_cmd(cmd, capture_output=False)


# =============================
# BUILD HOST PACKAGES
# =============================

def install_yocto_host_packages(log, container_name):
    log("PROCESS", "Installing Yocto recommended host packages...")

    pkg_list = " ".join(YOCTO_HOST_PACKAGES)
    cmds = [
        f"docker exec {container_name} apt-get update",
        f"docker exec {container_name} apt-get install -y {pkg_list}"
    ]
    for cmd in cmds:
        log("PROCESS", f"Running: {cmd}")
        run_cmd(cmd, capture_output=False)


# =============================
# USE GIT TO CLONE POKY
# =============================

def clone_and_checkout_poky(log, poky_dir, branch_remote, branch_local):
    log("PROCESS", f"Cloning Poky into '{poky_dir}' if it doesn't exist...")
    if not os.path.exists(poky_dir):
        cmd = f"git clone git://git.yoctoproject.org/poky {poky_dir}"
        result = run_cmd(cmd)
        log("INFO", result or f"Cloned into '{poky_dir}'")
    else:
        log("INFO", f"Directory '{poky_dir}' already exists. Skipping clone.")

    # Validate that it's a git repo
    if not os.path.isdir(os.path.join(poky_dir, ".git")):
        log("ERROR", f"Directory '{poky_dir}' exists but is not a git repo.")
        return

    os.chdir(poky_dir)
    log("PROCESS", "Listing all remote branches...")
    branches = run_cmd("git branch -r")
    log("INFO", f"Remote branches:\n{branches}")

    log("PROCESS", f"Checking out branch 'origin/{branch_remote}' as local '{branch_local}'...")
    checkout_cmd = f"git checkout -t origin/{branch_remote} -b {branch_local}"
    result = run_cmd(checkout_cmd)
    log("INFO", result or f"Checked out '{branch_local}' from 'origin/{branch_remote}'")

    os.chdir("..")  # return to previous working directory


def clone_poky_inside_container(log, container_name, poky_dir, branch_remote, branch_local):
    # Check if poky directory already exists
    check_cmd = f"docker exec {container_name} test -d {poky_dir}"
    exists = subprocess.run(check_cmd, shell=True).returncode == 0

    if not exists:
        log("PROCESS", f"Cloning poky inside container at '{poky_dir}'...")
        clone_cmd = f"docker exec {container_name} git clone git://git.yoctoproject.org/poky {poky_dir}"
        run_cmd(clone_cmd)
    else:
        log("INFO", f"Directory '{poky_dir}' already exists inside the container. Skipping clone.")

    log("PROCESS", f"Checking out branch '{branch_remote}' as '{branch_local}' inside container...")
    checkout_cmd = (
        f"docker exec {container_name} bash -c "
        f"\"cd {poky_dir} && git checkout -t origin/{branch_remote} -b {branch_local}\""
    )
    run_cmd(checkout_cmd)

# =============================
# MODIFY LOCAL.CONF TO ENABLE WIC
# =============================

def patch_local_conf_for_wic(log, container_name, build_dir="/home/yocto/poky/build"):
    conf_path = f"{build_dir}/conf/local.conf"
    log("PROCESS", "Ensuring .wic.bz2 is enabled in local.conf...")
    wic_cmd = (
        f'docker exec {container_name} bash -c "echo \'IMAGE_FSTYPES += \\"wic.bz2\\"\' >> {conf_path}"'
    )

    run_cmd(wic_cmd)


# =============================
# BUILDING YOUR IMAGE
# =============================

def fix_poky_permissions(log, container_name, poky_dir="/home/yocto/poky", username="yocto"):
    log("PROCESS", f"Fixing ownership of '{poky_dir}' to user '{username}'...")
    run_cmd(f"docker exec {container_name} chown -R {username}:{username} {poky_dir}", capture_output=False)


def ensure_locale_utf8(log, container_name):
    log("PROCESS", "Ensuring en_US.UTF-8 locale inside container...")
    cmds = [
        f"docker exec {container_name} apt-get update",
        f"docker exec {container_name} apt-get install -y locales",
        f"docker exec {container_name} locale-gen en_US.UTF-8",
        f"docker exec {container_name} update-locale LANG=en_US.UTF-8"
    ]
    for cmd in cmds:
        run_cmd(cmd, capture_output=False)


def prepare_non_root_user_and_websockets(log, container_name, username="yocto"):
    log("PROCESS", f"Ensuring user '{username}' and Python module 'websockets' inside container...")

    # Verificar si el usuario ya existe
    user_check = run_cmd(f"docker exec {container_name} id -u {username}", capture_output=True)
    if not user_check or "no such user" in user_check.lower():
        log("PROCESS", f"Creating user '{username}' in container...")
        run_cmd(f"docker exec {container_name} useradd -m {username}", capture_output=False)
        run_cmd(f"docker exec {container_name} passwd -d {username}", capture_output=False)

    # Instalar pip y websockets
    cmds = [
        f"docker exec {container_name} apt-get update",
        f"docker exec {container_name} apt-get install -y python3-pip",
        f"docker exec {container_name} pip3 install websockets==10.0"
    ]
    for cmd in cmds:
        log("PROCESS", f"Running: {cmd}")
        run_cmd(cmd, capture_output=False)


def patch_local_conf_for_hashserve(log, container_name, build_dir="/home/yocto/poky/build"):
    conf_path = f"{build_dir}/conf/local.conf"
    log("PROCESS", f"Patching local.conf in container for SSTATE_MIRRORS and hashserve...")

    sed_cmd = (
        f"docker exec {container_name} bash -c \""
        f"echo '' >> {conf_path} && "
        f"echo 'BB_HASHSERVE_UPSTREAM = \\\"wss://hashserv.yoctoproject.org/ws\\\"' >> {conf_path} && "
        f"echo 'SSTATE_MIRRORS ?= \\\"file://.* http://cdn.jsdelivr.net/yocto/sstate/all/PATH;downloadfilename=PATH\\\"' >> {conf_path} && "
        f"echo 'BB_HASHSERVE = \\\"auto\\\"' >> {conf_path} && "
        f"echo 'BB_SIGNATURE_HANDLER = \\\"OEEquivHash\\\"' >> {conf_path}\""
    )
    run_cmd(sed_cmd)


def build_image_in_container(log, container_name, poky_dir, target_image, enable_hashserve=False, run_qemu=False, username="yocto"):
    log("PROCESS", f"Initializing Yocto build environment inside container '{container_name}' as user '{username}'...")

    if enable_hashserve:
        patch_local_conf_for_hashserve(log, container_name, f"{poky_dir}/build")

    build_cmd = (
        f"docker exec --user {username} {container_name} bash -c 'cd {poky_dir} && "
        f"source oe-init-build-env build && "
        f"bitbake {target_image}'"
    )

    start_time = datetime.datetime.now()
    result = run_cmd_live(build_cmd)
    duration = (datetime.datetime.now() - start_time).total_seconds()
    log("INFO", f"Bitbake finished in {duration:.2f} seconds")

    if result != 0:
        log("ERROR", "Bitbake returned a non-zero exit code.")



def verify_build_success(log, container_name, poky_dir, target_image):
    deploy_dir = f"{poky_dir}/build/tmp/deploy/images"
    check_cmd = (
        f"docker exec {container_name} bash -c \""
        f"find {deploy_dir} -type f \\( -name '*{target_image}*.ext4' "
        f"-o -name '*{target_image}*.wic' "
        f"-o -name '*{target_image}*.tar.bz2' \\)\""
    )
    output = run_cmd(check_cmd)
    
    if output:
        log("INFO", "Build completed successfully.")
        log("INFO", f"Generated image files:\n{output}")
    else:
        log("ERROR", "Build failed or no output images were found.")


def patch_local_conf_machine(log, container_name, machine):
    conf_path = "/home/yocto/poky/build/conf/local.conf"
    log("PROCESS", f"Setting MACHINE = \"{machine}\" in local.conf...")
    run_cmd(
        f"docker exec {container_name} bash -c \"echo 'MACHINE = \\\"{machine}\\\"' >> {conf_path}\"",
        capture_output=False
    )


def clone_required_layers(log, container_name, base_dir="/home/yocto/poky/sources", release="langdale"):
    repos = [
        ("meta-xilinx", "https://github.com/Xilinx/meta-xilinx.git"),
        ("meta-kria", "https://github.com/Xilinx/meta-kria.git")
    ]
    for name, url in repos:
        cmd = (
            f"docker exec {container_name} bash -c "
            f"\"mkdir -p {base_dir} && cd {base_dir} && "
            f"if [ ! -d {name} ]; then git clone -b {release} {url} {name}; fi\""
        )
        log("PROCESS", f"Cloning layer {name} if not exists...")
        run_cmd(cmd, capture_output=False)


def add_meta_layers(log, container_name, layers, poky_dir="/home/yocto/poky"):
    if not layers:
        log("INFO", "No additional meta-layers specified.")
        return

    for layer in layers:
        full_layer_path = f"{poky_dir}/{layer}"
        check_cmd = f"docker exec {container_name} bash -c 'test -d {full_layer_path}'"
        result = subprocess.run(check_cmd, shell=True)
        if result.returncode != 0:
            log("WARN", f"Layer directory not found: {full_layer_path}. Skipping.")
            continue

        log("PROCESS", f"Adding layer: {layer}")
        # Ejecutar dentro del entorno de build para que bitbake-layers esté disponible
        cmd = (
            f"docker exec {container_name} bash -c "
            f"'cd {poky_dir} && source oe-init-build-env build > /dev/null && "
            f"bitbake-layers add-layer ../{layer}'"
        )
        result = run_cmd(cmd)
        if result is None or "ERROR" in result:
            log("ERROR", f"Failed to add layer {layer}. Output:\n{result}")



# =============================
# ARGPARSE SETUP
# =============================

def parse_args():
    parser = argparse.ArgumentParser(description="Setup Docker container for Yocto development.")
    parser.add_argument("--container", type=str, default="yocto_builder", help="Docker container name")
    parser.add_argument("--image", type=str, default="ubuntu:22.04", help="Base Docker image")
    parser.add_argument("--auto-install", action="store_true", help="Auto install missing dependencies")
    parser.add_argument("--force", action="store_true", help="Force recreate the container")
    parser.add_argument("--install-yocto-deps", action="store_true", help="Install Yocto recommended host packages inside the container")
    parser.add_argument("--clone-poky", action="store_true", help="Clone poky repo and checkout a branch")
    parser.add_argument("--clone-poky-location", choices=["host", "container"], default="container",
                    help="Where to clone the Poky repo: 'host' or 'container'")
    parser.add_argument("--poky-dir", type=str, default="poky", help="Directory to clone poky into")
    parser.add_argument("--poky-branch", type=str, default="styhead", help="Remote poky branch to track")
    parser.add_argument("--poky-local", type=str, default="my-styhead", help="Name of local branch to create")
    parser.add_argument("--build-image", action="store_true", help="Build the image using bitbake")
    parser.add_argument("--target-image", type=str, default="core-image-sato", help="Bitbake target (e.g. core-image-minimal, core-image-sato)")
    parser.add_argument("--enable-hashserve", action="store_true", help="Enable shared state cache mirrors and hash equivalence in local.conf")
    parser.add_argument("--run-qemu", action="store_true", help="Run QEMU emulator after build")
    parser.add_argument("--machine", type=str, required=True, help="Target MACHINE name (e.g. k26-smk, raspberrypi4, qemux86-64)")
    parser.add_argument("--yocto-release", type=str, default="nanbield", help="Yocto release branch or tag (e.g. nanbield, kirkstone, rel-v2023.2)")
    parser.add_argument("--meta-layers", nargs="+", default=[], help="List of additional meta-layers to add (paths relative to poky)")

    return parser.parse_args()

# =============================
# MAIN LOGIC
# =============================

def main():
    args = parse_args()
    log, log_dir = setup_logging()

    log("INFO", f"Script started - logging to {log_dir}")
    get_system_info(log)
    ensure_container_running(log, args.container, args.image, force=args.force)

    log("INFO", "Validating required tools inside the container...")
    all_ok = True
    for tool, min_ver in REQUIRED_TOOLS.items():
        if not check_tool(log, args.container, tool, min_ver):
            all_ok = False

    if not all_ok and args.auto_install:
        log("PROCESS", "Installing missing or outdated tools...")
        install_dependencies(log, args.container)
        log("INFO", "Rechecking after installation...")
        for tool, min_ver in REQUIRED_TOOLS.items():
            check_tool(log, args.container, tool, min_ver)

    if args.install_yocto_deps:
        install_yocto_host_packages(log, args.container)

    if args.clone_poky:
        if args.clone_poky_location == "host":
            clone_and_checkout_poky(log, args.poky_dir, args.poky_branch, args.poky_local)
        else:
            clone_poky_inside_container(log, args.container, args.poky_dir, args.poky_branch, args.poky_local)

    if args.build_image:
        prepare_non_root_user_and_websockets(log, args.container)
        ensure_locale_utf8(log, args.container)
        fix_poky_permissions(log, args.container, args.poky_dir, "yocto")

        run_cmd(
            f"docker exec --user yocto {args.container} bash -c 'cd {args.poky_dir} && source oe-init-build-env build'",
            capture_output=False
        )

        patch_local_conf_machine(log, args.container, args.machine)
        patch_local_conf_for_wic(log, args.container)
        clone_required_layers(log, args.container)
        add_meta_layers(log, args.container, args.meta_layers)
        
        build_image_in_container(
            log,
            args.container,
            args.poky_dir,
            args.target_image,
            enable_hashserve=args.enable_hashserve,
            run_qemu=args.run_qemu,
            username="yocto"
        )
        verify_build_success(log, args.container, args.poky_dir, args.target_image)

    log("INFO", "Script completed.")

if __name__ == "__main__":
    main()
