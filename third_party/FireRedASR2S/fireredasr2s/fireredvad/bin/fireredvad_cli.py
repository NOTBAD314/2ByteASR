#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import argparse
import logging

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredvad")


def main():
    parser = argparse.ArgumentParser(description="FireRedVAD: VAD & AED")
    parser.add_argument("--task", type=str, required=True,
                        choices=["vad", "stream_vad", "aed"],
                        help="Task type: vad, stream_vad, or aed")
    parser.add_argument("--wav_path", type=str, required=True)
    parser.add_argument("--model_dir", type=str, default=None)
    parser.add_argument("--use_gpu", type=int, default=0)
    
    args, unknown = parser.parse_known_args()
    
    if args.task == "vad":
        from fireredvad import non_stream_vad
        model_dir = args.model_dir or "pretrained_models/FireRedVAD/VAD"
        result = non_stream_vad(args.wav_path, model_dir=model_dir, use_gpu=args.use_gpu)
    elif args.task == "stream_vad":
        from fireredvad import stream_vad_full
        model_dir = args.model_dir or "pretrained_models/FireRedVAD/Stream-VAD"
        result = stream_vad_full(args.wav_path, model_dir=model_dir, use_gpu=args.use_gpu)
    elif args.task == "aed":
        from fireredvad import non_stream_aed
        model_dir = args.model_dir or "pretrained_models/FireRedVAD/AED"
        result = non_stream_aed(args.wav_path, model_dir=model_dir, use_gpu=args.use_gpu)
    
    logger.info(f"Result: {result}")


if __name__ == "__main__":
    main()
