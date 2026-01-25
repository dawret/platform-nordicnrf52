from pathlib import Path
import os
import platform
import shutil
import tarfile
import yaml

from utils.utils import exec_command, get_platform_string, download_file

EXTENSION = "7z" if os.name == "nt" else "tar.xz"
SDK_BASE_URL = "https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v{version}/"
SDK_FILE_NAME = f"zephyr-sdk-{{version}}_{get_platform_string()}_minimal.{EXTENSION}"
PYTHON_VERSION = "3.12"
PYTHON_SETUP_MODULES = ["west==1.5.0"]
PYTHON_BUILD_MODULES = ["west==1.5.0", "ninja==1.13.0", "cmake==3.21.0", "pyocd==0.42.0"]
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


def setup_python(modules: list[str], path: Path):
    # Run in esphome's env to install python
    exec_command(
        [
            "uv",
            "venv",
            "--python",
            PYTHON_VERSION,
            str(path),
        ],
        "Failed to setup Python virtual environment",
    )
    if os.name == "nt":
        python_exe = path / "Scripts" / "python.exe"
    else:
        python_exe = path / "bin" / "python"
    exec_command(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python_exe),
        ]
        + modules,
        "Failed to install required Python modules",
    )


class BuildEnvironment:
    def __init__(
        self,
        base_dir: Path,
        platform_dir: Path,
        sdk_version: str,
        toolchain_archs: list[str],
    ):
        self.base_dir = base_dir
        self.sdk_version = sdk_version
        self.toolchain_version = None
        self.platform_dir = platform_dir
        self.toolchain_archs = toolchain_archs
        self.fresh_install = False

        self._user_env = {"PATH": [], "LD_LIBRARY_PATH": []}

    @property
    def sdk_dir(self):
        return self.base_dir / self.sdk_version

    @property
    def toolchain_dir(self):
        if not self.toolchain_version:
            raise ValueError("Toolchain version is not set")
        return self.base_dir / "toolchains" / self.toolchain_version

    @property
    def zephyr_sdk_dir(self):
        return self.toolchain_dir / "opt" / "zephyr_sdk"

    @property
    def python_dir(self):
        return self.toolchain_dir / "usr" / "local"

    @property
    def python(self):
        if os.name == "nt":
            return self.python_dir / "Scripts" / "python.exe"
        return self.python_dir / "bin" / "python"

    @property
    def zephyr_dir(self):
        return self.sdk_dir / "zephyr"

    @property
    def uf2conf(self):
        return self.zephyr_dir / "scripts" / "build" / "uf2conv.py"

    @property
    def _path(self):
        path = [self.zephyr_sdk_dir / tc / "bin" for tc in self.toolchain_archs]
        path += [
            self.python_dir / ("Scripts" if os.name == "nt" else "bin"),
        ]
        if os.name == "nt":
            path += [r"C:\\msys64\\usr\\bin\\"]
        return path

    @property
    def env(self):
        env = os.environ.copy()
        env["PATH"] = env["PATH"].split(os.pathsep)
        new_env = {
            "PATH": self._path,
            "ZEPHYR_SDK_INSTALL_DIR": str(self.zephyr_sdk_dir),
            "ZEPHYR_TOOLCHAIN_VARIANT": "zephyr",
            "VIRTUALENV": str(self.python_dir),
            "NRF_SDK_DIR": str(self.sdk_dir),
            "NRF_SDK_VERSION": self.sdk_version,
        }
        env = self._merge_env(env, new_env)
        env = self._merge_env(env, self._user_env)
        for k, v in env.items():
            if isinstance(v, list):
                env[k] = os.pathsep.join([str(p) for p in v])
            else:
                env[k] = str(v)
        return env

    def _python_exe_from_dir(self, python_dir: Path):
        if os.name == "nt":
            return python_dir / "Scripts" / "python.exe"
        return python_dir / "bin" / "python"

    def run(self, cmd: list[str], msg, **kwargs):
        return exec_command(
            cmd,
            msg,
            env=self.env,
            **kwargs,
        )

    def _get_system_path(self):
        return [Path(s) for s in os.environ['PATH'].strip().split(os.pathsep)]

    def add_env(self, additional_env):
        self._user_env = self._merge_env(self._user_env, additional_env)

    def add_path(self, path: list[Path] | Path):
        if isinstance(path, Path):
            path = [path]
        self.add_env({"PATH": path})

    def _merge_env(self, env, additional_env):
        env = env.copy()
        for k, n in additional_env.items():
            if k in env and isinstance(env[k], list):
                if isinstance(n, list):
                    env[k] = n + env[k]
                else:
                    env[k] = str(n).split(os.pathsep) + env[k]
            else:
                env[k] = str(n)
        return env

    def get_toolchain_version(self):
        base_dir = self.sdk_dir / "nrf" / "scripts"
        os_mapping = {
            "windows": base_dir / "tools-versions-win10.yml",
            "linux": base_dir / "tools-versions-linux.yml",
            "darwin": base_dir / "tools-versions-darwin.yml",
        }
        tools_file = os_mapping[platform.system().lower()]
        with open(tools_file) as f:
            tools = yaml.safe_load(f)
        return tools["zephyr-sdk"]["version"]

    def download_zephyr_sdk(self, download_dir: Path, setup_python_dir: Path):
        if (self.zephyr_sdk_dir / "sdk_version").is_file() and all(
            (self.zephyr_sdk_dir / tc).is_dir() for tc in self.toolchain_archs
        ):
            print("Zephyr SDK already installed.")
            return
        # Remove any existing installation
        shutil.rmtree(self.zephyr_sdk_dir, ignore_errors=True)

        url = SDK_BASE_URL + SDK_FILE_NAME
        local_path = download_dir / SDK_FILE_NAME.format(version=self.toolchain_version)
        download_dir.mkdir(parents=True, exist_ok=True)

        # Download the SDK archive
        download_file(
            url.format(version=self.toolchain_version),
            local_path,
        )
        print(f"Extracting Zephyr SDK version {self.toolchain_version}...")
        self.zephyr_sdk_dir.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            exec_command(
                [
                    "7z",
                    "x",
                    str(local_path),
                ],
                "Failed to extract Zephyr SDK archive",
                cwd=str(self.toolchain_dir / "opt"),
            )
            setup_file_name = "setup.cmd"
        else:
            with tarfile.open(local_path, "r:xz") as tar:
                tar.extractall(path=self.toolchain_dir / "opt")
            setup_file_name = "setup.sh"

        # Rename extracted directory to standard name to satisfy CMake
        Path(self.toolchain_dir / "opt" / f"zephyr-sdk-{self.toolchain_version}").rename(self.zephyr_sdk_dir)

        zephyr_sdk_setup = self.zephyr_sdk_dir / setup_file_name

        print(f"Installing Zephyr SDK version {self.toolchain_version}...")
        # Install toolchains
        cmd = [str(zephyr_sdk_setup)]
        for tc in self.toolchain_archs:
            cmd += ["/t" if os.name == "nt" else "-t", tc]
        self.run(cmd, "Failed to install Zephyr SDK toolchain", cwd=str(self.zephyr_sdk_dir))

        # Copy cmake files
        shutil.copytree(
            self.platform_dir / "files" / "cmake",
            self.toolchain_dir / "cmake",
            dirs_exist_ok=True,
        )

    def checkout_nrf_sdk(self, setup_python_dir: Path):
        if (self.sdk_dir / ".west" / "config").is_file():
            # Already checked out
            return
        shutil.rmtree(self.sdk_dir, ignore_errors=True)
        print(f"Cloning nRF Connect SDK version {self.sdk_version}...")
        python_exe = self._python_exe_from_dir(setup_python_dir)
        exec_command(
            [
                str(python_exe),
                "-m",
                "west",
                "init",
                "-m",
                NRF_SDK_URL,
                "-o=--depth=1",
                "--mr",
                self.sdk_version,
                str(self.sdk_dir),
            ],
            "Failed to initialize nRF Connect SDK repository",
            cwd=str(self.base_dir),
        )

    def update_nrf_sdk(self, setup_python_dir: Path):
        print("Updating nRF Connect SDK repository...")
        python_exe = self._python_exe_from_dir(setup_python_dir)
        exec_command(
            [
                str(python_exe),
                "-m",
                "west",
                "update",
                "--narrow",
                "-o=--depth=1",
            ],
            "Failed to update nRF Connect SDK repository",
            cwd=str(self.sdk_dir),
        )

    def install_nrf_sdk_python_requirements(self):
        requirements_files = [
            self.sdk_dir / "zephyr" / "scripts" / "requirements.txt",
            self.sdk_dir / "nrf" / "scripts" / "requirements.txt",
            self.sdk_dir / "bootloader" / "mcuboot" / "scripts" / "requirements.txt",
        ]
        cmd = [
            "uv",
            "pip",
            "install",
            "--python",
            str(self.python),
        ]
        for req in requirements_files:
            cmd.extend(["-r", str(req)])
        print("Installing nRF Connect SDK Python requirements...")
        exec_command(cmd, "Failed to install nRF Connect SDK Python requirements")

    def disable_nrf_modules(self):
        west_yml = self.sdk_dir / "nrf" / "west.yml"
        with open(west_yml) as f:
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

    def setup_nrf_sdk(self, setup_python_dir: Path):
        self.checkout_nrf_sdk(setup_python_dir)
        self.disable_nrf_modules()
        self.update_nrf_sdk(setup_python_dir)

    def setup_install_python(self):
        setup_python_dir = self.base_dir / "python"
        setup_python(PYTHON_SETUP_MODULES, setup_python_dir)
        return setup_python_dir
    
    def setup_toolchain_python(self):
        setup_python(PYTHON_BUILD_MODULES, self.python_dir)
        return self.python_dir

    def setup(self, download_dir: Path):
        valid_marker = self.sdk_dir / ".valid"
        if valid_marker.is_file() and valid_marker.stat().st_mtime > Path(self.sdk_dir / ".west").stat().st_mtime:
            print("nRF Connect SDK already set up.")
            self.toolchain_version = self.get_toolchain_version()
            return self
        valid_marker.unlink(missing_ok=True)
        # Setup a small python venv for checking out nrf sdk
        setup_python_dir = self.setup_install_python()
        self.setup_nrf_sdk(setup_python_dir)

        # Get toolchain version from nrf sdk
        self.toolchain_version = self.get_toolchain_version()

        # Setup the build python environment
        self.setup_toolchain_python()
        # Download and setup Zephyr SDK Toolchain
        self.download_zephyr_sdk(download_dir, setup_python_dir)
        self.install_nrf_sdk_python_requirements()
        print("Success!")
        valid_marker.touch()
        self.fresh_install = True
        return self
