from urllib.parse import urljoin
from pathlib import Path
import os
import shutil
import json

from utils.utils import exec_command, get_platorm_slug, download_file
from .nrfutil import NrfUtil, NrfUtilSdk


BASE_NORDIC_URL = "https://files.nordicsemi.com/artifactory/swtools/external/nrfutil/"
PACKAGES_BASE_URL = urljoin(BASE_NORDIC_URL, "packages/")
EXECUTABLE = {
    "version": "1.2.3",
    "base_url": urljoin(BASE_NORDIC_URL, "executables/"),
    "hash": "e0abdbe",
    "filename": "nrfutil-{platform_slug}-{version}-{hash}{extension}",
}
PACKAGE = {
    "version": "8.1.1",
    "base_url": urljoin(PACKAGES_BASE_URL, "nrfutil"),
    "filename": "nrfutil-{platform_slug}-{version}.tar.gz",
}
SUBCOMMANDS = {"sdk-manager": {}, "nrf5sdk-tools": {}}
EXTENSION = ".exe" if os.name == "nt" else ""


def download_components(executable, package, target_location: Path):
    platform_slug = get_platorm_slug()
    target_location.mkdir(parents=True, exist_ok=True)
    package_filename = package["filename"].format(
        platform_slug=platform_slug, version=package["version"]
    )
    files = {
        "exe": (
            target_location / f"nrfutil{EXTENSION}",
            urljoin(
                urljoin(executable["base_url"], platform_slug + "/"),
                executable["filename"].format(
                    platform_slug=platform_slug,
                    version=executable["version"],
                    hash=executable["hash"],
                    extension=EXTENSION,
                ),
            ),
        ),
        "nrfutil": (
            target_location / package_filename,
            urljoin(
                urljoin(package["base_url"], "nrfutil/"),
                package_filename,
            ),
        ),
    }

    for destination, url in files.values():
        if not destination.exists():
            download_file(url, destination)
        else:
            print(f"File {destination} already exists, skipping download.")
    return files


def install_executable(exe, install_location):
    target = install_location / f"nrfutil{EXTENSION}"
    shutil.copy(exe, target)
    target.chmod(target.stat().st_mode | 0o111)  # Make executable
    return target


def install_core_package(nrfutil, core_tarball, version):
    env = os.environ.copy()
    env["NRFUTIL_BOOTSTRAP_TARBALL_PATH"] = str(core_tarball)
    ret = exec_command(
        [nrfutil, "--version", "--json"],
        "Failed to get nrfutil version",
        env=env,
    )
    ret = json.loads(ret.stdout)["data"]
    if ret["version"] != version:
        raise RuntimeError(
            f"nrfutil version mismatch: expected {version}, got {ret['version']}",
        )


def install_subcommand(nrfutil, name, version=None):
    args = ["--json"]
    if version is not None:
        install_name = f"{name}={version}"
        args.append("--force")
    else:
        install_name = name
    exec_command(
        [nrfutil, "install", install_name] + args,
        f"Failed to install subcommand {name}",
    )


def install_nrfutil(downloaded, package, subcommands, install_location):
    install_location.mkdir(parents=True, exist_ok=True)
    nrfutil = install_executable(downloaded["exe"][0], install_location)
    install_core_package(nrfutil, downloaded["nrfutil"][0], package["version"])

    for name, cmd in subcommands.items():
        install_subcommand(nrfutil, name, cmd.get("version"))

    print("nrfutil installed successfully.")
    return nrfutil


def setup(download_dir: Path, install_dir: Path):

    if (install_dir / f"nrfutil{EXTENSION}").exists():
        return NrfUtil(install_dir / f"nrfutil{EXTENSION}")

    components = download_components(EXECUTABLE, PACKAGE, download_dir)
    exe = install_nrfutil(components, PACKAGE, SUBCOMMANDS, install_dir)
    return NrfUtil(exe)


def get_fake_sdk():
    toolchain_path = Path("/var/home/dawret/src/fake_ncs")
    new_path = [
        toolchain_path / "usr" / "local" / "bin",
        toolchain_path / "opt" / "zephyr_sdk" / "arm-zephyr-eabi" / "bin",
        toolchain_path / "opt" / "zephyr_sdk" / "riscv64-zephyr-eabi" / "bin",
    ]
    new_path.extend(os.getenv("PATH", "").split(os.pathsep))
    new_ld_library_path = [
        toolchain_path / "usr" / "local" / "lib",
    ]
    new_ld_library_path.extend(os.getenv("LD_LIBRARY_PATH", "").split(os.pathsep))
    env = {
        "PATH": os.pathsep.join([str(p) for p in new_path]),
        "LD_LIBRARY_PATH": os.pathsep.join([str(p) for p in new_ld_library_path]),
        "PYTHONHOME": "",#str(toolchain_path / "usr" / "local"),
        "PYTHONPATH": "",
        "ZEPHYR_SDK_INSTALL_DIR": str(toolchain_path / "opt" / "zephyr_sdk"),
        "ZEPHYR_TOOLCHAIN_VARIANT": "zephyr",
        "VIRTUALENV": str(toolchain_path / "usr" / "local"),
    }
    print(env)
    return NrfUtilSdk(
        nrfutil=None,
        version="v2.9.2",
        install_location=Path("/var/home/dawret/src/fake_ncs"),
        env=env,
        sdk_path="/var/home/dawret/src/fake_ncs/v2.9.2",
        toolchain_path=Path("/var/home/dawret/src/fake_ncs"),
        fresh_install=False,
    )

"""
os.pathsep.join(
            [
                str(toolchain_path / "usr" / "local" / "lib" / "python3.12"),
                str(
                    toolchain_path
                    / "usr"
                    / "local"
                    / "lib"
                    / "python3.12"
                    / "site-packages"
                ),
            ]
        ),
"""