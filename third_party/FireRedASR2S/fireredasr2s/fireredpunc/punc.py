# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Junjie Chen)
# Modified for 2ByteASR integration; notice added 2026-09-30.
# Changes relative to FireRedASR2S 4e7d9aaf4482a47cec1724807026b9b151926eb5:
# Restricted checkpoint loading with weights_only and explicit safe globals.
# Integration changes by the 2ByteASR project; not an upstream official release.
# Original copyright and Apache-2.0 license are retained.

import argparse
import logging
import os
import re
from dataclasses import dataclass

import torch

from .data.hf_bert_tokenizer import HfBertTokenizer
from .models.fireredpunc_bert import FireRedPuncBert
from .models.param import count_model_parameters
from .data.token_dict import TokenDict

logger = logging.getLogger(__name__)


@dataclass
class FireRedPuncConfig:
    use_gpu: bool = True
    sentence_max_length: int = -1


class FireRedPunc:
    @classmethod
    def from_pretrained(cls, model_dir, config):
        model = load_punc_bert_model(model_dir)
        model_io = ModelIO(model_dir)
        assert isinstance(config, FireRedPuncConfig)
        count_model_parameters(model)
        model.eval()
        return cls(model_io, model, config)

    def __init__(self, model_io, model, config):
        self.model_io = model_io
        self.model = model
        self.config = config
        if self.config.use_gpu:
            self.model.cuda()
        else:
            self.model.cpu()

    @torch.no_grad()
    def process(self, batch_text, batch_uttid=None):
        # Intercept empty input to prevent max([]) from throwing an error
        if not batch_text:
            return []

        # 1. Prepare inputs
        padded_inputs, lengths, txt_tokens = self.model_io.text2tensor(batch_text)
        if self.config.use_gpu:
            padded_inputs, lengths = padded_inputs.cuda(), lengths.cuda()

        # 2. Model inference
        logits = self.model.forward_model(padded_inputs, lengths)  # (N,T,C)
        preds = self.get_punc_pred(logits, lengths)

        # 3. Add Punc to txt
        punc_txts = self.model_io.add_punc_to_txt(txt_tokens, preds)
        punc_txts = [RuleBaedTxtFix.fix(txt) for txt in punc_txts]

        # 4. Format output
        results = []
        for i in range(len(batch_text)):
            result = {
                "punc_text": punc_txts[i],
                "origin_text": batch_text[i],
            }
            if batch_uttid is not None:
                result["uttid"] = batch_uttid[i]
            results.append(result)
        return results

    @torch.no_grad()
    def process_with_timestamp(self, batch_timestamp, batch_uttid=None):
        # Intercept empty input to prevent max([]) from throwing an error
        if not batch_timestamp:
            return []

        # 1. Prepare inputs
        padded_inputs, lengths, batch_txt_tokens, batch_tokens_split_num = \
            self.model_io.timestamp2tensor(batch_timestamp)
        if self.config.use_gpu:
            padded_inputs, lengths = padded_inputs.cuda(), lengths.cuda()

        # 2. Model inference
        logits = self.model.forward_model(padded_inputs, lengths)  # (N,T,C)
        preds = self.get_punc_pred(logits, lengths, batch_txt_tokens)

        # 3. Add Punc to txt
        punc_txts = self.model_io.add_punc_to_txt_with_timestamp(
            batch_txt_tokens, preds, batch_timestamp, batch_tokens_split_num)

        new_punc_txts = []
        for txts in punc_txts:
            new_txts = []
            for idx, txt in enumerate(txts):
                # Only capitalize first letter after sentence-ending punctuation (.!?), not after comma
                if idx == 0:
                    cap = True
                else:
                    prev_text = new_txts[idx - 1][0]
                    cap = bool(prev_text) and prev_text[-1] in '.!?。？！'
                new_txts.append((RuleBaedTxtFix.fix(txt[0], capitalize_first=cap), txt[1], txt[2]))
            new_punc_txts.append(new_txts)
        punc_txts = new_punc_txts

        # 4. Format output
        results = []
        for i in range(len(batch_timestamp)):
            result = {
                "punc_sentences": [
                    {"punc_text": t[0], "start_s": t[1], "end_s": t[2]} for t in punc_txts[i]
                ],
            }
            if batch_uttid is not None:
                result["uttid"] = batch_uttid[i]
            results.append(result)
        return results

    def get_punc_pred(self, punc_logits, lengths, batch_txt_tokens=None):
        max_len = torch.max(lengths).cpu().item()
        if max_len <= self.config.sentence_max_length or self.config.sentence_max_length <= 0 or batch_txt_tokens is None:
            _, preds = torch.max(punc_logits, dim=-1)
            preds = preds.cpu().tolist()
            preds = [pred[:lengths[i]] for i, pred in enumerate(preds)]
        else:
            preds = self.get_punc_pred_limit_max_len(punc_logits, lengths,
                                                     batch_txt_tokens)
        return preds

    def get_punc_pred_limit_max_len(self, punc_logits, lengths, batch_txt_tokens):
        sentence_max_length = self.config.sentence_max_length
        preds = []
        batch_probs = punc_logits.softmax(dim=-1).cpu()
        lengths = lengths.cpu()
        for n in range(len(batch_probs)):
            # Process each sentence
            single_sentence_seg_token_ids = []
            probs = batch_probs[n]
            L = lengths[n]
            tokens = batch_txt_tokens[n]
            l = 0
            while l < L:
                r = l
                total_num = 0.0
                max_seg_prob = -1.0
                max_index = -1
                while r < L:
                    token_num = 0.0
                    s = re.sub("^##", "", tokens[r])
                    for j in range(len(s)):
                        if re.match("[a-zA-Z0-9']", s[j]):
                            token_num += 0.5
                        else:
                            token_num += 1

                    if total_num + token_num > sentence_max_length and max_seg_prob >= 0:
                        break

                    space_prob = probs[r][0]
                    seg_prob = 1.0 - space_prob
                    if seg_prob >= max_seg_prob:
                        max_seg_prob = seg_prob
                        max_index = r
                    total_num += token_num
                    r += 1
                    if seg_prob >= space_prob:
                        break
                if r >= L:
                    # r is == sentence_length, r-- to avoid out-of-range-access
                    r -= 1
                else:
                    # if total_num + token_num > sentence_max_length,
                    # we find l to max score's index as a sentence
                    # (max index is betweent [l, r])
                    r = max_index
                if token_num > sentence_max_length:
                    logger.info(f"Too long token...{n}, {l}, {r}, {total_num}, {token_num}, {tokens[l]}, {tokens[r]}")
                # range [l, r] is a sentence
                for idx in range(l, r):
                    single_sentence_seg_token_ids.append(0)  # 0 should be space
                # argmax BEGIN (find an elegant way?)
                pred_id = 1;
                max_pred_prob = 0.0;
                for k in range(1, len(probs[r])):
                    if probs[r][k] > max_pred_prob:
                        pred_id = k;
                        max_pred_prob = probs[r][k];
                # argmax END
                single_sentence_seg_token_ids.append(pred_id);
                l = r + 1
            preds.append(single_sentence_seg_token_ids)
        return preds


