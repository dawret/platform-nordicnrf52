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
from os.path import join, isfile
from pathlib import Path
import semantic_version as semver

from SCons.Script import (
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)

env = DefaultEnvironment()
platform = env.PioPlatform()
board = env.BoardConfig()

import nrfutil
from frameworks import zephyr
import upload


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
SDK_DOWNLOAD_DIR = ROOT_DIR / "nrf-sdk/downloads"
SDK_DEFAULT_VERSION = "v2.9.2"

try:
    # Try to get SDK version from project options first
    SDK_VERSION = "v" + str(
        semver.Version(
            env.GetProjectOption("custom_framework_version", None)
        ).truncate()
    )
except:
    # Fall back to the default version
    SDK_VERSION = SDK_DEFAULT_VERSION

nrfutil_exe = nrfutil.setup(SDK_DOWNLOAD_DIR, SDK_INSTALL_DIR)
nrfutil_sdk = nrfutil_exe.get_sdk(SDK_VERSION, SDK_INSTALL_DIR)
if not nrfutil_sdk:
    print(f"Installing SDK version {SDK_VERSION}...")
    nrfutil_sdk = nrfutil_exe.install_sdk(SDK_VERSION, SDK_INSTALL_DIR)
uf2conv = nrfutil_sdk.sdk_path / "zephyr" / "scripts" / "build" / "uf2conv.py"

# Zephyr's final output file is merged.hex
env.Replace(PROGSUFFIX=".hex")
env.Replace(PROGNAME="merged")


# Gather source files
def source_files_from_env(env):
    "Gather source files from the environment"
    files = chain.from_iterable(env.get("PIOBUILDFILES"))
    files = chain.from_iterable([f.sources for f in files])
    files = [Path((f.srcnode().get_abspath())) for f in files]
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
                    for f in env.CollectBuildFiles(
                        dep.build_dir, dep.src_dir, dep.src_filter
                    )
                ],
                build_flags=env.ProcessFlags(dep.build_flags),
                dependencies=(
                    [d["name"] for d in dep.dependencies] if dep.dependencies else []
                ),
            )
        )
    return ret


# Main build action
def build_action(target, source, env):
    env.ProcessProgramDeps()
    env.ProcessCompileDbToolchainOption()
    env.ProcessProjectDeps()

    cflags = env.get("BUILD_FLAGS", [])
    linkflags = [x for x in env.get("BUILD_FLAGS", []) if x.startswith("-Wl,")]

    build_env = zephyr.BuildEnvironment(
        project_dir=Path(env.subst("$PROJECT_DIR")),
        source_dir=Path(env.subst("$PROJECT_SRC_DIR")),
        build_dir=Path(env.subst("$BUILD_DIR")),
        sdk=nrfutil_sdk,
    )

    build_env.build(
        board=board.get("build.zephyr.variant", board.id),
        build_flags=cflags,
        link_flags=linkflags,
        dependencies=dependencies_from_env(env),
        source_files=source_files_from_env(env),
        pristine=env.GetProjectOption("pristine", "False").lower() == "true",
        verbose=int(ARGUMENTS.get("PIOVERBOSE", 0)) > 0,
    )


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

target_hex = env.WestBuilder(env.subst("$PROGPATH"), [])
AlwaysBuild(target_hex)

target_uf2 = env.PackageUf2(join("$BUILD_DIR", "${PROGNAME}"), target_hex)
target_dfu_adafruit = env.PackageDfuAdafruit(
    join("$BUILD_DIR", "${PROGNAME}_adafruit"), target_hex
)
target_dfu_nordic = env.PackageDfuNordic(
    join("$BUILD_DIR", "${PROGNAME}_nordic"), target_hex
)

env.AddPlatformTarget(
    "flash_west",
    target_hex,
    upload.upload_swd(nrfutil_sdk.env),
    "Flash using West's default runner",
)
env.AddPlatformTarget(
    "flash_pyocd",
    target_hex,
    upload.upload_swd(nrfutil_sdk.env, "pyocd"),
    "Flash using pyOCD",
)
env.AddPlatformTarget(
    "flash_jlink",
    target_hex,
    upload.upload_swd(nrfutil_sdk.env, "jlink"),
    "Flash using J-Link",
)
env.AddPlatformTarget(
    "flash_uf2", target_uf2, upload.upload_uf2_adafruit(uf2conv), "Flash using UF2"
)
env.AddPlatformTarget(
    "flash_serial_adafruit",
    target_dfu_adafruit,
    upload.upload_serial_adafruit(),
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
