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

from itertools import chain
import json
from os.path import join, isfile
from pathlib import Path
import semantic_version as semver

from SCons.Script import (
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)
from SCons.Errors import BuildError

import sdk_manager
import nrfutil
from frameworks import zephyr
import upload

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()


def get_zephyr_config(env, name):
    config_path = join(env.subst("$BUILD_DIR"), "zephyr", "zephyr", ".config")
    if isfile(config_path):
        with open(config_path) as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"')
    return None


ROOT_DIR = Path(platform.get_dir())
SDK_INSTALL_DIR = ROOT_DIR / "nrf-sdk"
SDK_DOWNLOAD_DIR = ROOT_DIR / "nrf-sdk" / "downloads"
SDK_DEFAULT_VERSION = "v2.9.2"

try:
    # Try to get SDK version from project options first
    version_arg = env.GetProjectOption("custom_framework_version", None)
    if version_arg:
        SDK_VERSION = "v" + str(semver.Version(version_arg).truncate())
    else:
        SDK_VERSION = SDK_DEFAULT_VERSION
except (ValueError, TypeError):
    # Fall back to the default version
    SDK_VERSION = SDK_DEFAULT_VERSION

# Setup nrf-sdk and toolchain
build_env = sdk_manager.BuildEnvironment(
    base_dir=ROOT_DIR / "nrf-sdk",
    platform_dir=ROOT_DIR,
    sdk_version=SDK_VERSION,
    toolchain_archs=["arm-zephyr-eabi", "riscv64-zephyr-elf"],
)
build_env.setup(SDK_DOWNLOAD_DIR)

# Setup nordic nrfutil
nrfutil_exe = nrfutil.NrfUtil(
    path=build_env.base_dir / "nrfutil",
    build_env=build_env,
)
nrfutil_exe.setup(SDK_DOWNLOAD_DIR)

# Setup jlink
jlink_dir = Path(platform.get_package_dir("tool-jlink"))
build_env.add_env({"PATH": jlink_dir, "LD_LIBRARY_PATH": jlink_dir})

# Setup adafruit_nrfutil
adafruit_nrfutil_dir = Path(platform.get_package_dir("tool-adafruit-nrfutil"))
build_env.add_path(adafruit_nrfutil_dir)
adafruit_nrfutil = adafruit_nrfutil_dir / "adafruit-nrfutil.py"

# Zephyr's final output file is merged.hex
env.Replace(PROGSUFFIX=".hex")
env.Replace(PROGNAME="merged")
env.Replace(PYTHONEXE=str(build_env.python))


def source_files_from_env(env):
    "Gather source files from PIOBUILDFILES"
    files = chain.from_iterable(env.get("PIOBUILDFILES"))
    files = chain.from_iterable([f.sources for f in files])
    files = [Path(f.srcnode().get_abspath()) for f in files]
    files.sort()
    return files


def dependencies_from_env(env):
    "Gather dependencies from the environment"
    ret = []
    for dep in env.GetLibBuilders():
        ret.append(
            zephyr.ZephyrDependency(
                name=dep.name,
                public_include_dirs=dep.get_include_dirs(),
                private_include_dirs=[dep.include_dir] if dep.include_dir else [],
                sources=[
                    str(f.srcnode().get_abspath())
                    for f in env.CollectBuildFiles(dep.build_dir, dep.src_dir, dep.src_filter)
                ],
                build_flags=env.ProcessFlags(dep.build_flags),
                dependencies=([d["name"] for d in dep.dependencies] if dep.dependencies else []),
            )
        )
    return ret


