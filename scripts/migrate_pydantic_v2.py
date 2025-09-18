#!/usr/bin/env python3
"""
Conservative automatic migration helper: replace Pydantic v1 ``@validator`` decorators
with v2 ``@field_validator`` and add imports where needed.

This script writes a .bak file for any replaced file. It does not attempt to
rewrite cross-field validators or complex cases — review .bak files after running.

Run from repo root:

    python3 scripts/migrate_pydantic_v2.py

"""
import re
from pathlib import Path

EXCLUDE = {".venv", ".git", "__pycache__"}
ROOT = Path(".").resolve()

validator_pattern = re.compile(r"^([ \t]*)@validator\(", re.MULTILINE)
import_pattern = re.compile(r"from\s+pydantic\s+import\s+(.*)")


def should_skip(p: Path):
    return any(part in EXCLUDE for part in p.parts)


def add_field_validator_import(text: str) -> str:
    # If field_validator already imported, do nothing.
    if "field_validator" in text:
        return text
    m = import_pattern.search(text)
    if m:
        group = m.group(1).strip()
        # avoid duplicate commas, but keep style simple
        new_line = f"from pydantic import {group}, field_validator"
        text = import_pattern.sub(new_line, text, count=1)
        return text
    # No existing pydantic import - add one at top (after module docstring if present)
    lines = text.splitlines()
    insert_at = 0
    if lines and (lines[0].startswith('"""') or lines[0].startswith("'''")):
        # find closing docstring
        for i in range(1, len(lines)):
            if lines[i].endswith('"""') or lines[i].endswith("'''"):
                insert_at = i + 1
                break
    lines.insert(insert_at, "from pydantic import field_validator")
    return "\n".join(lines)


def migrate_file(path: Path) -> bool:
    text = path.read_text(encoding="utf8")
    if not validator_pattern.search(text):
        return False
    bak = path.with_suffix(path.suffix + ".bak")
    bak.write_text(text, encoding="utf8")

    # Replace decorator instances preserving indentation
    new_text = validator_pattern.sub(lambda m: f"{m.group(1)}@field_validator(", text)
    # Add import if needed
    new_text = add_field_validator_import(new_text)
    path.write_text(new_text, encoding="utf8")
    print(f"Updated: {path} (backup -> {bak})")
    return True


def main():
    changed = []
    for p in ROOT.rglob("*.py"):
        if should_skip(p):
            continue
        if migrate_file(p):
            changed.append(p)
    if not changed:
        print("No @validator decorators found or no files changed.")
    else:
        print(f"Migrated {len(changed)} files. Review .bak files and run tests.")


if __name__ == "__main__":
    main()