def load_punc_bert_model(model_dir):
    model_path = os.path.join(model_dir, "model.pth.tar")
    with torch.serialization.safe_globals([argparse.Namespace]):
        package = torch.load(
            model_path,
            map_location=lambda storage, loc: storage,
            weights_only=True,
        )
    package["args"].bert = None
    package["args"].pretrained_bert = os.path.join(model_dir, "chinese-lert-base")
    model = FireRedPuncBert.from_args(package["args"])
    model.load_state_dict(package["model_state_dict"], strict=False)
    return model


class ModelIO:
    def __init__(self, model_dir):
        self.tokenizer = HfBertTokenizer(os.path.join(model_dir, "chinese-lert-base"))
        self.in_dict = TokenDict(os.path.join(model_dir, "chinese-bert-wwm-ext_vocab.txt"), unk="[UNK]")
        self.out_dict = TokenDict(os.path.join(model_dir, "out_dict"))
        self.INPUT_IGNORE_ID = self.in_dict["[PAD]"]
        self.DEFAULT_OUT = " "

    def text2tensor(self, batch_text):
        batch_txt_tokens = []
        batch_input_seqs = []
        for text in batch_text:
            tokens, _ = self.tokenizer.tokenize(text, recover_unk=True)
            input_seq = []
            for token in tokens:
                input_seq.append(self.in_dict.get(token, self.in_dict.unk))
            batch_txt_tokens.append(tokens)
            batch_input_seqs.append(input_seq)
        padded_inputs, lengths = self.pad_list(batch_input_seqs, self.INPUT_IGNORE_ID)
        return padded_inputs, lengths, batch_txt_tokens

    def timestamp2tensor(self, batch_timestamp):
        batch_txt_tokens = []
        batch_input_seqs = []
        batch_tokens_split_num = []
        for timestamps in batch_timestamp:
            txt_token = []
            input_seq = []
            tokens_split_num = []
            for token, start, end in timestamps:
                sub_tokens, _ = self.tokenizer.tokenize(token, recover_unk=True)
                tokens_split_num.append(len(sub_tokens))
                txt_token.extend(sub_tokens)
                for sub_token in sub_tokens:
                    input_seq.append(self.in_dict.get(sub_token, self.in_dict.unk))
            batch_txt_tokens.append(txt_token)
            batch_input_seqs.append(input_seq)
            batch_tokens_split_num.append(tokens_split_num)
        padded_inputs, lengths = self.pad_list(batch_input_seqs, self.INPUT_IGNORE_ID)
        return padded_inputs, lengths, batch_txt_tokens, batch_tokens_split_num

    @classmethod
    def pad_list(cls, input_seqs, pad_value):
        lengths = [len(seq) for seq in input_seqs]
        padded_inputs = torch.zeros(len(input_seqs), max(lengths)).fill_(pad_value).long()
        for i, input_seq in enumerate(input_seqs):
            end = lengths[i]
            padded_inputs[i, :end] = torch.LongTensor(input_seq[:end])
        lengths = torch.IntTensor(lengths)
        return padded_inputs, lengths

    def add_punc_to_txt(self, token_seqs, pred_seqs):
        punc_txts = []
        for token_seq, pred_seq in zip(token_seqs, pred_seqs):
            assert len(token_seq) == len(pred_seq)
            txt = ""
            for i, token in enumerate(token_seq):
                tag = self.out_dict[pred_seq[i]]

                # tokenizer_type == "huggingface_bert":
                if token.startswith("##"):
                    token = token.replace("##", "")
                elif re.search("[a-zA-Z0-9#]+", token) and \
                     i > 0 and re.search("[a-zA-Z0-9#]+", token_seq[i-1]):
                    if self.out_dict[pred_seq[i-1]] == self.DEFAULT_OUT:
                        token = " " + token

                if tag == self.DEFAULT_OUT:
                    txt += token
                else:
                    txt += token + tag
            txt = txt.replace("  ", " ")
            punc_txts.append(txt)
        return punc_txts

    def add_punc_to_txt_with_timestamp(self, token_seqs, pred_seqs,
                                       batch_timestamp, batch_tokens_split_num):
        punc_txts = []
        for token_seq, pred_seq, timestamps, tokens_split_num in \
                zip(token_seqs, pred_seqs, batch_timestamp, batch_tokens_split_num):
            assert len(token_seq) == len(pred_seq)
            sentences = []
            txt, start, end = "", -1, -1

            i = 0
            j = 0
            last_token = ""
            last_tag = ""
            while i < len(token_seq) and j < len(tokens_split_num):
                split_num = tokens_split_num[j]
                timestamp = timestamps[j]
                assert len(timestamp) == 3
                if start == -1:
                    start = timestamp[1]
                end = timestamp[2]

                # Initialize the variables 'token' and 'tag' before each iteration to prevent contamination from the previous word's variables
                token = ""
                tag = self.DEFAULT_OUT

                for k in range(split_num):
                    sub_token = token_seq[i]
                    tag = self.out_dict[pred_seq[i]]
                    sub_token = re.sub("^##", "", sub_token)
                    if k == 0:
                        token = sub_token
                    else:  # k > 0
                        token += sub_token
                    i += 1

                # If the word segmenter fails to produce any tokens (for example, the input is an empty string "")
                # Forcefully assign the original string to the token to ensure that the assertion passes and the subsequent logic retains all necessary information
                if split_num == 0:
                    token = timestamp[0]

                assert token == timestamp[0], f"{token}/{timestamp}"
                j += 1
                # Add " " before English & Digit
                if re.search("[a-zA-Z0-9#]+", token) and \
                     j > 0 and re.search("[a-zA-Z0-9#]+", last_token):
                    if last_tag == self.DEFAULT_OUT:
                        token = " " + token

                if tag == self.DEFAULT_OUT:
                    txt += token
                else:
                    txt += token + tag
                    # Get New sentence
                    txt = txt.replace("  ", " ")
                    assert start != -1
                    sentences.append((txt, start, end))
                    txt, start, end = "", -1, -1
                last_token = token
                last_tag = tag
            if txt != "":
                assert start != -1 and end != -1
                sentences.append((txt, start, end))

            punc_txts.append(sentences)
        return punc_txts


