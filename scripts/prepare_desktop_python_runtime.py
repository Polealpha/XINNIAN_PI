from __future__ import annotations

import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable, Set

from packaging.markers import default_environment
from packaging.requirements import Requirement


DIST_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")

REQUIRED_RUNTIME_MARKERS = (
    "fastapi",
    "uvicorn",
    "pydantic",
    "httpx",
)

PYTHON_HOME_EXCLUDES = {
    "__pycache__",
    "Doc",
    "docs",
    "include",
    "libs",
    "Scripts",
    "tcl",
    "test",
    "tests",
    "idlelib",
    "ensurepip",
    "venv",
    "tkinter",
    "pydoc_data",
}

PYTHON_HOME_FILE_EXCLUDES = {
    "NEWS.txt",
}


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "").strip()).lower()


def parse_requirements_file(path: Path, seen: Set[Path] | None = None) -> list[str]:
    if seen is None:
        seen = set()
    path = path.resolve()
    if path in seen or not path.exists():
        return []
    seen.add(path)
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            nested = (path.parent / line[3:].strip()).resolve()
            result.extend(parse_requirements_file(nested, seen))
            continue
        match = DIST_NAME_RE.match(line)
        if match:
            result.append(match.group(0))
    return result


def requirement_name_from_spec(spec: str) -> str:
    match = DIST_NAME_RE.match(str(spec or "").strip())
    return match.group(0) if match else ""


def should_include_requirement(spec: str) -> bool:
    try:
        requirement = Requirement(str(spec or "").strip())
    except Exception:
        return bool(requirement_name_from_spec(spec))
    if requirement.marker is None:
        return True
    marker_env = default_environment()
    marker_env["extra"] = ""
    try:
        return bool(requirement.marker.evaluate(marker_env))
    except Exception:
        return True


def collect_needed_distributions(root_requirements: Iterable[str]) -> tuple[list[metadata.Distribution], list[str]]:
    installed = {normalize_name(dist.metadata.get("Name", "")): dist for dist in metadata.distributions()}
    required: list[metadata.Distribution] = []
    missing: list[str] = []
    queue = [normalize_name(name) for name in root_requirements if str(name or "").strip()]
    seen: set[str] = set()

    while queue:
        name = queue.pop(0)
        if not name or name in seen:
            continue
        seen.add(name)
        dist = installed.get(name)
        if dist is None:
            missing.append(name)
            continue
        required.append(dist)
        for dep_spec in dist.requires or []:
            if not should_include_requirement(dep_spec):
                continue
            dep_name = normalize_name(requirement_name_from_spec(dep_spec))
            if dep_name and dep_name not in seen:
                queue.append(dep_name)
    return required, missing


def copy_distributions(dists: Iterable[metadata.Distribution], target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: set[Path] = set()
    for dist in dists:
        for file in dist.files or []:
            source = Path(dist.locate_file(file))
            if not source.exists() or source.is_dir():
                continue
            try:
                relative = source.relative_to(source.anchor).parts
            except Exception:
                relative = ()
            if "site-packages" in relative:
                index = relative.index("site-packages")
                destination = target_dir.joinpath(*relative[index + 1 :])
            else:
                destination = target_dir / Path(file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source in copied:
                continue
            shutil.copy2(source, destination)
            copied.add(source)


def clean_target(target_dir: Path) -> None:
    if target_dir.exists():
        stale_dir = target_dir.with_name(f"{target_dir.name}-stale")
        if stale_dir.exists():
            shutil.rmtree(stale_dir, ignore_errors=True)
        target_dir.rename(stale_dir)
        shutil.rmtree(stale_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)


def target_looks_ready(target_dir: Path) -> bool:
    if not target_dir.exists():
        return False
    return all((target_dir / marker).exists() for marker in REQUIRED_RUNTIME_MARKERS)


def clean_and_recreate(target_dir: Path) -> None:
    if target_dir.exists():
        stale_dir = target_dir.with_name(f"{target_dir.name}-stale")
        if stale_dir.exists():
            shutil.rmtree(stale_dir, ignore_errors=True)
        target_dir.rename(stale_dir)
        shutil.rmtree(stale_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)


def _should_skip_python_home_path(source_root: Path, current: Path) -> bool:
    try:
        relative = current.relative_to(source_root)
    except Exception:
        return False
    parts = [part for part in relative.parts if part]
    if not parts:
        return False
    if parts[0] == "Lib":
        if len(parts) > 1 and parts[1] == "site-packages":
            return True
        if len(parts) > 1 and parts[1] in PYTHON_HOME_EXCLUDES:
            return True
    if len(parts) >= 2 and parts[0] == "DLLs" and parts[1] in {"tcl86t.dll", "tk86t.dll"}:
        return True
    return any(part in PYTHON_HOME_EXCLUDES for part in parts)


def copy_python_home(source_root: Path, target_dir: Path) -> None:
    source_root = source_root.resolve()
    clean_and_recreate(target_dir)
    copied_files = 0
    for current_root, dirnames, filenames in os.walk(source_root):
        current_root_path = Path(current_root)
        dirnames[:] = [
            name
            for name in dirnames
            if not _should_skip_python_home_path(source_root, current_root_path / name)
        ]
        if _should_skip_python_home_path(source_root, current_root_path):
            dirnames[:] = []
            continue
        relative_root = current_root_path.relative_to(source_root)
        destination_root = target_dir / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)
        for filename in filenames:
            source_file = current_root_path / filename
            if _should_skip_python_home_path(source_root, source_file):
                continue
            if filename in PYTHON_HOME_FILE_EXCLUDES:
                continue
            destination_file = destination_root / filename
            destination_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination_file)
            copied_files += 1
    print(f"Copied Python home ({copied_files} files) into {target_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vendor Python runtime dependencies for Electron desktop packaging.")
    parser.add_argument("--target", required=True, help="Target directory for vendored site-packages")
    parser.add_argument(
        "--python-home-target",
        help="Optional target directory for a self-contained Python home copied from the current interpreter",
    )
    parser.add_argument(
        "--requirements",
        nargs="+",
        required=True,
        help="Requirement files to resolve and vendor",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    target_dir = Path(args.target).resolve()
    python_home_target = Path(args.python_home_target).resolve() if args.python_home_target else None
    requirement_files = [Path(item).resolve() for item in args.requirements]

    requirement_names: list[str] = []
    for req_file in requirement_files:
        requirement_names.extend(parse_requirements_file(req_file))

    dists, missing = collect_needed_distributions(requirement_names)
    if missing:
        print("Missing installed distributions:", ", ".join(sorted(set(missing))), file=sys.stderr)
        return 2

    if target_looks_ready(target_dir):
        print(f"Reusing existing vendored site-packages at {target_dir}")
    else:
        clean_target(target_dir)
        copy_distributions(dists, target_dir)
        print(f"Vendored {len(dists)} distributions into {target_dir}")

    if python_home_target is not None:
        python_home_source = Path(sys.base_prefix).resolve()
        if not (python_home_target / "python.exe").exists():
            copy_python_home(python_home_source, python_home_target)
        else:
            print(f"Reusing existing vendored Python home at {python_home_target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
