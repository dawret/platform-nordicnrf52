from dataclasses import dataclass
from itertools import chain
from pathlib import Path
import textwrap

from sdk_manager import BuildEnvironment


@dataclass
class ZephyrDependency:
    name: str
    public_include_dirs: list[str]
    private_include_dirs: list[str]
    build_flags: list[str]
    sources: list[str]
    dependencies: list[str]

    @property
    def is_header_only(self):
        return len(self.sources) == 0

    def include_dirs(self, build_env):
        dirs = self.public_include_dirs
        if not dirs:
            dirs = self.private_include_dirs
        return [str(Path(d).relative_to(build_env.app_dir, walk_up=True)) for d in dirs]

    def to_zephyr_cmake(self, build_env):
        if self.is_header_only:
            return ""
        ret = f"zephyr_library_named({self.name})"
        sources = [str(Path(s).relative_to(build_env.app_dir, walk_up=True)) for s in self.sources]
        ret += f"\nzephyr_library_sources({' '.join(sorted(sources))})"
        private_include_dirs = [
            str(Path(d).relative_to(build_env.app_dir, walk_up=True)) for d in self.private_include_dirs
        ]
        ret += f"\nzephyr_library_include_directories({' '.join(sorted(private_include_dirs))})"
        if self.build_flags:
            ret += f"\nzephyr_library_compile_options({' '.join(sorted(self.build_flags))})"
        for d in self.dependencies:
            ret += f"\nzephyr_library_link_libraries({d})"
        return ret


class ZephyrEnvironment:
    def __init__(
        self,
        project_dir: Path,
        source_dir: Path,
        app_dir: Path,
        build_dir: Path,
        build_env: BuildEnvironment,
    ):
        self.project_dir = project_dir
        self.source_dir = source_dir
        self.build_dir = build_dir
        self.app_dir = app_dir
        self.build_env = build_env
        self.reconfigure_required = False

    def run(self, cmd: list[str], cwd=None, verbose=False, **kwargs):
        if not cwd:
            cwd = self.build_env.sdk_dir
        cmd = [str(self.build_env.python), "-m"] + cmd
        ret = self.build_env.run(
            cmd,
            "West command failed",
            cwd=cwd,
            verbose=verbose,
            **kwargs,
        )
        return (ret.stdout, ret.stderr)

    def _is_reconfigure_required(self, board):
        if self.build_env.fresh_install or self.reconfigure_required:
            return True
        cmake_cache_file = self.build_dir / "CMakeCache.txt"
        if not cmake_cache_file.is_file():
            return True
        build_ninja_file = self.build_dir / "build.ninja"
        if not build_ninja_file.is_file():
            return True
        pm_static_file = self.app_dir / "pm_static.yml"
        if pm_static_file.is_file() and pm_static_file.stat().st_mtime > cmake_cache_file.stat().st_mtime:
            # Reconfigure if pm_static.yml has changed
            return True
        board_file = self.project_dir / "boards" / f"{board}.json"
        if board_file.is_file() and board_file.stat().st_mtime > cmake_cache_file.stat().st_mtime:
            # Reconfigure if the board configuration has changed
            return True
        return False

    def _generate_project_files(
        self,
        build_flags: list[str],
        link_flags: list[str],
        dependencies: list[ZephyrDependency],
        source_files: list[Path],
    ):
        sources = [str(f.relative_to(self.app_dir, walk_up=True)) for f in source_files]
        dep_include_dirs = set(chain.from_iterable(d.include_dirs(self) for d in dependencies))
        self.app_dir.mkdir(parents=True, exist_ok=True)
        cmake_file = self.app_dir / "CMakeLists.txt"
        cmake_tpl = textwrap.dedent(
            f"""
            cmake_minimum_required(VERSION 3.20.0)

            set(Zephyr_DIR "$ENV{{ZEPHYR_BASE}}/share/zephyr-package/cmake/")

            find_package(Zephyr)

            project({self.project_dir.name})
            """
        )
        cmake_tpl += "\n".join([d.to_zephyr_cmake(self) for d in dependencies])
        deps = [d.name for d in dependencies if not d.is_header_only]
        cmake_tpl += textwrap.dedent(
            f"""

            zephyr_compile_options($<$<COMPILE_LANGUAGE:CXX>:{" ".join(sorted(build_flags))}>)
            zephyr_include_directories({" ".join(sorted(dep_include_dirs))})
            zephyr_ld_options({" ".join(sorted(link_flags))})

            target_sources(app PRIVATE {" ".join(sorted(sources))})
            target_link_libraries(app PRIVATE {" ".join(sorted(deps))})
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
        dependencies: list[ZephyrDependency],
        source_files: list[Path],
        pristine: bool = False,
        verbose: bool = False,
        generate_project_files: bool = True,
    ):
        if generate_project_files:
            self._generate_project_files(build_flags, link_flags, dependencies, source_files)

        west_cmd = [
            "west",
            "build",
            "--sysbuild",
            ("--pristine" if pristine or self._is_reconfigure_required(board) else "--pristine=auto"),
            "-b",
            board,
            "-d",
            str(self.build_dir),
            str(self.app_dir),
        ]
        print("Building nRF Connect SDK application...")
        if verbose:
            print(" ".join(map(str, west_cmd)))

        self.run(
            west_cmd,
            verbose=verbose,
        )
