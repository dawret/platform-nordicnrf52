# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
from os.path import join, isfile
from pathlib import Path

from SCons.Script import (
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)


def get_zephyr_config(env, name):
    config_path = join(env.subst("$BUILD_DIR"), "app", "zephyr", ".config")
    if isfile(config_path):
        with open(config_path) as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

try:
    import sdk as nrfutil_sdk
except ImportError:
    framework_dir = Path(platform.get_package_dir("framework-zephyr"))
    if not framework_dir.is_dir():
        raise RuntimeError("framework-zephyr directory not found")
    sys.path.append(str(framework_dir))
    import sdk as nrfutil_sdk
nrfutil = nrfutil_sdk.get_nrfutil(platform)

env.Replace(PROGSUFFIX=".hex")

# Zephyr's final output file is merged.hex
env.Replace(PROGNAME="merged")

"""
Supported upload methods:
* swd: Direct via SWD using JLink, OpenOCD, pyocd and others using west (https://docs.zephyrproject.org/latest/develop/flash_debug/host-tools.html#flash-debug-host-tools)
* dfu_adafruit: DFU Via the UF2 bootloader over usb (using adafruit-nrfutil)
* dfu_uf2: DFU via the UF2 bootloader using .uf2 file copy
* dfu_nordic: DFU via Nordic's Open USB bootloader
* dfu_mcumgr: DFU via MCUBoot using mcumgr (USB, BLE)
"""

upload_port = env.subst("$UPLOAD_PORT")
upload_protocol = env.subst("$UPLOAD_PROTOCOL")
bootloader = board.get("bootloader", "none")


def get_serial_port_info(port_name):
    from serial.tools import list_ports

    for port in list_ports.comports():
        if port.device == port_name:
            return port
    return None


# Auto-detect upload protocol only if not explicitly provided
if not upload_protocol:
    serial_port = get_serial_port_info(upload_port) if upload_port else None
    if upload_port == "swd":
        upload_protocol = "swd"
    elif serial_port is not None:
        if bootloader == "nordic":
            upload_protocol = "dfu_nordic"
        elif bootloader == "adafruit":
            upload_protocol = "dfu_adafruit"
        else:
            raise RuntimeError(f"Invalid bootloader type '{bootloader}'")
    elif (
        bootloader == "adafruit"
        and upload_port
        and Path(upload_port).is_dir()
        and (Path(upload_port) / "INFO_UF2.TXT").is_file()
    ):
        upload_protocol = "dfu_uf2"

if "dfu_adafruit" == upload_protocol:
    env.Append(
        BUILDERS=dict(
            PackageDfu=Builder(
                action=env.VerboseAction(
                    " ".join(
                        [
                            '"$PYTHONEXE"',
                            '"%s"'
                            % join(
                                platform.get_package_dir("tool-adafruit-nrfutil") or "",
                                "adafruit-nrfutil.py",
                            ),
                            "dfu",
                            "genpkg",
                            "--dev-type",
                            "0x0052",
                            "--application",
                            "$SOURCES",
                            "$TARGET",
                        ]
                    ),
                    "Building $TARGET",
                ),
                suffix=".zip",
                src_suffix=".hex",
            )
        )
    )

if "dfu_nordic" == upload_protocol:
    env.Append(
        BUILDERS=dict(
            PackageDfu=Builder(
                action=lambda target, source, env: nrfutil.create_dfu_package(
                    Path(source[0].get_abspath()), Path(target[0].get_abspath())
                ),
                suffix=".zip",
                src_suffix=".hex",
            )
        )
    )

if "dfu_uf2" == upload_protocol:

    def build_uf2(target, source, env):
        family_id = get_zephyr_config(env, "CONFIG_BUILD_OUTPUT_UF2_FAMILY_ID")
        uf2conv = nrfutil_sdk.get_uf2conv(platform)
        cmd = env.VerboseAction(
            " ".join(
                [
                    "$PYTHONEXE",
                    str(uf2conv),
                    str(source[0].get_abspath()),
                    "-c",
                    "-f",
                    str(family_id),
                    "-o",
                    str(target[0].get_abspath()),
                ]
            ),
            "Building $TARGET",
        )
        return cmd(target, source, env)

    env.Append(
        BUILDERS=dict(
            PackageUf2=Builder(
                action=build_uf2,
                suffix=".uf2",
                src_suffix=".hex",
            )
        )
    )


