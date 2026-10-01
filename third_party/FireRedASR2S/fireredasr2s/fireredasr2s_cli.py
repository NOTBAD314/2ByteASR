#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang, Yan Jia, Junjie Chen, Wenpeng Li)

import argparse
import glob
import json
import logging
import os

import soundfile as sf
from textgrid import IntervalTier, TextGrid

from fireredasr2s.fireredasr2 import FireRedAsr2Config
from fireredasr2s.fireredasr2system import (FireRedAsr2System,
                                            FireRedAsr2SystemConfig)
from fireredasr2s.fireredlid import FireRedLidConfig
from fireredasr2s.fireredpunc import FireRedPuncConfig
from fireredasr2s.fireredvad import FireRedVadConfig

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredasr2s.asr_system")


parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
input_g = parser.add_argument_group("Input Options")
input_g.add_argument("--wav_path", type=str)
input_g.add_argument("--wav_paths", type=str, nargs="*")
input_g.add_argument("--wav_dir", type=str)
input_g.add_argument("--wav_scp", type=str)
input_g.add_argument("--sort_wav_by_dur", type=int, default=0)

output_g = parser.add_argument_group("Output Options")
output_g.add_argument("--outdir", type=str, default="output")
output_g.add_argument("--write_textgrid", type=int, default=1)
output_g.add_argument("--write_srt", type=int, default=1)
output_g.add_argument("--save_segment", type=int, default=0)

module_g = parser.add_argument_group("Module Switches")
module_g.add_argument('--enable_vad', type=int, default=1, choices=[0, 1])
module_g.add_argument('--enable_lid', type=int, default=1, choices=[0, 1])
module_g.add_argument('--enable_punc', type=int, default=1, choices=[0, 1])

asr_g = parser.add_argument_group("ASR Options")
asr_g.add_argument('--asr_type', type=str, default="aed", choices=["aed", "llm"])
asr_g.add_argument('--asr_model_dir', type=str, default="pretrained_models/FireRedASR2-AED")
asr_g.add_argument('--asr_use_gpu', type=int, default=1)
asr_g.add_argument('--asr_use_half', type=int, default=0)
asr_g.add_argument("--asr_batch_size", type=int, default=1)
# FireRedASR-AED
asr_g.add_argument("--beam_size", type=int, default=3)
asr_g.add_argument("--decode_max_len", type=int, default=0)
asr_g.add_argument("--nbest", type=int, default=1)
asr_g.add_argument("--softmax_smoothing", type=float, default=1.25)
asr_g.add_argument("--aed_length_penalty", type=float, default=0.6)
asr_g.add_argument("--eos_penalty", type=float, default=1.0)
asr_g.add_argument("--return_timestamp", type=int, default=1)
# FireRedASR-AED External LM
asr_g.add_argument("--elm_dir", type=str, default="")
asr_g.add_argument("--elm_weight", type=float, default=0.0)

vad_g = parser.add_argument_group("VAD Options")
vad_g.add_argument('--vad_model_dir', type=str, default="pretrained_models/FireRedVAD/VAD")
vad_g.add_argument('--vad_use_gpu', type=int, default=1)
# Non-streaming VAD
vad_g.add_argument("--vad_chunk_max_frame", type=int, default=30000)
vad_g.add_argument("--smooth_window_size", type=int, default=5)
vad_g.add_argument("--speech_threshold", type=float, default=0.2)
vad_g.add_argument("--min_speech_frame", type=int, default=20)
vad_g.add_argument("--max_speech_frame", type=int, default=1000)
vad_g.add_argument("--min_silence_frame", type=int, default=10)
vad_g.add_argument("--merge_silence_frame", type=int, default=50)
vad_g.add_argument("--extend_speech_frame", type=int, default=10)

lid_g = parser.add_argument_group("LID Options")
lid_g.add_argument('--lid_model_dir', type=str, default="pretrained_models/FireRedLID")
lid_g.add_argument('--lid_use_gpu', type=int, default=1)

punc_g = parser.add_argument_group("Punc Options")
punc_g.add_argument('--punc_model_dir', type=str, default="pretrained_models/FireRedPunc")
punc_g.add_argument('--punc_use_gpu', type=int, default=1)
punc_g.add_argument("--punc_batch_size", type=int, default=1)
punc_g.add_argument('--punc_with_timestamp', type=int, default=1)
punc_g.add_argument('--punc_sentence_max_length', type=int, default=-1)


