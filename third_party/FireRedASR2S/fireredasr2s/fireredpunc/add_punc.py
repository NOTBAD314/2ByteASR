#!/usr/bin/env python3

# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Junjie Chen)

import argparse
import logging
import re

from fireredpunc.punc import FireRedPunc, FireRedPuncConfig

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s (%(module)s:%(lineno)d) %(levelname)s: %(message)s")
logger = logging.getLogger("fireredvad.bin.vad")


parser = argparse.ArgumentParser()
parser.add_argument('--model_dir', type=str, required=True)
# Input / Output
parser.add_argument("--input_txt", type=str, default="")
parser.add_argument("--input_file", type=str, default="")
parser.add_argument("--output", type=str)
parser.add_argument("--input_contain_uttid", type=int, default=0)
# Punc Options
parser.add_argument('--use_gpu', type=int, default=1)
parser.add_argument('--batch_size', type=int, default=1)
parser.add_argument('--sentence_max_length', type=int, default=-1)


def main(args):
    in_texts = get_input(args)
    fout = open(args.output, "w") if args.output else None

    punc_config = FireRedPuncConfig(
        args.use_gpu,
        args.sentence_max_length
    )
    model = FireRedPunc.from_pretrained(args.model_dir, punc_config)

    batch_text = []
    batch_uttid = []
    for i, (uttid, text) in enumerate(in_texts):
        batch_text.append(text)
        batch_uttid.append(uttid)
        if len(batch_text) < args.batch_size and i != len(in_texts) - 1:
            continue

        results = model.process(batch_text)

        for uttid, result in zip(batch_uttid, results):
            logger.info(result)
            if fout:
                if args.input_contain_uttid:
                    fout.write(f"{uttid}\t{result['punc_text']}\n")
                else:
                    fout.write(f"{result['punc_text']}\n")

        batch_text = []
        batch_uttid = []
        if fout: fout.flush()


def get_input(args):
    in_texts = []
    if args.input_file:
        with open(args.input_file, "r") as fin:
            for i, l in enumerate(fin):
                uttid = i
                text = l.strip()
                if args.input_contain_uttid:
                    uttid, text = text.split(maxsplit=1)
                text = _remove_punc_and_fix_space(text)
                in_texts.append((uttid, text))
        logger.info(f"#text={len(in_texts)}")
    elif args.input_txt:
        logger.info(f"Input txt: {args.input_txt}")
        text = _remove_punc_and_fix_space(args.input_txt)
        in_texts.append((0, text))
    return in_texts


def _remove_punc_and_fix_space(text):
    origin = text
    text = re.sub("[，。？！,\.?!]", " ", text)
    pattern = re.compile(r'([\u3400-\u4dbf\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\U00020000-\U0002a6df\U0002a700-\U0002b73f\U0002b740-\U0002b81f\U0002b820-\U0002ceaf\U0002ceb0-\U0002ebef\U00030000-\U0003134f])')
    parts = pattern.split(text.strip())
    parts = [p for p in parts if len(p.strip()) > 0]
    text = "".join(parts)
    if origin != text:
        logger.debug(f"Change text: '{origin}' --> '{text}'")
    return text


if __name__ == "__main__":
    args = parser.parse_args()
    logger.info(args)
    main(args)
