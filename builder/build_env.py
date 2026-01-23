import os

from pathlib import Path
from utils.utils import exec_command


class BuildEnv:
    def __init__(
        self,
        base_dir: Path,
        platform_dir: Path,
        sdk_version: str,
    ):
        self.base_dir = base_dir
        self.sdk_version = sdk_version
        self.platform_dir = platform_dir
        self.fresh_install = False

        self._env = {
            "PATH": self._get_clean_env(),
        }

    @property
    def sdk_dir(self):
        return self.base_dir / self.sdk_version
    
    @property
    def toolchain_dir(self):
        return self.base_dir / "toolchain"
    
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
    def env(self):
        env = {}
        for k, v in self._env.items():
            if isinstance(v, list):
                env[k] = os.pathsep.join(reversed([str(p) for p in v]))
            elif v:
                env[k] = str(v)
        return env

    def set_env(self, key: str, value: str | Path):
        self._env[key] = value

    def append_path(self, path: list[Path] | Path):
        if not isinstance(path, list):
            path = [path]
        self._env["PATH"].extend(path)

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
