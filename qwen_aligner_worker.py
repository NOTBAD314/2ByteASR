"""Isolated Qwen3-ForcedAligner worker (main managed runtime, source and frozen runs).

Each job aligns one text against one audio window of the shared task PCM.
Units come from ``twobyteasr.forced_alignment`` with spans in the original
text; the official model, processor and monotonic repair are used unchanged.
Two passes run per job: tokenizer words (nagisa for Japanese) and characters
inside words (the model's own per-unit slots). Raw slot values, repaired
values and the repair kind are all returned. On Windows the weight file is
mapped read-only while the official loader runs (``load_aligner``).
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path

PROTOCOL = "qwen-aligner-units-v1"
TAG_PROTOCOL = "ja-morphology-v1"


def _emit(event: str, **payload: object) -> None:
    print("[2BYTEASR_QWEN3_ALIGNER] " + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _atomic_write(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _tokenize(aligner, text: str, language: str):
    if language.lower() == "japanese":
        import nagisa
        return list(nagisa.tagging(text).words), "nagisa"
    if language.lower() == "korean":
        processor = aligner.aligner_processor
        if processor.ko_tokenizer is None:
            from soynlp.tokenizer import LTokenizer
            processor.ko_tokenizer = LTokenizer(scores=processor.ko_score)
        return list(processor.ko_tokenizer.tokenize(text)), "soynlp"
    return list(aligner.aligner_processor.tokenize_space_lang(text)), "space_lang"


def _align_batch(aligner, audios, unit_lists, torch, *, refiner=None, sample_ids=None, pass_id='word'):
    """``Qwen3ForcedAligner.align`` with caller-supplied units; returns raw and repaired slot times."""
    from twobyteasr.forced_alignment import slot_text
    inputs = aligner.processor(text=[slot_text(units) for units in unit_lists], audio=audios,
                               return_tensors="pt", padding=True)
    inputs = inputs.to(aligner.model.device).to(aligner.model.dtype)
    with torch.inference_mode():
        captured = []
        handle = None
        if refiner is not None:
            def capture(_module, args):
                captured.append(refiner.capture(args[0], inputs, unit_lists, aligner.timestamp_token_id))
            handle = aligner.model.thinker.lm_head.register_forward_pre_hook(capture)
        try:
            aligner._twobyte_forward_attempts = getattr(aligner,'_twobyte_forward_attempts',0) + 1
            logits = aligner.model.thinker(**inputs).logits
        finally:
            if handle is not None:
                handle.remove()
        if refiner is not None and len(captured) != 1:
            raise RuntimeError('Local Head expected one forward capture')
        output_ids = logits.argmax(dim=-1)
        results = []
        step = float(aligner.timestamp_segment_time)
        for row, (input_id, output_id, units) in enumerate(zip(inputs["input_ids"], output_ids, unit_lists)):
            mask = input_id == aligner.timestamp_token_id
            raw = (output_id[mask] * aligner.timestamp_segment_time).to("cpu").numpy()
            if len(raw) != 2 * len(units):
                raise RuntimeError(f"aligner slot count {len(raw)} != 2 x {len(units)} units")
            fixed = aligner.aligner_processor.fix_timestamp(raw)
            # The slot's own posterior over the time classes that lie inside this
            # window (later classes are impossible here), renormalised: peak
            # probability, mass within one class of the peak, and spread.
            classes = min(logits.shape[-1], int(len(audios[row]) * 1000 / 16000 / step) + 2)
            probs = logits[row][mask][:, :classes].float().softmax(dim=-1)
            grid = torch.arange(classes, device=probs.device, dtype=probs.dtype) * step
            mean = probs @ grid
            spread = ((probs * (grid[None, :] - mean[:, None]) ** 2).sum(-1)).clamp_min(0).sqrt()
            peak = probs.argmax(dim=-1)
            padded = torch.nn.functional.pad(probs, (1, 1))
            local = padded.gather(1, peak[:, None]) + padded.gather(1, peak[:, None] + 1) + padded.gather(1, peak[:, None] + 2)
            posterior = {"p_max": [round(float(x), 4) for x in probs.max(dim=-1).values.cpu()],
                         "p_local": [round(float(x), 4) for x in local[:, 0].cpu()],
                         "spread_ms": [round(float(x), 1) for x in spread.cpu()]}
            positions=mask.nonzero().flatten().detach().cpu().tolist()
            posterior['slot_positions']=positions
            posterior['sample_id']=str(sample_ids[row]) if sample_ids is not None else None
            posterior['pass_id']=pass_id
            extractor=getattr(aligner.processor,'feature_extractor',None)
            feature_mask=inputs.get('feature_attention_mask')
            posterior['input_metadata']=dict(timestamp_positions=positions,
                input_shapes={k:list(v.shape) for k,v in inputs.items() if hasattr(v,'shape')},
                attention_mask=inputs['attention_mask'][row].detach().cpu().tolist(),
                feature_attention_mask=feature_mask[row].detach().cpu().tolist() if feature_mask is not None else None,
                sampling_rate=getattr(extractor,'sampling_rate',16000),hop_length=getattr(extractor,'hop_length',None),n_fft=getattr(extractor,'n_fft',None),
                device=str(aligner.model.device),dtype=str(aligner.model.dtype))
            if refiner is not None:
                base = [float(x) for x in fixed]
                try:
                    fixed, refinement = refiner.refine(audios[row], units, base, captured[0][row],
                        sample_id=sample_ids[row], pass_id=pass_id)
                except Exception as exc:
                    if 'out of memory' in str(exc).lower():
                        raise
                    fixed = base
                    refinement = dict(status='base_fallback', reason=f'{type(exc).__name__}: {exc}',
                        sample_id=str(sample_ids[row]), pass_id=pass_id, base_fixed_ms=base,
                        refined_ms=base, candidate_ms=None, slots=[], extra_base_forwards=0)
                posterior['refinement'] = refinement
            results.append(([float(x) for x in raw], [float(x) for x in fixed], posterior))
        captured.clear()
    return results


def select_device(torch, requested: str = "auto"):
    """CUDA (bf16/fp16) when usable, otherwise CPU float32 (2026-10-13).

    The CPU route uses the same official model, processor and timestamp
    classes; only speed differs. ``TWOBYTEASR_ALIGNER_DEVICE=cpu`` forces CPU
    for comparisons on a CUDA machine.
    """
    requested = str(requested or "auto").lower()
    if requested not in {"auto", "cuda", "cpu"}:
        raise RuntimeError(f"Unsupported aligner device: {requested}")
    if requested != "cpu" and torch.cuda.is_available():
        return "cuda:0", (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
    if requested == "cuda":
        raise RuntimeError("Qwen3-ForcedAligner: CUDA was requested but is not available")
    return "cpu", torch.float32


FAILURE_FACTS: dict = {}


def load_aligner(model_dir: Path, device: str, dtype, torch):
    """Returns ``(aligner, weights_loader)``.

    2026-10-15: safetensors maps the 1.75 GB weight file copy-on-write, which
    Windows charges in full against RAM plus page file; PCs with a small page
    file failed here with os error 1455 ("页面文件太小"). On Windows the file is
    mapped read-only while the official loader runs
    (``twobyteasr/read_only_weights.py``); any problem there uses the plain
    official loading.
    """
    from twobyteasr.recognition.qwen_runtime_compat import prepare_qwen_import
    prepare_qwen_import()
    from qwen_asr import Qwen3ForcedAligner
    from twobyteasr import read_only_weights
    return read_only_weights.load(
        torch, lambda: Qwen3ForcedAligner.from_pretrained(str(model_dir), local_files_only=True,
                                                          device_map=device, dtype=dtype),
        lambda aligner: [aligner.model],
        report=lambda error_type, detail: _emit("read_only_load_failed", error_type=error_type, detail=detail))


def _tag_texts(manifest_path: Path, output: Path) -> None:
    """Model-free mode: nagisa words and part-of-speech tags for subtitle line breaking."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("protocol") != TAG_PROTOCOL:
        raise RuntimeError("Unsupported morphology protocol")
    texts = [str(text) for text in manifest.get("texts") or []]
    started = time.perf_counter()
    import nagisa
    loaded = time.perf_counter()
    results = []
    for text in texts:
        tagged = nagisa.tagging(text) if text.strip() else None
        results.append({"text": text, "words": [[word, tag] for word, tag in
                                                 zip(tagged.words, tagged.postags)] if tagged else []})
    _atomic_write(output, {"protocol": TAG_PROTOCOL, "tagger": "nagisa",
                           "tagger_version": getattr(nagisa, "__version__", ""), "results": results,
                           "load_ms": round((loaded - started) * 1000), "tag_ms": round((time.perf_counter() - loaded) * 1000)})


