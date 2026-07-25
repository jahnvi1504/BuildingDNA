from __future__ import annotations

import shutil
import site
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IDFSelfHealer:
    """Apply bounded, auditable field patches with eppy and a backup."""

    def __init__(self, idf_path: Path, idd_path: Path) -> None:
        self.idf_path = idf_path
        self.idd_path = idd_path

    def apply_patch(self, diff: dict[str, Any]) -> dict[str, Any]:
        # Some Windows Python installs contain a stray base-level decorator.py
        # ahead of the virtual environment. eppy requires the real PyPI
        # ``decorator`` package, so make the isolated site-packages precedence
        # explicit before importing eppy.
        for package_dir in reversed(site.getsitepackages()):
            if package_dir in sys.path:
                sys.path.remove(package_dir)
            sys.path.insert(0, package_dir)
        sys.modules.pop("decorator", None)
        from eppy.modeleditor import IDF

        operations = diff.get("operations", [])
        if not operations or len(operations) > 20:
            raise ValueError("diff.operations must contain between 1 and 20 field patches")
        if not self.idf_path.is_file() or not self.idd_path.is_file():
            raise FileNotFoundError("IDF or Energy+.idd is missing")

        try:
            IDF.setiddname(str(self.idd_path))
        except IDF.IDDAlreadySetError:
            pass
        idf = IDF(str(self.idf_path))
        applied: list[dict[str, Any]] = []
        for operation in operations:
            object_type = str(operation["object_type"]).upper()
            object_name = str(operation["object_name"])
            field = str(operation["field"])
            value = operation["value"]
            matches = [
                obj for obj in idf.idfobjects[object_type]
                if str(getattr(obj, "Name", "")).casefold() == object_name.casefold()
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Expected one {object_type} named {object_name!r}; found {len(matches)}"
                )
            obj = matches[0]
            if field not in obj.fieldnames:
                raise ValueError(f"Unknown field {field!r} for {object_type}")
            old = getattr(obj, field)
            setattr(obj, field, value)
            applied.append({**operation, "old_value": old})

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.idf_path.with_suffix(f".{stamp}.bak.idf")
        shutil.copy2(self.idf_path, backup)
        idf.saveas(str(self.idf_path))
        return {
            "patched": True,
            "backup": str(backup),
            "applied": applied,
            "diagnosis": diff.get("diagnosis", ""),
        }
