#!/usr/bin/env python3
"""Fine-tune MOSS-Transcribe-Diarize on conversation-format JSONL data."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import soundfile as sf
import soxr
import torch
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    HfArgumentParser,
    Trainer,
    TrainingArguments,
)

from moss_transcribe_diarize.inference_utils import build_transcription_messages
from moss_transcribe_diarize.processing_moss_transcribe_diarize import MossTranscribeDiarizeProcessor


@dataclass
class ScriptArguments:
    train_jsonl: str = field(metadata={"help": "Conversation-format training manifest."})
    model_name_or_path: str = "OpenMOSS-Team/MOSS-Transcribe-Diarize"
    max_length: int = 131072
    attn_implementation: str = "sdpa"


class ConversationDataset(Dataset):
    def __init__(self, path: str):
        manifest = Path(path).expanduser().resolve()
        self.samples = []
        with manifest.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                self.samples.append(self._parse(json.loads(line), manifest.parent, line_no))
        if not self.samples:
            raise ValueError(f"No samples found in {manifest}")

    @staticmethod
    def _parse(row: dict, root: Path, line_no: int) -> dict[str, str]:
        conversation = row.get("conversation") or []
        expected = [("user", "text"), ("user", "audio"), ("assistant", "text")]
        if not isinstance(conversation, list) or not all(isinstance(item, dict) for item in conversation):
            raise ValueError(f"Line {line_no}: conversation must be a list of messages")
        actual = [(item.get("role"), item.get("message_type")) for item in conversation]
        if actual != expected:
            raise ValueError(f"Line {line_no}: expected user/text, user/audio, assistant/text")

        prompt, audio_path, target = (item.get("content") for item in conversation)
        if not all(isinstance(value, str) and value.strip() for value in (prompt, audio_path, target)):
            raise ValueError(f"Line {line_no}: prompt, audio path, and target must be non-empty strings")

        audio = Path(audio_path).expanduser()
        if not audio.is_absolute():
            audio = (root / audio).resolve()
        return {
            "audio": str(audio),
            "prompt": prompt.strip(),
            "target": target.strip(),
        }

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> dict[str, str]:
        return self.samples[index]


class DataCollator:
    def __init__(self, processor, max_length: int):
        self.processor = processor
        self.max_length = max_length
        self.sample_rate = int(processor.feature_extractor.sampling_rate)

    def __call__(self, samples: list[dict[str, str]]) -> dict[str, torch.Tensor]:
        prompts, texts, audios = [], [], []
        for sample in samples:
            prompt = self.processor.apply_chat_template(
                build_transcription_messages(sample["audio"], sample["prompt"]),
                tokenize=False,
                add_generation_prompt=True,
            )
            prompts.append(prompt)
            texts.append(prompt + sample["target"] + self.processor.tokenizer.eos_token)
            audio, sample_rate = sf.read(sample["audio"], dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if sample_rate != self.sample_rate:
                audio = soxr.resample(audio, sample_rate, self.sample_rate)
            audios.append(audio)

        batch = self.processor(
            text=texts,
            audio=audios,
            max_length=self.max_length,
            return_tensors="pt",
        )
        audio_lengths = torch.zeros(len(samples), dtype=torch.long)
        audio_lengths.scatter_add_(
            0,
            batch["audio_chunk_mapping"].cpu(),
            batch["audio_feature_lengths"].cpu(),
        )

        labels = batch["input_ids"].clone()
        for index, (prompt, audio_length) in enumerate(zip(prompts, audio_lengths.tolist())):
            prompt_ids = self.processor.expand_audio_token(
                prompt,
                audio_length,
                self.max_length,
            )
            labels[index, : len(prompt_ids)] = -100
        labels[batch["attention_mask"] == 0] = -100
        batch["labels"] = labels
        return dict(batch)


def main() -> None:
    parser = HfArgumentParser((ScriptArguments, TrainingArguments))
    script_args, training_args = parser.parse_args_into_dataclasses()
    training_args.remove_unused_columns = False
    training_args.label_names = ["labels"]

    processor = MossTranscribeDiarizeProcessor.from_pretrained(
        script_args.model_name_or_path,
        trust_remote_code=True,
    )
    dataset = ConversationDataset(script_args.train_jsonl)
    collator = DataCollator(processor, script_args.max_length)

    dtype = torch.bfloat16 if training_args.bf16 else torch.float16 if training_args.fp16 else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        script_args.model_name_or_path,
        trust_remote_code=True,
        dtype=dtype,
        attn_implementation=script_args.attn_implementation,
    )
    model.tie_weights()
    model.config.use_cache = False
    model.config.text_config.use_cache = False

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=collator,
        processing_class=processor,
    )
    result = trainer.train(resume_from_checkpoint=training_args.resume_from_checkpoint)
    trainer.save_model()
    trainer.save_state()
    trainer.save_metrics("train", result.metrics)


if __name__ == "__main__":
    main()
