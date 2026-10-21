#!/usr/bin/env python3
"""Create an opt-in fictional workspace, refusing every overwrite."""
import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    examples = Path(__file__).resolve().parent
    root = args.root.expanduser().resolve()
    sources = sorted(path for name in ("sot", "data") for path in (examples / name).glob("*") if path.is_file())
    destinations = [(source, root / source.relative_to(examples)) for source in sources]
    existing = [str(destination.relative_to(root)) for _, destination in destinations if destination.exists()]
    if existing:
        raise SystemExit("Refusing to overwrite existing files: " + ", ".join(existing))
    for source, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as out, source.open("rb") as original:
            shutil.copyfileobj(original, out)
    for name in ("jobs", "research", "outputs", "exports"):
        (root / name).mkdir(exist_ok=True)
    print("Fictional examples seeded. Replace them locally before preparing real documents.")


if __name__ == "__main__":
    main()
