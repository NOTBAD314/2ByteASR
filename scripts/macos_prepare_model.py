# SPDX-License-Identifier: GPL-3.0-only
"""Use the project's locked downloader/integrity contract for SenseVoice CPU."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--models",type=Path,required=True)
    parser.add_argument("--source",choices=["HF_OFFICIAL","HF_MIRROR","MODELSCOPE","AUTO"],default="HF_OFFICIAL")
    args=parser.parse_args(argv)
    from twobyteasr.model_integrity import locked_model, verify_model_files
    from twobyteasr.repository_download import download_model
    spec=locked_model("sensevoice",root=ROOT)
    destination=args.models.expanduser().resolve()/Path(spec["path"]).name
    download_model(model_key="sensevoice",spec=spec,destination=destination,mode=args.source,
                   staging_root=args.models.resolve()/".download-staging")
    verify_model_files("sensevoice",destination,root=ROOT)
    print("Locked model verified:",destination)
    return 0


if __name__=="__main__": raise SystemExit(main())
