# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Junjie Chen)

import logging

import torch
import torch.nn as nn
import transformers

logger = logging.getLogger(__name__)


class FireRedPuncBert(nn.Module):
    @classmethod
    def from_args(cls, args):
        assert args.pretrained_bert, "just support pretrained bert"
        args.bert = transformers.BertModel.from_pretrained(f"{args.pretrained_bert}")
        args.bert.pooler = None
        args.hidden_size = args.bert.config.hidden_size
        return cls(args)

    def __init__(self, args):
        super().__init__()
        self.bert = args.bert if args.pretrained_bert else None  # init in build()
        self.dropout = nn.Dropout(float(args.classifier_dropout))
        self.classifier = nn.Linear(args.hidden_size, args.odim)
        self.max_input_len = self.bert.embeddings.position_embeddings.num_embeddings - 1
        self.cls_id = args.cls_id  # set in punc_data.py:PuncData.build()
        self.ignore_index = args.ignore_index  # used by loss

    @torch.jit.export
    def forward_model(self, padded_inputs, lengths):
        if padded_inputs.size(1) <= self.max_input_len:
            score = self._forward(padded_inputs, lengths)
        else:
            logger.info("padded_inputs is too long, split it into chunks") #, flush=True)
            chunk_score = []
            chunks = padded_inputs.split(self.max_input_len, dim=1)
            left_lengths = lengths
            for i, chunk in enumerate(chunks, 1):
                chunk_lengths = torch.clamp(left_lengths, min=0, max=self.max_input_len)
                left_lengths = left_lengths - chunk_lengths
                chunk_score.append(self._forward(chunk, chunk_lengths))
            score = torch.cat(chunk_score, dim=1)
        return score

    def _forward(self, padded_inputs, lengths):
        padded_inputs, lengths = self.add_cls(padded_inputs, lengths)
        attention_mask = create_huggingface_bert_attention_mask(lengths)
        outputs = self.bert(padded_inputs, attention_mask)
        sequence_output = outputs[0][:, 1:]  # 1 means remove [CLS]'s output
        sequence_output = self.dropout(sequence_output)
        score = self.classifier(sequence_output)
        return score

    def add_cls(self, padded_inputs, lengths):
        N = padded_inputs.size(0)
        cls = padded_inputs.new_ones(N, 1).fill_(self.cls_id)
        padded_inputs = torch.cat((cls, padded_inputs), dim=1)
        lengths = lengths + 1
        return padded_inputs, lengths


def create_huggingface_bert_attention_mask(lengths):
    N = int(lengths.size(0))
    T = int(lengths.max())
    mask = lengths.new_ones((N, T))
    for i in range(N):
        mask[i, lengths[i]:] = 0
    return mask.float()
