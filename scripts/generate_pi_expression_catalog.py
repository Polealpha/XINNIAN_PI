from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT.parent / "emotion engine" / "XINNIAN" / "lib" / "hardware" / "face_expressions.cpp"
DEFAULT_OUTPUT = PROJECT_ROOT / "pi_runtime" / "expression_catalog.json"

EXPRESSION_RE = re.compile(
    r'\{\s*"(?P<id>[^"]+)"\s*,\s*\{(?P<left>[^{}]+)\}\s*,\s*\{(?P<right>[^{}]+)\}\s*\}',
    re.MULTILINE,
)


def _parse_eye(raw: str) -> dict[str, int]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 7:
        raise ValueError(f"unexpected eye definition: {raw}")
    x, y, w, h, r, rot, color = parts
    return {
        "x": int(x, 0),
        "y": int(y, 0),
        "w": int(w, 0),
        "h": int(h, 0),
        "r": int(r, 0),
        "rot": int(rot, 0),
        "color": int(color, 0),
    }


def generate_catalog(source: Path) -> list[dict[str, object]]:
    text = source.read_text(encoding="utf-8")
    catalog: list[dict[str, object]] = []
    for match in EXPRESSION_RE.finditer(text):
        catalog.append(
            {
                "id": match.group("id"),
                "left": _parse_eye(match.group("left")),
                "right": _parse_eye(match.group("right")),
            }
        )
    if not catalog:
        raise ValueError(f"no expressions found in {source}")
    return catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Pi expression catalog from the legacy ESP32 source.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE), help="Path to legacy face_expressions.cpp")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Path to generated expression_catalog.json")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    catalog = generate_catalog(source)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[catalog] wrote {len(catalog)} expressions to {output}")


if __name__ == "__main__":
    main()
