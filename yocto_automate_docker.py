import os
import platform
import subprocess
import shutil
import datetime
import re
import argparse
import json
import sys
from textwrap import dedent
from pathlib import Path

# =============================================================
#  DEFAULT CONFIGURATION
# =============================================================

REQUIRED_TOOLS = {
    "git": "1.8.3",
    "tar": "1.28",
    "python3": "3.8",
    "gcc": "8.0",
    "make": "4.0",
}

YOCTO_HOST_PACKAGES = [
    "build-essential",
    "chrpath",
    "cpio",
    "debianutils",
    "diffstat",
    "file",
    "gawk",
    "gcc",
    "git",
    "iputils-ping",
    "libacl1",
    "liblz4-tool",
    "locales",
    "nano",
    "python3",
    "python3-git",
    "python3-jinja2",
    "python3-pexpect",
    "python3-pip",
    "python3-subunit",
    "socat",
    "texinfo",
    "unzip",
    "wget",
    "xz-utils",
    "zstd",
]

DEFAULT_LAYERS = [
    "sources/meta-openembedded/meta-oe",
    "sources/meta-openembedded/meta-python",
    "sources/meta-openembedded/meta-networking",
    "sources/meta-openembedded/meta-filesystems",
    "sources/meta-virtualization",
    "sources/meta-xilinx/meta-xilinx-bsp", 
    "sources/meta-xilinx/meta-xilinx-core",
    "sources/meta-xilinx/meta-xilinx-standalone",
    "sources/meta-xilinx/meta-microblaze",
    "sources/meta-xilinx/meta-xilinx-standalone-experimental",
    "sources/meta-kria",
]

APT_ENV = "-e DEBIAN_FRONTEND=noninteractive -e TZ=Etc/UTC"

# =============================================================
#  LOGGER
# =============================================================

def setup_logging():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join(os.getcwd(), f"yocto_project/{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "setup.log")

    def _log(tag: str, message: str):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{tag}] {t} – {message}"
        print(line)
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    return _log, log_dir


# =============================================================
#  SYSTEM INFORMATION
# =============================================================

def get_system_info(log):
    log("INFO", "Collecting system information …")
    total, _, free = shutil.disk_usage("/")
    log("INFO", f"OS            : {platform.system()} {platform.release()}")
    log("INFO", f"Architecture  : {platform.machine()}")
    log("INFO", f"Disk total    : {total // (2 ** 30)} GB")
    log("INFO", f"Disk free     : {free // (2 ** 30)} GB")
    log("INFO", f"CPU cores     : {os.cpu_count()}")

    try:
        if platform.system() == "Darwin":  # macOS
            ram = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode()) // (2 ** 30)
            log("INFO", f"RAM           : {ram} GB (sysctl)")
        else:  # Linux
            ram_info = subprocess.check_output("free -h", shell=True, text=True)
            log("INFO", "RAM info:\n" + ram_info.strip())
    except Exception as exc:  # pragma: no cover – best‑effort only
        log("WARN", f"Could not retrieve RAM info → {exc}")


# =============================================================
#  GENERIC SHELL HELPERS
# =============================================================

def run_cmd(cmd: str, *, capture_output: bool = True):
    """Run *cmd* on the host and return stdout (if *capture_output*)."""
    res = subprocess.run(cmd, shell=True, text=True, capture_output=capture_output)
    return res.stdout.strip() if capture_output else None


def run_cmd_live(cmd: str) -> int:
    """Run *cmd* printing output in real time; return exit code."""
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:  # type: ignore[assignment]
        if line:
            print(line.rstrip())
    proc.wait()
    return proc.returncode


def container_exists(name: str) -> bool:
    return name in run_cmd(f"docker ps -a --filter name=^{name}$ --format '{{{{.Names}}}}'").splitlines()


def container_running(name: str) -> bool:
    return name in run_cmd(f"docker ps --filter name=^{name}$ --format '{{{{.Names}}}}'").splitlines()


