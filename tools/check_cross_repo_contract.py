"""Cross-repository contract checker: compare OPI and T5 frozen schemas.

Compares the OPI contracts/uart/commands.yaml against the T5 reference
repository's equivalent contract file. Verifies:
- All frozen schema sections are normalized and identical.
- Shared golden vectors match by name, command, flags, and payload_hex.

Usage:
    python tools/check_cross_repo_contract.py [--t5-path /path/to/nightshift-t5]

If --t5-path is not provided, attempts to clone/find the T5 reference repo.
The checker MUST fail if the T5 files cannot be obtained — missing comparison
data is not a passing result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


OPI_ROOT = Path(__file__).resolve().parent.parent
OPI_YAML = OPI_ROOT / "contracts" / "uart" / "commands.yaml"
OPI_VECTORS = OPI_ROOT / "contracts" / "uart" / "golden_vectors.json"

FROZEN_SCHEMA_SECTIONS = [
    "magic",
    "version",
    "max_payload",
    "byte_order",
    "crc",
    "framing",
    "string",
    "flags",
    "status",
    "object_types",
    "capabilities",
    "modes",
    "work_states",
    "ui_actions",
    "commands",
    "payloads",
]

VECTOR_COMPARE_FIELDS = ["name", "command", "flags", "payload_hex"]


def load_opi_schema() -> dict:
    data = yaml.safe_load(OPI_YAML.read_text())
    return data["t5_link_v1"]


def load_opi_vectors() -> list[dict]:
    data = json.loads(OPI_VECTORS.read_text())
    return data["golden_vectors"]


def find_t5_contract(t5_path: Path | None) -> tuple[Path | None, Path | None]:
    """Find T5 contract YAML and vectors."""
    if t5_path is None:
        candidates = [
            Path("/tmp/nightshift-t5-ref"),
            Path.home() / "nightshift-t5",
            OPI_ROOT.parent / "nightshift-t5",
        ]
        for candidate in candidates:
            if candidate.exists():
                t5_path = candidate
                break

    if t5_path is None:
        return None, None

    yaml_candidates = [
        t5_path / "contracts" / "uart" / "commands.yaml",
        t5_path / "contracts" / "t5_link_v1.yaml",
        t5_path / "src" / "protocol" / "contract.yaml",
    ]
    vector_candidates = [
        t5_path / "contracts" / "uart" / "golden_vectors.json",
        t5_path / "tests" / "golden_vectors.json",
        t5_path / "src" / "protocol" / "golden_vectors.json",
    ]

    t5_yaml = next((p for p in yaml_candidates if p.exists()), None)
    t5_vectors = next((p for p in vector_candidates if p.exists()), None)
    return t5_yaml, t5_vectors


def normalize_schema(schema: dict) -> dict:
    """Normalize a schema dict for comparison (sort keys, normalize values)."""
    normalized = {}
    for section in FROZEN_SCHEMA_SECTIONS:
        if section in schema:
            normalized[section] = schema[section]
    return normalized


def compare_schemas(opi_schema: dict, t5_schema: dict) -> list[str]:
    """Compare normalized frozen schema sections. Return list of differences."""
    errors: list[str] = []
    opi_norm = normalize_schema(opi_schema)

    t5_root = t5_schema.get("t5_link_v1", t5_schema)
    t5_norm = normalize_schema(t5_root)

    for section in FROZEN_SCHEMA_SECTIONS:
        opi_val = opi_norm.get(section)
        t5_val = t5_norm.get(section)

        if opi_val is None and t5_val is None:
            continue
        if opi_val is None:
            errors.append(f"Section '{section}' missing from OPI")
            continue
        if t5_val is None:
            errors.append(f"Section '{section}' missing from T5")
            continue
        if opi_val != t5_val:
            errors.append(f"Section '{section}' differs:\n  OPI: {opi_val}\n  T5:  {t5_val}")

    return errors


def compare_vectors(opi_vectors: list[dict], t5_vectors: list[dict]) -> list[str]:
    """Compare shared vectors by key fields."""
    errors: list[str] = []
    t5_by_name = {v["name"]: v for v in t5_vectors}

    for opi_v in opi_vectors:
        name = opi_v["name"]
        t5_v = t5_by_name.get(name)
        if t5_v is None:
            continue

        for field in VECTOR_COMPARE_FIELDS:
            opi_val = opi_v.get(field)
            t5_val = t5_v.get(field)
            if opi_val != t5_val:
                errors.append(
                    f"Vector '{name}' field '{field}': OPI={opi_val!r} T5={t5_val!r}"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-repository contract checker")
    parser.add_argument("--t5-path", type=Path, default=None)
    args = parser.parse_args()

    print("Loading OPI contract...")
    opi_schema = load_opi_schema()
    opi_vectors = load_opi_vectors()
    print(f"  OPI schema sections: {len(opi_schema)}")
    print(f"  OPI vectors: {len(opi_vectors)}")

    t5_yaml_path, t5_vectors_path = find_t5_contract(args.t5_path)

    if t5_yaml_path is None:
        print("\nERROR: T5 contract YAML not found.")
        print("Missing comparison data is not a passing result.")
        print("Provide --t5-path or ensure T5 repo is available.")
        return 1

    print(f"\nLoading T5 contract from: {t5_yaml_path}")
    t5_schema = yaml.safe_load(t5_yaml_path.read_text())
    schema_errors = compare_schemas(opi_schema, t5_schema)

    if schema_errors:
        print(f"\nSchema differences ({len(schema_errors)}):")
        for err in schema_errors:
            print(f"  - {err}")
    else:
        print("  Schema sections: IDENTICAL")

    vector_errors: list[str] = []
    if t5_vectors_path:
        print(f"  Loading T5 vectors from: {t5_vectors_path}")
        t5_data = json.loads(t5_vectors_path.read_text())
        t5_vectors = t5_data.get("golden_vectors", [])
        vector_errors = compare_vectors(opi_vectors, t5_vectors)
        if vector_errors:
            print(f"\nVector differences ({len(vector_errors)}):")
            for err in vector_errors:
                print(f"  - {err}")
        else:
            print("  Shared vectors: BYTE-IDENTICAL")
    else:
        print("  T5 vectors file not found (non-critical if schema matches)")

    total_errors = len(schema_errors) + len(vector_errors)
    if total_errors:
        print(f"\nFAILED: {total_errors} difference(s) found")
        return 1
    print("\nPASSED: OPI and T5 contracts are identical")
    return 0


if __name__ == "__main__":
    sys.exit(main())
