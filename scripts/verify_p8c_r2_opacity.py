from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from twobyteasr.color_picker import SimpleColorDialog, percent_to_alpha
from twobyteasr.state_ownership_audit import StateOwnershipAudit


PERCENTS = (0, 1, 25, 50, 75, 99, 100)


def run(output: Path) -> dict[str, object]:
    app = QApplication.instance() or QApplication([])
    output.mkdir(parents=True, exist_ok=True)
    audit = StateOwnershipAudit(limit=len(PERCENTS))
    rows = []
    for percent in PERCENTS:
        color = QColor("#FF20D9FF")
        color.setAlpha(percent_to_alpha(percent))
        dialog = SimpleColorDialog(color, title=f"Opacity {percent}%")
        dialog.show()
        app.processEvents()
        picker = dialog.picker
        picker._opacity_slider.setValue(percent)
        app.processEvents()
        accepted = dialog.selected_color()
        screenshot = output / f"opacity-{percent:03d}.png"
        dialog.grab().save(str(screenshot))
        sample = audit.record(
            "opacity",
            ui_value=picker.alpha_spin.value(),
            domain_value=round(accepted.alpha() * 100 / 255),
            snapshot_value=round(picker.color().alpha() * 100 / 255),
            renderer_value=picker._opacity_slider.value(),
            pixel_value=accepted.alpha(),
            owner="ColorPickerWidget",
        )
        rows.append({
            "percent": percent,
            "qcolor_alpha": accepted.alpha(),
            "ui_percent": picker.alpha_spin.value(),
            "slider_percent": picker._opacity_slider.value(),
            "screenshot": str(screenshot),
            "consistent": sample.values_match(),
        })
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
    result = {
        "fixture": "headed-show-grab",
        "rows": rows,
        "audit": audit.to_dict(),
        "verified": all(
            row["percent"] == row["ui_percent"] == row["slider_percent"]
            and row["consistent"]
            for row in rows
        ),
    }
    (output / "opacity-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