def create_container(log, name: str, image: str):
    log("PROCESS", f"Creating container '{name}' from image '{image}' …")
    run_cmd(f"docker run -dit --name {name} {image} bash", capture_output=False)


def ensure_container_running(log, name: str, image: str, *, force: bool = False):
    if force and container_exists(name):
        log("PROCESS", f"Removing existing container '{name}' (forced)")
        run_cmd(f"docker rm -f {name}", capture_output=False)

    if not container_exists(name):
        create_container(log, name, image)
    elif not container_running(name):
        log("PROCESS", f"Starting container '{name}' …")
        run_cmd(f"docker start {name}", capture_output=False)
    else:
        log("INFO", f"Container '{name}' is already running")


# -------------------------------------------------------------
#  Version helpers
# -------------------------------------------------------------

def _parse_version(output: str) -> str:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", output)
    return m.group(1) if m else "0.0"


def _ver_ge(a: str, b: str) -> bool:
    to_ints = lambda v: [int(x) for x in v.split(".")]
    return to_ints(a) >= to_ints(b)


def check_tool(log, container: str, tool: str, min_version: str) -> bool:
    try:
        out = run_cmd(f"docker exec {container} {tool} --version")
        cur = _parse_version(out)
        ok = _ver_ge(cur, min_version)
        log("INFO" if ok else "WARN", f"{tool}: {cur} (needs ≥ {min_version})")
        return ok
    except Exception as exc:
        log("ERROR", f"Failed to check {tool}: {exc}")
        return False

# ============================================================
#  CONFIG.JSON HANDLING
# ============================================================

def load_profile(cfg_file: str, board: str) -> dict:
    """Return the dictionary describing *board* taken from *cfg_file*."""
    cfg = json.loads(Path(cfg_file).read_text(encoding="utf-8"))
    if board not in cfg.get("boards", {}):
        print(f"[FATAL] board '{board}' not found in {cfg_file}")
        sys.exit(3)

    profile = cfg["boards"][board].copy()

    # inherit repo defaults from the root of the JSON
    profile.setdefault("yocto_release", cfg.get("yocto_release", "nanbield"))
    profile.setdefault("poky_branch",   cfg.get("default_poky_branch", "master"))
    profile.setdefault("poky_local",    cfg.get("default_poky_local",  "my-master"))
    profile.setdefault("extra_layers",  [])
    profile.setdefault("local_conf",    [])
    profile.setdefault("multiconfig",   False)
    return profile

# -------------------------------------------------------------
#  APT helpers (inside container)
# -------------------------------------------------------------

def _kill_apt_frontend(container: str):
    cmd = (
        "command -v fuser >/dev/null 2>&1 || "
        "(apt-get update && apt-get install -y --no-install-recommends psmisc); "
        "fuser -k /var/lib/dpkg/lock-frontend || true"
    )
    run_cmd(f"docker exec {container} bash -c \"{cmd}\"", capture_output=False)


def install_dependencies(log, container: str):
    _kill_apt_frontend(container)
    log("PROCESS", "Installing basic build tools …")
    for cmd in (
        f"docker exec {APT_ENV} {container} apt-get update",
        f"docker exec {APT_ENV} {container} apt-get install -y git tar python3 gcc make",
    ):
        run_cmd(cmd, capture_output=False)


def install_yocto_host_packages(log, container: str):
    _kill_apt_frontend(container)
    log("PROCESS", "Installing full Yocto host package set …")
    pkg_list = " ".join(YOCTO_HOST_PACKAGES)
    for cmd in (
        f"docker exec {APT_ENV} {container} apt-get update",
        f"docker exec {APT_ENV} {container} apt-get install -y {pkg_list}",
    ):
        run_cmd(cmd, capture_output=False)


# =============================================================
#  POKY CLONE / CHECKOUT
# =============================================================

