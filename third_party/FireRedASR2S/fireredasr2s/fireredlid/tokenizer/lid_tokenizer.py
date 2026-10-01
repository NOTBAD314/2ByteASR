# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Yan Jia)

from ..data.token_dict import TokenDict


class LidTokenizer:

    def __init__(self, dict_path, unk="<unk>"):
        self.dict = TokenDict(dict_path, unk=unk)

    def detokenize(self, inputs, join_symbol=" "):
        if len(inputs) > 0 and type(inputs[0]) == int:
            tokens = [self.dict[id] for id in inputs]
        else:
            tokens = inputs
        s = f"{join_symbol}".join(tokens)
        return s
