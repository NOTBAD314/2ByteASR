"""Real Studio controls under their original timeline host, allocated by Qt."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLabel,QSplitter,QVBoxLayout,QWidget


def test_wrapped_actual_toolbar_parent_minimum_and_splitter_resize_roundtrip(tmp_path):
    from twobyteasr.design import theme_manager
    from twobyteasr.design.studio_theme import build_studio_qss
    from twobyteasr.studio.studio_ui import SubtitleStudioPage
    from twobyteasr.design.typography import application_font
    from twobyteasr.design.ui_theme import theme_definition
    app=QApplication.instance() or QApplication([])
    theme_manager.apply_application_theme(app,'grape');app.setFont(application_font())
    page=SubtitleStudioPage()
    # Populate the normal duration label; the first two groups almost fill a
    # narrow row. No media load, substitute controls or custom geometry calls.
    page.timeline_duration_label.setText('/ 1:07')
    bar=page._timeline_command_bar;host=bar.parentWidget();host.setParent(None)
    shell=QWidget();shell.setObjectName('subtitleStudio')
    shell.setStyleSheet(build_studio_qss(theme_definition('grape')))
    outer=QVBoxLayout(shell);outer.setContentsMargins(0,0,0,0)
    splitter=QSplitter(Qt.Vertical);outer.addWidget(splitter)
    upper=QLabel('Upper workspace');upper.setMinimumHeight(200)
    splitter.addWidget(upper);splitter.addWidget(host)
    snapshots=[]
    def settle():
        # Drain normal LayoutRequest/Polish/resize work. Never assign child
        # geometry or compare only the flow's own predicted height.
        for _ in range(4):app.processEvents()
    def inspect(name):
        settle()
        origin=bar.mapToGlobal(bar.rect().topLeft())
        groups=[]
        for group,widgets in zip(page._timeline_group_widgets,page._timeline_command_groups):
            point=group.mapToGlobal(group.rect().topLeft())-origin
            controls=[]
            for widget in widgets:
                if not widget.isVisible():continue
                local=widget.mapToGlobal(widget.rect().topLeft())-origin
                rect=[local.x(),local.y(),widget.width(),widget.height()]
                assert rect[0]>=0 and rect[1]>=0
                assert rect[0]+rect[2]<=bar.width() and rect[1]+rect[3]<=bar.height(),(name,rect,bar.size())
                controls.append(rect)
            groups.append(dict(role=group.property('commandGroup'),rect=[point.x(),point.y(),group.width(),group.height()],controls=controls))
        range_bar=page.project_range_bar
        # 2026-10-09 (M16): the in/out row left the toolbar (I/O marks are on
        # the ruler; the context menu names and clears the range).
        assert range_bar.parentWidget() is host
        assert range_bar.isHidden()
        result=dict(name=name,bar=[bar.width(),bar.height()],minimum_hint=[bar.minimumSizeHint().width(),bar.minimumSizeHint().height()],
            policy_hfw=bar.sizePolicy().hasHeightForWidth(),host_height=host.height(),host_minimum=host.minimumHeight(),
            groups=groups,splitter_sizes=splitter.sizes())
        snapshots.append(result);return result
    try:
        shell.resize(2048,1105);shell.show();splitter.setSizes([790,300])
        wide=inspect('wide-before')
        assert len({row['rect'][1] for row in wide['groups']})<=2
        shell.resize(980,700)
        narrow=inspect('narrow')
        # 2026-10-08: 声音诊断 / AI 断句 left the bar, so 980px wraps once.
        assert len({row['rect'][1] for row in narrow['groups']})>=2
        assert narrow['bar'][1]>wide['bar'][1]
        assert host.minimumHeight()>wide['host_minimum']
        for theme in ('warm','slate','grape'):
            theme_manager.apply_application_theme(app,theme)
            shell.setStyleSheet(build_studio_qss(theme_definition(theme)))
            current=inspect('narrow-'+theme)
            assert all(w.font().pixelSize()==13 for w in page._timeline_command_groups[3])
            assert current['bar'][1]>=narrow['bar'][1]
        shell.resize(2048,1105)
        restored=inspect('wide-restored')
        assert restored['bar']==wide['bar'] and restored['groups']==wide['groups']
        assert restored['splitter_sizes']==wide['splitter_sizes']
        assert restored['host_minimum']==wide['host_minimum']
        (tmp_path/'actual-parent-allocation.json').write_text(json.dumps(snapshots,ensure_ascii=False,indent=2),'utf8')
    finally:
        page.close_page();shell.close();page.close();shell.deleteLater();page.deleteLater();settle()