def clone_and_checkout_poky(log, poky_dir: str, remote_branch: str, local_branch: str, container):
    if not os.path.exists(poky_dir):
        log("PROCESS", f"Cloning Poky → {poky_dir}")
        run_cmd(f"git clone git://git.yoctoproject.org/poky {poky_dir}", capture_output=False)
    else:
        log("INFO", f"Poky dir '{poky_dir}' already exists – skip clone")

    if not os.path.isdir(os.path.join(poky_dir, ".git")):
        log("ERROR", f"Directory '{poky_dir}' exists but is not a git repo!")
        return

    os.chdir(poky_dir)
    branches = run_cmd("git branch -r")
    log("INFO", "Remote branches:\n" + branches)

    run_cmd(f"git checkout -B {local_branch} origin/{remote_branch}", capture_output=False)
    os.chdir("..")
    mark_git_safe_directory(log, container, poky_dir)


def clone_poky_inside_container(log, container: str, poky_dir: str, remote_branch: str, local_branch: str):
    if subprocess.run(f"docker exec {container} test -d {poky_dir}", shell=True).returncode != 0:
        log("PROCESS", f"Cloning Poky inside container → {poky_dir}")
        run_cmd(f"docker exec {container} git clone git://git.yoctoproject.org/poky {poky_dir}")
    else:
        log("INFO", f"Poky dir '{poky_dir}' already exists in container – skip clone")

    run_cmd(
        f"docker exec {container} bash -c \"cd {poky_dir} && git checkout -B {local_branch} origin/{remote_branch}\"",
        capture_output=False,
    )
    mark_git_safe_directory(log, container, poky_dir)


# =============================================================
#  CONF PATCH HELPERS
# =============================================================

def append_block(container: str, conf: str, block: str):
    here = f'cat >> {conf} << "EOF"\n{block}\nEOF'
    run_cmd(f"docker exec {container} bash -c '{here}'", capture_output=False)


def patch_local_conf_for_wic(log, container, build_dir="/home/yocto/poky/build"):
    conf = f"{build_dir}/conf/local.conf"
    log("PROCESS", "Enabling .wic.bz2 output format …")

    run_cmd(
        f"docker exec {container} bash -c 'sed -i \"/^[[:space:]]*IMAGE_FSTYPES[[:space:]]*\\+=/d\" {conf}'",
        capture_output=False,
    )
    append_block(container, conf, 'IMAGE_FSTYPES += "wic.bz2"')


def patch_local_conf_for_hashserve(log, container, build_dir="/home/yocto/poky/build"):
    conf = f"{build_dir}/conf/local.conf"
    log("PROCESS", "Enabling hash equivalence + CDN sstate cache …")

    block = '''\
BB_HASHSERVE_UPSTREAM = "wss://hashserv.yoctoproject.org/ws"
SSTATE_MIRRORS ?= "file://.* http://cdn.jsdelivr.net/yocto/sstate/all/PATH;downloadfilename=PATH"'''
    append_block(container, conf, block)


def patch_local_conf_machine(log, container, machine, build_dir="/home/yocto/poky/build"):
    conf = f"{build_dir}/conf/local.conf"
    log("PROCESS", f'Setting MACHINE = "{machine}" …')

    # borra cualquier línea previa
    run_cmd(
        f"docker exec {container} bash -c 'sed -i \"/^[[:space:]]*MACHINE[[:space:]]*??=/d\" {conf}'",
        capture_output=False,
    )

    append_block(container, conf, f'MACHINE ??= "{machine}"')


