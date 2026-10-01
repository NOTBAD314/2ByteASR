# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import functools
import glob
import logging
import os
import time

import soundfile as sf
from textgrid import TextGrid, IntervalTier

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
        with open(args.wav_scp) as fin:
            wavs = [line.strip().split() for line in fin]
    elif args.wav_dir:
        wavs = glob.glob(f"{args.wav_dir}/**/*.wav", recursive=True)
        wavs = [(base(p), p) for p in sorted(wavs)]
    else:
        raise ValueError("Please provide valid wav info")
    logger.info(f"#wavs={len(wavs)}")
    return wavs


def write_textgrid(wav_path, wav_dur, event):
    textgrid_file = wav_path.replace(".wav", ".TextGrid")
    logger.info(f"Write {textgrid_file}")
    textgrid = TextGrid(maxTime=wav_dur)
    tier = IntervalTier(name="voice", maxTime=wav_dur)
    for start_s, end_s in event:
        if start_s == end_s:
            logger.warning(f"Write TG, skip start=end {start_s}")
            continue
        start_s = max(start_s, 0)
        end_s = min(end_s, wav_dur)
        tier.add(minTime=start_s, maxTime=end_s, mark="1")
    textgrid.append(tier)
    textgrid.write(textgrid_file)


def write_event_textgrid(wav_path, wav_dur, event2starts_ends_s):
    textgrid_file = wav_path.replace(".wav", ".TextGrid")
    logger.info(f"Write {textgrid_file}")
    textgrid = TextGrid(maxTime=wav_dur)
    for event, starts_ends_s in event2starts_ends_s.items():
        tier = IntervalTier(name=event, maxTime=wav_dur)
        for start_s, end_s in starts_ends_s:
            if start_s == end_s:
                logger.warning(f"Write TG, skip start=end {start_s}")
                continue
            start_s = max(start_s, 0)
            end_s = min(end_s, wav_dur)
            tier.add(minTime=start_s, maxTime=end_s, mark="1")
        textgrid.append(tier)
    textgrid.write(textgrid_file)



def split_and_save_segment(wav_path, timestamps, save_segment_dir):
    logger.info("Split & save segment")
    os.makedirs(save_segment_dir, exist_ok=True)
    wav_np, sample_rate = sf.read(wav_path, dtype="int16")
    for j, (start_s, end_s) in enumerate(timestamps):
        uttid = wav_path.split("/")[-1].replace(".wav", "")
        seg_id = f"{uttid}_{j}_{int(start_s*1000)}_{int(end_s*1000)}"
        seg_path = f"{save_segment_dir}/{seg_id}.wav"
        start, end = int(start_s * sample_rate), int(end_s * sample_rate)
        sf.write(seg_path, wav_np[start:end], samplerate=sample_rate)


def split_and_save_event_segment(wav_path, event2timestamps, save_segment_dir):
    logger.info("Split & save segment")
    os.makedirs(save_segment_dir, exist_ok=True)
    wav_np, sample_rate = sf.read(wav_path, dtype="int16")
    for event, timestamps in event2timestamps.items():
        for i, (start_s, end_s) in enumerate(timestamps):
            uttid = wav_path.split("/")[-1].replace(".wav", "")
            seg_id = f"{uttid}_{event}_{i}_{int(start_s*1000)}_{int(end_s*1000)}"
            seg_path = f"{save_segment_dir}/{seg_id}.wav"
            start, end = int(start_s * sample_rate), int(end_s * sample_rate)
            sf.write(seg_path, wav_np[start:end], samplerate=sample_rate)


def timeit(func):
    # dur must be last return value of func
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        r = func(*args, **kwargs)
        elapsed = time.time() - start
        dur = r[-1]
        rtf = elapsed / dur if dur else 0
        logger.info(f"RTF={round(rtf, 5)}, elapsed={round(elapsed*1000, 2)}ms, dur={dur}s")
        return r
    return wrapper
