import textwrap
from pathlib import Path
from utils.utils import exec_command


class BuildEnvironment:
    def __init__(self, project_dir: Path, source_dir: Path, build_dir: Path, sdk):
        self.project_dir = project_dir
        self.source_dir = source_dir
        self.build_dir = build_dir
        self.app_dir = project_dir / "zephyr"
        self.sdk = sdk
        self.reconfigure_required = False

    def run(self, cmd: list[str], cwd=None, **kwargs):
        if not cwd:
            cwd = self.sdk.sdk_path
        ret = exec_command(
            cmd, f"Command {' '.join(cmd)} failed", env=self.sdk.env, cwd=cwd, **kwargs
        )
        return (ret.stdout, ret.stderr)

    def _is_reconfigure_required(self, board):
        if self.sdk.fresh_install or self.reconfigure_required:
            return True
        cmake_cache_file = self.build_dir / "CMakeCache.txt"
        if not cmake_cache_file.is_file():
            return True
        build_ninja_file = self.build_dir / "build.ninja"
        if not build_ninja_file.is_file():
            return True
        pm_static_file = self.project_dir / "zephyr" / "pm_static.yml"
        if (
            pm_static_file.is_file()
            and pm_static_file.stat().st_mtime > cmake_cache_file.stat().st_mtime
        ):
            # Reconfigure if pm_static.yml has changed
            return True
        board_file = self.project_dir / "boards" / f"{board}.json"
        if (
            board_file.is_file()
            and board_file.stat().st_mtime > cmake_cache_file.stat().st_mtime
        ):
            # Reconfigure if the board configuration has changed
            return True
        return False

    def _generate_cmake_library_entries(self, libraries):
        include_dirs = set()
        libs = []
        for l in libraries:
            lib = f"zephyr_library_named({l['name']})"
            lib += f"\nzephyr_library_sources({' '.join(l['sources'])})"
            lib += (
                f"\nzephyr_library_include_directories({' '.join(l['include_dirs'])})"
            )
            include_dirs.update(l["include_dirs"])
            if l["build_flags"]:
                lib += f"\nzephyr_library_compile_options({' '.join(l['build_flags'])})"
            for d in l.get("dependencies", []):
                lib += f"\nzephyr_library_link_libraries({d})"
            libs.append(lib)
        return libs, include_dirs

    def _generate_project_files(
        self,
        build_flags: list[str],
        link_flags: list[str],
        dependencies: list[dict],
        source_files: list[Path],
    ):
        deps, deps_include_dirs = self._generate_cmake_library_entries(dependencies)
        sources = [str(f.relative_to(self.app_dir, walk_up=True)) for f in source_files]
        self.app_dir.mkdir(parents=True, exist_ok=True)
        cmake_file = self.app_dir / "CMakeLists.txt"
        cmake_tpl = textwrap.dedent(
            f"""
            cmake_minimum_required(VERSION 3.20.0)

            set(Zephyr_DIR "$ENV{{ZEPHYR_BASE}}/share/zephyr-package/cmake/")

            find_package(Zephyr)

            project({self.project_dir.name})

            {'\n'.join(deps)}

            zephyr_compile_options($<$<COMPILE_LANGUAGE:CXX>:{' '.join(build_flags)}>)
            zephyr_include_directories({' '.join(deps_include_dirs)})
            zephyr_ld_options({' '.join(link_flags)})

            target_sources(app PRIVATE {" ".join(sources)})
            target_link_libraries(app PRIVATE {" ".join([d['name'] for d in dependencies])})
            target_include_directories(app PRIVATE ../src)
            """
        )

        app_tpl = textwrap.dedent(
            """
            #include <zephyr.h>
            void main(void) {}
            """
        )
        if not cmake_file.is_file() or cmake_file.read_text() != cmake_tpl:
            cmake_file.write_text(cmake_tpl)
            self.reconfigure_required = True
        if not any(self.source_dir.iterdir()):
            main_c_file = self.source_dir / "main.c"
            main_c_file.parent.mkdir(parents=True, exist_ok=True)
            main_c_file.write_text(app_tpl)
            self.reconfigure_required = True

    def _set_extra_cmake_args(self, cmake_extra_args: list[str]):
        try:
            old_args, _ = self.run(["west", "config", "build.cmake-args"])
            old_args = old_args.strip().split()
            if sorted(old_args) == sorted(cmake_extra_args):
                return
        except Exception:
            pass

        print("Setting extra CMake args:", cmake_extra_args)
        self.run(
            [
                "west",
                "config",
                "build.cmake-args",
                "--",
                " ".join(cmake_extra_args),
            ]
        )
        self.reconfigure_required = True

    def build(
        self,
        board: str,
        build_flags: list[str],
        link_flags: list[str],
        dependencies: list[dict],
        source_files: list[Path],
        pristine: bool = False,
        verbose: bool = False,
    ):
        self._generate_project_files(build_flags, link_flags, dependencies, source_files)

        west_cmd = [
            "west",
            "build",
            "--sysbuild",
            (
                "--pristine"
                if pristine or self._is_reconfigure_required(board)
                else "--pristine=auto"
            ),
            "-b",
            board,
            "-d",
            str(self.build_dir),
            str(self.app_dir),
        ]
        print("Building nRF Connect SDK application...")
        if verbose:
            print(" ".join(map(str, west_cmd)))

        out, err = self.run(
            west_cmd,
        )

        if verbose:
            print(out)
            print(err)
