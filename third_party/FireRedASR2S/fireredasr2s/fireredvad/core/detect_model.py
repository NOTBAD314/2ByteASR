# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Kai Huang)
# Modified for 2ByteASR integration; notice added 2026-09-30.
# Changes relative to FireRedASR2S 4e7d9aaf4482a47cec1724807026b9b151926eb5:
# Restricted checkpoint loading with weights_only and explicit safe globals.
# Integration changes by the 2ByteASR project; not an upstream official release.
# Original copyright and Apache-2.0 license are retained.

import argparse
import os

import torch
import torch.nn as nn
import torch.nn.functional as F


class DetectModel(nn.Module):
    @classmethod
    def from_pretrained(cls, model_dir):
        model_path = os.path.join(model_dir, "model.pth.tar")
        with torch.serialization.safe_globals([argparse.Namespace]):
            package = torch.load(
                model_path,
                map_location=lambda storage, loc: storage,
                weights_only=True,
            )
        model = cls(package["args"])
        model.load_state_dict(package["model_state_dict"], strict=True)
        model.eval()
        return model

    def __init__(self, args):
        super().__init__()
        self.dfsmn = DFSMN(args.idim, args.R, args.M, args.H, args.P,
                           args.N1, args.S1, args.N2, args.S2,
                           args.dropout)
        self.out = torch.nn.Linear(args.H, args.odim)

    @torch.no_grad()
    def forward(self, feat, caches=None):
        # type: (Tensor, Optional[List[Tensor]]) -> Tuple[Tensor, List[Tensor]]
        x, new_caches = self.dfsmn(feat, caches=caches)
        logits = self.out(x)
        probs = torch.sigmoid(logits)
        return probs, new_caches


class DFSMN(nn.Module):
    def __init__(self, D, R, M, H, P, N1, S1, N2=0, S2=0, dropout=0.1):
        """
        DFSMN config: Rx[H-P(N1,N2,S1,S2)]-MxH
        Args:
            D: input dimension
            R: number of DFSMN blocks
            M: number of DNN layers
            H: hidden size
            P: projection size
            N1: lookback order
            S1: lookback stride
            N2: lookahead order
            S2: lookahead stride
        """
        super().__init__()
        # Components
        # 1st FSMN block connecting input layer, without skip connection
        self.fc1 = nn.Sequential(nn.Linear(D, H, bias=True),
                                 nn.ReLU(),
                                 nn.Dropout(dropout))
        self.fc2 = nn.Sequential(nn.Linear(H, P, bias=True),
                                 nn.ReLU(),
                                 nn.Dropout(dropout))
        self.fsmn1 = FSMN(P, N1, S1, N2, S2)
        # N-1 DFSMN blocks
        self.fsmns = nn.ModuleList([DFSMNBlock(H, P, N1, S1, N2, S2, dropout) for _ in range(R-1)])
        # M DNN layers 
        dnn = [nn.Linear(P, H, bias=True), nn.ReLU(), nn.Dropout(dropout)]
        for l in range(M - 1):
            dnn += [nn.Linear(H, H, bias=True), nn.ReLU(), nn.Dropout(dropout)]
        self.dnns = nn.Sequential(*dnn)

    def forward(self, inputs, input_lengths=None, caches=None):
        # type: (Tensor, Optional[Tensor], Optional[List[Tensor]]) -> Tuple[Tensor, List[Tensor]]
        """
        Args:
            inputs: [N, T, D], padded, T is sequence length, D is input dim
            mask: processing padding issue, masked position is 1
                tensor.masked_fill(mask, value) will fill elements of tensor with value where mask is one.
        Returns:
            output: [N, T, P]
        """
        if input_lengths is None:
            mask = None
        else:
            mask = get_mask_from_lengths(input_lengths)
        # 1st FSMN
        h = self.fc1(inputs)
        p = self.fc2(h)
        new_caches = []
        if caches is None:
            cache = None
        else:
            cache = caches[0]
        memory, new_cache = self.fsmn1(p, mask=mask, cache=cache)
        new_caches.append(new_cache)

        # R-1 FSMN
        i = 1
        for fsmn in self.fsmns:
            if caches is None:
                cache = None
            else:
                cache = caches[i]
            memory, new_cache = fsmn(memory, mask=mask, cache=cache)
            new_caches.append(new_cache)
            i += 1
        # M DNN
        output = self.dnns(memory)
        return output, new_caches



def get_mask_from_lengths(lengths):
    """Mask position is set to 1 for Tensor.masked_fill(mask, value)
    Args:
        lengths: (N, )
    Return:
        mask: (N, T)
    """
    N = lengths.size(0)
    T = torch.max(lengths).item()
    mask = torch.zeros(N, T).to(lengths.device)
    for i in range(N):
        mask[i, lengths[i]:] = 1
    return mask.to(torch.uint8)



