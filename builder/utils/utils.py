import platform
from pathlib import Path
import urllib.request
import subprocess


def exec_command(cmd, msg, **kwargs):
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        **kwargs,
    )
    if result.returncode != 0:
        raise RuntimeError(f"{msg}:\ncmd: {cmd}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result


def get_platform_string():
    os_map = {
        "linux": "linux",
        "darwin": "macos",
        "windows": "windows",
    }

    arch_map = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }
    system = platform.system().lower()
    machine = platform.machine().lower()

    os_name = os_map.get(system, system)
    arch_name = arch_map.get(machine, machine)

    return f"{os_name}-{arch_name}"


def get_platform_slug():
    if platform.system().lower() == "windows":
        print(f"Comparison: {platform.machine() != 'AMD64'}")
        if platform.machine() != "x86_64" and platform.machine() != "AMD64":
            raise RuntimeError(f"Unsupported architecture: {platform.machine()} on Windows")
        return "x86_64-pc-windows-msvc"
    elif platform.system().lower() == "linux":
        if platform.machine() == "x86_64":
            return "x86_64-unknown-linux-gnu"
        elif platform.machine() == "arm64" or platform.machine() == "aarch64":
            return "aarch64-unknown-linux-gnu"
        else:
            raise RuntimeError(
                f"Unsupported architecture: {platform.machine()} on Linux",
            )
    elif platform.system().lower() == "darwin":
        if platform.machine() == "x86_64":
            return "x86_64-apple-darwin"
        elif platform.machine() == "arm64":
            return "aarch64-apple-darwin"
        else:
            raise RuntimeError(
                f"Unsupported architecture: {platform.machine()} on macOS",
            )
    else:
        raise RuntimeError(f"Unsupported operating system: {platform.system()}")


def download_file(url: str, destination: Path):
    print(f"Downloading {url}...")
    with urllib.request.urlopen(url) as response, open(destination, "wb") as out_file:
        out_file.write(response.read())
    print(f"Downloaded to {destination}")
