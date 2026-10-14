"""MOSS long audio (2026-10-13): plan the context and GPU memory, split into windows when needed.

Fixture models only: these tests prove planning, transport, splitting and
stitching contracts, not recognition or speaker accuracy.
"""
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import moss_firered_pipeline as pipeline
import moss_worker as worker

ROOT = Path(__file__).resolve().parents[1]
GIB = 2**30
KV = 28 * 2 * 8 * 128 * 2          # MOSS text model: 112 KiB per token in bf16


def text_config():
    return SimpleNamespace(num_hidden_layers=28, num_attention_heads=16, num_key_value_heads=8, head_dim=128,
                           hidden_size=1024, max_position_embeddings=131072)


def test_kv_bytes_match_the_moss_config():
    assert worker.kv_bytes_per_token(text_config(), 2) == KV == 114688


def test_report_case_needs_windows_and_every_window_fits():
    # 2 h 23 min stream: 114,384 prompt tokens; ~13.3 GiB free after loading on a 16 GB card.
    plan = worker.plan_windows(8610.261, 114384, 131072, int(13.3 * GIB), KV)
    assert plan["mode"] == "context_windows" and plan["count"] >= 3
    policy = worker.WINDOW_POLICY
    longest = plan["nominal_window_seconds"] + policy["overlap_seconds"] + 2 * policy["cut_search_seconds"]
    assert longest <= plan["max_window_seconds"] + 1
    estimate = plan["estimate"]
    assert estimate["context_ok"] and estimate["bytes"] <= int(13.3 * GIB) - policy["safety_bytes"]
    # The failed single pass would have needed far more than the card.
    whole = worker.window_estimate(8610.261, plan["prompt_tokens_per_second"], 131072, KV)
    assert not whole["context_ok"] and whole["bytes"] > 16 * GIB


def test_short_audio_and_big_gpu_keep_one_context():
    assert worker.plan_windows(223.296, 2990, 131072, int(13 * GIB), KV)["mode"] == "single_context"
    # One hour fits the context; a 24 GB card has the memory for it.
    assert worker.plan_windows(3600, 47747, 131072, int(21 * GIB), KV)["count"] == 1
    assert worker.plan_windows(3600, 47747, 131072, int(13.3 * GIB), KV)["count"] == 2


def test_too_little_memory_fails_with_the_needed_amount():
    plan = worker.plan_windows(8610.261, 114384, 131072, int(2 * GIB), KV)
    assert plan["mode"] == "insufficient" and plan["count"] == 0
    assert plan["needed_bytes"] > 2 * GIB


def test_short_audio_asks_only_for_its_own_length():
    # A 30 s clip that does not fit reports what 30 s needs, not a 3-minute window (2026-10-14).
    plan = worker.plan_windows(30.0, 600, 131072, int(0.6 * GIB), KV)
    assert plan["mode"] == "insufficient" and plan["minimum_window_seconds"] == 30.0
    rate = plan["prompt_tokens_per_second"]   # rounded in the plan, so compare to within 1 KiB
    expected = worker.window_estimate(30.0, rate, 131072, KV)["bytes"] + worker.WINDOW_POLICY["safety_bytes"]
    assert abs(plan["needed_bytes"] - expected) < 1024
    three_minutes = worker.window_estimate(180.0, rate, 131072, KV)["bytes"] + worker.WINDOW_POLICY["safety_bytes"]
    assert plan["needed_bytes"] < three_minutes


def noisy(seconds, quiet=()):
    audio = (np.random.default_rng(1).standard_normal(int(seconds * 16000)) * 0.2).astype(np.float32)
    for start, end in quiet:
        audio[int(start * 16000):int(end * 16000)] = 0.0
    return audio


def test_cuts_land_in_silence_and_windows_overlap_exactly():
    audio = noisy(1000, quiet=[(480, 482.5)])
    bounds = worker.window_bounds(audio, 1000.0, 2)
    cut = bounds[0][1] - 10
    assert 480 <= cut <= 482.5
    assert bounds[0][0] == 0 and bounds[1][1] == 1000
    assert round(bounds[0][1] - bounds[1][0], 3) == 20
    # Without silence the cut stays inside the search span around the target.
    plain = worker.quiet_cut(noisy(200), 100, 45)
    assert 55 <= plain <= 145


class Inputs(dict):
    def to(self, device):
        return self


