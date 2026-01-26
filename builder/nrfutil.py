from pathlib import Path
import shutil
from urllib.parse import urljoin
import os

from utils import download_file, get_platform_slug, get_platform_string
from sdk_manager import BuildEnvironment

NORDIC_BASE_URL = "https://files.nordicsemi.com/artifactory/swtools/external/nrfutil/executables/"
EXTENSION = ".exe" if os.name == "nt" else ""
SUBCOMMANDS = ["device"]
if get_platform_string() != "linux-aarch64":
    # Linux arm64 currently doesn't support this module
    SUBCOMMANDS.append("nrf5sdk-tools")


class NrfUtil:
    def __init__(self, path: Path, build_env: BuildEnvironment):
        self.path = path
        self.build_env = build_env
        self.default_args = ["--json"]

    @property
    def executable(self):
        return self.path / f"nrfutil{EXTENSION}"

    @property
    def home(self):
        return self.path / ".nrfutil"

    def run(self, cmd, **kwargs):
        full_cmd = [self.executable] + cmd
        ret = self.build_env.run(
            full_cmd,
            f"nrfutil command {' '.join(cmd)} failed",
            **kwargs,
        )
        return ret.stdout

    def setup(self, download_dir: Path):
        self.build_env.add_env({"PATH": self.path, "NRFUTIL_HOME": self.home})
        if self.executable.is_file():
            return
        download_file(
            urljoin(NORDIC_BASE_URL, get_platform_slug() + f"/nrfutil{EXTENSION}"),
            download_dir / f"nrfutil{EXTENSION}",
        )
        self.path.mkdir(parents=True, exist_ok=True)
        shutil.move(download_dir / f"nrfutil{EXTENSION}", self.executable)
        self.executable.chmod(self.executable.stat().st_mode | 0o111)  # Make executable

        self.run(["install"] + SUBCOMMANDS)

    def create_dfu_package(self, input: Path, output: Path):
        if get_platform_string() == "linux-aarch64":
            raise RuntimeError("Nordic DFU is not supported on Linux aarch64")
        args = [
            "pkg",
            "generate",
            "--hw-version",
            "52",
            "--sd-req",
            "0x00",
            "--application",
            str(input),
            "--application-version",
            "1",
            str(output),
        ]
        self.run(["nrf5sdk-tools"] + args)
        if not output.is_file():
            raise RuntimeError(f"Failed to create DFU package at {output}")

    def flash_dfu_package(self, port: str, speed: str, package: Path):
        if get_platform_string() == "linux-aarch64":
            raise RuntimeError("Nordic DFU is not supported on Linux aarch64")
        args = [
            "dfu",
            "usb-serial",
            "-pkg",
            str(package),
            "-p",
            port,
            "-b",
            speed,
        ]
        self.run(["nrf5sdk-tools"] + args)
