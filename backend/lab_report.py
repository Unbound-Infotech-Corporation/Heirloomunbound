"""Write tonight's local usefulness report. Used by ``heirloom-box report``."""
from __future__ import annotations

from lab_mode import default_store, publish_report, report_dir


def main() -> int:
    result = publish_report(default_store(), report_dir())
    print(result["path"])
    print(f"github={result['github']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
