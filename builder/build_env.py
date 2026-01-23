import os

from pathlib import Path
from utils.utils import exec_command


class BuildEnv:
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
        self._base_path = self._get_clean_env()

        self._user_env = {"PATH": []}

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
        return self.python_dir / "bin" / "python"

    @property
    def zephyr_dir(self):
        return self.sdk_dir / "zephyr"
    
    @property
    def path(self):
        path = [
            *self._base_path,
            self.python_dir / "bin",
        ]
        path += [self.zephyr_sdk_dir / tc / "bin" for tc in self.toolchain_archs]
        path += self._user_env.get("PATH", [])
        return path

    @property
    def env(self):
        env = {
            "PATH": os.pathsep.join([str(p) for p in self.path]),
            "ZEPHYR_SDK_INSTALL_DIR": str(self.zephyr_sdk_dir),
            "ZEPHYR_TOOLCHAIN_VARIANT": "zephyr",
            "VIRTUALENV": str(self.python_dir),
        }
        return env

    def run(self, cmd: list[str], msg, **kwargs):
        return exec_command(
            cmd,
            msg,
            env=self.env,
            **kwargs,
        )

    def _get_clean_env(self):
        if os.name == "nt":
            res = exec_command(
                ["cmd", "/c", "echo %PATH%"], "Failed to get system path", env={}
            )
        else:
            shell = os.environ.get("SHELL", "/bin/sh")
            res = exec_command(
                [shell, "-c", "echo $PATH"], "Failed to get system path", env={}
            )
        return [Path(s) for s in res.stdout.strip().split(os.pathsep)]
