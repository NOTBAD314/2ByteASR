# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)

import glob
import logging
import os

logger = logging.getLogger(__name__)


def get_wav_info(args):
    """
    Returns:
        wavs: list of (uttid, wav_path)
    """
    base = lambda p: os.path.basename(p).replace(".wav", "")
    if args.wav_path:
        wavs = [(base(args.wav_path), args.wav_path)]
    elif args.wav_paths and len(args.wav_paths) >= 1:
        wavs = [(base(p), p) for p in sorted(args.wav_paths)]
    elif args.wav_scp:
        wavs = [line.strip().split() for line in open(args.wav_scp)]
        if args.sort_wav_by_dur:
            logger.info("Sort wav by duration...")
            utt2dur = os.path.join(os.path.dirname(args.wav_scp), "utt2dur")
            if os.path.exists(utt2dur):
                utt2dur = [l.strip().split() for l in open(utt2dur)]
                utt2dur = {l[0]: float(l[1]) for l in utt2dur if len(l) == 2}
                wavs = sorted(wavs, key=lambda x: -utt2dur[x[0]])
                logger.info("Sort Done")
            else:
                logger.info(f"Not find {utt2dur}, un-sort")
    elif args.wav_dir:
        wavs = glob.glob(f"{args.wav_dir}/**/*.wav", recursive=True)
        wavs = [(base(p), p) for p in sorted(wavs)]
    else:
        raise ValueError("Please provide valid wav info")
    logger.info(f"#wavs={len(wavs)}")
    return wavs
