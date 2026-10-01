#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)

import argparse
import json
import logging
import os

from fireredlid.lid import FireRedLid, FireRedLidConfig
from fireredlid.utils.io import get_wav_info

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredlid.bin.speech2lang")


parser = argparse.ArgumentParser()
parser.add_argument('--model_dir', type=str, required=True)

# Input / Output
parser.add_argument("--wav_path", type=str)
parser.add_argument("--wav_paths", type=str, nargs="*")
parser.add_argument("--wav_dir", type=str)
parser.add_argument("--wav_scp", type=str)
parser.add_argument("--sort_wav_by_dur", type=int, default=0)
parser.add_argument("--output", type=str)
# Decode Options
parser.add_argument('--use_gpu', type=int, default=1)
parser.add_argument('--use_half', type=int, default=0)
parser.add_argument("--batch_size", type=int, default=1)


def main(args):
    wavs = get_wav_info(args)
    fout = open(args.output, "w") if args.output else None
    foutl = open(args.output + ".jsonl", "w") if args.output else None

    lid_config = FireRedLidConfig(
            args.use_gpu,
            args.use_half
    )
    model = FireRedLid.from_pretrained(args.model_dir, lid_config)

    batch_uttid = []
    batch_wav_path = []
    for i, wav in enumerate(wavs):
        uttid, wav_path = wav
        batch_uttid.append(uttid)
        batch_wav_path.append(wav_path)
        if len(batch_wav_path) < args.batch_size and i != len(wavs) - 1:
            continue

        results = model.process(batch_uttid, batch_wav_path)

        for result in results:
            logger.info(result)
            if fout is not None:
                foutl.write(f"{json.dumps(result, ensure_ascii=False)}\n")
                fout.write(f"{result['uttid']}\t{result['lang']}\n")

        if fout: fout.flush()
        if foutl: foutl.flush()
        batch_uttid = []
        batch_wav_path = []
    if fout: fout.close()
    if foutl: foutl.close()


if __name__ == "__main__":
    args = parser.parse_args()
    logger.info(args)
    main(args)
