import subprocess
from pathlib import Path
import re
import json
import configparser
import click

ROOT_DIR = Path(__file__).parent.parent.resolve()

SAMPLES = [
    "zephyr/samples/basic/blinky",
    "nrf/samples/openthread/cli",
    "nrf/samples/bluetooth/peripheral_uart",
]

BOARDS = {
    "xiao_ble": "xiao_ble",
    "adafruit_feather_nrf52840": "adafruit_feather_nrf52840",
    "nrf5340dk": "nrf5340dk/nrf5340/cpuapp",
    "nrf54l15dk": "nrf54l15df/nrf54l15/cpuapp",
}


def run_pio(args):
    result = subprocess.run(["pio"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"PlatformIO command failed: {' '.join(args)}\n{result.stderr}")
    return result.stdout.strip()


def get_env(build_dir: Path, ini: Path):
    stdout = run_pio(["run", "-d", str(build_dir), "-c", str(ini.absolute()), "--target", "dump_env"])
    if match := re.search(r"==== Build Environment ====\n(.*?)\n==== End Build Environment ====", stdout, re.DOTALL):
        env_str = match.group(1)
        return json.loads(env_str)
    raise RuntimeError("Failed to get build environment")


def generate_env_platformio_ini(target_dir: Path, sdk_version, board: str):
    ini = configparser.ConfigParser()
    ini["platformio"] = {
        "description": "Auto-generated PlatformIO configuration for test samples",
    }
    ini["env:sample_env"] = {
        "platform": "nordicnrf52",
        "custom_framework_version": sdk_version[1:],
        "board": board,
    }
    with open(target_dir / "platformio.ini", "w") as f:
        ini.write(f)
    return target_dir / "platformio.ini"


def generate_sample_platformio_ini(build_dir: Path, sample_name: str, board: str, boards_dir: Path, sdk_version: str):
    ini = configparser.ConfigParser()
    ini["platformio"] = {
        "description": "Auto-generated PlatformIO configuration for test samples",
        "build_dir": str((build_dir / sample_name).absolute()),
        "boards_dir": str(boards_dir.absolute()),
        "src_dir": str(build_dir.absolute()),
    }
    ini["env:sample_env"] = {
        "platform": "nordicnrf52",
        "board": board,
        "framework": "zephyr",
        "custom_framework_version": sdk_version[1:],
        "custom_zephyr_app_dir": sample_name,
        "custom_generate_project_files": "false",
    }
    with open(build_dir / f"platformio_{sample_name}.ini", "w") as f:
        ini.write(f)
    return build_dir / f"platformio_{sample_name}.ini"


def generate_board_file(boards_dir: Path, board_id: str, board_name: str):
    board_file = boards_dir / f"{board_id}.json"
    board_data = {
        "build": {"bsp": {"name": "adafruit"}, "zephyr": {"variant": board_name}, "softdevice": {"sd_fwid": "0x00B6"}},
        "url": "https://esphome.io/",
        "vendor": "esphome",
        "frameworks": ["zephyr"],
        "name": board_id,
        "upload": {"maximum_ram_size": 248832, "maximum_size": 815104, "speed": 115200},
    }
    boards_dir.mkdir(parents=True, exist_ok=True)
    with open(board_file, "w") as f:
        json.dump(board_data, f, indent=4)
    return board_file


def build_sample(sample, sdk_dir, build_dir, board, boards_dir, sdk_version):
    sample_dir = sdk_dir / sample
    sample_name = sample_dir.name
    samples_dir = sample_dir.parent
    ini = generate_sample_platformio_ini(build_dir, sample_name, board, boards_dir, sdk_version)
    print(f"Building sample '{sample}' for board: {board}...")
    run_pio(["run", "-d", str(samples_dir), "-c", str(ini.absolute())])
    if not (build_dir / sample_name / "sample_env" / "merged.hex").is_file():
        raise RuntimeError(f"Failed to build sample '{sample_name}'")


@click.command()
@click.option("-d", "--build-dir", type=str, default=Path("build"))
@click.option("-sv", "--sdk_version", type=str, default="v2.9.2")
def main(build_dir, sdk_version):
    build_dir = Path(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    for b_id, b_name in BOARDS.items():
        board_dir = build_dir / "boards"
        generate_board_file(board_dir, b_id, b_name)
        ini = generate_env_platformio_ini(build_dir, sdk_version, b_id)
        env = get_env(build_dir, ini)
        sdk_dir = Path(env["NRF_SDK_DIR"])
        with open(build_dir / "dummy.c", "w") as f:
            f.write("int main() { return 0; }")
        for s in SAMPLES:
            build_sample(s, sdk_dir, build_dir, b_id, board_dir, sdk_version)


if __name__ == "__main__":
    main()
