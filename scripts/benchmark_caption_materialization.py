"""Compare the production caption preparation before/after a single cue edit."""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=args.source.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ.update(TWOBYTEASR_TEST_ROOT=str(out),QT_QPA_PLATFORM='offscreen')
    sys.path.insert(0,str(root))
    from twobyteasr.test_isolation import install
    install()
    from PySide6.QtWidgets import QApplication
    from twobyteasr.app.ui import _register_bundled_fonts
    from twobyteasr.projects.studio_project import SubtitleProject,StudioCue,StudioMedia
    from twobyteasr.projects.studio_revisions import StudioRevisionStore
    from twobyteasr.rendering.caption_playback_cache import materialize_caption_project
    app=QApplication.instance() or QApplication([]);_register_bundled_fonts()
    incremental='previous' in inspect.signature(materialize_caption_project).parameters
    result={'source':str(root),'source_hash':hashlib.sha256(Path(inspect.getfile(materialize_caption_project)).read_bytes()).hexdigest(),
            'kind':'worker preparation; not input-to-pixel or video FPS','cases':[]}
    for count in (60,600,2000):
        for bilingual in (False,True):
            p=SubtitleProject(media=StudioMedia(''),cues=[StudioCue(str(i),i*1000,(i+1)*1000,'今天終於通過最後一關') for i in range(count)])
            if bilingual:
                p.generation_metadata['translations']={c.id:'We cleared the last stage' for c in p.cues}
                p.studio_state['bilingual']={'mode':'bilingual'}
            p.validate();revision=StudioRevisionStore(p).render
            began=time.perf_counter();previous=materialize_caption_project(revision);cold=(time.perf_counter()-began)*1000
            durations=[];reuses=[]
            for i in range(3):
                p.cues[i].text+='！';revision=StudioRevisionStore(p).render
                began=time.perf_counter()
                updated=materialize_caption_project(revision,previous) if incremental else materialize_caption_project(revision)
                durations.append((time.perf_counter()-began)*1000)
                reuses.append(sum(a is b for a,b in zip(previous.cues,updated.cues)))
                previous=updated
            result['cases'].append(dict(cues=count,bilingual=bilingual,cold_ms=cold,
                edit_ms=durations,edit_median_ms=statistics.median(durations),reused_cues=reuses))
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