def build_action(target, source, env):
    "Main build action"
    # Those three calls populate the environment with build files, flags and dependencies
    env.ProcessProgramDeps()
    env.ProcessCompileDbToolchainOption()
    env.ProcessProjectDeps()

    cflags = env.get("BUILD_FLAGS", [])
    linkflags = [x for x in env.get("BUILD_FLAGS", []) if x.startswith("-Wl,")]

    app_dir_name = env.GetProjectOption("custom_zephyr_app_dir", "zephyr")
    zephyr_app_dir = Path(env.subst("$PROJECT_DIR")) / app_dir_name

    zephyr_env = zephyr.ZephyrEnvironment(
        project_dir=Path(env.subst("$PROJECT_DIR")),
        source_dir=Path(env.subst("$PROJECT_SRC_DIR")),
        build_dir=Path(env.subst("$BUILD_DIR")),
        app_dir=zephyr_app_dir,
        build_env=build_env,
    )

    try:
        zephyr_env.build(
            board=board.get("build.zephyr.variant", board.id),
            build_flags=cflags,
            link_flags=linkflags,
            dependencies=dependencies_from_env(env),
            source_files=source_files_from_env(env),
            pristine=env.GetProjectOption("custom_pristine", "false").lower() == "true",
            verbose=int(ARGUMENTS.get("PIOVERBOSE", 0)) > 0,  # noqa: F821
            generate_project_files=env.GetProjectOption("custom_generate_project_files", "true").lower() == "true",
        )
    except RuntimeError as e:
        raise BuildError(errstr=str(e))


env.Append(
    BUILDERS=dict(
        WestBuilder=Builder(
            action=build_action,
        )
    )
)

env.Append(
    BUILDERS=dict(
        PackageDfuAdafruit=Builder(
            action=env.VerboseAction(
                lambda target, source, env: build_env.run(
                    [
                        "python",
                        str(adafruit_nrfutil),
                        "dfu",
                        "genpkg",
                        "--dev-type",
                        "0x0052",
                        "--application",
                        env.subst("$SOURCES"),
                        env.subst("$TARGET"),
                    ],
                    "Failed to create DFU package",
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
            action=lambda target, source, env: nrfutil_exe.create_dfu_package(
                Path(source[0].get_abspath()), Path(target[0].get_abspath())
            ),
            suffix=".zip",
            src_suffix=".hex",
        )
    )
)


def build_uf2(target, source, env):
    family_id = get_zephyr_config(env, "CONFIG_BUILD_OUTPUT_UF2_FAMILY_ID")
    cmd = env.VerboseAction(
        lambda source, target, env: build_env.run(
            [
                "python",
                str(build_env.uf2conv),
                str(source[0].get_abspath()),
                "-c",
                "-f",
                str(family_id),
                "-o",
                str(target[0].get_abspath()),
            ],
            "Failed to create UF2 package",
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


def dump_env_action(target, source, env):
    print("==== Build Environment ====")
    print(json.dumps(build_env.env, indent=2))
    print("==== End Build Environment ====")


### Dump env target
env.AddPlatformTarget(
    "dump_env",
    None,
    dump_env_action,
    "Dump build environment variables",
)

### Build targets

target_hex = env.WestBuilder(env.subst("$PROGPATH"), [])
AlwaysBuild(target_hex)

target_uf2 = env.PackageUf2(join("$BUILD_DIR", "${PROGNAME}"), target_hex)
target_dfu_adafruit = env.PackageDfuAdafruit(join("$BUILD_DIR", "${PROGNAME}_adafruit"), target_hex)
target_dfu_nordic = env.PackageDfuNordic(join("$BUILD_DIR", "${PROGNAME}_nordic"), target_hex)

### Upload targets

env.AddPlatformTarget(
    "flash_west",
    target_hex,
    upload.upload_swd(build_env),
    "Flash using West's default runner",
)
env.AddPlatformTarget(
    "flash_pyocd",
    target_hex,
    upload.upload_swd(build_env, "pyocd"),
    "Flash using pyOCD",
)
env.AddPlatformTarget(
    "flash_jlink",
    target_hex,
    upload.upload_swd(build_env, "jlink"),
    "Flash using J-Link",
)
env.AddPlatformTarget("flash_uf2", target_uf2, upload.upload_uf2_adafruit(build_env), "Flash using UF2")
env.AddPlatformTarget(
    "flash_serial_adafruit",
    target_dfu_adafruit,
    upload.upload_serial_adafruit(adafruit_nrfutil),
    "Flash using Adafruit uf2 bootloader (serial)",
)
env.AddPlatformTarget(
    "flash_serial_nordic",
    target_dfu_nordic,
    upload.upload_serial_nordic(nrfutil_exe),
    "Flash using Nordic bootloader (serial)",
)

# For compatibility
env.Alias("upload", "flash_serial_adafruit")

Default(target_hex)