def main(args):
    wavs = get_wav_info(args)
    if args.outdir:
        os.makedirs(args.outdir, exist_ok=True)
    fout = open(args.outdir + "/result.jsonl", "w") if args.outdir else None

    # Build Models
    # VAD
    vad_config = FireRedVadConfig(
        args.vad_use_gpu,
        args.smooth_window_size,
        args.speech_threshold,
        args.min_speech_frame,
        args.max_speech_frame,
        args.min_silence_frame,
        args.merge_silence_frame,
        args.extend_speech_frame,
        args.vad_chunk_max_frame
    )
    # LID
    lid_config = FireRedLidConfig(args.lid_use_gpu)
    # ASR
    asr_config = FireRedAsr2Config(
        args.asr_use_gpu,
        args.asr_use_half,
        args.beam_size,
        args.nbest,
        args.decode_max_len,
        args.softmax_smoothing,
        args.aed_length_penalty,
        args.eos_penalty,
        args.return_timestamp,
        0, 1.0, 0.0, 1.0,
        args.elm_dir,
        args.elm_weight
    )
    # Punc
    punc_config = FireRedPuncConfig(
        args.punc_use_gpu,
        args.punc_sentence_max_length
    )

    asr_system_config = FireRedAsr2SystemConfig(
        args.vad_model_dir, args.lid_model_dir,
        args.asr_type, args.asr_model_dir, args.punc_model_dir,
        vad_config, lid_config, asr_config, punc_config,
        args.asr_batch_size, args.punc_batch_size,
        args.enable_vad, args.enable_lid, args.enable_punc
    )
    asr_system = FireRedAsr2System(asr_system_config)

    for i, (uttid, wav_path) in enumerate(wavs):
        logger.info("")

        result = asr_system.process(wav_path, uttid)

        logger.info(f"FINAL: {result}")

        if fout:
            fout.write(f"{json.dumps(result, ensure_ascii=False)}\n")
            fout.flush()
        name = os.path.basename(wav_path).replace(".wav", "")
        if args.write_textgrid:
            tg_dir = os.path.join(args.outdir, "asr_tg")
            write_textgrid(tg_dir, name, result["dur_s"], result["sentences"], result["words"])
        if args.write_srt:
            srt_dir = os.path.join(args.outdir, "asr_srt")
            write_srt(srt_dir, name, result["sentences"])
        if args.save_segment:
            save_segment_dir = os.path.join(args.outdir, "vad_segment")
            split_and_save_segment(wav_path, result["vad_segments_ms"], save_segment_dir)

    if fout:
        fout.close()
    logger.info("All Done")


def get_wav_info(args):
    """
    Returns:
        wavs: list of (uttid, wav_path)
    """
    def base(p): return os.path.basename(p).replace(".wav", "")
    if args.wav_path:
        wavs = [(base(args.wav_path), args.wav_path)]
    elif args.wav_paths and len(args.wav_paths) >= 1:
        wavs = [(base(p), p) for p in sorted(args.wav_paths)]
    elif args.wav_scp:
        wavs = [line.strip().split() for line in open(args.wav_scp)]
    elif args.wav_dir:
        wavs = glob.glob(f"{args.wav_dir}/**/*.wav", recursive=True)
        wavs = [(base(p), p) for p in sorted(wavs)]
    else:
        raise ValueError("Please provide valid wav info")
    logger.info(f"#wavs={len(wavs)}")
    return wavs


def write_textgrid(tg_dir, name, wav_dur, sentences, words=None):
    os.makedirs(tg_dir, exist_ok=True)
    textgrid_file = os.path.join(tg_dir, name + ".TextGrid")
    logger.info(f"Write {textgrid_file}")
    textgrid = TextGrid(maxTime=wav_dur)

    tier = IntervalTier(name="sentence", maxTime=wav_dur)
    for sentence in sentences:
        start_s = sentence["start_ms"] / 1000.0
        end_s = sentence["end_ms"] / 1000.0
        text = sentence["text"]
        confi = sentence["asr_confidence"]
        if start_s == end_s:
            logger.info(f"(sent) Write TG, skip start=end {start_s} {text}")
            continue
        start_s = max(start_s, 0)
        end_s = min(end_s, wav_dur)
        tier.add(minTime=start_s, maxTime=end_s, mark=f"{text}\n{confi}")
    textgrid.append(tier)

    if words:
        tier = IntervalTier(name="token", maxTime=wav_dur)
        for word in words:
            start_s = word["start_ms"] / 1000.0
            end_s = word["end_ms"] / 1000.0
            text = word["text"]
            if start_s == end_s:
                logger.info(f"(word) Write TG, skip start=end {start_s} {text}")
                continue
            start_s = max(start_s, 0)
            end_s = min(end_s, wav_dur)
            tier.add(minTime=start_s, maxTime=end_s, mark=text)
        textgrid.append(tier)
    textgrid.write(textgrid_file)


def write_srt(srt_dir, name, sentences):
    def _ms2srt_time(ms):
        h = ms // 1000 // 3600
        m = (ms // 1000 % 3600) // 60
        s = (ms // 1000 % 3600) % 60
        ms = (ms % 1000)
        r = f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        return r
    os.makedirs(srt_dir, exist_ok=True)
    srt_file = os.path.join(srt_dir, name + ".srt")
    logger.info(f"Write {srt_file}")

    i = 0
    with open(srt_file, "w") as fout:
        for sentence in sentences:
            start_ms = sentence["start_ms"]
            end_ms = sentence["end_ms"]
            text = sentence["text"]
            if text.strip() == "":
                continue

            i += 1
            fout.write(f"{i}\n")
            s = _ms2srt_time(start_ms)
            e = _ms2srt_time(end_ms)
            fout.write(f"{s} --> {e}\n")
            fout.write(f"{text}\n")
            if i != len(sentences):
                fout.write("\n")


def split_and_save_segment(wav_path, timestamps_ms, save_segment_dir):
    logger.info("Split & save segment")
    os.makedirs(save_segment_dir, exist_ok=True)
    wav_np, sample_rate = sf.read(wav_path, dtype="int16")
    for i, (start_ms, end_ms) in enumerate(timestamps_ms):
        uttid = wav_path.split("/")[-1].replace(".wav", "")
        seg_id = f"{uttid}_{i}_{start_ms}_{end_ms}"
        seg_path = f"{save_segment_dir}/{seg_id}.wav"
        start = int(start_ms / 1000 * sample_rate)
        end = int(end_ms / 1000 * sample_rate)
        sf.write(seg_path, wav_np[start:end], samplerate=sample_rate)


def cli_main():
    args = parser.parse_args()
    logger.info(args)
    main(args)


if __name__ == "__main__":
    cli_main()
