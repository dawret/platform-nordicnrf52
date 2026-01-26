import sys
from pathlib import Path
import click

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "builder"))

from builder import nrfutil
from builder.sdk_manager import BuildEnvironment


@click.group()
def main():
    pass


@main.command("checkout_sdk")
@click.argument("sdk_version")
def checkout_sdk(sdk_version):
    build_env = BuildEnvironment(
        base_dir=ROOT_DIR / "nrf-sdk",
        platform_dir=ROOT_DIR,
        sdk_version=sdk_version,
        toolchain_archs=["arm-zephyr-eabi", "riscv64-zephyr-elf"],
    )

    setup_python_dir = build_env.setup_install_python()
    build_env.setup_nrf_sdk(setup_python_dir)

    build_env.toolchain_version = build_env.get_toolchain_version()

    return build_env


@main.command("get_toolchain_version")
@click.argument("sdk_version")
def get_toolchain_version(sdk_version):
    build_env = BuildEnvironment(
        base_dir=ROOT_DIR / "nrf-sdk",
        platform_dir=ROOT_DIR,
        sdk_version=sdk_version,
        toolchain_archs=["arm-zephyr-eabi", "riscv64-zephyr-elf"],
    )

    build_env.toolchain_version = build_env.get_toolchain_version()
    print(f"TOOLCHAIN_VERSION={build_env.toolchain_version}")
    print(f"TOOLCHAIN_DIR={build_env.toolchain_dir}")


@main.command("checkout_toolchain")
@click.argument("sdk_version")
@click.argument("toolchain_version")
def checkout_toolchain(sdk_version, toolchain_version):
    build_env = BuildEnvironment(
        base_dir=ROOT_DIR / "nrf-sdk",
        platform_dir=ROOT_DIR,
        sdk_version=sdk_version,
        toolchain_archs=["arm-zephyr-eabi", "riscv64-zephyr-elf"],
    )

    setup_python_dir = build_env.setup_install_python()
    build_env.toolchain_version = toolchain_version
    build_env.setup_toolchain_python()
    build_env.download_zephyr_sdk(build_env.base_dir / "downloads", setup_python_dir)
    build_env.install_nrf_sdk_python_requirements()

    # Setup nordic nrfutil
    nrfutil_exe = nrfutil.NrfUtil(
        path=build_env.base_dir / "nrfutil",
        build_env=build_env,
    )
    nrfutil_exe.setup(build_env.base_dir / "downloads")


if __name__ == "__main__":
    main()
