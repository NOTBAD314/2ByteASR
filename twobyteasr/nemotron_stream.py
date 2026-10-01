"""Pinned Transformers streaming contract; independent of ASR chunk boundaries."""
MODEL_REVISION='f667ed73aee57d40cc39428eb768b4fd87a0a29e'
RUNTIME_REVISION='4b28d51d0d5f17ec20c23a187d0475a8e68810c8'
MODE='low_latency'


def processor_chunks(audio, processor):
    total=len(audio);rate=processor.feature_extractor.sampling_rate
    if total < processor.feature_extractor.hop_length:
        raise ValueError('Nemotron 输入不足一个有效帧')
    first=processor.num_samples_first_audio_chunk
    if total < first:
        yield 0,True,processor(audio,sampling_rate=rate,is_streaming=True,
            is_first_audio_chunk=True,is_last_audio_chunk=True)
        return
    yield 0,False,processor(audio[:first],sampling_rate=rate,is_streaming=True,is_first_audio_chunk=True)
    cursor=processor.num_mel_frames_per_step
    start=processor.audio_chunk_start(cursor);size=processor.num_samples_per_audio_chunk
    while start+size <= total:
        yield cursor,False,processor(audio[start:start+size],sampling_rate=rate,
            is_streaming=True,is_first_audio_chunk=False)
        cursor+=processor.num_mel_frames_per_step;start=processor.audio_chunk_start(cursor)
    yield cursor,True,processor(audio[start:],sampling_rate=rate,is_streaming=True,
        is_first_audio_chunk=False,is_last_audio_chunk=True)


def probabilities(audio,processor,model,torch,check=lambda:None,observe=None):
    cache=None;emitted=0
    with torch.inference_mode():
        for origin,last,inputs in processor_chunks(audio,processor):
            check()
            frames=int(inputs['attention_mask'][0].sum().item())
            expected=frames-int(inputs.get('num_lookahead_frames',0))*processor.subsampling_factor
            if expected<=0 or origin!=emitted:raise RuntimeError('Nemotron 帧时间连续性错误')
            outputs=model(**inputs.to(model.device,dtype=model.dtype),speaker_cache=cache)
            check()
            if tuple(outputs.logits.shape)!=(1,expected,8):raise RuntimeError('Nemotron 输出帧或通道数不匹配')
            if not last and outputs.speaker_cache is None:raise RuntimeError('Nemotron 未返回连续身份缓存')
            if observe is not None:
                observe(dict(origin_frame=emitted, valid_feature_frames=frames,
                    lookahead_encoder_frames=int(inputs.get('num_lookahead_frames',0)),
                    output_shape=list(outputs.logits.shape), last=last,
                    cache_continued=cache is not None, cache_returned=outputs.speaker_cache is not None))
            cache=outputs.speaker_cache
            # The pinned implementation returns raw logits, not probabilities.
            yield emitted,outputs.logits[0].detach().float().sigmoid().cpu().numpy()
            emitted+=expected
