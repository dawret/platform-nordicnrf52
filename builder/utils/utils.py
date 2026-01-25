import platform
from pathlib import Path
import urllib.request
import subprocess
import threading


def exec_command(cmd, msg="Command failed", verbose=False, **kwargs):
    def read_stream(stream, output_list):
        for line in stream:
            output_list.append(line)
            if verbose:
                print(line, end="")

    stdout_lines = []
    stderr_lines = []

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        **kwargs,
    ) as process:
        stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines))
        stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines))

        stdout_thread.start()
        stderr_thread.start()

        stdout_thread.join()
        stderr_thread.join()

    process.stdout = "".join(stdout_lines)
    process.stderr = "".join(stderr_lines)

    if process.returncode != 0:
        if verbose:
            # If verbose, the output has already been printed
            raise RuntimeError(f"{msg}: Command returned non-zero exit status {process.returncode}")
        else:
            raise RuntimeError(
                f"{msg}: Command {cmd} returned non-zero exit status {process.returncode}: \n{process.stdout}\n{process.stderr}"
            )

    return process


def is_arm64():
    machine = platform.machine().lower()
    return machine in ("aarch64", "arm64")


def is_amd64():
    machine = platform.machine().lower()
    return machine in ("x86_64", "amd64")


# For downloading Zephyr SDK
def get_platform_string():
    os_map = {
        "linux": "linux",
        "darwin": "macos",
        "windows": "windows",
    }

    system = platform.system().lower()
    machine = platform.machine().lower()

    os_name = os_map.get(system, system)
    arch_name = "aarch64" if is_arm64() else "x86_64" if is_amd64() else machine

    return f"{os_name}-{arch_name}"


# For downloading nrfutil
def get_platform_slug():
    if platform.system().lower() == "windows":
        print(f"Comparison: {platform.machine() != 'AMD64'}")
        if not is_amd64():
            raise RuntimeError(f"Unsupported architecture: {platform.machine()} on Windows")
        return "x86_64-pc-windows-msvc"
    elif platform.system().lower() == "linux":
        if is_amd64():
            return "x86_64-unknown-linux-gnu"
        elif is_arm64():
            return "aarch64-unknown-linux-gnu"
        else:
            raise RuntimeError(
                f"Unsupported architecture: {platform.machine()} on Linux",
            )
    elif platform.system().lower() == "darwin":
        if is_amd64():
            return "x86_64-apple-darwin"
        elif is_arm64():
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
