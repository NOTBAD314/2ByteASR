# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)

import torch

from .module.conformer_encoder import ConformerEncoder
from .module.transformer_decoder import TransformerDecoder


class FireRedLidAed(torch.nn.Module):
    @classmethod
    def from_args(cls, args):
        return cls(args)

    def __init__(self, args):
        super().__init__()
        self.sos_id = args.sos_id
        self.eos_id = args.eos_id

        self.encoder = ConformerEncoder(
            args.idim, args.n_layers_enc, args.n_head, args.d_model,
            args.residual_dropout, args.dropout_rate,
            args.kernel_size, args.pe_maxlen)

        self.lid_decoder = TransformerDecoder(
            args.sos_id, args.eos_id, args.pad_id, args.lid_odim,
            args.n_layers_lid_dec, args.n_head, args.d_model,
            args.residual_dropout, args.pe_maxlen)

    def process(self, padded_input, input_lengths,
                beam_size=3, nbest=1, decode_max_len=2,
                softmax_smoothing=1.25, length_penalty=0.6, eos_penalty=1.0):
        enc_outputs, enc_lengths, enc_mask = self.encoder(padded_input, input_lengths)
        nbest_hyps = self.lid_decoder.batch_beam_search(
            enc_outputs, enc_mask,
            beam_size, nbest, decode_max_len,
            softmax_smoothing, length_penalty, eos_penalty)
        return nbest_hyps
