#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)

import argparse
import json
import logging

import soundfile as sf

from fireredvad.core.constants import SAMPLE_RATE, FRAME_LENGTH_SAMPLE, FRAME_SHIFT_SAMPLE
from fireredvad.stream_vad import FireRedStreamVadConfig, FireRedStreamVad
from fireredvad.utils.io import get_wav_info, write_textgrid, split_and_save_segment, timeit

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredvad.bin.stream_vad")


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
    default="pretrained_models/FireRedVAD-VAD-stream-251104")
parser.add_argument('--stream_vad_mode', type=str, default="all",
    choices=["framewise", "chunkwise", "full", "all"])
parser.add_argument('--stream_chunk_frame', type=int, default=10)
# Vad Config
parser.add_argument('--use_gpu', type=int, default=0)
parser.add_argument("--smooth_window_size", type=int, default=5)
parser.add_argument("--speech_threshold", type=float, default=0.3)
parser.add_argument("--pad_start_frame", type=int, default=5)
parser.add_argument("--min_speech_frame", type=int, default=8)
parser.add_argument("--max_speech_frame", type=int, default=2000)
parser.add_argument("--min_silence_frame", type=int, default=20)
parser.add_argument("--chunk_max_frame", type=int, default=30000)


def main(args):
    logger.info("Start Stream VAD...\n")
    wavs = get_wav_info(args)
    fout = open(args.output, "w") if args.output else None

    vad_config = FireRedStreamVadConfig(
        use_gpu = args.use_gpu,
        smooth_window_size = args.smooth_window_size,
        speech_threshold = args.speech_threshold,
        pad_start_frame = args.pad_start_frame,
        min_speech_frame = args.min_speech_frame,
        max_speech_frame = args.max_speech_frame,
        min_silence_frame = args.min_silence_frame,
        chunk_max_frame = args.chunk_max_frame)
    logger.info(f"{vad_config}")
    stream_vad = FireRedStreamVad.from_pretrained(args.model_dir, vad_config)

    for i, (uttid, wav_path) in enumerate(wavs):
        logger.info("")
        logger.info(f">>> {i} Processing {wav_path}")

        if args.stream_vad_mode in ["all", "full"]:
            results, timestamps, dur = vad_full(wav_path, stream_vad, args)

        if args.stream_vad_mode in ["all", "chunkwise"]:
            results, timestamps, dur = vad_chunkwise(wav_path, stream_vad, args)

        if args.stream_vad_mode in ["all", "framewise"]:
            results, timestamps, dur = vad_framewise(wav_path, stream_vad, args)

        if fout:
            d = {"uttid": uttid, "wav_path": wav_path, "dur": dur, "timestamps": timestamps}
            fout.write(f"{json.dumps(d, ensure_ascii=False)}\n")
        if args.write_textgrid:
            write_textgrid(wav_path, dur, timestamps) 
        if args.save_segment_dir:
            split_and_save_segment(wav_path, timestamps, args.save_segment_dir)
    if fout: fout.close()

    logger.info("All Stream VAD Done")


@timeit
def vad_framewise(wav_path, stream_vad, args):
    logger.info("Stream VAD Mode: framewise")

    wav_np, sr = sf.read(wav_path, dtype="int16")
    assert sr == SAMPLE_RATE
    n_frame = 0
    frame_results = []
    stream_vad.reset()
    for j in range(0, len(wav_np) - FRAME_LENGTH_SAMPLE + 1, FRAME_SHIFT_SAMPLE):
        audio_frame = wav_np[j:j+FRAME_LENGTH_SAMPLE]
        result = stream_vad.detect_frame(audio_frame)
        n_frame += 1
        logger.debug(f"{n_frame:4d} {result}")
        if result.is_speech_start:
            logger.info(f"Speech start {result.speech_start_frame}")
        elif result.is_speech_end:
            logger.info(f"Speech end {result.speech_end_frame}")
        frame_results.append(result)

    logger.info(f"#frame={len(frame_results)}")
    timestamps = stream_vad.results_to_timestamps(frame_results)
    logger.info(f"timestamps(seconds): {timestamps}")
    dur = len(wav_np) / sr
    return frame_results, timestamps, dur


@timeit
def vad_chunkwise(wav_path, stream_vad, args):
    logger.info(f"Stream VAD Mode: chunkwise {args.stream_chunk_frame}")
    N = args.stream_chunk_frame
    assert N > 0
    chunk_length = FRAME_LENGTH_SAMPLE + (N-1)*FRAME_SHIFT_SAMPLE
    chunk_shift = N * FRAME_SHIFT_SAMPLE

    wav_np, sr = sf.read(wav_path, dtype="int16")
    assert sr == SAMPLE_RATE
    n_frame = 0
    chunk_results = []
    stream_vad.reset()
    for j in range(0, len(wav_np), chunk_shift):
        audio_chunk = wav_np[j:j+chunk_length]
        results = stream_vad.detect_chunk(audio_chunk)
        for result in results:
            n_frame += 1
            logger.debug(f"{n_frame:4d} {result}")
            if result.is_speech_start:
                logger.info(f"Speech start {result.speech_start_frame}")
            elif result.is_speech_end:
                logger.info(f"Speech end {result.speech_end_frame}")
            chunk_results.append(result)

    logger.info(f"#frame={len(chunk_results)}")
    timestamps = stream_vad.results_to_timestamps(chunk_results)
    logger.info(f"timestamps(seconds): {timestamps}")
    dur = len(wav_np) / sr
    return chunk_results, timestamps, dur


@timeit
def vad_full(wav_path, stream_vad, args):
    logger.info("Stream VAD Mode: full")
    frame_results, result = stream_vad.detect_full(wav_path)
    logger.info(f"Result: {result}")
    timestamps = result["timestamps"]
    dur = result["dur"]

    n_frame = 0
    for frame_result in frame_results:
        n_frame += 1
        logger.debug(f"{n_frame:4d} {result}")
        if frame_result.is_speech_start:
            logger.info(f"Speech start {frame_result.speech_start_frame}")
        elif frame_result.is_speech_end:
            logger.info(f"Speech end {frame_result.speech_end_frame}")
    logger.info(f"#frame={len(frame_results)}")

    return frame_results, timestamps, dur


if __name__ == "__main__":
    args = parser.parse_args()
    logger.info(f"{args}")
    main(args)
