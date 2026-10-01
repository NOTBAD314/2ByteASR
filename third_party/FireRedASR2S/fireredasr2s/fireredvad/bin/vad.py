#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import argparse
import json
import logging
import time

from fireredvad.vad import FireRedVadConfig, FireRedVad
from fireredvad.utils.io import get_wav_info, write_textgrid, split_and_save_segment

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredvad.bin.vad")


parser = argparse.ArgumentParser()
# Input
parser.add_argument("--wav_path", type=str)
parser.add_argument("--wav_paths", type=str, nargs="*")
parser.add_argument("--wav_scp", type=str)
parser.add_argument("--wav_dir", type=str)
# Output
parser.add_argument("--output", type=str, default="vad_output")
parser.add_argument("--write_textgrid", type=int, default=0)
parser.add_argument("--save_segment_dir", type=str, default="")
# VAD Options
parser.add_argument('--model_dir', type=str,
    default="pretrained_models/FireRedVAD-VAD-preview")
parser.add_argument('--use_gpu', type=int, default=0)
parser.add_argument("--smooth_window_size", type=int, default=5)
parser.add_argument("--speech_threshold", type=float, default=0.4)
parser.add_argument("--min_speech_frame", type=int, default=20)
parser.add_argument("--max_speech_frame", type=int, default=2000)
parser.add_argument("--min_silence_frame", type=int, default=20)
parser.add_argument("--merge_silence_frame", type=int, default=0)
parser.add_argument("--extend_speech_frame", type=int, default=0)
parser.add_argument("--chunk_max_frame", type=int, default=30000)


def main(args):
    logger.info("Start VAD...\n")
    wavs = get_wav_info(args)
    fout = open(args.output, "w") if args.output else None

    vad_config = FireRedVadConfig(
        use_gpu = args.use_gpu,
        smooth_window_size = args.smooth_window_size,
        speech_threshold = args.speech_threshold,
        min_speech_frame = args.min_speech_frame,
        max_speech_frame = args.max_speech_frame,
        min_silence_frame = args.min_silence_frame,
        merge_silence_frame = args.merge_silence_frame,
        extend_speech_frame = args.extend_speech_frame,
        chunk_max_frame = args.chunk_max_frame)
    logger.info(f"{vad_config}")
    vad = FireRedVad.from_pretrained(args.model_dir, vad_config)

    for i, (uttid, wav_path) in enumerate(wavs):
        logger.info("")
        logger.info(f">>> {i} Processing {wav_path}")
        start_time = time.time()

        result, probs = vad.detect(wav_path)

        elapsed = time.time() - start_time
        dur = result["dur"]
        rtf = elapsed / dur if dur > 0 else 0
        logger.info(f"Result: {result}")
        logger.info(f"Dur={dur} elapsed(ms)={round(elapsed*1000, 2)} RTF={round(rtf, 5)}")

        if fout:
            fout.write(f"{json.dumps(result, ensure_ascii=False)}\n")
        if args.write_textgrid:
            write_textgrid(result["wav_path"], result["dur"], result["timestamps"])
        if args.save_segment_dir:
            split_and_save_segment(wav_path, result["timestamps"], args.save_segment_dir)
    if fout: fout.close()

    logger.info("All VAD Done")



if __name__ == "__main__":
    args = parser.parse_args()
    logger.info(f"{args}")
    main(args)