def load_official(name, relative):
    path = ROOT / 'third_party/MOSS-Transcribe-Diarize/moss_transcribe_diarize' / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_gpu(monkeypatch):
    import torch
    utility = load_official('moss_transcribe_diarize.inference_utils', 'inference_utils.py')
    monkeypatch.setitem(sys.modules, 'moss_transcribe_diarize.inference_utils', utility)
    for name in ('set_per_process_memory_fraction', 'reset_peak_memory_stats', 'empty_cache'):
        monkeypatch.setattr(torch.cuda, name, lambda *a, **k: None)
    monkeypatch.setattr(torch.cuda, 'max_memory_allocated', lambda *a, **k: 3 * GIB)
    monkeypatch.setattr(worker, 'install_encoder_batching', lambda *a: {'batch_size': 2})
    return torch


class Processor:
    """13.3 prompt tokens per audio second; remembers every window it saw."""
    feature_extractor = SimpleNamespace(sampling_rate=16000)

    def __init__(self):
        self.lengths = []
        self.tokenizer = SimpleNamespace(decode=self.decode)
        self._last = 0

    def apply_chat_template(self, *a, **k):
        return 'prompt'

    def __call__(self, **kw):
        samples = len(kw['audio'][0])
        self.lengths.append(samples)
        import torch
        tokens = 100 + int(samples / 16000 * 13.3)
        self._last = samples / 16000
        return Inputs(input_ids=torch.ones((1, tokens), dtype=torch.long),
                      attention_mask=torch.ones((1, tokens), dtype=torch.long),
                      input_features=torch.zeros((max(1, int(samples / 16000 / 30) + 1), 2, 2)))

    def decode(self, *a, **k):
        # Two native speakers per window, times relative to the window.
        end = self._last
        return f'[0.50][S01]第一句[{end / 2:.2f}][{end / 2 + 1:.2f}][S02]第二句[{end - 1:.2f}]'


def model_with(generate):
    config = SimpleNamespace(text_config=text_config())
    return SimpleNamespace(config=config, generation_config=SimpleNamespace(eos_token_id=151645), generate=generate)


def parse_transcript(raw):
    rows = []
    for start, speaker, text, end in re.findall(r'\[([0-9.]+)\]\[(S\d+)\]([^\[]+)\[([0-9.]+)\]', raw):
        rows.append(SimpleNamespace(start=float(start), end=float(end), speaker=speaker, text=text))
    return rows


def run(audio, processor, generate, usable, tmp_path):
    import torch
    receipt = {'generation_attempts': 0, 'retries': [], 'complete': False}
    payload = {'chunks': []}
    original = worker.usable_device_bytes
    worker.usable_device_bytes = lambda torch_module: (int(usable), 16 * GIB, 0.9)
    try:
        worker.run_windows(model_with(generate), processor, audio, [], torch.device('cpu'), torch.bfloat16,
                           worker.ExecutionProgress(), receipt, payload, parse_transcript, str(tmp_path / 'moss.json'))
    finally:
        worker.usable_device_bytes = original
    return receipt, payload


def test_long_task_runs_windows_in_one_process(fake_gpu, tmp_path):
    torch = fake_gpu
    audio = noisy(3 * 3600, quiet=[(3600, 3602), (7200, 7202)])
    processor = Processor()
    calls = []

    def generate(**kw):
        calls.append(kw['input_ids'].shape[1])
        return torch.cat([kw['input_ids'], torch.tensor([[7, 8, 151645]])], dim=1)

    receipt, payload = run(audio, processor, generate, 13.3 * GIB, tmp_path)
    chunks = payload['chunks']
    assert receipt['window_mode'] == 'context_windows' and receipt['window_plan']['count'] == len(chunks) >= 3
    assert len(calls) == len(chunks)                    # one generate per window, model loaded once
    assert processor.lengths[0] == len(audio)           # planning saw the whole task first
    assert chunks[0]['offset'] == 0 and abs(chunks[-1]['offset'] + chunks[-1]['duration'] - 3 * 3600) < 1e-3
    for left, right in zip(chunks, chunks[1:]):
        assert abs(left['offset'] + left['duration'] - right['offset'] - 20) < 0.01
    assert all(len(chunk['segments']) == 2 for chunk in chunks)
    assert receipt['complete'] and receipt['end_reason'] == 'eos'
    assert receipt['generated_tokens'] == 3 * len(chunks)
    assert json.loads((tmp_path / 'moss.json').read_text('utf8'))['chunks'][-1]['segments']


