"""Embed the priority-model visual story into a copy of the Power BI report.

Power BI Desktop stores reports saved with the enhanced PBIR format as a ZIP
package. This script adds two image-only report pages and registers four PNG
charts derived from ``build_priority_story_charts.py``. The existing PBIX is
never overwritten.

Usage:
    python src/reporting/embed_priority_story_in_pbix.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE_REPORT = ROOT / "data" / "powerbi" / "maritime_anomaly_dashboard_priority.pbix"
OUTPUT_REPORT = ROOT / "data" / "powerbi" / "maritime_anomaly_dashboard_priority_story_final.pbix"
CHART_DIR = ROOT / "docs" / "images" / "priority_model"

CHARTS = (
    "01_detector_evidence_ceilings.png",
    "02_priority_queue_funnel.png",
    "03_signal_gap_behavior_factors.png",
    "04_case_score_anatomy.png",
)


def _stable_id(label: str) -> str:
    """Return the 20-character hexadecimal identifiers used by PBIR."""

    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:20]


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _resource_name(filename: str) -> str:
    path = Path(filename)
    return f"{path.stem}20261021000000000{path.suffix}"


def _image_visual(
    visual_id: str,
    resource_name: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    tab_order: int,
) -> dict:
    return {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/visualContainer/2.14.0/schema.json"
        ),
        "name": visual_id,
        "position": {
            "x": x,
            "y": y,
            "z": 0,
            "height": height,
            "width": width,
            "tabOrder": tab_order,
        },
        "visual": {
            "visualType": "image",
            "objects": {
                "general": [
                    {
                        "properties": {
                            "imageUrl": {
                                "expr": {
                                    "ResourcePackageItem": {
                                        "PackageName": "RegisteredResources",
                                        "PackageType": 1,
                                        "ItemName": resource_name,
                                    }
                                }
                            }
                        }
                    }
                ]
            },
            "drillFilterOtherVisuals": True,
        },
    }


def _page(page_id: str, display_name: str) -> dict:
    return {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definition/page/2.1.0/schema.json"
        ),
        "name": page_id,
        "displayName": display_name,
        "displayOption": "FitToPage",
        "height": 1080,
        "width": 1920,
    }


def _update_content_types(content_types: bytes) -> bytes:
    """Update the package MIME map while preserving Power BI's XML bytes.

    Power BI expects the root element to be the unprefixed ``Types`` tag. XML
    libraries may legally rewrite it as ``ns0:Types``, but Desktop rejects that
    equivalent representation. A byte-level replacement keeps the original
    BOM, namespace declaration, quoting, and root tag untouched.
    """

    security_override = b'<Override PartName="/SecurityBindings" ContentType="" />'
    if security_override not in content_types:
        raise ValueError("SecurityBindings override was not found in [Content_Types].xml")
    content_types = content_types.replace(security_override, b"", 1)

    png_type = b'<Default Extension="png" ContentType="image/png" />'
    if png_type not in content_types:
        json_type = b'<Default Extension="json" ContentType="" />'
        if json_type not in content_types:
            raise ValueError("JSON content type was not found in [Content_Types].xml")
        content_types = content_types.replace(json_type, json_type + png_type, 1)
    return content_types


def build_story_report() -> Path:
    missing = [path for path in (SOURCE_REPORT, *(CHART_DIR / name for name in CHARTS)) if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required input(s): " + ", ".join(str(path) for path in missing))
    if OUTPUT_REPORT == SOURCE_REPORT:
        raise ValueError("Output report must differ from the source report")
    for chart_name in CHARTS:
        chart_path = CHART_DIR / chart_name
        if not chart_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Power BI story asset is not a valid PNG: {chart_path}")

    with zipfile.ZipFile(SOURCE_REPORT, "r") as source:
        entries = {name: source.read(name) for name in source.namelist()}

    report_path = "Report/definition/report.json"
    pages_path = "Report/definition/pages/pages.json"
    report = json.loads(entries[report_path])
    pages = json.loads(entries[pages_path])

    # Power BI may persist an unfinished default scratch page named ``Page 1``
    # from an interrupted editing session. It is not part of the interview
    # narrative and can contain partial visuals, so omit it from the generated
    # copy without changing the source PBIX.
    scratch_page_ids = []
    for page_id in pages["pageOrder"]:
        page_key = f"Report/definition/pages/{page_id}/page.json"
        if json.loads(entries[page_key]).get("displayName") == "Page 1":
            scratch_page_ids.append(page_id)
    if scratch_page_ids:
        pages["pageOrder"] = [
            page_id for page_id in pages["pageOrder"] if page_id not in scratch_page_ids
        ]
        for scratch_page_id in scratch_page_ids:
            scratch_prefix = f"Report/definition/pages/{scratch_page_id}/"
            entries = {
                name: data for name, data in entries.items() if not name.startswith(scratch_prefix)
            }

    resource_items = []
    registered = next(
        (package for package in report.get("resourcePackages", []) if package.get("name") == "RegisteredResources"),
        None,
    )
    if registered is None:
        registered = {"name": "RegisteredResources", "type": "RegisteredResources", "items": []}
        report.setdefault("resourcePackages", []).append(registered)

    for chart_name in CHARTS:
        resource_name = _resource_name(chart_name)
        resource_items.append(resource_name)
        registered["items"] = [item for item in registered["items"] if item.get("name") != resource_name]
        registered["items"].append(
            {"name": resource_name, "path": resource_name, "type": "Image"}
        )
        entries[f"Report/StaticResources/RegisteredResources/{resource_name}"] = (
            CHART_DIR / chart_name
        ).read_bytes()

    page_specs = (
        (
            "priority-model-mechanics",
            "Model Mechanics",
            (
                (0, 30, 25, 910, 495),
                (1, 980, 25, 910, 495),
                (2, 30, 550, 1860, 500),
            ),
        ),
        (
            "priority-score-anatomy",
            "Score Anatomy",
            ((3, 30, 25, 1860, 1030),),
        ),
    )

    new_page_ids = []
    for page_label, display_name, visuals in page_specs:
        page_id = _stable_id(page_label)
        new_page_ids.append(page_id)
        entries[f"Report/definition/pages/{page_id}/page.json"] = _json_bytes(
            _page(page_id, display_name)
        )
        for tab_order, (chart_index, x, y, width, height) in enumerate(visuals):
            visual_id = _stable_id(f"{page_label}-{chart_index}")
            entries[f"Report/definition/pages/{page_id}/visuals/{visual_id}/visual.json"] = _json_bytes(
                _image_visual(
                    visual_id,
                    resource_items[chart_index],
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    tab_order=tab_order,
                )
            )

    # Replace pages with these deterministic IDs if the script is run again.
    pages["pageOrder"] = [page_id for page_id in pages["pageOrder"] if page_id not in new_page_ids]
    pages["pageOrder"].extend(new_page_ids)

    # Put the report in presentation order. The analysis starts broad, explains
    # why Signal Gap deserves attention, exposes the scoring math, shows the
    # resulting queue, and only then compares it with manual validation.
    page_display_names = {}
    for page_id in pages["pageOrder"]:
        page_key = f"Report/definition/pages/{page_id}/page.json"
        page_display_names[page_id] = json.loads(entries[page_key])["displayName"]
    presentation_order = {
        name: index
        for index, name in enumerate(
            (
                "Overview",
                "Signal Gap Analysis",
                "Model Mechanics",
                "P1 Queue",
                "Score Anatomy",
                "Manual Validation",
                "Validation Sample",
                "Rule Descriptions",
                "Priority Model",
            )
        )
    }
    original_order = {page_id: index for index, page_id in enumerate(pages["pageOrder"])}
    pages["pageOrder"].sort(
        key=lambda page_id: (
            presentation_order.get(page_display_names[page_id], len(presentation_order)),
            original_order[page_id],
        )
    )
    pages["activePageName"] = next(
        page_id for page_id, display_name in page_display_names.items() if display_name == "Overview"
    )
    entries[report_path] = _json_bytes(report)
    entries[pages_path] = _json_bytes(pages)

    # SecurityBindings signs package contents. Power BI recreates it after the
    # first successful Desktop save, so it must be omitted after editing.
    entries.pop("SecurityBindings", None)
    content_types_path = "[Content_Types].xml"
    entries[content_types_path] = _update_content_types(entries[content_types_path])

    with zipfile.ZipFile(OUTPUT_REPORT, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, data in entries.items():
            output.writestr(name, data)

    with zipfile.ZipFile(OUTPUT_REPORT, "r") as result:
        corrupt_member = result.testzip()
        if corrupt_member:
            raise RuntimeError(f"Corrupt member in output package: {corrupt_member}")
        names = set(result.namelist())
        for page_id in new_page_ids:
            required = f"Report/definition/pages/{page_id}/page.json"
            if required not in names:
                raise RuntimeError(f"Missing generated report page: {required}")
        for name in resource_items:
            required = f"Report/StaticResources/RegisteredResources/{name}"
            if required not in names:
                raise RuntimeError(f"Missing registered chart: {required}")
        content_types = result.read("[Content_Types].xml")
        expected_root = b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        if expected_root not in content_types:
            raise RuntimeError("[Content_Types].xml does not contain Power BI's required Types root tag")
        if b"SecurityBindings" in content_types:
            raise RuntimeError("[Content_Types].xml still registers SecurityBindings")
        if b'<Default Extension="png" ContentType="image/png" />' not in content_types:
            raise RuntimeError("[Content_Types].xml does not register the image/png MIME type")

    return OUTPUT_REPORT


if __name__ == "__main__":
    output = build_story_report()
    with zipfile.ZipFile(output, "r") as package:
        page_metadata = json.loads(package.read("Report/definition/pages/pages.json"))
    print(f"Written: {output}")
    print(f"Report pages: {len(page_metadata['pageOrder'])}")
    print("Added pages: Model Mechanics, Score Anatomy")
    print("Embedded charts: 4")
    print("Package integrity: passed")
