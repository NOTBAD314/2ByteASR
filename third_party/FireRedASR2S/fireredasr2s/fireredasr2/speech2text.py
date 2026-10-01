#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu)

import argparse
import json
import logging
import os

from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config
from fireredasr2.utils.io import get_wav_info, write_textgrid

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredasr2.bin.speech2text")


parser = argparse.ArgumentParser()
parser.add_argument('--asr_type', type=str, required=True, choices=["aed", "llm"])
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
parser.add_argument("--beam_size", type=int, default=1)
parser.add_argument("--decode_max_len", type=int, default=0)
# FireRedASR-AED
parser.add_argument("--nbest", type=int, default=1)
parser.add_argument("--softmax_smoothing", type=float, default=1.0)
parser.add_argument("--aed_length_penalty", type=float, default=0.0)
parser.add_argument("--eos_penalty", type=float, default=1.0)
parser.add_argument("--return_timestamp", type=int, default=0)
parser.add_argument("--write_textgrid", type=int, default=0)
# AED External LM
parser.add_argument("--elm_dir", type=str, default="")
parser.add_argument("--elm_weight", type=float, default=0.0)
# FireRedASR-LLM
parser.add_argument("--decode_min_len", type=int, default=0)
parser.add_argument("--repetition_penalty", type=float, default=1.0)
parser.add_argument("--llm_length_penalty", type=float, default=0.0)
parser.add_argument("--temperature", type=float, default=1.0)


def main(args):
    wavs = get_wav_info(args)
    fout = open(args.output, "w") if args.output else None
    foutl = open(args.output + ".jsonl", "w") if args.output else None

    asr_config = FireRedAsr2Config(
            args.use_gpu,
            args.use_half,
            args.beam_size,
            args.nbest,
            args.decode_max_len,
            args.softmax_smoothing,
            args.aed_length_penalty,
            args.eos_penalty,
            args.return_timestamp,
            args.decode_min_len,
            args.repetition_penalty,
            args.llm_length_penalty,
            args.temperature,
            args.elm_dir,
            args.elm_weight
    )
    model = FireRedAsr2.from_pretrained(args.asr_type, args.model_dir, asr_config)

    batch_uttid = []
    batch_wav_path = []
    for i, wav in enumerate(wavs):
        uttid, wav_path = wav
        batch_uttid.append(uttid)
        batch_wav_path.append(wav_path)
        if len(batch_wav_path) < args.batch_size and i != len(wavs) - 1:
            continue

        results = model.transcribe(batch_uttid, batch_wav_path)

        for result in results:
            logger.info(result)
            if fout is not None:
                foutl.write(f"{json.dumps(result, ensure_ascii=False)}\n")
                fout.write(f"{result['uttid']}\t{result['text']}\n")
            if args.write_textgrid and "timestamp" in result:
                write_textgrid(result["wav"], result["dur_s"], result["timestamp"])

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