def patch_local_conf_for_kria(
    log,
    container,
    build_dir="/home/yocto/poky/build",
    poky_dir="/home/yocto/poky",
):
    conf = f"{build_dir}/conf/local.conf"
    log("PROCESS", "Patching Xilinx variables …")

    # ── 1. borra definiciones previas ──────────────────────────────
    run_cmd(
        f"""docker exec {container} bash -c '
            sed -i \
              -e "/^[[:space:]]*XILINX_VER_BUILD[[:space:]]*=.*/d" \
              -e "/^[[:space:]]*XILINX_VER_UPDATE[[:space:]]*=.*/d" \
              -e "/^[[:space:]]*LICENSE_FLAGS_ACCEPTED[[:space:]].*xilinx.*/d" \
              "{conf}"'
        """,
        capture_output=False,
    )

    # ── 2. bloque nuevo con las variables ─────────────────────────
    block = dedent("""\
        XILINX_VER_BUILD  = "00000000"
        XILINX_VER_UPDATE = "release"
        LICENSE_FLAGS_ACCEPTED += "xilinx"
        FSBL_PROVIDER      = "fsbl-firmware"
    """)
    append_block(container, conf, block)

    # ── (el BBMULTICONFIG se añade fuera, en 7‑E) ─────────────────


# =============================================================
#  BUILD UTILITIES
# =============================================================

def fix_poky_permissions(log, container: str, poky_dir: str = "/home/yocto/poky", username: str = "yocto"):
    log("PROCESS", f"Fixing ownership of '{poky_dir}' …")
    run_cmd(f"docker exec {container} chown -R {username}:{username} {poky_dir} {poky_dir}/build", capture_output=False)


def ensure_locale_utf8(log, container: str):
    log("PROCESS", "Ensuring en_US.UTF-8 locale …")
    for cmd in (
        f"docker exec {container} apt-get update",
        f"docker exec {container} apt-get install -y locales",
        f"docker exec {container} locale-gen en_US.UTF-8",
        f"docker exec {container} update-locale LANG=en_US.UTF-8",
    ):
        run_cmd(cmd, capture_output=False)


def prepare_non_root_user(log, container: str, username: str = "yocto"):
    if subprocess.run(f"docker exec {container} id -u {username}", shell=True).returncode != 0:
        log("PROCESS", f"Creating user '{username}' …")
        run_cmd(f"docker exec {container} useradd -m {username}", capture_output=False)
        run_cmd(f"docker exec {container} passwd -d {username}", capture_output=False)

    run_cmd(f"docker exec {container} apt-get update", capture_output=False)
    run_cmd(f"docker exec {container} apt-get install -y python3-pip", capture_output=False)
    run_cmd(f"docker exec {container} pip3 install websockets==10.0", capture_output=False)


# -------------------------------------------------------------
#  LAYER HANDLING
# -------------------------------------------------------------

def exec_as_yocto(container: str, cmd: str, capture: bool = False):
    return run_cmd(f"docker exec --user yocto {container} bash -c \"{cmd}\"",
                   capture_output=capture)


def mark_git_safe_directory(log, container: str, path: str):
    run_cmd(f"docker exec {container} git config --global --add safe.directory {path}", capture_output=False)


def clone_required_layers(log, container: str, release: str = "nanbield", base_dir: str = "/home/yocto/poky/sources"):
    repos = [
        ("meta-xilinx", "https://github.com/Xilinx/meta-xilinx.git"),
        ("meta-kria", "https://github.com/Xilinx/meta-kria.git"),
        ("meta-openembedded", "https://github.com/openembedded/meta-openembedded.git"),
        ("meta-virtualization", "https://git.yoctoproject.org/meta-virtualization"),
    ]
    for name, url in repos:
        dest = f"{base_dir}/{name}"
        cmd = f"docker exec {container} bash -c \"[ -d {dest} ] || git clone -b {release} {url} {dest}\""
        run_cmd(cmd, capture_output=False)
        mark_git_safe_directory(log, container, dest)


def add_meta_layers(log, container: str, layers, poky_dir: str = "/home/yocto/poky"):
    if not layers:
        return

    for rel_path in layers:
        full = f"{poky_dir}/{rel_path}"
        if subprocess.run(f"docker exec {container} test -d {full}", shell=True).returncode != 0:
            log("WARN", f"Layer path not found: {full} – skipping")
            continue

        log("PROCESS", f"Adding layer {rel_path}")
        cmd = (
            f"cd {poky_dir} && source oe-init-build-env build > /dev/null && "
            f"bitbake-layers add-layer ../{rel_path}"
        )
        exec_as_yocto(container, cmd)