def test_short_task_keeps_one_context_and_reuses_the_planning_input(fake_gpu, tmp_path):
    torch = fake_gpu
    processor = Processor()
    generate = lambda **kw: torch.cat([kw['input_ids'], torch.tensor([[7, 151645]])], dim=1)
    receipt, payload = run(noisy(300), processor, generate, 13.3 * GIB, tmp_path)
    assert receipt['window_mode'] == 'single_context' and len(payload['chunks']) == 1
    assert processor.lengths == [300 * 16000]           # no second processor pass
    assert payload['raw_text'] and receipt['input_tokens'] == 100 + int(300 * 13.3)


def test_decoder_oom_splits_the_window_instead_of_retrying_it(fake_gpu, tmp_path, monkeypatch):
    torch = fake_gpu
    processor = Processor()
    hook = {}

    def encoder_batching(model, batch_size, progress):
        hook['progress'] = progress            # the real hook marks "generation" after encoding
        return {'batch_size': batch_size}

    monkeypatch.setattr(worker, 'install_encoder_batching', encoder_batching)
    calls = []

    def generate(**kw):
        calls.append(kw['input_ids'].shape[1])
        hook['progress'].set_phase('generation')
        if len(calls) == 1:
            raise torch.cuda.OutOfMemoryError('fixture OOM in prefill')
        return torch.cat([kw['input_ids'], torch.tensor([[7, 151645]])], dim=1)

    receipt, payload = run(noisy(1200), processor, generate, 13.3 * GIB, tmp_path)
    assert [retry['reason'] for retry in receipt['retries']] == ['cuda_oom_window_split']
    assert receipt['retries'][0]['phase'] == 'generation'
    assert len(payload['chunks']) == 2 and receipt['window_mode'] == 'context_windows'
    left, right = payload['chunks']
    assert abs(left['offset'] + left['duration'] - right['offset'] - 20) < 0.01
    assert len(calls) == 3 and calls[1] < calls[0] and calls[2] < calls[0]


def test_decoder_oom_is_not_retried_with_the_same_input(fake_gpu):
    torch = fake_gpu
    calls = []

    def generate(**kw):
        calls.append(1)
        raise torch.cuda.OutOfMemoryError('decoder')

    progress = worker.ExecutionProgress()
    original_set_phase = progress.set_phase
    progress.set_phase = lambda phase: original_set_phase('generation' if phase == 'audio_encoding' and calls else phase)
    processor = Processor()
    inputs, _ = worker.prompt_inputs(processor, noisy(10), [], 131072)
    receipt = {'generation_attempts': 0, 'retries': []}
    calls.append(0)   # the encoder already finished: OOM belongs to the decoder
    with pytest.raises(torch.cuda.OutOfMemoryError):
        worker.generate_full_context(model_with(generate), processor, noisy(10), [], torch.device('cpu'),
                                     torch.bfloat16, progress, receipt, inputs=inputs)
    assert receipt['generation_attempts'] == 1 and receipt['retries'] == []


def test_insufficient_memory_stops_before_any_generate(fake_gpu, tmp_path):
    torch = fake_gpu
    generate = lambda **kw: pytest.fail('generate must not run')
    with pytest.raises(worker.WindowCapacityError, match='显存不足'):
        run(noisy(600), Processor(), generate, 1 * GIB, tmp_path)


def legacy(events, reviews):
    import subtitle_core
    return SimpleNamespace(AUDIO_SAMPLE_RATE=16000, clean_subtitle_text=subtitle_core.clean_subtitle_text,
                           content_only=subtitle_core.content_only,
                           asr_consensus_similarity=subtitle_core.asr_consensus_similarity,
                           record_run_event=lambda kind, **kw: events.append((kind, kw)),
                           add_review_item=lambda *a, **kw: reviews.append(a))


def windowed_payload(audio):
    bounds = [(0.0, 45.0), (25.0, 75.0), (55.0, 100.0)]
    chunks = []
    for index, (start, end) in enumerate(bounds, 1):
        # Window-local native labels: the host is S01, S02, S01 in the three windows.
        host = 'S02' if index == 2 else 'S01'
        guest = 'S01' if index == 2 else 'S02'
        chunks.append({'chunk_id': index, 'offset': start, 'duration': end - start, 'segments': [
            {'start': 12.0, 'end': 16.0, 'speaker': host, 'text': f'主播第{index}段开场'},
            {'start': 22.0, 'end': 26.0, 'speaker': guest, 'text': f'嘉宾第{index}段回应'}]})
    execution = {'sample_count': len(audio), 'sample_rate': 16000, 'complete': True,
                 'task_audio_fingerprint': worker.audio_fingerprint(audio, 16000),
                 'window_mode': 'context_windows', 'windows': [{'index': 1}, {'index': 2}, {'index': 3}]}
    return {'inference_mode': worker.INFERENCE_MODE, 'cache_version': worker.CACHE_VERSION,
            'chunks': chunks, 'execution': execution}


