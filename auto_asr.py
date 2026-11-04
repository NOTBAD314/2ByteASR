"""Thin launcher for the production subtitle workflow."""

import os

import moss_firered_pipeline
import subtitle_core


PIPELINE_BUILD_ID = "2026.08.10-v7.18-asr-result-schema-v2"


def main():
    try:
        moss_firered_pipeline.verify_pipeline_contract(
            subtitle_core,
            os.path.realpath(__file__),
            PIPELINE_BUILD_ID,
        )
    except Exception as exc:
        print(f"\n[版本/路径自检失败] {exc}")
        subtitle_core.pause_exit(1)
    moss_firered_pipeline.main(subtitle_core)


if __name__ == "__main__":
    main()
