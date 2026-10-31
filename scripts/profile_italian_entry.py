"""Offline, isolated normal-entry wrapper for all-thread caption profiling."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import runpy
    os.environ['TWOBYTEASR_TEST_ROOT'] = os.environ['TWOBYTEASR_ACCEPTANCE_DIR']
    from twobyteasr.test_isolation import install, require_isolated_paths
    install()
    require_isolated_paths('Italian real-project caption profile')
    before = os.environ.get('ITALIAN_BEFORE')
    if before:
        import importlib.abc
        import importlib.util
        modules = {}
        for name in ('projects.studio_revisions', 'timeline.studio_commands', 'recognition.speaker_recovery',
                     'caption_style.resolved_caption_style', 'caption_style.scoped_transform',
                     'studio.studio_speaker_manager', 'caption_style.caption_layer_transform',
                     'rendering.caption_playback_cache', 'caption_style.caption_transform_panel'):
            module_name = 'twobyteasr.' + name
            path = Path(before) / (name.rsplit('.', 1)[1] + '.py')
            if module_name in sys.modules:
                raise RuntimeError('Baseline must precede the first import: '+module_name)
            modules[module_name] = str(path)
        class Before(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname in modules:
                    return importlib.util.spec_from_file_location(fullname, modules[fullname])
        sys.meta_path.insert(0, Before())
    if os.environ.get('ITALIAN_PROFILE') != '1':
        runpy.run_path(str(ROOT / 'quick_start.py'), run_name='__main__')
        return
    from twobyteasr.rendering.caption_playback_cache import PlaybackCaptionCache
    original = PlaybackCaptionCache._work

    def profiled(self):
        import cProfile
        import pstats
        import io
        profile = cProfile.Profile()
        try:
            return profile.runcall(original, self)
        finally:
            stream = io.StringIO()
            stats = pstats.Stats(profile, stream=stream)
            stats.sort_stats('cumtime').print_stats(70)
            stats.sort_stats('tottime').print_stats(35)
            output = Path(os.environ['TWOBYTEASR_ACCEPTANCE_DIR'])
            (output / f'profile-caption-thread-{id(self)}.txt').write_text(stream.getvalue(), encoding='utf8')
    PlaybackCaptionCache._work = profiled
    runpy.run_path(str(ROOT / 'quick_start.py'), run_name='__main__')


if __name__ == '__main__':
    main()
