import click
import re
from pathlib import Path


@click.command()
@click.argument("uf2_repo_path", type=click.Path(exists=True))
def main(uf2_repo_path):
    pattern = re.compile(r"#define\s+(?P<name>\w+)\s+0x(?P<value>[0-9A-Fa-f]+)")
    board_path = Path(uf2_repo_path) / "src" / "boards"
    vids_pids = {}
    for header_file in board_path.rglob("board.h"):
        print(f"Processing file: {header_file}")
        with header_file.open("r") as f:
            content = f.read()
            vid = None
            pids = set()
            for match in pattern.finditer(content):
                name = match.group("name")
                value = int(match.group("value"), 16)
                if name.endswith("_VID"):
                    vid = value
                elif name.endswith("_PID"):
                    pids.add(value)
        if vid is None:
            print(f"Warning! No VID found in {header_file}")
            continue
        if vid not in vids_pids:
            vids_pids[vid] = set()
        vids_pids[vid].update(pids)

    out = "UF2_VIDS_PIDS = {"
    for vid, pids in vids_pids.items():
        out += f"{hex(vid)}: [{', '.join(hex(pid) for pid in pids)}], "
    out += "}"
    print(out)


if __name__ == "__main__":
    main()
