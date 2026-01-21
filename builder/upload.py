from .utils.usb_vids import VIDS_PIDS
from .utils import sdk as nrfutil_sdk

import os
from os.path import join
from pathlib import Path
import re
import time

from platformio.public import list_serial_ports

from SCons.Script import (
    DefaultEnvironment,
)

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

RESET_TIMEOUT = 10  # seconds
REGEX = re.compile(
    r"USB VID:PID=(?P<vid>[0-9A-Fa-f]{4}):(?P<pid>[0-9A-Fa-f]{4}) SER=(?P<ser>[^ ]+)"
)


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


def upload_swd(runner=None):
    jlink_dir = platform.get_package_dir("tool-jlink")

    def upload_action(target, source, env):
        sdk = nrfutil_sdk.get_sdk(env)
        west_env = sdk.env.copy()
        west_env["PATH"] = f"{jlink_dir}{os.pathsep}{west_env.get('PATH','')}"
        west_env["LD_LIBRARY_PATH"] = (
            f"{jlink_dir}{os.pathsep}{west_env.get('LD_LIBRARY_PATH','')}"
        )
        if runner is not None:
            west_runner = f"--runner {runner}"
        else:
            print("Using West default runner")
            west_runner = ""
        env.Replace(
            UPLOADER="west",
            WEST_RUNNER=west_runner,
            UPLOADCMD="$UPLOADER flash $WEST_RUNNER --build-dir $BUILD_DIR -- $UPLOADERFLAGS",
            ENV=west_env,
        )
        print(env.subst("$UPLOADCMD"))
        cmd = env.Action("$UPLOADCMD", "Uploading $SOURCE", chdir=str(sdk.sdk_path))
        return cmd(target, source, env)

    return [upload_action]


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


def upload_serial_adafruit():
    def upload_action(target, source, env):
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
            cmd=env.VerboseAction("$UPLOADCMD", "Uploading $SOURCE"),
        )

    return [
        env.Action(reset_to_bootloader),
        upload_action,
    ]


def upload_serial_nordic():
    def upload_nordic(target, source, env):
        nrfutil_sdk.get_nrfutil(env).flash_dfu_package(
            env.subst("$UPLOAD_PORT"),
            env.subst("$UPLOAD_SPEED") or "115200",
            Path(str(source[0])),
        )

    return [
        env.Action(reset_to_bootloader),
        env.VerboseAction(upload_nordic, "Uploading $SOURCE (serial_nordic)"),
    ]


def setup_upload_targets(
    env, target_hex, target_uf2, target_dfu_adafruit, target_dfu_nordic
):
    env.AddPlatformTarget(
        "flash_west", target_hex, upload_swd(), "Flash using West's default runner"
    )
    env.AddPlatformTarget(
        "flash_pyocd", target_hex, upload_swd("pyocd"), "Flash using pyOCD"
    )
    env.AddPlatformTarget(
        "flash_jlink", target_hex, upload_swd("jlink"), "Flash using J-Link"
    )
    env.AddPlatformTarget(
        "flash_uf2", target_uf2, upload_uf2_adafruit(), "Flash using UF2"
    )
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