class RuleBaedTxtFix:
    @classmethod
    def fix(cls, txt_ori, capitalize_first=True):
        txt = txt_ori.lower()
        # English Punc
        txt = re.sub(r"([a-z])，([a-z])", r"\1, \2", txt)
        txt = re.sub(r"([a-z])。([a-z])", r"\1. \2", txt)
        txt = re.sub(r"([a-z])？([a-z])", r"\1? \2", txt)
        txt = re.sub(r"([a-z])！([a-z])", r"\1! \2", txt)
        txt = re.sub(r"^([a-z]+)，", r"\1,", txt)
        txt = re.sub(r"^([a-z]+)。", r"\1.", txt)
        txt = re.sub(r"^([a-z]+)？", r"\1?", txt)
        txt = re.sub(r"^([a-z]+)！", r"\1!", txt)
        txt = re.sub(r"( [a-zA-Z']+)，$", r"\1,", txt)
        txt = re.sub(r"( [a-zA-Z']+)。$", r"\1.", txt)
        txt = re.sub(r"( [a-zA-Z']+)？$", r"\1?", txt)
        txt = re.sub(r"( [a-zA-Z']+)！$", r"\1!", txt)
        # I
        txt = re.sub("^i ", "I ", txt)
        txt = re.sub("^i'm ", "I'm ", txt)
        txt = re.sub("^i'd ", "I'd ", txt)
        txt = re.sub("^i've ", "I've ", txt)
        txt = re.sub("^i'll ", "I'll ", txt)
        txt = re.sub(" i ", " I ", txt)
        txt = re.sub(" i'm ", " I'm ", txt)
        txt = re.sub(" i'd ", " I'd ", txt)
        txt = re.sub(" i've ", " I've ", txt)
        txt = re.sub(" i'll ", " I'll ", txt)
        # First English upper
        if capitalize_first and len(txt) > 0 and re.match("[a-z]", txt[0]):
            txt = txt[0].upper() + txt[1:]
        txt = re.sub(r'([.!?。？！])\s+([a-z])', lambda m: f"{m.group(1)} {m.group(2).upper()}", txt)

        return txt


if __name__ == "__main__":
    txts = [
        "i'm ok. how are you? i'm fine.",
        "Tim，"
    ]
    for txt in txts:
        txt2 = RuleBaedTxtFix.fix(txt)
