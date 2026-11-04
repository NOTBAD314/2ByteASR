"""Create isolated playback cases from an existing bilingual project copy."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start-ms', type=int, default=2100000)
    parser.add_argument('--media', type=Path, required=True, help='Owned copy of the original source media')
    parser.add_argument('--only', help='Build only the named case')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if out.exists() or not out.is_relative_to(root / 'tmp'):
        parser.error('Output must be a new directory under source/tmp')
    out.mkdir(parents=True)
    source = json.loads(args.project.read_text(encoding='utf-8-sig'))
    original_media = source['media']['path']
    copied_media = str(args.media.resolve())
    if not args.media.is_file():
        parser.error('Copied media does not exist')
    def relink(value):
        if isinstance(value, dict):
            return {key: relink(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relink(item) for item in value]
        return copied_media if value == original_media else value
    source = relink(source)
    motion = {'entry': {'type': 'fade', 'duration': 180},
              'exit': {'type': 'fade', 'duration': 140},
              'loop': {'type': 'loop_breathe', 'duration': 1200, 'strength': 'medium'},
              'motion_override': True}
    cases = [('video', 'original', False, True, False),
             ('original', 'original', False, False, False),
             ('bilingual', 'bilingual', False, False, False),
             ('original-motion', 'original', True, False, False),
             ('bilingual-motion', 'bilingual', True, False, False),
             ('small-bilingual-motion', 'bilingual', True, False, True),
             ('expanded-bilingual-motion', 'bilingual', True, False, False),
             ('long-overlap-bilingual-motion', 'bilingual', True, False, False)]
    # Reparse to avoid retaining several copies of the large recognition evidence.
    for name, language, animated, hidden, small in cases:
        if args.only and name != args.only:
            continue
        project = json.loads(json.dumps(source, ensure_ascii=False))
        project['studio_state'].setdefault('bilingual', {})['mode'] = language
        project['studio_state']['bilingual_mode'] = language == 'bilingual'
        if hidden:
            project['studio_state']['subtitle_track_visibility'] = {c['speaker_id']: False for c in project['cues']}
        if small:
            cues = sorted(project['cues'], key=lambda cue: abs(cue['start_ms'] - args.start_ms - 60000))[:250]
            ids = {cue['id'] for cue in cues}
            project['cues'] = sorted(cues, key=lambda cue: (cue['start_ms'], cue['id']))
            translations = project['generation_metadata'].get('translations', {})
            project['generation_metadata']['translations'] = {key: value for key, value in translations.items() if key in ids}
        if name in {'expanded-bilingual-motion', 'long-overlap-bilingual-motion'}:
            # Extra copies lie outside the measured two-minute interval, so
            # its real active cues and overlaps remain exactly the same.
            translations = project['generation_metadata']['translations']
            candidates = [cue for cue in project['cues']
                          if cue['start_ms'] >= args.start_ms + 180000 and cue['id'] in translations]
            needed = max(0, 2000 - len(project['cues']))
            if len(candidates) < needed:
                raise ValueError('Not enough translated cues outside the measurement interval')
            for cue in candidates[:needed]:
                duplicate = json.loads(json.dumps(cue, ensure_ascii=False))
                duplicate['id'] = 'performance-copy-' + str(cue['id'])
                project['cues'].append(duplicate)
                translations[duplicate['id']] = translations[cue['id']]
            project['cues'].sort(key=lambda cue: (cue['start_ms'], cue['id']))
        if name == 'long-overlap-bilingual-motion':
            long_cue = json.loads(json.dumps(project['cues'][0], ensure_ascii=False))
            long_cue.update(id='performance-long-overlap', start_ms=0,
                            end_ms=project['media']['duration_ms'],
                            text='Long overlap fixture', original_text='Long overlap fixture')
            project['cues'].append(long_cue)
            project['cues'].sort(key=lambda cue: (cue['start_ms'], cue['id']))
            project['generation_metadata']['translations'][long_cue['id']] = 'Long overlap translation'
        if animated:
            project['effects']['large-playback-test-breathe'] = motion
            for cue in project['cues']:
                cue['effect_id'] = 'large-playback-test-breathe'
                cue.setdefault('transform', {})['language_motion'] = {
                    'linked': True, 'translation_effect_id': 'large-playback-test-breathe', 'word_fallback': 'none'}
        dest = out / (name + '.2byteproj')
        dest.write_text(json.dumps(project, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
        print(name, len(project['cues']), len(project['generation_metadata'].get('translations', {})), flush=True)


if __name__ == '__main__':
    main()