if not env.get("PIOFRAMEWORK"):
    env.SConscript("frameworks/_bare.py")

if "zephyr" in env.get("PIOFRAMEWORK", []):
    env.SConscript(
        join(
            platform.get_package_dir("framework-zephyr"),
            "scripts",
            "platformio",
            "platformio-build-pre.py",
        ),
        exports={"env": env},
    )


env.ProcessProgramDeps()
env.ProcessCompileDbToolchainOption()
env.ProcessProjectDeps()
env.Append(BUILDERS=dict(DummyBuilder=Builder(action=lambda *_: None)))
target_hex = env.WestBuilder(env.subst("$PROGPATH"), [])
target_hexbuildprog = env.Alias("hexbuildprog", target_hex, target_hex)
AlwaysBuild(target_hexbuildprog)
target_firm = target_hex

upload_actions = []

if upload_protocol == "swd":
    if not env.get("WEST_RUNNER"):
        env.Replace(WEST_RUNNER="pyocd")

    def upload_swd(target, source, env):
        sdk = nrfutil_sdk.get_sdk(platform)
        env.Replace(
            UPLOADER="west",
            UPLOADCMD="$UPLOADER flash -r $WEST_RUNNER $UPLOADERFLAGS --build-dir $BUILD_DIR",
            ENV=sdk.env,
        )
        cmd = env.Action("$UPLOADCMD", "Uploading $SOURCE", chdir=sdk.sdk_path)
        return cmd(target, source, env)

    upload_actions = [upload_swd]
elif upload_protocol == "dfu_uf2":
    target_firm = env.PackageUf2(join("$BUILD_DIR", "${PROGNAME}"), target_hex)

    def upload_uf2(target, source, env):
        uf2conv = nrfutil_sdk.get_uf2conv(platform)
        env.Replace(
            UPLOADER=str(uf2conv),
            UPLOADERFLAGS=["-D", "-d", "$UPLOAD_PORT"],
            UPLOADCMD='"$PYTHONEXE" "$UPLOADER" $SOURCE $UPLOADERFLAGS',
        )
        cmd = env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")
        return cmd(target, source, env)

    upload_actions = [upload_uf2]
elif upload_protocol == "dfu_adafruit":
    target_firm = env.PackageDfu(join("$BUILD_DIR", "${PROGNAME}"), target_hex)
    if not env.get("UPLOAD_SPEED"):
        env.Replace(UPLOAD_SPEED="115200")
    env.Replace(
        UPLOADER=join(
            platform.get_package_dir("tool-adafruit-nrfutil") or "",
            "adafruit-nrfutil.py",
        ),
        UPLOADERFLAGS=[
            "dfu",
            "serial",
            "-p",
            "$UPLOAD_PORT",
            "-b",
            "$UPLOAD_SPEED",
            "--singlebank",
            "-t",
            "1200",
        ],
        UPLOADCMD='"$PYTHONEXE" "$UPLOADER" $UPLOADERFLAGS -pkg $SOURCE',
    )
    upload_actions = [
        env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
    ]
elif upload_protocol == "dfu_nordic":
    target_firm = env.PackageDfu(join("$BUILD_DIR", "${PROGNAME}"), target_hex)

    def upload_nordic(target, source, env):
        nrfutil.flash_dfu_package(
            env.subst("$UPLOAD_PORT"),
            env.subst("$UPLOAD_SPEED") or "115200",
            str(source[0]),
        )

    upload_actions = [upload_nordic]
elif upload_protocol == "dfu_mcumgr":
    sys.stderr.write("Error! mcumgr flashing not implemented yet\n")
# custom upload tool
elif upload_protocol == "custom":
    upload_actions = [env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")]

else:
    sys.stderr.write("Warning! Unknown upload protocol %s\n" % upload_protocol)

target_firmbuildprog = env.Alias("firmbuildprog", target_firm, target_firm)

env.AddPlatformTarget("upload", target_firm, upload_actions, "Upload")


#
# Target: Erase Flash
#

env.AddPlatformTarget(
    "erase", None, env.VerboseAction("$ERASECMD", "Erasing..."), "Erase Flash"
)


#
# Default targets
#

Default(target_firmbuildprog)