def check_layer_dependencies(log, container: str):
    res = run_cmd(f"docker exec {container} bitbake-layers show-layers")
    if "depends on layer" in res or "not enabled in your configuration" in res:
        log("ERROR", "Unresolved Yocto layer dependencies detected! Aborting …")
        print(res)
        sys.exit(1)


# -------------------------------------------------------------
#  BITBAKE BUILD
# -------------------------------------------------------------

def build_image_in_container(
    log,
    container: str,
    poky_dir: str,
    target_image: str,
    *,
    enable_hashserve: bool = False,
    run_qemu: bool = False,
    username: str = "yocto",
):
    log("PROCESS", "Starting BitBake build …")

    if enable_hashserve:
        patch_local_conf_for_hashserve(log, container, f"{poky_dir}/build")

    cmd = (
        f"docker exec --user {username} {container} bash -c 'cd {poky_dir} && "
        f"source oe-init-build-env build && bitbake {target_image}'"
    )

    start = datetime.datetime.now()
    rc = run_cmd_live(cmd)
    dt = (datetime.datetime.now() - start).total_seconds()
    log("INFO", f"BitBake finished in {dt:.0f}s (rc={rc})")

    if rc != 0:
        log("ERROR", "BitBake returned non‑zero exit code – build failed")


# -------------------------------------------------------------
#  BUILD RESULT VERIFICATION
# -------------------------------------------------------------

def verify_build_success(log, container: str, poky_dir: str, target_image: str):
    deploy = f"{poky_dir}/build/tmp/deploy/images"
    out = run_cmd(
        f"docker exec {container} bash -c \"find {deploy} -type f -name '*{target_image}*'\""
    )
    if out:
        log("INFO", "Build completed successfully – artefacts:\n" + out)
    else:
        log("ERROR", "No output images found – build likely failed")


# ----------------- MULTICONFIG COPIER -------------------------

def copy_multiconfig_if_any(container: str, poky_dir: str, build_dir: str):
    """
    Copy every conf/multiconfig/*.conf found under poky/sources into
    build/conf/multiconfig so that any BBMULTICONFIG entry is resolvable.
    """
    cmd = dedent(f"""
        set -e
        mkdir -p {build_dir}/conf/multiconfig
        # only run find if sources/ exists (first run may clone later)
        [ -d {poky_dir}/sources ] && \
          find {poky_dir}/sources -path "*/conf/multiconfig/*.conf" \\
              -exec cp -n {{}} {build_dir}/conf/multiconfig/ \\;
    """)
    run_cmd(f"docker exec --user yocto {container} bash -c '{cmd}'",
            capture_output=False)


# ============================================================
#  MAIN
# ============================================================

def make_parser():
    p = argparse.ArgumentParser(description="Yocto build automation (multi‑board)")
    p.add_argument("--board",               required=True, help="Board profile as defined in config.json")
    p.add_argument("--config",              default="config.json", help="Path to config file")

    # generic knobs (can override JSON)
    p.add_argument("--container",           default="yocto_builder")
    p.add_argument("--image",               default="ubuntu:22.04")
    p.add_argument("--force",               action="store_true", help="Recreate container")

    p.add_argument("--machine")            # overrides profile.machine
    p.add_argument("--target-image")       # overrides profile.target_image
    p.add_argument("--yocto-release")      # overrides profile.yocto_release
    p.add_argument("--poky-branch")        # overrides profile.poky_branch
    p.add_argument("--poky-local")         # overrides profile.poky_local
    p.add_argument("--clone-poky", action="store_true")
    p.add_argument("--clone-poky-location", choices=["host", "container"], default="container")
    p.add_argument("--poky-dir", default="/home/yocto/poky",  
                   help="Path (inside container) where Poky will be cloned")


    p.add_argument("--build-image",         action="store_true", help="Run BitBake after setup")
    p.add_argument("--enable-hashserve",    action="store_true")
    p.add_argument("--run-qemu",            action="store_true")

    # extra layers on top of JSON / defaults
    p.add_argument("--meta-layers",         nargs="+", default=[])

    p.add_argument("--auto-install",        action="store_true")
    p.add_argument("--install-yocto-deps",  action="store_true")
    return p

