"""Startup guard implementation; the compatibility facade supplies live state."""

def run_startup_self_test(core):
    """运行不加载模型、不访问网络的关键字幕护栏自测。"""
    import contextlib
    import io
    checks = []

    def require(condition, label):
        if not condition:
            raise RuntimeError(label)
        checks.append(label)
    saved_review_items = list(core.RUN_REVIEW_ITEMS)
    try:
        core.RUN_REVIEW_ITEMS.clear()
        muted_output = io.StringIO()
        with contextlib.redirect_stdout(muted_output):
            require(abs(core.ISOLATED_CUE_TAIL_SECONDS - 0.2) < 1e-09, '字幕尾帧必须固定为 200ms')
            require(abs(core.SHORT_DISPLAY_GAP_BRIDGE_SECONDS - 0.5) < 1e-09, '全轨短空白衔接阈值必须固定为 500ms')
            require(core.PREFERRED_MAX_SUBTITLE_CHARS <= core.MAX_SUBTITLE_CHARS == core.COMPLETE_PHRASE_SOFT_MAX_CHARS <= 16, '字幕舒适目标与最终 16 字硬上限必须生效')
            require(core.format_subtitle_display_text('哦耶还没到保底') == '哦耶还没到保底', '完整反应词“哦耶”不得被机械空格拆开')
            require(core.format_subtitle_display_text('OK啊') == 'OK啊', '完整反应词“OK啊”不得被机械空格拆开')
            require(core.format_subtitle_display_text('没事哎') == '没事 哎', '句尾补充反应“哎”前必须保留视觉气口')
            require(core.format_subtitle_display_text('没事没事失败乃成功之母') == '没事没事 失败乃成功之母', '重复反应与后续完整判断之间必须保留视觉气口')
            moderate_particle_pause = [core.SpeechSegment(1, 0.0, 1.0, '哦耶还没到保底我就抽到', 0.9, [], speaker='S01'), core.SpeechSegment(2, 2.351, 3.0, '了哈哈', 0.9, [], speaker='S01')]
            require(11 not in core.hard_break_character_offsets(moderate_particle_pause), '不足 3 秒的停顿不得强制切成“抽到｜了哈哈”')
            particle_batch = [core.SpeechSegment(1, 0.0, 4.0, '哦耶还没到保底我就抽到了哈哈', 0.9, [], speaker='S01')]
            require(core.repair_dependent_particle_boundary_offsets(particle_batch, [11, 12, 14]) == [7, 14], '助词残句必须修成“哦耶还没到保底｜我就抽到了哈哈”')
            midword_batch = [core.SpeechSegment(1, 8.41, 10.62, '那我们就直接进入一个珊瑚场啊', 0.9, [], speaker='S01')]
            midword_offsets = core.repair_segmenter_word_boundary_offsets(midword_batch, [7, 14])
            require(7 not in set(midword_offsets[:-1]), '词边界护栏不得保留 进|入')
            midword_texts = core.texts_from_boundary_offsets(midword_batch, midword_offsets)
            require(all(('进' not in text or '进入' in text or (not text.endswith('进')) for text in midword_texts)) or midword_texts == ['那我们就直接进入', '一个珊瑚场啊'] or midword_texts == ['那我们就直接', '进入一个珊瑚场啊'], '进入不得拆成上下两条残词')
            adjacent = core.repair_mid_word_adjacent_cues([core.SubtitleCue(1, 8.41, 9.42, '那我们就直接进', speaker='S01'), core.SubtitleCue(2, 9.42, 10.62, '入一个珊瑚场啊', speaker='S01'), core.SubtitleCue(3, 39.0, 40.0, '这就是八件藏', speaker='S01'), core.SubtitleCue(4, 40.0, 41.0, '品的轮廓啊', speaker='S01')])
            joined = [cue.text for cue in adjacent]
            require(not any((text.endswith('进') for text in joined)) and (not any((text.startswith('入') and '进入' not in text for text in joined))), '相邻字幕兜底必须修好 进|入')
            require(not any((text.endswith('藏') for text in joined)) and (not any((text.startswith('品') and '藏品' not in text for text in joined))), '相邻字幕兜底必须修好 藏|品')
            hang_batch = [core.SpeechSegment(1, 0.0, 2.5, '我们有300万的启动资金啊', 0.9, [], speaker='S01')]
            hang_offsets = core.repair_hanging_attribute_boundary_offsets(hang_batch, [8, 13])
            require(hang_offsets == [13], '300万的｜启动资金啊 必须合并成一句')
            coral_batch = [core.SpeechSegment(1, 8.4, 10.8, '那我们就直接进入一个珊瑚场啊', 0.9, [], speaker='S01')]
            coral_offsets = core.repair_hanging_attribute_boundary_offsets(coral_batch, [10, 14])
            coral_texts = core.texts_from_boundary_offsets(coral_batch, coral_offsets)
            require(coral_texts in (['那我们就直接进入一个珊瑚场啊'], ['那我们就直接进入', '一个珊瑚场啊']), '进入一个｜珊瑚场啊 必须整句或切到一个前')
            hang_cues = core.merge_hanging_attribute_cues([core.SubtitleCue(1, 0.0, 1.3, '我们有300万的', speaker='S01'), core.SubtitleCue(2, 1.3, 2.5, '启动资金啊', speaker='S01'), core.SubtitleCue(3, 8.4, 9.7, '那我们就直接进入一个', speaker='S01'), core.SubtitleCue(4, 9.7, 10.8, '珊瑚场啊', speaker='S01')])
            hang_joined = [cue.text for cue in hang_cues]
            require('我们有300万的启动资金啊' in hang_joined, '成片轨必须合并 300万的启动资金啊')
            require(any(('珊瑚场啊' in text and '进入' in text for text in hang_joined)) or ('那我们就直接进入' in hang_joined and '一个珊瑚场啊' in hang_joined), '成片轨必须修好 进入一个｜珊瑚场啊')
            force_units = []
            cursor_t = 0.0
            sample = '那我们就直接进入一个珊瑚场啊'
            for char in core.content_exact(sample):
                force_units.append(core.WordUnit(cursor_t, cursor_t + 0.12, char, 1.0))
                cursor_t += 0.12
            forced_local = core.locally_repair_resegmented_cue(sample, force_units, forced_boundaries={7})
            require([cue.text for cue in forced_local] in (['那我们就直接进入', '一个珊瑚场啊'], ['那我们就直接', '进入一个珊瑚场啊']), '本地修复遇到词中强制点时必须贴到词边界')
            tail_cues = [core.SubtitleCue(1, 0.0, 1.0, '第一句', speaker='S01'), core.SubtitleCue(2, 1.1, 1.5, '第二句', speaker='S01'), core.SubtitleCue(3, 0.0, 1.0, '重叠说话', speaker='S02')]
            core.extend_cue_tails_by_speaker(tail_cues, 2.0, core.TIMELINE_FPS)
            require(abs(tail_cues[0].end - 1.1) <= 1.0 / core.TIMELINE_FPS, '同主播下一句必须截断上一句尾帧')
            require(abs(tail_cues[2].end - 1.2) <= 1.0 / core.TIMELINE_FPS, '独立字幕尾帧不得超过 200ms')
            bridge_cues = [core.SubtitleCue(1, 0.0, 1.0, '主播一', speaker='S01'), core.SubtitleCue(2, 1.184, 2.0, '主播二', speaker='S02'), core.SubtitleCue(3, 2.6, 3.2, '长空白', speaker='S01')]
            core.bridge_short_display_gaps(bridge_cues, 4.0, core.TIMELINE_FPS)
            require(abs(bridge_cues[0].end - bridge_cues[1].start) <= 1.0 / core.TIMELINE_FPS, '跨说话人不足 500ms 的空白必须衔接')
            require(abs(bridge_cues[1].end - 2.0) <= 1.0 / core.TIMELINE_FPS, '超过 500ms 的空白必须保留')
            forbidden_samples = {'跟我们要调查的事件有线索': '事件', '这里有什么跟案发线索有关': '案发', '你厨房里边为什么会有': '为什么'}
            for (sample, term) in forbidden_samples.items():
                start = core.content_exact(sample).find(term)
                forbidden = core.lexical_forbidden_boundary_offsets(sample)
                require(all((offset in forbidden for offset in range(start + 1, start + len(term)))), f'完整词“{term}”不得从中间断开')
            duplicate_segments = [core.SpeechSegment(1, 10.0, 14.0, '这个连续签到七天了啊每天都签了', 0.9, [], speaker='S01'), core.SpeechSegment(2, 10.03, 12.1, '这个连续签到七天了啊', 0.9, [], speaker='S01')]
            deduplicated = core.remove_overlapping_duplicate_segments(duplicate_segments)
            require(len(deduplicated) == 1 and '每天都签了' in deduplicated[0].text, '同起点高重叠的完整前缀副本必须删除')
            genuine_repetition = [core.SpeechSegment(1, 20.0, 21.0, '好好好好', 0.9, [], speaker='S01'), core.SpeechSegment(2, 21.5, 22.5, '好好好好', 0.9, [], speaker='S01')]
            require(len(core.remove_overlapping_duplicate_segments(genuine_repetition)) == 2, '没有声学重叠的正常口语重复必须保留')
            onset_cues = [core.SubtitleCue(1, 1.0, 2.0, '句首校准', speaker='S01')]
            original_start = onset_cues[0].start
            core.snap_cue_starts_to_vad_onsets(onset_cues, [{'start': 1.3, 'end': 2.0}], core.TIMELINE_FPS)
            require(onset_cues[0].start >= original_start, 'VAD 句首校准绝不能把字幕提前')
            require(abs(onset_cues[0].start - 1.3) <= 1.0 / core.TIMELINE_FPS, '静音区字幕必须向后贴到 VAD 起音')
            with core.tempfile.TemporaryDirectory(prefix='twobyteasr_startup_') as folder:
                txt_path = core.os.path.join(folder, 'sample_剪映文稿.txt')
                srt_path = core.os.path.join(folder, 'sample_剪映文稿.srt')
                output_cues = [core.SubtitleCue(1, 0.0, 1.0, '主播一', speaker='S01'), core.SubtitleCue(2, 0.2, 1.2, '主播二', speaker='S02')]
                result = core.write_all_outputs_transactional(output_cues, txt_path, srt_path, include_review_track=False)
                speaker_paths = [path for (_, path, _) in result['speaker_outputs']]
                require(core.os.path.isfile(txt_path) and core.os.path.isfile(srt_path), '总 TXT/SRT 事务写入必须成功')
                require(len(speaker_paths) == 2 and all((core.os.path.isfile(path) for path in speaker_paths)), '双说话人分轨必须同时生成')
                with open(speaker_paths[0], 'r', encoding='utf-8-sig') as first_track:
                    first_text = first_track.read()
                with open(speaker_paths[1], 'r', encoding='utf-8-sig') as second_track:
                    second_text = second_track.read()
                require('主播一' in first_text and '主播二' in second_text, '说话人字幕不得串轨')
            require(core.format_srt_time(1.234) == '00:00:01,234', 'SRT 毫秒格式必须稳定')
            require(callable(core._load_secret_value) and callable(core.require_runtime_secrets), '密钥加载器必须可用')
            require('host_voiceprints' in core.HOST_VOICEPRINT_DIR.replace('\\', '/'), '主播声纹目录必须位于 LocalAppData/2ByteASR')
    except Exception as exc:
        raise RuntimeError(f'{core.STARTUP_SELF_TEST_ID} 未通过：{exc}') from exc
    finally:
        core.RUN_REVIEW_ITEMS[:] = saved_review_items
    return {'id': core.STARTUP_SELF_TEST_ID, 'checks': len(checks)}
