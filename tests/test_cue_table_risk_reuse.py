from PySide6.QtWidgets import QApplication
from twobyteasr.studio import studio_cue_table as table
from twobyteasr.projects.studio_project import StudioCue,StudioMedia,SubtitleProject


def test_filter_and_status_share_one_risk_map(monkeypatch):
    app=QApplication.instance() or QApplication([])
    project=SubtitleProject(media=StudioMedia(path='fixture.mp4',duration_ms=120000),
        cues=[StudioCue(str(i),i*1000,i*1000+900,'正文') for i in range(120)])
    calls=[]
    def risks(_project):
        calls.append(1)
        return {str(i):dict(level=('suggested','high','confident')[i%3]) for i in range(120)}
    monkeypatch.setattr(table,'cached_review_risks',risks)
    model=table.CueTableModel(project)
    assert len(calls)==1 and model.rowCount()==120
    for status,total in (('priority',40),('critical',40),('issue',80)):
        calls.clear();model.set_filter(status)
        assert len(calls)==1 and model.rowCount()==total
