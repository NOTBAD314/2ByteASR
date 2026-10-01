# Fine-tuning

`finetune.py` provides a minimal fine-tuning workflow built on the Hugging Face
Transformers `Trainer`.

## Installation

Follow the environment setup in the main README, then install the additional
training dependency:

```bash
uv pip install accelerate
```

## Data format

Training data must be a JSONL file with one conversation per line. Each record
must contain one text prompt, one audio path, and one reference transcript, in
that order:

```json
{"conversation":[{"role":"user","message_type":"text","content":"Transcribe the audio with timestamps and speaker labels."},{"role":"user","message_type":"audio","content":"audio/example.wav"},{"role":"assistant","message_type":"text","content":"[0.00][S01]Welcome[0.72]"}]}
```

Audio paths may be absolute or relative to the JSONL file. Reference transcripts
must follow the output format requested by the prompt.

## Training

To fine-tune on a single GPU:

```bash
python finetune.py \
  --train_jsonl data/train.jsonl \
  --output_dir outputs/finetuned \
  --per_device_train_batch_size 1 \
  --num_train_epochs 3 \
  --learning_rate 1e-5 \
  --bf16 \
  --gradient_checkpointing
```

For multi-GPU training, replace `python` in the command above with
`torchrun --nproc_per_node=<num_gpus>`.

Any standard `TrainingArguments` option can also be passed on the command line.
The effective batch size is the number of GPUs multiplied by the per-device
batch size and gradient accumulation steps.

The default maximum sequence length is 131,072 tokens. Use `--max_length` to
lower it for shorter audio when memory is limited. The final model, processor,
and intermediate checkpoints are saved under `output_dir`.