def _read_request(manifest_path, np):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    policy = manifest.get('policy', {})
    if (policy.get('version') != PROTOCOL or policy.get('audio_format') != 'float32-mono-npy-v1'
            or policy.get('sample_rate') != 16000 or not 1 <= int(policy.get('batch_size', 0)) <= 16
            or not set(policy.get('passes') or ['word']) <= {'word', 'char'}):
        raise RuntimeError('Invalid aligner worker policy')
    audio = manifest.get('audio') or {}
    pcm = np.load(audio['path'], mmap_mode='r', allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(audio['samples']):
        raise RuntimeError('Aligner input is not the declared mono float32 PCM')
    jobs = manifest.get('jobs') or []
    if not jobs:
        raise RuntimeError('Aligner manifest is empty')
    from twobyteasr.recognition.alignment_items import verify_items
    verify_items(jobs,audio)
    return manifest, pcm, jobs, policy


def _infer_request(aligner, manifest, pcm, jobs, policy, output_path, torch, np, fa, device, dtype, load_ms, refiner=None):
    identity = policy['alignment_identity']
    forward_start = getattr(aligner,'_twobyte_forward_attempts',0)
    feature_start=(getattr(aligner,'_audio_feature_hits',0),getattr(aligner,'_audio_feature_misses',0))
    compat_start=(getattr(getattr(aligner,'_twobyte_compat_model',None),'_twobyte_forward_attempts',0),getattr(aligner,'_twobyte_compat_loads',0))
    from twobyteasr.recognition.audio_feature_reuse import reuse_audio_features
    from contextlib import nullcontext
    sample_rate, batch_size = int(policy['sample_rate']), int(policy['batch_size'])
    passes = list(policy.get('passes') or ['word'])
    audio_spec = manifest['audio']
    from twobyteasr.recognition.alignment_measurements import model_audio,decoded_units,sentence_measurement,accept_retry,display_segments,matching_anchors,ownership_conflict,retry_window
    enhanced=identity['audio'].get('input_policy') not in {None,'preserve'}
    prepared_inputs={}
    prepared = []
    results = {}
    for job in jobs:
        text = str(job.get("text") or "")
        language = str(job.get("language") or "Japanese")
        from twobyteasr.recognition.alignment_items import sample_bounds
        start,end=sample_bounds(job,min(pcm.size,int(audio_spec.get('valid_samples',pcm.size))))
        actual_window_hash = hashlib.sha256(memoryview(pcm[start:end]).cast('B')).hexdigest()
        expected_hash = (audio_spec.get('window_hashes') or {}).get(str(job['id']))
        expected_hash = expected_hash or (job.get('_checkpoint') or {}).get('identity', {}).get('audio_sha256')
        if expected_hash and expected_hash != actual_window_hash:
            raise RuntimeError('Aligner PCM window changed after manifest preparation')
        row = {"alignment_item":job.get("alignment_item"),"audio_window_sha256":actual_window_hash, "id": job["id"], "text": text, "language": language,
               "window_start_ms": int(job["window_start_ms"]), "window_end_ms": int(job["window_end_ms"])}
        if end - start > fa.ALIGNER_MAX_SECONDS * sample_rate:
            row["status"] = "window_too_long"
        elif end - start < int(0.08 * sample_rate):
            row["status"] = "window_too_short"
        elif not fa.content_char_map(text):
            row["status"] = "no_alignable_text"
        else:
            words, tokenizer = _tokenize(aligner, text, language)
            try:
                word_units = fa.word_units(text, words)
                row["mapping"] = tokenizer
            except fa.UnitMappingError as exc:
                # Tokenizer normalisation we cannot invert: align per character instead.
                word_units = [fa.AlignUnit(c, a, b, "char", i) for i, (c, a, b) in enumerate(fa.content_char_map(text))]
                row["mapping"] = f"{tokenizer}_fallback_chars"
                row["mapping_error"] = str(exc)
            row["tokenizer_words"] = words
            row["status"] = "aligned"
            original=np.ascontiguousarray(pcm[start:end],dtype=np.float32)
            encoded,shift,details=model_audio(original,job.get('artificial_padding_samples',(0,0)),enabled=enhanced)
            details.update(absolute_original_pcm_samples=[start,end],absolute_feature_origin_samples=start+details['feature_origin_original_samples'])
            prepared_inputs[str(row['id'])]=(encoded,details,start,end,job)
            prepared.append((row, original, word_units,
                             fa.char_units(text, word_units) if "char" in passes else None))
        results[str(job["id"])] = row
    prepared.sort(key=lambda item: item[1].size)
    started = time.perf_counter()
    done = 0
    oom_retries = 0
    def infer_group(group):
        nonlocal oom_retries
        audios = [prepared_inputs[str(item[0]['id'])][0] for item in group]
        ids = [item[0]['id'] for item in group]
        try:
            with (reuse_audio_features(aligner,torch) if refiner is None else nullcontext()):
                _emit('pass_started', pass_id='word', jobs=len(group))
                word_out = _align_batch(aligner, audios, [item[2] for item in group], torch,
                                       refiner=refiner, sample_ids=ids, pass_id='word')
                if 'char' in passes:
                    _emit('pass_started', pass_id='char', jobs=len(group))
                    char_out = _align_batch(aligner, audios, [item[3] for item in group], torch,
                                           refiner=refiner, sample_ids=ids, pass_id='char')
                else:
                    char_out = [None] * len(group)
            return [(group, word_out, char_out)]
        except Exception as exc:
            if not any(marker in str(exc).lower() for marker in ('out of memory', 'alloc_failed')) or len(group) == 1:
                raise
            word_out = char_out = None
            oom_retries += 1
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            middle = len(group) // 2
            _emit('oom_batch_reduced', previous=len(group), next=middle, retry=oom_retries)
        # Leave the exception scope, releasing its traceback, before retry.
        return infer_group(group[:middle]) + infer_group(group[middle:])
    for offset in range(0, len(prepared), batch_size):
        batch = prepared[offset:offset + batch_size]
        long_window = max(item[1].size for item in batch) > 60 * sample_rate
        groups = [[item] for item in batch] if long_window else [batch]
        for group, word_out, char_out in [result for group in groups for result in infer_group(group)]:
            retry_requests=[]
            if enhanced:
                for (rr,original,uu,cc),ww,cpair in zip(group,word_out,char_out):
                    _,dd,aa,bb,jj=prepared_inputs[str(rr['id'])]
                    wt0=fa.unit_rows(decoded_units(uu,ww,aa/16,len(original),dd,fa))
                    ct0=fa.unit_rows(decoded_units(cc,cpair,aa/16,len(original),dd,fa)) if cpair is not None else []
                    pp=sentence_measurement(rr['text'],wt0,ct0,[aa/16+dd['valid_original_samples'][0]/16,aa/16+dd['valid_original_samples'][1]/16])
                    if not (any(v['value_ms'] is None for v in pp.values()) and any(v['value_ms'] is not None for v in pp.values())):continue
                    av=jj['alignment_item']['available_context_samples'];lo,hi,window_kind=retry_window(jj,aa,bb,av)
                    if (lo!=aa or hi!=bb) and hi-lo<=fa.ALIGNER_MAX_SECONDS*16000 and not any(jj.get('artificial_padding_samples',[0,0])):
                        ra=np.ascontiguousarray(pcm[lo:hi],dtype=np.float32)
                        re,_,rd=model_audio(ra,enabled=True)
                        rd.update(absolute_original_pcm_samples=[lo,hi],absolute_feature_origin_samples=lo+rd['feature_origin_original_samples'],retry_window_kind=window_kind)
                        retry_requests.append((str(rr['id']),re,rd,lo,hi,uu,cc))
            def run_retry_batch(requests):
                nonlocal oom_retries
                if not requests:return {}
                try:
                    with reuse_audio_features(aligner,torch):
                        rw=_align_batch(aligner,[r[1] for r in requests],[r[5] for r in requests],torch,sample_ids=[r[0] for r in requests],pass_id='word')
                        rc=_align_batch(aligner,[r[1] for r in requests],[r[6] for r in requests],torch,sample_ids=[r[0] for r in requests],pass_id='char') if 'char' in passes else [None]*len(requests)
                    return {r[0]:(w,c,r[2],r[3],r[4]) for r,w,c in zip(requests,rw,rc)}
                except Exception as exc:
                    if not any(x in str(exc).lower() for x in ('out of memory','alloc_failed')) or len(requests)==1:raise
                    oom_retries+=1
                gc.collect()
                if torch.cuda.is_available():torch.cuda.empty_cache()
                mid=len(requests)//2
                return dict(run_retry_batch(requests[:mid]),**run_retry_batch(requests[mid:]))
            retry_cache=run_retry_batch(retry_requests)
            for (row, audio, units, chars), (raw, fixed, posterior), char_pair in zip(group, word_out, char_out):
                window_ms = round(audio.size * 1000 / sample_rate)
                encoded,details,input_start,input_end,job=prepared_inputs[str(row['id'])]
                row['input_processing']=dict(details,word_input=posterior.get('input_metadata'),char_input=char_pair[2].get('input_metadata') if char_pair else None,
                    raw_word_model_ms=list(raw),fixed_word_model_ms=list(fixed),raw_char_model_ms=list(char_pair[0]) if char_pair else None,fixed_char_model_ms=list(char_pair[1]) if char_pair else None)
                word_timed=decoded_units(units,(raw,fixed,posterior),input_start/16,len(audio),details,fa)
                char_timed=decoded_units(chars,char_pair,input_start/16,len(audio),details,fa) if char_pair is not None else None
                segments, stats = fa.reliable_segments(word_timed, char_timed)
                row["word_units"] = fa.unit_rows(word_timed)
                row["char_units"] = fa.unit_rows(char_timed) if char_timed is not None else None
                row["segments"] = fa.unit_rows(fa.cover_display_span(row["text"], segments))
                row["stats"] = stats
                valid=[input_start/16+details['valid_original_samples'][0]/16,input_start/16+details['valid_original_samples'][1]/16]
                primary=sentence_measurement(row['text'],row['word_units'],row['char_units'],valid)
                accepted=primary
                retry_record=None
                if str(row['id']) in retry_cache:
                    rw,rc,retry_details,lo,hi=retry_cache[str(row['id'])]
                    retry_words=fa.unit_rows(decoded_units(units,rw,lo/16,hi-lo,retry_details,fa))
                    retry_chars=fa.unit_rows(decoded_units(chars,rc,lo/16,hi-lo,retry_details,fa)) if chars is not None else []
                    retried=sentence_measurement(row['text'],retry_words,retry_chars,[lo/16,hi/16])
                    anchors=matching_anchors(row['word_units'],retry_words)
                    accepted,used=accept_retry(primary,retried,source_range=[lo/16,hi/16],anchors=anchors)
                    retry_record=dict(source='same_material_same_parent_same_text',absolute_pcm_samples=[lo,hi],
                        input_processing=retry_details,word_units=retry_words,char_units=retry_chars,measurement=retried,
                        adopted_sides=used,anchor_policy='opposite endpoint or two original-word spans within one80msgrid',internal_anchors=anchors,
                        model=identity['model'],model_revision=identity['model_revision'],head=False)
                row['measurement']=dict(primary=primary,accepted=accepted,retry=retry_record,
                    state='complete' if all(p['value_ms'] is not None for p in accepted.values()) else 'partial' if any(p['value_ms'] is not None for p in accepted.values()) else 'unmeasured',
                    old_model_fallback=False)
                row['segments'],row['display_fallback']=display_segments(row['segments'],accepted,valid_range=valid)
                row['raw_candidate_segments']=fa.unit_rows(fa.cover_display_span(row['text'],segments))
                row['actual_measurement_range_ms']=[min(valid[0],retry_record['absolute_pcm_samples'][0]/16) if retry_record else valid[0],max(valid[1],retry_record['absolute_pcm_samples'][1]/16) if retry_record else valid[1]]
                if ownership_conflict(accepted,job.get('parent_pcm_range_ms')):
                    import copy
                    ultra_attempt=copy.deepcopy({k:row[k] for k in ['measurement','word_units','char_units','segments','input_processing','stats']})
                    row['measurement']['ownership_rejection']='accepted utterance lies outside the independent ASR parent; no endpoint clamp'
                    row['measurement']['accepted']={side:dict(value_ms=None,reason='outside_parent_ownership') for side in ['start','end']}
                    row['measurement']['state']='unmeasured'
                    row['status']='unaligned';row['segments']=[];row['failure_reason']='outside_parent_ownership'
                    ultra_attempt['pre_ownership_measurement']=ultra_attempt['measurement']
                    ultra_attempt['measurement']=copy.deepcopy(row['measurement'])
                    row['pure_configured_attempt']=ultra_attempt
                    compat_dir=getattr(aligner,'_twobyte_compat_dir',None)
                    if compat_dir:
                        try:
                            from twobyteasr.model_integrity import verify_model_files
                            compat=getattr(aligner,'_twobyte_compat_model',None)
                            if compat is None:
                                verify_model_files('qwen_aligner',Path(compat_dir))
                                _emit('compatibility_loading',model='Qwen/Qwen3-ForcedAligner-0.6B',reason='parent_ownership_conflict')
                                compat,_loader=load_aligner(Path(compat_dir),device,dtype,torch)
                                aligner._twobyte_compat_model=compat
                                aligner._twobyte_compat_loads=getattr(aligner,'_twobyte_compat_loads',0)+1
                            fallback_audio,_,fallback_details=model_audio(audio,job.get('artificial_padding_samples',(0,0)),enabled=False)
                            with reuse_audio_features(compat,torch):
                                fw=_align_batch(compat,[fallback_audio],[units],torch)[0]
                                fc=_align_batch(compat,[fallback_audio],[chars],torch)[0] if chars is not None else None
                            fwrows=fa.unit_rows(decoded_units(units,fw,input_start/16,len(audio),fallback_details,fa))
                            fcrows=fa.unit_rows(decoded_units(chars,fc,input_start/16,len(audio),fallback_details,fa)) if chars is not None else []
                            fm=sentence_measurement(row['text'],fwrows,fcrows,valid)
                            if ownership_conflict(fm,job.get('parent_pcm_range_ms')):raise RuntimeError('official compatibility also conflicts with parent')
                            # Complete independent item, never masquerading as a pure Ultra measurement.
                            ft=decoded_units(units,fw,input_start/16,len(audio),fallback_details,fa)
                            fct=decoded_units(chars,fc,input_start/16,len(audio),fallback_details,fa) if chars is not None else None
                            fs,st=fa.reliable_segments(ft,fct)
                            row['word_units']=fwrows;row['char_units']=fcrows;row['stats']=st
                            row['measurement']=dict(primary=fm,accepted=fm,retry=None,state='complete' if all(p['value_ms'] is not None for p in fm.values()) else 'partial',old_model_fallback=True)
                            row['segments'],row['display_fallback']=display_segments(fa.unit_rows(fa.cover_display_span(row['text'],fs)),fm,valid_range=valid)
                            spec=identity['compatibility']
                            effective=dict(identity,backend='qwen_official_compat',model_key='qwen_aligner',model=spec['repository'],model_revision=spec['revision'],files=spec['files'],local_head=None,compatibility=None,
                                audio=dict(identity['audio'],input_policy='preserve',source_context_retry_ms=0))
                            row['effective_model_identity']=dict(model=spec['repository'],model_revision=spec['revision'],alignment_identity=effective)
                            row['compatibility_fallback']=dict(reason='parent_ownership_conflict',verified_files=True,model=spec['repository'],revision=spec['revision'],input_processing=fallback_details,head=False)
                            row['actual_measurement_range_ms']=valid
                            row['status']='aligned';row.pop('failure_reason',None)
                        except Exception as exc:
                            if 'out of memory' in str(exc).lower():
                                if hasattr(aligner,'_twobyte_compat_model'):del aligner._twobyte_compat_model
                                if torch.cuda.is_available():torch.cuda.empty_cache()
                            row['compatibility_fallback_failed']=str(exc)
                # Measurement and final display are separate, including rejected or compatibility cases.
                if not any(piece['end_ms'] > piece['start_ms'] and
                           (piece['start_basis'] == 'model' or piece['end_basis'] == 'model') for piece in row["segments"]):
                    row['status'] = 'unaligned'
                    row.setdefault('failure_reason','no_usable_measured_span')
                    row['segments'] = []
                row['refinement'] = {name: pair[2].get('refinement') for name, pair in
                    (('word', (raw, fixed, posterior)), ('char', char_pair)) if pair is not None}
        from twobyteasr.recognition.alignment_checkpoints import save_worker_checkpoint
        metadata = dict(protocol=PROTOCOL, policy=policy, model=identity["model"],
            model_revision=identity["model_revision"], code=identity["code"], unit_policy=identity["unit_policy"],
            alignment_identity=identity, execution_identity=dict(device=device, dtype=str(dtype), torch_version=torch.__version__),
            dtype=str(dtype), torch_version=torch.__version__, device=device)
        by_job = {str(job['id']): job for job in jobs}
        for row, *_ in batch:
            save_worker_checkpoint(by_job[str(row['id'])].get('_checkpoint'), row, metadata)
        done += len(batch)
        _emit("progress", done=done, total=len(prepared),
              range_start_ms=min(row['window_start_ms'] for row,*_ in batch),
              range_end_ms=max(row['window_end_ms'] for row,*_ in batch))
    inference_ms = (time.perf_counter() - started) * 1000.0
    try:
        import psutil
        memory = psutil.Process().memory_info()
        peak_ram_mb = getattr(memory, 'peak_wset', memory.rss) / 1024**2
    except Exception:
        peak_ram_mb = None
    peak_vram_mb = torch.cuda.max_memory_allocated() / 1024**2 if device.startswith('cuda') else None
    _atomic_write(Path(output_path), {
        "protocol": PROTOCOL, "policy": policy, "results": [results[str(job["id"])] for job in jobs],
        "audio_sha256": audio_spec.get("sha256"), "python": sys.executable, "pid": os.getpid(),
        "torch_version": torch.__version__, "dtype": str(dtype), "device": device,
        "backend": "torch-cuda" if device.startswith("cuda") else "torch-cpu", "model": identity["model"],
        "model_revision": identity["model_revision"], "code": identity["code"], "unit_policy": identity["unit_policy"],
        "alignment_identity": identity, "execution_identity": dict(device=device, dtype=str(dtype), torch_version=torch.__version__),
         "peak_ram_mb": peak_ram_mb, "peak_vram_mb": peak_vram_mb,
        "base_forward_attempts": getattr(aligner, "_twobyte_forward_attempts", 0)-forward_start,
        "compatibility_model_loads":getattr(aligner,"_twobyte_compat_loads",0)-compat_start[1],
        "compatibility_rows":sum(bool(r.get("compatibility_fallback")) for r in results.values()),
        "compatibility_forward_attempts":getattr(getattr(aligner,"_twobyte_compat_model",None),"_twobyte_forward_attempts",0)-compat_start[0],
        "audio_feature_reuse":dict(hits=getattr(aligner,"_audio_feature_hits",0)-feature_start[0],misses=getattr(aligner,"_audio_feature_misses",0)-feature_start[1],scope="exact tensors+all kwargs, one word/char pair, same eval model only"),
        "oom_retries": oom_retries, "timestamp_grid_ms": float(aligner.timestamp_segment_time),
        "load_ms": round(load_ms, 3), "inference_ms": round(inference_ms, 3)})
    _emit("completed", aligned=len(prepared), jobs=len(jobs), inference_ms=round(inference_ms, 3), device=device)


def main() -> None:
    # numpy and scipy each load OpenBLAS, which commits about 24 MB per CPU
    # thread at import (1.5 GB of this worker's peak on a 32-thread CPU).
    # Nothing here uses their BLAS; torch has its own (2026-10-15).
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model-dir")
    parser.add_argument("--head-dir")
    parser.add_argument("--compat-dir")
    parser.add_argument("--tag-only", action="store_true")
    parser.add_argument("--resident", action="store_true")
    args = parser.parse_args()
    if args.tag_only:
        _tag_texts(Path(args.manifest), Path(args.output))
        return
    if not args.model_dir:
        parser.error("--model-dir is required")
    root = Path(__file__).resolve().parent
    if root.name == "workers":
        root = root.parent
    sys.path.append(str(root))
    import numpy as np
    import torch
    from twobyteasr.model_integrity import verify_model_files
    from twobyteasr import forced_alignment as fa

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    policy = manifest.get("policy", {})
    if policy.get("version") != PROTOCOL or policy.get("audio_format") != "float32-mono-npy-v1":
        raise RuntimeError("Unsupported aligner worker protocol")
    sample_rate = int(policy.get("sample_rate", 0))
    batch_size = int(policy.get("batch_size", 0))
    passes = list(policy.get("passes") or ["word"])
    if sample_rate != 16000 or not 1 <= batch_size <= 16 or not set(passes) <= {"word", "char"}:
        raise RuntimeError("Invalid aligner worker policy")
    audio_spec = manifest.get("audio") or {}
    pcm = np.load(str(audio_spec["path"]), mmap_mode="r", allow_pickle=False)
    if pcm.dtype != np.float32 or pcm.ndim != 1 or pcm.size != int(audio_spec["samples"]):
        raise RuntimeError("Aligner input is not the declared mono float32 PCM")
    jobs = manifest.get("jobs") or []
    if not jobs:
        raise RuntimeError("Aligner manifest is empty")
    from twobyteasr.recognition.alignment_items import verify_items
    verify_items(jobs,audio_spec)
    from twobyteasr.recognition.alignment_backend import request_identity, worker_comparable
    identity = policy.get('alignment_identity') or {}
    backend = identity.get('backend')
    observed_identity = request_identity(backend, sys.executable, passes=passes, batch_size=batch_size)
    if worker_comparable(identity) != worker_comparable(observed_identity):
        raise RuntimeError('Worker alignment identity differs from requested configuration/runtime')
    observed_gpu = (observed_identity.get('execution') or {}).get('gpu')
    if observed_gpu != (identity.get('execution') or {}).get('gpu'):
        # Only the nvidia-smi reading differs (e.g. one side timed out); the
        # request identity, with the parent's reading, stays the loaded one.
        _emit('gpu_identity_differs', requested=(identity.get('execution') or {}).get('gpu'), observed=observed_gpu)
    actual_identity = identity
    if actual_identity['execution']['packages'].get('qwen-asr') != '0.0.6':
        raise RuntimeError('The slot implementation requires qwen-asr==0.0.6')
    _emit('verifying', model=actual_identity['model'], model_revision=actual_identity['model_revision'])
    if actual_identity['execution']['packages'].get('nagisa') != '0.2.11':
        raise RuntimeError('Unit mapping requires the pinned nagisa==0.2.11')
    verify_model_files(actual_identity['model_key'], Path(args.model_dir), root=root)
    if bool(args.head_dir) != bool(identity['local_head']):
        raise RuntimeError('Local Head selection does not match requested profile')
    device, dtype = select_device(torch, os.environ.get("TWOBYTEASR_ALIGNER_DEVICE", "auto"))
    if identity['execution']['resolved_execution']['device'] != device or identity['execution']['resolved_execution']['dtype'] != str(dtype):
        raise RuntimeError('Actual device or precision changed after the request probe')
    load_started = time.perf_counter()
    _emit("loading", python=sys.executable, model_path=str(Path(args.model_dir).resolve()), pid=os.getpid(),
          jobs=len(jobs), device=device, dtype=str(dtype))
    aligner, weights_loader = load_aligner(Path(args.model_dir), device, dtype, torch)
    load_ms = (time.perf_counter() - load_started) * 1000.0
    refiner = None
    if args.head_dir:
        from twobyteasr.recognition.ultra_local_head import LocalHead
        refiner = LocalHead(Path(args.head_dir), torch=torch)
    load_ms = (time.perf_counter() - load_started) * 1000.0
    aligner._twobyte_compat_dir=args.compat_dir
    _emit("loaded", elapsed_ms=round(load_ms, 3), weights_loader=weights_loader, alignment_identity=actual_identity)
    try:
        _infer_request(aligner, manifest, pcm, jobs, policy, args.output, torch, np, fa, device, dtype, load_ms, refiner)
        pcm._mmap.close()
        if args.resident:
            _emit('request_completed', output=str(args.output), model_load_count=1)
            for raw in sys.stdin:
                request = json.loads(raw)
                if request.get('shutdown'):
                    break
                manifest, pcm, jobs, policy = _read_request(request['manifest'], np)
                if policy.get('alignment_identity') != actual_identity:
                    raise RuntimeError('Resident aligner request attempted to switch loaded identity')
                _infer_request(aligner, manifest, pcm, jobs, policy, request['output'], torch, np, fa, device, dtype, 0., refiner)
                pcm._mmap.close()
                _emit('request_completed', output=str(request['output']), model_load_count=1)
    except Exception as exc:
        FAILURE_FACTS.update(memory_facts(exc))  # measured before the model is released below
        raise
    finally:
        del aligner
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def memory_facts(exc: BaseException) -> dict:
    """Free VRAM and Windows commit when an allocation failed (2026-10-15).

    Once the commit limit is reached, GPU allocations fail as well and read
    "CUDA out of memory" while most of the VRAM is free; these numbers tell
    the two apart in the readiness check and in user logs.
    """
    lowered = str(exc).lower()
    if not any(marker in lowered for marker in ("out of memory", "alloc_failed", "1455", "paging file", "页面文件")):
        return {}
    facts = {}
    try:
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            facts.update(free_vram_mb=free >> 20, total_vram_mb=total >> 20)
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PerformanceInformation(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), *[(name, ctypes.c_size_t) for name in (
                    "CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal", "PhysicalAvailable", "SystemCache",
                    "KernelTotal", "KernelPaged", "KernelNonpaged", "PageSize")],
                    ("HandleCount", wintypes.DWORD), ("ProcessCount", wintypes.DWORD), ("ThreadCount", wintypes.DWORD)]

            info = PerformanceInformation(cb=ctypes.sizeof(PerformanceInformation))
            # kernel32 is already loaded; at the limit there may be no room to load psapi.dll.
            if ctypes.windll.kernel32.K32GetPerformanceInfo(ctypes.byref(info), info.cb):
                page = info.PageSize
                facts.update(commit_total_mb=info.CommitTotal * page >> 20, commit_limit_mb=info.CommitLimit * page >> 20,
                             physical_total_mb=info.PhysicalTotal * page >> 20)
        except Exception:
            pass
    return facts


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit("failed", error_type=type(exc).__name__, detail=str(exc), **(FAILURE_FACTS or memory_facts(exc)))
        raise SystemExit(1)
