from pathlib import Path
import os
import platform
import shutil
import tarfile
import yaml

from utils.utils import exec_command, get_platform_string, download_file
from build_env import BuildEnv

EXTENSION = "7z" if os.name == "nt" else "tar.xz"
SDK_BASE_URL = (
    f"https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{{version}}/"
)
SDK_FILE_NAME = f"zephyr-sdk-{{version}}_{get_platform_string()}_minimal.{EXTENSION}"
PYTHON_VERSION = "3.12"
PYTHON_SETUP_MODULES = ["west", "py7zr"]
PYTHON_BUILD_MODULES = ["west", "ninja", "cmake", "pyocd"]
ZEPHYR_TOOLCHAINS = ["arm-zephyr-eabi", "riscv64-zephyr-elf"]
NRF_SDK_URL = "https://github.com/nrfconnect/sdk-nrf"
NRF_DISABLED_MODULES = [
    "matter",
    "lvgl",
    "trusted-firmware-m",
    "sidewalk",
    "hal_st",
    "hostap",
    "loramac-node",
    "tf-m-tests",
    "psa-arch-tests",
    "qcbor",
]


def get_toolchain_version(build_env: BuildEnv):
    base_dir = build_env.sdk_dir / "nrf" / "scripts"
    os_mapping = {
        "windows": base_dir / "tools-versions-win10.yml",
        "linux": base_dir / "tools-versions-linux.yml",
        "darwin": base_dir / "tools-versions-darwin.yml",
    }
    tools_file = os_mapping[platform.system().lower()]
    with open(tools_file) as f:
        tools = yaml.safe_load(f)
    return tools["zephyr-sdk"]["version"]


def setup_python(build_env: BuildEnv, modules: list[str], path: Path):
    # Run in esphome's env to install python
    ret = exec_command(
        [
            "uv",
            "venv",
            "--python",
            PYTHON_VERSION,
            str(path),
        ],
        "Failed to setup Python virtual environment",
    )
    ret = exec_command(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(path / "bin" / "python"),
        ]
        + modules,
        "Failed to install required Python modules",
    )
    build_env.append_path(path / "bin")
    build_env.set_env("VIRTUALENV", path)


def download_zephyr_sdk(version, build_env: BuildEnv, download_dir: Path):
    if (build_env.zephyr_sdk_dir / "sdk_version").is_file():
        print("Zephyr SDK already installed.")
        return
    # Remove any existing installation
    shutil.rmtree(build_env.zephyr_sdk_dir, ignore_errors=True)

    url = SDK_BASE_URL + SDK_FILE_NAME
    local_path = download_dir / SDK_FILE_NAME.format(version=version)
    download_dir.mkdir(parents=True, exist_ok=True)

    # Download the SDK archive
    download_file(
        url.format(version=version),
        local_path,
    )
    print(f"Extracting Zephyr SDK version {version}...")
    build_env.zephyr_sdk_dir.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        build_env.run(
            ["py7zr", "x", str(local_path)],
            "Failed to extract Zephyr SDK archive",
            cwd=str(build_env.toolchain_dir / "opt"),
        )
        setup_file_name = "setup.cmd"
    else:
        with tarfile.open(local_path, "r:xz") as tar:
            tar.extractall(path=build_env.toolchain_dir / "opt")
        setup_file_name = "setup.sh"

    # Rename extracted directory to standard name to satisfy CMake
    Path(build_env.toolchain_dir / "opt" / f"zephyr-sdk-{version}").rename(
        build_env.zephyr_sdk_dir
    )

    zephyr_sdk_setup = build_env.zephyr_sdk_dir / setup_file_name

    print(f"Installing Zephyr SDK version {version}...")
    # Install toolchains
    cmd = [str(zephyr_sdk_setup)]
    for tc in ZEPHYR_TOOLCHAINS:
        cmd += ["-t", tc]
    build_env.run(
        cmd, "Failed to install Zephyr SDK toolchain", cwd=str(build_env.zephyr_sdk_dir)
    )

    # Copy cmake files
    shutil.copytree(
        build_env.platform_dir / "files" / "cmake",
        build_env.toolchain_dir / "cmake",
        dirs_exist_ok=True,
    )