def voiceprints(chunks, *args, **kwargs):
    host, guest = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    vectors = {}
    for index, chunk in enumerate(chunks):
        for row in chunk['segments']:
            vectors[(index, row['speaker'])] = host if '主播' in row['text'] else guest
    return vectors


def test_windows_are_stitched_by_voiceprint_and_flagged_for_review(monkeypatch):
    audio = np.zeros(100 * 16000, np.float32)
    events, reviews = [], []
    monkeypatch.setattr(pipeline, '_compute_chunk_speaker_embeddings', voiceprints)
    payload = windowed_payload(audio)
    result = pipeline._normalize_moss_full_context(copy.deepcopy(payload), audio, legacy(events, reviews))
    hosts = {row['speaker'] for row in result['segments'] if '主播' in row['text']}
    guests = {row['speaker'] for row in result['segments'] if '嘉宾' in row['text']}
    assert len(hosts) == 1 and len(guests) == 1 and hosts != guests
    starts = [row['start'] for row in result['segments'] if '主播' in row['text']]
    assert starts == [12.0, 37.0, 67.0]                 # window offsets applied once
    assert result['provenance']['normalization'] == 'context_windows_voiceprint_stitched'
    assert any(item[1] == '长音频分段识别' for item in reviews)
    assert [kind for kind, _ in events].count('moss_windows_merged') == 1
    assert result['chunks'] == payload['chunks']        # a cached result is stitched again the same way
    again = pipeline._decode_moss_full_context_cache(copy.deepcopy(result), audio, legacy([], []))
    assert again['segments'] == result['segments']


@pytest.mark.parametrize('mutate', [
    lambda p: p['execution'].pop('window_mode'),
    lambda p: p['chunks'][1].update(offset=30.0),
    lambda p: p['chunks'][0].update(offset=1.0),
    lambda p: p['chunks'][2].update(duration=30.0),
    lambda p: p['chunks'].insert(1, copy.deepcopy(p['chunks'][0])),
])
def test_untrusted_windows_are_rejected(monkeypatch, mutate):
    audio = np.zeros(100 * 16000, np.float32)
    monkeypatch.setattr(pipeline, '_compute_chunk_speaker_embeddings', voiceprints)
    payload = windowed_payload(audio)
    mutate(payload)
    with pytest.raises(RuntimeError):
        pipeline._normalize_moss_full_context(payload, audio, legacy([], []))


def test_report_shows_duration_on_failure_and_window_plan(monkeypatch):
    from twobyteasr import reporting
    report = {'job_id': 'job', 'events': [], 'media': {'name': 'x.mp4'}}
    monkeypatch.setattr(reporting, '_active_report', report)
    reporting.record_media_event('task_audio_ready', job_id='job', seconds=8610.261)
    assert report['media']['audio_seconds'] == 8610.261
    lines = reporting._moss_window_lines({'window_plan': {'mode': 'context_windows', 'count': 4,
                                                          'usable_bytes': int(13.3 * GIB)},
                                          'windows': [{'start': 0, 'end': 2180, 'peak_allocated_gb': 11.9}]})
    assert '计划 4 段' in lines[0] and '11.9 GiB' in lines[0]
    lines = reporting._moss_window_lines({'window_plan': {'mode': 'insufficient', 'usable_bytes': GIB,
                                                          'needed_bytes': 3 * GIB}})
    assert '显存不足' in lines[0]


def test_max_window_override_only_shortens():
    plan = worker.plan_windows(1600, 21300, 131072, int(13.3 * GIB), KV, max_window_seconds='600')
    assert plan['mode'] == 'context_windows' and plan['count'] >= 3 and plan['max_window_override'] == 600
    assert worker.plan_windows(1600, 21300, 131072, int(13.3 * GIB), KV, max_window_seconds='100000')['count'] == 1
    assert worker.plan_windows(1600, 21300, 131072, int(13.3 * GIB), KV, max_window_seconds='junk')['count'] == 1
    # Never below the minimum window.
    assert worker.plan_windows(1600, 21300, 131072, int(13.3 * GIB), KV, max_window_seconds='10')['max_window_override'] == 180
