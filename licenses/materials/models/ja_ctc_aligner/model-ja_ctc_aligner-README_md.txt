---
language: ja
datasets:
- common_voice
metrics:
- wer
- cer
tags:
- audio
- automatic-speech-recognition
- speech
- xlsr-fine-tuning-week
license: apache-2.0
model-index:
- name: XLSR Wav2Vec2 Japanese by Jonatas Grosman
  results:
  - task: 
      name: Speech Recognition
      type: automatic-speech-recognition
    dataset:
      name: Common Voice ja
      type: common_voice
      args: ja
    metrics:
       - name: Test WER
         type: wer
         value: 81.80
       - name: Test CER
         type: cer
         value: 20.16
---

# Fine-tuned XLSR-53 large model for speech recognition in Japanese

Fine-tuned [facebook/wav2vec2-large-xlsr-53](https://huggingface.co/facebook/wav2vec2-large-xlsr-53) on Japanese using the train and validation splits of [Common Voice 6.1](https://huggingface.co/datasets/common_voice), [CSS10](https://github.com/Kyubyong/css10) and [JSUT](https://sites.google.com/site/shinnosuketakamichi/publication/jsut).
When using this model, make sure that your speech input is sampled at 16kHz.

This model has been fine-tuned thanks to the GPU credits generously given by the [OVHcloud](https://www.ovhcloud.com/en/public-cloud/ai-training/) :)

The script used for training can be found here: https://github.com/jonatasgrosman/wav2vec2-sprint

## Usage

The model can be used directly (without a language model) as follows...

Using the [HuggingSound](https://github.com/jonatasgrosman/huggingsound) library:

```python
from huggingsound import SpeechRecognitionModel

model = SpeechRecognitionModel("jonatasgrosman/wav2vec2-large-xlsr-53-japanese")
audio_paths = ["/path/to/file.mp3", "/path/to/another_file.wav"]

transcriptions = model.transcribe(audio_paths)
```

Writing your own inference script:

```python
import torch
import librosa
from datasets import load_dataset
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

LANG_ID = "ja"
MODEL_ID = "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
SAMPLES = 10

test_dataset = load_dataset("common_voice", LANG_ID, split=f"test[:{SAMPLES}]")

processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
model = Wav2Vec2ForCTC.from_pretrained(MODEL_ID)

# Preprocessing the datasets.
# We need to read the audio files as arrays
def speech_file_to_array_fn(batch):
    speech_array, sampling_rate = librosa.load(batch["path"], sr=16_000)
    batch["speech"] = speech_array
    batch["sentence"] = batch["sentence"].upper()
    return batch

test_dataset = test_dataset.map(speech_file_to_array_fn)
inputs = processor(test_dataset["speech"], sampling_rate=16_000, return_tensors="pt", padding=True)

with torch.no_grad():
    logits = model(inputs.input_values, attention_mask=inputs.attention_mask).logits

predicted_ids = torch.argmax(logits, dim=-1)
predicted_sentences = processor.batch_decode(predicted_ids)

for i, predicted_sentence in enumerate(predicted_sentences):
    print("-" * 100)
    print("Reference:", test_dataset[i]["sentence"])
    print("Prediction:", predicted_sentence)
```

| Reference  | Prediction |
| ------------- | ------------- |
| 祖母は、おおむね機嫌よく、サイコロをころがしている。 | 人母は重にきね起くさいがしている |
| 財布をなくしたので、交番へ行きます。 | 財布をなく手端ので勾番へ行きます |
| 飲み屋のおやじ、旅館の主人、医者をはじめ、交際のある人にきいてまわったら、みんな、私より収入が多いはずなのに、税金は安い。 | ノ宮屋のお親じ旅館の主に医者をはじめ交際のアル人トに聞いて回ったらみんな私より収入が多いはなうに税金は安い |
| 新しい靴をはいて出かけます。 | だらしい靴をはいて出かけます |
| このためプラズマ中のイオンや電子の持つ平均運動エネルギーを温度で表現することがある | このためプラズマ中のイオンや電子の持つ平均運動エネルギーを温度で表弁することがある |
| 松井さんはサッカーより野球のほうが上手です。 | 松井さんはサッカーより野球のほうが上手です |
| 新しいお皿を使います。 | 新しいお皿を使います |
| 結婚以来三年半ぶりの東京も、旧友とのお酒も、夜行列車も、駅で寝て、朝を待つのも久しぶりだ。 | 結婚ル二来三年半降りの東京も吸とのお酒も野越者も駅で寝て朝を待つの久しぶりた |
| これまで、少年野球、ママさんバレーなど、地域スポーツを支え、市民に密着してきたのは、無数のボランティアだった。 | これまで少年野球<unk>三バレーなど地域スポーツを支え市民に満着してきたのは娘数のボランティアだった |
| 靴を脱いで、スリッパをはきます。 | 靴を脱いでスイパーをはきます |

## Evaluation

The model can be evaluated as follows on the Japanese test data of Common Voice.

```python
import torch
import re
import librosa
from datasets import load_dataset, load_metric
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

LANG_ID = "ja"
MODEL_ID = "jonatasgrosman/wav2vec2-large-xlsr-53-japanese"
DEVICE = "cuda"

CHARS_TO_IGNORE = [",", "?", "¿", ".", "!", "¡", ";", "；", ":", '""', "%", '"', "�", "ʿ", "·", "჻", "~", "՞",
                   "؟", "،", "।", "॥", "«", "»", "„", "“", "”", "「", "」", "‘", "’", "《", "》", "(", ")", "[", "]",
                   "{", "}", "=", "`", "_", "+", "<", ">", "…", "–", "°", "´", "ʾ", "‹", "›", "©", "®", "—", "→", "。",
                   "、", "﹂", "﹁", "‧", "～", "﹏", "，", "｛", "｝", "（", "）", "［", "］", "【", "】", "‥", "〽",
                   "『", "』", "〝", "〟", "⟨", "⟩", "〜", "：", "！", "？", "♪", "؛", "/", "\\", "º", "−", "^", "'", "ʻ", "ˆ"]

test_dataset = load_dataset("common_voice", LANG_ID, split="test")

wer = load_metric("wer.py") # https://github.com/jonatasgrosman/wav2vec2-sprint/blob/main/wer.py
cer = load_metric("cer.py") # https://github.com/jonatasgrosman/wav2vec2-sprint/blob/main/cer.py

chars_to_ignore_regex = f"[{re.escape(''.join(CHARS_TO_IGNORE))}]"

processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
model = Wav2Vec2ForCTC.from_pretrained(MODEL_ID)
model.to(DEVICE)

# Preprocessing the datasets.
# We need to read the audio files as arrays
def speech_file_to_array_fn(batch):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        speech_array, sampling_rate = librosa.load(batch["path"], sr=16_000)
    batch["speech"] = speech_array
    batch["sentence"] = re.sub(chars_to_ignore_regex, "", batch["sentence"]).upper()
    return batch

test_dataset = test_dataset.map(speech_file_to_array_fn)

# Preprocessing the datasets.
# We need to read the audio files as arrays
def evaluate(batch):
    inputs = processor(batch["speech"], sampling_rate=16_000, return_tensors="pt", padding=True)

    with torch.no_grad():
        logits = model(inputs.input_values.to(DEVICE), attention_mask=inputs.attention_mask.to(DEVICE)).logits

    pred_ids = torch.argmax(logits, dim=-1)
    batch["pred_strings"] = processor.batch_decode(pred_ids)
    return batch

result = test_dataset.map(evaluate, batched=True, batch_size=8)

predictions = [x.upper() for x in result["pred_strings"]]
references = [x.upper() for x in result["sentence"]]

print(f"WER: {wer.compute(predictions=predictions, references=references, chunk_size=1000) * 100}")
print(f"CER: {cer.compute(predictions=predictions, references=references, chunk_size=1000) * 100}")
```

**Test Result**:

In the table below I report the Word Error Rate (WER) and the Character Error Rate (CER) of the model. I ran the evaluation script described above on other models as well (on 2021-05-10). Note that the table below may show different results from those already reported, this may have been caused due to some specificity of the other evaluation scripts used.

| Model | WER | CER |
| ------------- | ------------- | ------------- |
| jonatasgrosman/wav2vec2-large-xlsr-53-japanese | **81.80%** | **20.16%** |
| vumichien/wav2vec2-large-xlsr-japanese | 1108.86% | 23.40% |
| qqhann/w2v_hf_jsut_xlsr53 | 1012.18% | 70.77% |

## Citation
If you want to cite this model you can use this:

```bibtex
@misc{grosman2021xlsr53-large-japanese,
  title={Fine-tuned {XLSR}-53 large model for speech recognition in {J}apanese},
  author={Grosman, Jonatas},
  howpublished={\url{https://huggingface.co/jonatasgrosman/wav2vec2-large-xlsr-53-japanese}},
  year={2021}
}
```