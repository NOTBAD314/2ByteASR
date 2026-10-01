"""Compute ECAPA speaker embeddings in the MAIN runtime venv (P8C-R3.1).

The packaged GUI process has no torch; this worker runs inside the main
runtime venv (`-I`, clean of the install root's cp310 .pyd files) and
mirrors `moss_firered_pipeline._compute_chunk_speaker_embeddings`:

    speaker_embed_worker.py --manifest manifest.json --output embeddings.json

manifest = {
  "audio_npy": "<cache_dir>/audio_16k.npy",
  "sample_rate": 16000,
  "model_dir": "<models>/spkrec-ecapa-voxceleb",
  "max_audio_seconds": 14.0,
  "chunk_overlap_seconds": 20.0,
  "audio_seconds": 875.23,
  "chunks": [{"offset": 0.0, "duration": 180.0,
              "segments": [{"start": .., "end": .., "speaker": "S01"}]}]
}

output = {"0|S01": [float, ...], "1|S02": [...]}  (L2-normalized embeddings)

All paths arrive from the parent process (values it computed itself); each
is resolved and existence-checked before use.
"""

from __future__ import annotations

import argparse
import json
import os
import warnings
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with Path(args.manifest).resolve().open(encoding="utf-8") as stream:
        manifest = json.load(stream)

    audio_npy = Path(manifest["audio_npy"]).resolve()
    if not audio_npy.is_file():
        raise SystemExit(f"audio_npy missing: {audio_npy}")
    model_dir = Path(manifest["model_dir"]).resolve()
    if not (model_dir / "embedding_model.ckpt").is_file():
        raise SystemExit(f"ECAPA model missing: {model_dir}")
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    import numpy as np

    audio = np.load(audio_npy, mmap_mode="r")
    sample_rate = int(manifest.get("sample_rate") or 16000)
    max_audio_seconds = float(manifest.get("max_audio_seconds") or 14.0)
    overlap = float(manifest.get("chunk_overlap_seconds") or 20.0)
    audio_seconds = float(manifest.get("audio_seconds") or (len(audio) / sample_rate))
    chunks = manifest.get("chunks") or []
    chunk_count = len(chunks)

    import torch
    import torchaudio
    if manifest.get('threads'):
        torch.set_num_threads(max(1, int(manifest['threads'])))

    # SpeechBrain 1.0.3 queries torchaudio backends removed in newer
    # torchaudio; we feed tensors directly, so declaring the soundfile
    # backend is enough for compatibility.
    if not hasattr(torchaudio, "list_audio_backends"):
        torchaudio.list_audio_backends = lambda: ["soundfile"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy

        encoder = EncoderClassifier.from_hparams(
            source=str(model_dir),
            savedir=str(model_dir),
            overrides={"pretrained_path": str(model_dir)},
            local_strategy=LocalStrategy.NO_LINK,
            run_opts={"device": "cpu"},
        )

    keys = []
    signals = []
    for chunk_index, chunk in enumerate(chunks):
        offset = float(chunk.get("offset", 0.0))
        duration = float(chunk.get("duration", 0.0))
        owned_start = offset if chunk_index == 0 else offset + overlap / 2.0
        chunk_end = min(audio_seconds, offset + duration)
        owned_end = chunk_end if chunk_index == chunk_count - 1 else chunk_end - overlap / 2.0
        local_speakers = sorted(
            {
                str(item.get("speaker") or "S00").strip("[] ")
                for item in chunk.get("segments", [])
            }
        )
        for local_speaker in local_speakers:
            rows = []
            for raw in chunk.get("segments", []):
                if str(raw.get("speaker") or "S00").strip("[] ") != local_speaker:
                    continue
                start = max(0.0, offset + float(raw["start"]))
                end = min(audio_seconds, max(start + 0.01, offset + float(raw["end"])))
                center = (start + end) / 2.0
                if owned_start <= center < owned_end or (
                    chunk_index == chunk_count - 1 and center <= owned_end
                ):
                    rows.append((start, end))
            rows.sort(key=lambda item: min(4.0, item[1] - item[0]), reverse=True)
            pieces = []
            remaining = int(max_audio_seconds * sample_rate)
            for start, end in rows:
                left = max(0, int((start + 0.08) * sample_rate))
                right = min(len(audio), int((end - 0.08) * sample_rate))
                if right - left < int(0.35 * sample_rate):
                    continue
                piece = np.asarray(audio[left:right], dtype=np.float32)[:remaining]
                pieces.append(piece)
                remaining -= len(piece)
                if remaining <= 0:
                    break
            if not pieces:
                continue
            signal = np.concatenate(pieces)
            peak = float(np.max(np.abs(signal)))
            keys.append([chunk_index, local_speaker])
            signals.append(torch.from_numpy(np.ascontiguousarray(signal / max(peak, 1e-4))))

    if not signals:
        output_path.write_text("{}", encoding="utf-8")
        return

    matrices = []
    batch_size = max(1, int(manifest.get('batch_size') or 16))
    with torch.inference_mode():
        for start in range(0, len(signals), batch_size):
            batch = signals[start:start+batch_size]
            lengths = torch.tensor([len(item) for item in batch], dtype=torch.float32)
            padded = torch.nn.utils.rnn.pad_sequence(batch, batch_first=True)
            matrix = encoder.encode_batch(padded, lengths/padded.shape[1]).squeeze(1)
            matrices.append(torch.nn.functional.normalize(matrix, dim=-1).cpu().numpy())
    matrix = np.concatenate(matrices)

    embeddings = {}
    for key, vector in zip(keys, matrix):
        embeddings[f"{key[0]}|{key[1]}"] = [float(value) for value in vector]
    output_path.write_text(json.dumps(embeddings), encoding="utf-8")


if __name__ == "__main__":
    main()
