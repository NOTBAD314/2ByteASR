#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import argparse
import json
import logging
import time

from fireredvad.aed import FireRedAedConfig, FireRedAed
from fireredvad.utils.io import get_wav_info, write_event_textgrid, split_and_save_event_segment

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredvad.bin.aed")


parser = argparse.ArgumentParser()
# Input
parser.add_argument("--wav_path", type=str)
parser.add_argument("--wav_paths", type=str, nargs="*")
parser.add_argument("--wav_scp", type=str)
parser.add_argument("--wav_dir", type=str)
# Output
parser.add_argument("--output", type=str, default="aed_output")
parser.add_argument("--write_textgrid", type=int, default=0)
parser.add_argument("--save_segment_dir", type=str, default="")
# AED Options
parser.add_argument('--model_dir', type=str,
    default="pretrained_models/FireRedVAD-AED-251104")
parser.add_argument('--use_gpu', type=int, default=0)
parser.add_argument("--smooth_window_size", type=int, default=5)
parser.add_argument("--speech_threshold", type=float, default=0.4)
parser.add_argument("--singing_threshold", type=float, default=0.5)
parser.add_argument("--music_threshold", type=float, default=0.5)
parser.add_argument("--min_event_frame", type=int, default=20)
parser.add_argument("--max_event_frame", type=int, default=2000)
parser.add_argument("--min_silence_frame", type=int, default=20)
parser.add_argument("--merge_silence_frame", type=int, default=0)
parser.add_argument("--extend_speech_frame", type=int, default=0)
parser.add_argument("--chunk_max_frame", type=int, default=30000)


def main(args):
    logger.info("Start AED...\n")
    wavs = get_wav_info(args)
    fout = open(args.output, "w") if args.output else None

    aed_config = FireRedAedConfig(
        use_gpu = args.use_gpu,
        smooth_window_size = args.smooth_window_size,
        speech_threshold = args.speech_threshold,
        singing_threshold = args.singing_threshold,
        music_threshold = args.music_threshold,
        min_event_frame = args.min_event_frame,
        max_event_frame = args.max_event_frame,
        min_silence_frame = args.min_silence_frame,
        merge_silence_frame = args.merge_silence_frame,
        extend_speech_frame = args.extend_speech_frame,
        chunk_max_frame = args.chunk_max_frame)
    logger.info(f"{aed_config}")
    aed = FireRedAed.from_pretrained(args.model_dir, aed_config)

    for i, (uttid, wav_path) in enumerate(wavs):
        logger.info("")
        logger.info(f">>> {i} Processing {wav_path}")
        start_time = time.time()

        result, probs = aed.detect(wav_path)

        elapsed = time.time() - start_time
        dur = result["dur"]
        rtf = elapsed / dur if dur > 0 else 0
        logger.info(f"Result: {result}")
        logger.info(f"Dur={dur} elapsed(ms)={round(elapsed*1000, 2)} RTF={round(rtf, 5)}")

        if fout:
            fout.write(f"{json.dumps(result, ensure_ascii=False)}\n")
        if args.write_textgrid:
            write_event_textgrid(result["wav_path"], result["dur"], result["event2timestamps"])
        if args.save_segment_dir:
            split_and_save_event_segment(wav_path, result["event2timestamps"], args.save_segment_dir)
    if fout: fout.close()

    logger.info("All AED Done")



if __name__ == "__main__":
    args = parser.parse_args()
    logger.info(f"{args}")
    main(args)
