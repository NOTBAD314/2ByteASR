# Copyright 2026 Xiaohongshu. (Author: Kaituo Xu, Junjie Chen)

import logging
import re
import traceback

from transformers import BertTokenizer

logger = logging.getLogger(__name__)


# HuggingFace BERT Tokenizer Wrapper
class HfBertTokenizer:
    def __init__(self, huggingface_tokenizer_dir):
        self.tokenizer = BertTokenizer.from_pretrained(huggingface_tokenizer_dir)

    def tokenize(self, text, recover_unk=False):
        tokens = self.tokenizer.tokenize(text)
        tokens_id = self.tokenizer.convert_tokens_to_ids(tokens)
        if recover_unk:
            try:
                tokens = self._recover_unk(text.lower(), tokens)
            except Exception as e:
                traceback.print_exc()
        return tokens, tokens_id

    def _recover_unk(self, text, tokens):
        if "[UNK]" not in tokens:
            return tokens

        new_tokens = []
        text_no_space = text.replace(" ", "")

        # Fast recover:
        if re.match(r"^[^a-zA-Z0-9']+$", text):
            tmp_text = text_no_space
            if len(tmp_text) == len(tokens):
                success = True
                for t, tok in zip(tmp_text, tokens):
                    if tok != "[UNK]" and t != tok:
                        success = False
                        break
                    new_tokens.append(t)
                if success:
                    return new_tokens
        new_tokens = []

        text_pos = 0
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "[UNK]":
                unk_count = 0
                j = i
                while j < len(tokens) and tokens[j] == "[UNK]":
                    unk_count += 1
                    j += 1

                post_token = ""
                if j < len(tokens):
                    post_token = tokens[j].replace("##", "")

                if post_token:
                    remaining = text_no_space[text_pos:]
                    anchor_pos = remaining.find(post_token)
                    if anchor_pos != -1:
                        unk_chars = remaining[:anchor_pos]
                    else:
                        unk_chars = remaining[:unk_count]
                else:
                    unk_chars = text_no_space[text_pos:text_pos + unk_count]

                for k in range(unk_count):
                    if k < len(unk_chars):
                        new_tokens.append(unk_chars[k])
                    else:
                        new_tokens.append("")
                text_pos += len(unk_chars)
                i = j
            else:
                new_tokens.append(token)
                token_clean = token.replace("##", "")
                text_pos += len(token_clean)
                i += 1

        new_tokens = [t for t in new_tokens if t and t != "[UNK]"]
        return new_tokens

    def detokenize(self, inputs, join_symbol="", replace_spm_space=True):
        raise NotImplementedError



if __name__ == "__main__":
    import os
    model_dir = "../../../pretrained_models/FireRedPunc"
    tokenizer = HfBertTokenizer(os.path.join(model_dir, "chinese-lert-base"))

    txts = [
        # 基础测试
        "你好吗",
        "你好 吗",
        "hello how are you",

        # 连续生僻字（连续 [UNK]）
        "寄蜉蝣于天地渺沧海之一粟",
        "魑魅魍魉",  # 4个连续生僻字
        "饕餮耄耋",  # 另一组4个连续生僻字

        # 中英混合 + 生僻字
        "寄蜉蝣于天地渺沧海之一粟how are you魑魅魍魉你蝣蜉啊蝣",
        "hello魑魅world魍魉test",  # 英文夹生僻字

        # 开头/结尾的 [UNK]
        "蜉蝣你好",  # 开头连续生僻字
        "你好蜉蝣",  # 结尾连续生僻字
        "蜉你蝣好",  # 交替出现

        # 特殊符号（可能产生 [UNK]）
        "你好！@#￥%",
        "【测试】《标题》",
        "价格：￥99.9元",

        # 复杂混合
        "【魑魅】说：你好蜉蝣",
        "饕餮之徒hello耄耋老人",

        # 边界情况
        "",  # 空字符串
        "蜉",  # 单个生僻字
        "魑魅魍魉饕餮",  # 6个连续生僻字

        # ------------------------------------------
        # 测试：一个 [UNK] 可能对应多个字符的场景
        # ------------------------------------------

        # 生僻英文单词（可能不在词表中）
        "价格是xyz123元",  # xyz123 可能被标记为 [UNK]
        "使用qwerty键盘",  # qwerty 可能被标记为 [UNK]

        # 特殊符号组合
        "商标™注册®版权©",  # TM R C 等符号
        "温度是25℃左右",  # 摄氏度符号
        "面积100㎡价格",  # 平方米符号

        # 日文/韩文字符（可能不在中文词表中）
        "你好こんにちは世界",  # 日文平假名
        "欢迎안녕하세요光临",  # 韩文

        # 罗马数字
        "第Ⅷ章内容",  # 罗马数字8
        "共Ⅻ个部分",  # 罗马数字12

        # 数学符号
        "结果是≈100左右",  # 约等于符号
        "价格≤1000元",  # 小于等于符号

        # 带圈数字
        "第①步操作",  # 带圈数字1
        "共⑩个选项",  # 带圈数字10
    ]

    print("=" * 60)
    print("UNK 恢复测试")
    print("=" * 60)
    for txt in txts:
        if not txt:
            print(f"(空字符串) --> []")
            continue
        tokens_raw = tokenizer.tokenizer.tokenize(txt)
        tokens_recovered, _ = tokenizer.tokenize(txt, recover_unk=True)
        has_unk = "[UNK]" in tokens_raw
        status = "✓" if "[UNK]" not in tokens_recovered else "✗"
        if has_unk:
            print(f"{status} {txt}")
            print(f"   原始: {tokens_raw}")
            print(f"   恢复: {tokens_recovered}")
        else:
            print(f"  {txt} --> {tokens_recovered}")
    print("=" * 60)
