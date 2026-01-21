from urllib.parse import urljoin
import platform
import sys
import urllib.request
from pathlib import Path
from platformio.proc import exec_command
import os
import shutil
import json
from .util import check_command_return

ROOT_DIR = Path(__file__).parent.parent.resolve()
DOWNLOAD_LOCATION = ROOT_DIR / "downloads"
INSTALL_LOCATION = ROOT_DIR / "installed"
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


def get_platorm_slug():
    if platform.system().lower() == "windows":
        if platform.machine() != "x86_64" and platform.machine() != "AMD64":
            print(
                f"Unsupported architecture: {platform.machine()} on Windows",
                file=sys.stderr,
            )
            exit(1)
        return "x86_64-pc-windows-msvc"
    elif platform.system().lower() == "linux":
        if platform.machine() == "x86_64":
            return "x86_64-unknown-linux-gnu"
        elif platform.machine() == "arm64" or platform.machine() == "aarch64":
            return "aarch64-unknown-linux-gnu"
        else:
            print(
                f"Unsupported architecture: {platform.machine()} on Linux",
                file=sys.stderr,
            )
            exit(1)
    elif platform.system().lower() == "darwin":
        if platform.machine() == "x86_64":
            return "x86_64-apple-darwin"
        elif platform.machine() == "arm64":
            return "aarch64-apple-darwin"
        else:
            print(
                f"Unsupported architecture: {platform.machine()} on macOS",
                file=sys.stderr,
            )
            exit(1)
    else:
        print(f"Unsupported operating system: {platform.system()}", file=sys.stderr)
        exit(1)


def download_file(url: str, destination: Path):
    print(f"Downloading {url}...")
    with urllib.request.urlopen(url) as response, open(destination, "wb") as out_file:
        out_file.write(response.read())
    print(f"Downloaded to {destination}")


def download_components(executable, package, target_location: Path):
    platform_slug = get_platorm_slug()
    target_location.mkdir(parents=True, exist_ok=True)
    package_filename = package["filename"].format(
        platform_slug=platform_slug, version=package["version"]
    )
    extension = ".exe" if platform.system().lower() == "windows" else ""
    files = {
        "exe": (
            target_location / f"nrfutil{extension}",
            urljoin(
                urljoin(executable["base_url"], platform_slug + "/"),
                executable["filename"].format(
                    platform_slug=platform_slug,
                    version=executable["version"],
                    hash=executable["hash"],
                    extension=extension,
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
    extension = ".exe" if platform.system().lower() == "windows" else ""
    target = install_location / f"nrfutil{extension}"
    shutil.copy(exe, target)
    target.chmod(target.stat().st_mode | 0o111)  # Make executable
    return target


def install_core_package(nrfutil, core_tarball, version):
    env = os.environ.copy()
    env["NRFUTIL_BOOTSTRAP_TARBALL_PATH"] = str(core_tarball)
    ret = exec_command([nrfutil, "--version", "--json"], env=env)
    check_command_return(ret, "Failed to install nrfutil core tarball")
    ret = json.loads(ret["out"])["data"]
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
    ret = exec_command([nrfutil, "install", install_name] + args)
    check_command_return(ret, f"Failed to install subcommand {name}")


def install_nrfutil(downloaded, package, subcommands, install_location):
    install_location.mkdir(parents=True, exist_ok=True)
    nrfutil = install_executable(downloaded["exe"][0], install_location)
    install_core_package(nrfutil, downloaded["nrfutil"][0], package["version"])

    for name, cmd in subcommands.items():
        install_subcommand(nrfutil, name, cmd.get("version"))

    print("nrfutil installed successfully.")
    return nrfutil


def setup():
    from .nrfutil import NrfUtil
    extension = ".exe" if platform.system().lower() == "windows" else ""
    if (INSTALL_LOCATION / f"nrfutil{extension}").exists():
        return NrfUtil(INSTALL_LOCATION / f"nrfutil{extension}")

    components = download_components(EXECUTABLE, PACKAGE, DOWNLOAD_LOCATION)
    exe = install_nrfutil(components, PACKAGE, SUBCOMMANDS, INSTALL_LOCATION)
    return NrfUtil(exe)
