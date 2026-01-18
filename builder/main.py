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

import os
import re
import sys
import time
from os.path import join, isfile
from pathlib import Path

from SCons.Script import (
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)

from platformio.public import list_serial_ports

RESET_TIMEOUT = 10  # seconds
REGEX = re.compile(
    r"USB VID:PID=(?P<vid>[0-9A-Fa-f]{4}):(?P<pid>[0-9A-Fa-f]{4}) SER=(?P<ser>[^ ]+)"
)

# All possible values of the Adafruit UF2 Bootloader VID/PID.
# Generated with scripts/vid_dump.py

UF2_VIDS_PIDS = {
    0x239A: [
        0x40,
        0x45,
        0x87,
        0x88,
        0x10B,
        0x10D,
        0x10E,
        0x51,
        0x52,
        0x93,
        0xD8,
        0xDA,
        0x9F,
        0x63,
        0x64,
        0x29,
        0x2A,
        0x7B,
        0xBB,
        0x71,
        0xB3,
        0x79,
        0x3B,
        0x7F,
        0x3F,
    ],
    0x1209: [0x7380, 0x7381, 0x7A01, 0x5284, 0x805A, 0xCECE],
    0x1D50: [0x6160, 0x6157, 0x616F],
    0x2886: [0x44, 0x45, 0x57, 0xF00E, 0xF00F],
    0x16D0: [0x10ED],
    0x1B4F: [0x22, 0x23],
}

NORDIC_VIDS_PIDS = {0x1915: [0x521F]}  # Nordic's Open Bootloader VID/PID

VIDS_PIDS = {**UF2_VIDS_PIDS, **NORDIC_VIDS_PIDS}


def get_serial_port_info(desc):
    match = REGEX.search(desc)
    if match:
        return (
            int(match.group("vid"), 16),
            int(match.group("pid"), 16),
            match.group("ser"),
        )
    print(f"Warning! Cannot detect VID:PID and SER of the current serial port: {desc}")
    return None, None, None


def reset_to_bootloader(target, source, env):  # pylint: disable=W0613,W0621
    before_ports = list_serial_ports()
    current_port = None
    for port in before_ports:
        if port["port"] == env.subst("$UPLOAD_PORT"):
            current_port = port
    if not current_port:
        print("Warning! Invalid serial port.")
        return
    vid, pid, ser = get_serial_port_info(current_port["hwid"])
    if vid in VIDS_PIDS and pid in VIDS_PIDS[vid]:
        print("Device is already in bootloader mode.")
        env.Replace(UPLOAD_PORT=current_port["port"])
        return

    print("Resetting device into bootloader mode...")
    env.FlushSerialBuffer("$UPLOAD_PORT")
    env.TouchSerialPort("$UPLOAD_PORT", 1200)

    start_time = time.time()
    while (time.time() - start_time) < RESET_TIMEOUT:
        ports = list_serial_ports()
        for port in ports:
            if port["hwid"] == "n/a":
                continue
            new_vid, new_pid, new_ser = get_serial_port_info(port["hwid"])
            if not new_vid or not new_pid or not new_ser:
                continue
            if ser == new_ser and (
                new_vid in VIDS_PIDS and new_pid in VIDS_PIDS[new_vid]
            ):
                print(f"Device reset detected on port {port['port']}")
                env.Replace(UPLOAD_PORT=port["port"])
                return
        time.sleep(0.5)


def get_zephyr_config(env, name):
    config_path = join(env.subst("$BUILD_DIR"), "zephyr", "zephyr", ".config")
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
nrfutil = nrfutil_sdk.get_nrfutil(env)

env.Replace(PROGSUFFIX=".hex")

# Zephyr's final output file is merged.hex
env.Replace(PROGNAME="merged")


