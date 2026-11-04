# SPDX-License-Identifier: GPL-3.0-only
"""Check the actual pip report against the reviewed native wheel digests."""
from __future__ import annotations
import re


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+","-",name).lower()


def verify_native_wheels(report: dict, lock: dict) -> list[dict]:
    actual={normalize(row["metadata"]["name"]):row for row in report.get("install",[])}
    verified=[]
    for name,spec in lock["critical_wheel_availability"].items():
        row=actual.get(normalize(name))
        if row is None:raise RuntimeError("The fresh pip report omitted a required native wheel: "+name)
        if row["metadata"]["version"]!=spec["version"]:
            raise RuntimeError("Native package version drift: "+name)
        info=row.get("download_info",{})
        digest=info.get("archive_info",{}).get("hashes",{}).get("sha256","")
        expected=next((wheel for wheel in spec["arm64_cp310_or_universal"] if wheel["sha256"]==digest),None)
        if expected is None:raise RuntimeError("Native wheel digest differs from reviewed lock: "+name)
        verified.append({"package":name,"version":spec["version"],"filename":expected["filename"],
                         "sha256":digest,"actual_download_url":info.get("url","")})
    return verified