def setup_zephyr_sdk_paths(build_env: BuildEnv):
    # Add toolchains to PATH
    build_env.append_path(
        [build_env.zephyr_sdk_dir / tc / "bin" for tc in ZEPHYR_TOOLCHAINS]
    )
    # Add host tools to PATH, if available
    if Path(build_env.zephyr_sdk_dir / "sysroots" / "x86_64-pokysdk-linux").is_dir():
        build_env.append_path(
            build_env.zephyr_sdk_dir
            / "sysroots"
            / "x86_64-pokysdk-linux"
            / "usr"
            / "bin"
        )

    build_env.set_env("ZEPHYR_SDK_INSTALL_DIR", build_env.zephyr_sdk_dir)
    build_env.set_env("ZEPHYR_TOOLCHAIN_VARIANT", "zephyr")


def checkout_nrf_sdk(version, build_env: BuildEnv):
    if (build_env.sdk_dir / ".west" / "config").is_file():
        # Already checked out
        return
    shutil.rmtree(build_env.sdk_dir, ignore_errors=True)
    print(f"Cloning nRF Connect SDK version {version}...")
    build_env.run(
        [
            "west",
            "init",
            "-m",
            NRF_SDK_URL,
            "-o=--depth=1",
            "--mr",
            version,
            str(build_env.sdk_dir),
        ],
        "Failed to initialize nRF Connect SDK repository",
        cwd=str(build_env.base_dir),
    )


def update_nrf_sdk(build_env: BuildEnv):
    print("Updating nRF Connect SDK repository...")
    build_env.run(
        ["west", "update", "--narrow", "-o=--depth=1"],
        "Failed to update nRF Connect SDK repository",
        cwd=str(build_env.sdk_dir),
    )


def install_nrf_sdk_python_requirements(build_env: BuildEnv):
    requirements_files = [
        build_env.sdk_dir / "zephyr" / "scripts" / "requirements.txt",
        build_env.sdk_dir / "nrf" / "scripts" / "requirements.txt",
        build_env.sdk_dir / "bootloader" / "mcuboot" / "scripts" / "requirements.txt",
    ]
    cmd = [
        "uv",
        "pip",
        "install",
        "--python",
        str(build_env.python),
    ]
    for req in requirements_files:
        cmd.extend(["-r", str(req)])
    print(f"Installing nRF Connect SDK Python requirements...")
    exec_command(cmd, "Failed to install nRF Connect SDK Python requirements")


def disable_nrf_modules(build_env: BuildEnv):
    west_yml = build_env.sdk_dir / "nrf" / "west.yml"
    with open(west_yml, "r") as f:
        west_config = yaml.safe_load(f)
    new_west_config = west_config.copy()
    projects = west_config["manifest"]["projects"]

    # Filter out disabled modules and update zephyr project
    filtered_projects = []
    for project in projects:
        if project["name"] in NRF_DISABLED_MODULES:
            continue  # Skip this project entirely
        if project["name"] == "zephyr":
            # Remove disabled modules from zephyr's name-allowlist
            for mod in NRF_DISABLED_MODULES:
                try:
                    project["import"]["name-allowlist"].remove(mod)
                except (ValueError, KeyError):
                    pass
        filtered_projects.append(project)

    new_west_config["manifest"]["projects"] = filtered_projects

    with open(west_yml, "w") as f:
        yaml.dump(new_west_config, f)


def setup_nrf_sdk(version, build_env: BuildEnv):
    checkout_nrf_sdk(version, build_env)
    disable_nrf_modules(build_env)
    update_nrf_sdk(build_env)


def setup(sdk_version: str, build_env: BuildEnv, download_dir: Path):
    valid_marker = build_env.sdk_dir / ".valid"
    if (
        valid_marker.is_file()
        and valid_marker.stat().st_mtime
        > Path(build_env.sdk_dir / ".west").stat().st_mtime
    ):
        print("nRF Connect SDK already set up.")
        return build_env
    
    valid_marker.unlink(missing_ok=True)
    # Setup a small python venv for checking out nrf sdk
    setup_python(build_env, PYTHON_SETUP_MODULES, build_env.base_dir / "python")
    setup_nrf_sdk(sdk_version, build_env)

    # Get toolchain version from nrf sdk
    toolchain_version = get_toolchain_version(build_env)
    build_env.toolchain_version = toolchain_version

    # Download and setup Zephyr SDK Toolchain
    download_zephyr_sdk(toolchain_version, build_env, download_dir)
    setup_zephyr_sdk_paths(build_env)

    # Setup the build python environment
    setup_python(build_env, PYTHON_BUILD_MODULES, build_env.python_dir)
    install_nrf_sdk_python_requirements(build_env)
    print("Success!")
    valid_marker.touch()
    build_env.fresh_install = True
    return build_env
