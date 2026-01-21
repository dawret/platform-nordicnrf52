from .util import check_command_return
from pathlib import Path
from platformio.proc import exec_command
import json
import shutil


class NrfUtilSdk:
    def __init__(
        self,
        nrfutil,
        version,
        install_location,
        env,
        sdk_path,
        toolchain_path,
        fresh_install=False,
    ):
        self.nrfutil = nrfutil
        self.version = version
        self.install_location = install_location
        self.env = env
        self.sdk_path = Path(sdk_path)
        self.toolchain_path = Path(toolchain_path)
        self.fresh_install = fresh_install


class NrfUtil:
    def __init__(self, nrfutil: Path):
        if not nrfutil.exists():
            raise FileNotFoundError(
                "nrfutil is not installed. Please run the install script."
            )
        self.executable = nrfutil
        self.default_args = ["--json"]

    def run_subcommand(self, name, args):
        cmd = [self.executable, name] + args
        ret = exec_command(cmd)
        check_command_return(ret, f"nrfutil {name} command failed")
        return ret["out"]
    
    def get_sdk(self, version, location: Path):
        path = self.get_sdk_path(version, location)
        if path is None:
            return None
        return NrfUtilSdk(
            nrfutil=self,
            version=version,
            install_location=location,
            env=self.get_sdk_env(version, location),
            sdk_path=path,
            toolchain_path=self.get_toolchain_path(version, location),
            fresh_install=False,
        )


    def install_sdk(self, version, location: Path):
        fresh_install = self.get_sdk_path(version, location) is None
        args = [
            self.executable,
            "sdk-manager",
            "install",
            version,
            "--install-dir",
            str(location),
        ] + self.default_args
        ret = exec_command(args)
        check_command_return(ret, f"Failed to install SDK version {version}")
        shutil.rmtree(location / "downloads", ignore_errors=True)
        print(f"SDK version {version} installed successfully at {location}.")
        return NrfUtilSdk(
            nrfutil=self,
            version=version,
            install_location=location,
            env=self.get_sdk_env(version, location),
            sdk_path=self.get_sdk_path(version, location),
            toolchain_path=self.get_toolchain_path(version, location),
            fresh_install=fresh_install,
        )

    def _list_sdks(self, install_location: Path):
        args = [
            self.executable,
            "sdk-manager",
            "list",
            "--install-dir",
            str(install_location),
        ] + self.default_args
        ret = exec_command(args)
        check_command_return(ret, "Failed to list SDK versions")
        if ret["out"].strip() == "" or "data" not in ret["out"]:
            return []
        out = json.loads(ret["out"])
        return out["data"]["versions"]

    def get_toolchain_path(self, version, install_location: Path):
        for v in self._list_sdks(install_location):
            if v["version"] == version and v["toolchainStatus"] == "installed":
                return v["toolchainPath"]
        raise RuntimeError(f"Toolchain version {version} not found.")

    def get_sdk_path(self, version, install_location: Path):
        for v in self._list_sdks(install_location):
            if v["version"] == version and v["toolchainStatus"] == "installed":
                if len(v["dirNames"]) != 1:
                    raise RuntimeError(
                        f"Multiple SDK directories found for version {version}: {v['dirNames']}"
                    )
                return v["dirNames"][0]
        return None

    def get_sdk_env(self, version, install_location: Path):
        args = [
            self.executable,
            "sdk-manager",
            "toolchain",
            "env",
            "--ncs-version",
            version,
            "--install-dir",
            str(install_location),
        ] + self.default_args
        ret = exec_command(args)
        check_command_return(
            ret, f"Failed to get SDK environment for version {version}"
        )
        data = json.loads(ret["out"])["data"]
        return {e["key"]: e["value"] for e in data["env_variables"]}

    def create_dfu_package(self, input: Path, output: Path):
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
        self.run_subcommand("nrf5sdk-tools", args)
        if not output.is_file():
            raise RuntimeError(f"Failed to create DFU package at {output}")

    def flash_dfu_package(self, port: str, speed: str, package: Path):
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
        self.run_subcommand("nrf5sdk-tools", args)