env.Append(
    BUILDERS=dict(
        PackageDfuAdafruit=Builder(
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

env.Append(
    BUILDERS=dict(
        PackageDfuNordic=Builder(
            action=lambda target, source, env: nrfutil.create_dfu_package(
                Path(source[0].get_abspath()), Path(target[0].get_abspath())
            ),
            suffix=".zip",
            src_suffix=".hex",
        )
    )
)


def build_uf2(target, source, env):
    family_id = get_zephyr_config(env, "CONFIG_BUILD_OUTPUT_UF2_FAMILY_ID")
    uf2conv = nrfutil_sdk.get_uf2conv(env)
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


def upload_swd(runner):
    jlink_dir = platform.get_package_dir("tool-jlink")

    def upload_action(target, source, env):
        sdk = nrfutil_sdk.get_sdk(env)
        west_env = sdk.env.copy()
        west_env["PATH"] = f"{jlink_dir}{os.pathsep}{west_env.get('PATH','')}"
        west_env["LD_LIBRARY_PATH"] = (
            f"{jlink_dir}{os.pathsep}{west_env.get('LD_LIBRARY_PATH','')}"
        )
        env.Replace(
            UPLOADER="west",
            WEST_RUNNER=runner,
            UPLOADERFLAGS=[],
            UPLOADCMD="$UPLOADER flash -r $WEST_RUNNER $UPLOADERFLAGS --build-dir $BUILD_DIR",
            ENV=west_env,
        )
        cmd = env.Action("$UPLOADCMD", "Uploading $SOURCE", chdir=str(sdk.sdk_path))
        return cmd(target, source, env)

    return [upload_action]


target_uf2 = env.PackageUf2(join("$BUILD_DIR", "${PROGNAME}"), target_hex)


def upload_uf2_adafruit():
    def upload_action(target, source, env):
        uf2conv = nrfutil_sdk.get_uf2conv(env)
        env.Replace(
            UPLOADER=str(uf2conv),
            UPLOADERFLAGS=["-D", "-d", "$UPLOAD_PORT"],
            UPLOADCMD='"$PYTHONEXE" "$UPLOADER" $SOURCE $UPLOADERFLAGS',
        )
        cmd = env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE")
        return cmd(target, source, env)

    return [
        upload_action,
    ]


target_dfu_adafruit = env.PackageDfuAdafruit(
    join("$BUILD_DIR", "${PROGNAME}_adafruit"), target_hex
)


def upload_serial_adafruit():
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
        ],
        UPLOADCMD='"$PYTHONEXE" "$UPLOADER" $UPLOADERFLAGS -pkg $SOURCE',
    )
    return [
        env.Action(reset_to_bootloader),
        env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
    ]


target_dfu_nordic = env.PackageDfuNordic(
    join("$BUILD_DIR", "${PROGNAME}_nordic"), target_hex
)


def upload_serial_nordic():
    def upload_nordic(target, source, env):
        nrfutil.flash_dfu_package(
            env.subst("$UPLOAD_PORT"),
            env.subst("$UPLOAD_SPEED") or "115200",
            str(source[0]),
        )

    return [
        env.Action(reset_to_bootloader),
        env.VerboseAction(upload_nordic, "Uploading $SOURCE (serial_nordic)"),
    ]


env.AddPlatformTarget(
    "flash_pyocd", target_hex, upload_swd("pyocd"), "Flash using pyOCD"
)
env.AddPlatformTarget(
    "flash_jlink", target_hex, upload_swd("jlink"), "Flash using J-Link"
)
env.AddPlatformTarget("flash_uf2", target_uf2, upload_uf2_adafruit(), "Flash using UF2")
env.AddPlatformTarget(
    "flash_serial_adafruit",
    target_dfu_adafruit,
    upload_serial_adafruit(),
    "Flash using Adafruit uf2 bootloader (serial)",
)
env.AddPlatformTarget(
    "flash_serial_nordic",
    target_dfu_nordic,
    upload_serial_nordic(),
    "Flash using Nordic bootloader (serial)",
)

# For compatibility
env.Alias("upload", "flash_serial_adafruit")

Default(target_hex)
