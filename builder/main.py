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
from .utils import sdk as nrfutil_sdk

import upload

from SCons.Script import (
    AlwaysBuild,
    Builder,
    Default,
    DefaultEnvironment,
)

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
nrfutil = nrfutil_sdk.get_nrfutil(env)

# Zephyr's final output file is merged.hex
env.Replace(PROGSUFFIX=".hex")
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

env.ProcessProgramDeps()
env.ProcessCompileDbToolchainOption()
env.ProcessProjectDeps()
env.Append(BUILDERS=dict(DummyBuilder=Builder(action=lambda *_: None)))
target_hex = env.WestBuilder(env.subst("$PROGPATH"), [])
target_hexbuildprog = env.Alias("hexbuildprog", target_hex, target_hex)
AlwaysBuild(target_hexbuildprog)

target_uf2 = env.PackageUf2(join("$BUILD_DIR", "${PROGNAME}"), target_hex)
target_dfu_adafruit = env.PackageDfuAdafruit(
    join("$BUILD_DIR", "${PROGNAME}_adafruit"), target_hex
)
target_dfu_nordic = env.PackageDfuNordic(
    join("$BUILD_DIR", "${PROGNAME}_nordic"), target_hex
)

upload.setup_upload_targets(env, target_hex, target_uf2, target_dfu_adafruit, target_dfu_nordic)

Default(target_hex)