# -------------------------

def main():
    args = make_parser().parse_args()

    log, log_dir = setup_logging()
    log("INFO", f"Script started – logs at {log_dir}")
    get_system_info(log)

    # ---------- Load board profile ----------
    prof = load_profile(args.config, args.board)

    # apply profile defaults unless overridden via CLI
    for attr in ("machine", "target_image", "yocto_release", "poky_branch", "poky_local"):
        if getattr(args, attr) is None:
            setattr(args, attr, prof[attr])

    # merge meta layers: defaults + profile + CLI
    args.meta_layers = list(dict.fromkeys(DEFAULT_LAYERS + prof["extra_layers"] + args.meta_layers))

    # ---------- Container ----------
    ensure_container_running(log, args.container, args.image, force=args.force)

    # ---------- Toolchain check ----------
    tools_ok = all(check_tool(log, args.container, t, v) for t, v in REQUIRED_TOOLS.items())
    if not tools_ok and args.auto_install:
        install_dependencies(log, args.container)
        tools_ok = all(check_tool(log, args.container, t, v) for t, v in REQUIRED_TOOLS.items())
    if not tools_ok:
        log("ERROR", "Missing or outdated tools – aborting")
        sys.exit(2)

    # optional extra host packages
    if args.install_yocto_deps:
        install_yocto_host_packages(log, args.container)

    # ---------- Clone Poky ----------
    clone_poky_inside_container(log, args.container, args.poky_dir, args.poky_branch, args.poky_local)
    mark_git_safe_directory(log, args.container, args.poky_dir)

    # ---------- Prepare for build ----------
    prepare_non_root_user(log, args.container, "yocto")
    ensure_locale_utf8(log, args.container)
    fix_poky_permissions(log, args.container, args.poky_dir, "yocto")

    # init build dir (creates local.conf)
    run_cmd(
        f"docker exec --user yocto {args.container} bash -c 'cd {args.poky_dir} && source oe-init-build-env build > /dev/null'",
        capture_output=False,
    )

    # clone required external layers (branch matches Yocto release)
    clone_required_layers(log, args.container, args.yocto_release)

    # copy any multiconfig files if the profile wants it
    if prof["multiconfig"]:
        copy_multiconfig_if_any(args.container, args.poky_dir, f"{args.poky_dir}/build")

    # patch local.conf (machine, wic, kria vars, plus custom lines)
    patch_local_conf_machine(log, args.container, args.machine, f"{args.poky_dir}/build")
    patch_local_conf_for_wic(log, args.container, f"{args.poky_dir}/build")
    patch_local_conf_for_kria(log, args.container, f"{args.poky_dir}/build", args.poky_dir)

    if prof["local_conf"]:
        append_block(args.container,
                     f"{args.poky_dir}/build/conf/local.conf",
                     "\n".join(prof["local_conf"]))

    # add layers
    add_meta_layers(log, args.container, args.meta_layers, args.poky_dir)

    # build if requested
    if args.build_image:
        build_image_in_container(log, args.container, args.poky_dir, args.target_image,
                                 enable_hashserve=args.enable_hashserve, run_qemu=args.run_qemu, username="yocto")
        verify_build_success(log, args.container, args.poky_dir, args.target_image)

    log("INFO", "Script completed successfully")

# ============================================================
if __name__ == "__main__":
    main()