class DFSMNBlock(nn.Module):
    def __init__(self, H, P, N1, S1, N2=0, S2=0, dropout=0.1):
        """
        DFSMNBlock = [input -> Affine+ReLU -> Affine -> vFSMN -> output]
                        |                                           ^
                        |-------------------------------------------|
                                 (skip connection)
        Args:
            H: hidden size
            P: projection size
            N1: lookback order
            S1: lookback stride
            N2: lookahead order
            S2: lookahead stride
        """
        super().__init__()
        # Hyper-parameter
        self.H, self.P, self.N1, self.S1, self.N2, self.S2 = H, P, N1, S1, N2, S2
        # Components
        # step1. \hat{P}^{l-1} -> H^{l}, nonlinear affine transform
        self.fc1 = nn.Sequential(nn.Linear(P, H, bias=True),
                                 nn.ReLU(),
                                 nn.Dropout(dropout))
        # Step2. H^{l} -> P^{l}, linear affine transform
        self.fc2 = nn.Linear(H, P, bias=False)
        # Step3. P^{l}-> \hat{P}^{l}, fsmn layer
        self.fsmn = FSMN(P, N1, S1, N2, S2)

    def forward(self, inputs, mask=None, cache=None):
        # type: (Tensor, Optional[Tensor], Optional[Tensor]) -> Tuple[Tensor, Tensor]
        """
        Args:
            inputs: [N, T, P], padded, T is sequence length, P is projection size
            mask: processing padding issue, masked position is 1
                tensor.masked_fill(mask, value) will fill elements of tensor with value where mask is one.
        Returns:
            output: [N, T, P]
        """
        residual = inputs
        # step1. \hat{P}^{l-1} -> H^{l}, nonlinear affine transform
        h = self.fc1(inputs)
        # Step2. H^{l} -> P^{l}, linear affine transform
        p = self.fc2(h)
        # Step3. P^{l}-> \hat{P}^{l}, fsmn layer
        memory, new_cache = self.fsmn(p, mask=mask, cache=cache)
        # Step4. skip connection
        output = memory + residual
        return output, new_cache


class FSMN(nn.Module):
    def __init__(self, P, N1, S1, N2=0, S2=0):
        """
        Args:
            P: projection size
            N1: lookback order
            S1: lookback stride
            N2: lookahead order
            S2: lookahead stride
        """
        super().__init__()
        # Hyper-parameter
        assert N1 >= 1
        self.N1, self.S1, self.N2, self.S2 = N1, S1, N2, S2
        # Components
        # P^{l}-> \hat{P}^{l}
        self.lookback_padding = (N1-1)*S1
        self.lookback_filter = nn.Conv1d(in_channels=P, out_channels=P,
                                         kernel_size=N1, stride=1,
                                         padding=self.lookback_padding, dilation=S1,
                                         groups=P, bias=False)
        if self.N2 > 0:
            self.lookahead_filter = nn.Conv1d(in_channels=P, out_channels=P,
                                              kernel_size=N2, stride=1,
                                              padding=(N2-1)*S2, dilation=S2,
                                              groups=P, bias=False)
        else:
            self.lookahead_filter = nn.Identity()

    def forward(self, inputs, mask=None, cache=None):
        # type: (Tensor, Optional[Tensor], Optional[Tensor]) -> Tuple[Tensor, Tensor]
        """
        Args:
            inputs: [N, T, P], padded, T is sequence length, P is projection size
            mask: processing padding issue, masked position is 1
                tensor.masked_fill(mask, value) will fill elements of tensor with value where mask is one.
        Returns:
            memory: [N, T, P]
        """
        T = inputs.size(1)
        if mask is not None:
            mask = mask.unsqueeze(-1) # [N, T, 1]
            inputs = inputs.masked_fill(mask, 0.0)

        inputs = inputs.permute((0, 2, 1)).contiguous() # [N, T, P] -> [N, P, T]
        residual = inputs
        
        if cache is not None:
            inputs = torch.cat((cache, inputs), dim=2)  # (N, P, C+T)
        new_cache = inputs[:, :, -self.lookback_padding:]  # (N, P, Co)

        # P^{l}-> \hat{P}^{l}, fsmn layer
        lookback = self.lookback_filter(inputs)
        if self.N1 > 1:
            lookback = lookback[:, :, :-(self.N1-1)*self.S1]
            if cache is not None:
                start = cache.size(2)
                lookback = lookback[:, :, start:]
            memory = residual + lookback
        else:
            memory = residual + lookback

        if self.N2 > 0 and T > 1:
            lookahead = self.lookahead_filter(inputs)
            memory += F.pad(lookahead[:, :, self.N2*self.S2:], (0, self.S2))
        memory = memory.permute((0, 2, 1)).contiguous() # [N, P, T] -> [N, T, P]

        if mask is not None:
            memory = memory.masked_fill(mask, 0.0)
        return memory, new_cache
