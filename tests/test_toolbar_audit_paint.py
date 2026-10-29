"""Audit pixel gates inspect unmodified captures and actual ancestor state."""
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget,QPushButton,QVBoxLayout
from tests.test_storage_maintenance_ui import qapp
from twobyteasr.acceptance.toolbar_scope_audit import pixmap_evidence,widget_paint_state,capture_raw_widgets,pixel_gate_results


def test_flat_capture_is_not_visual_evidence_but_real_controls_are(qapp,tmp_path):
    flat=QPixmap(200,60);flat.fill('#141019')
    assert not pixmap_evidence(flat)['non_flat']
    window=QWidget();window.setObjectName('ownedPixelAudit')
    layout=QVBoxLayout(window);button=QPushButton('实际工具栏 / Play');layout.addWidget(button)
    window.resize(400,100);window.show();qapp.processEvents()
    pixmap=window.grab();evidence=pixmap_evidence(pixmap)
    assert evidence['non_flat'] and evidence['width']>0 and evidence['height']>0
    assert pixmap.save(str(tmp_path/'actual-controls.png'))
    assert evidence==pixmap_evidence(pixmap)


def test_ancestor_update_and_visibility_probe_is_readonly(qapp):
    window=QWidget();window.setObjectName('ownedUpdateAncestor')
    button=QPushButton('Actual child',window);button.setObjectName('ownedChild')
    window.resize(300,90);window.show();qapp.processEvents()
    visible=widget_paint_state(button)
    assert visible['window_visible'] and not visible['window_minimized']
    assert all(node['updates_enabled'] for node in visible['ancestors'])
    window.setUpdatesEnabled(False)
    disabled=widget_paint_state(button)
    assert not button.updatesEnabled() and not window.updatesEnabled()
    assert disabled['ancestors'][-1]['object_name']=='ownedUpdateAncestor'
    assert all(node['updates_disabled'] for node in disabled['ancestors'])
    window.setUpdatesEnabled(True);window.hide()
    hidden=widget_paint_state(button)
    assert not hidden['window_visible'] and not any(node['visible'] for node in hidden['ancestors'])


def test_flat_whole_window_does_not_suppress_actual_bar_and_range_captures(qapp,tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    flat=QPixmap(200,60);flat.fill('#141019')
    bar=QPushButton('实际工具栏');range_bar=QPushButton('入点 / 出点')
    bar.resize(200,40);range_bar.resize(200,40);bar.show();range_bar.show();qapp.processEvents()
    result=capture_raw_widgets(dict(window=SimpleNamespace(grab=lambda:flat),bar=bar,range_bar=range_bar),tmp_path,'all-before-check')
    assert all(row['saved'] and Path(row['path']).is_file() for row in result.values())
    assert not result['window']['non_flat'] and result['bar']['non_flat'] and result['range_bar']['non_flat']
    assert result['window']['sha256']==pixmap_evidence(flat)['sha256']


def test_only_three_theme_roots_are_explicit_capture_limits_and_controls_stay_strict():
    from copy import deepcopy
    captures={key:dict(non_flat=key!='window',path=key+'.png') for key in ('window','bar','range_bar')}
    for name in ('01-direct','02-settings-return','03-text-tools-return','04-completion-replay-return','06-narrow','07-wide-restored'):
        checks,limitations=pixel_gate_results(name,captures)
        assert len(checks)==3 and not checks[0]['passed'] and not limitations
    for name in ('05-theme-warm','05-theme-slate','05-theme-grape'):
        checks,limitations=pixel_gate_results(name,captures)
        assert len(checks)==2 and all(row['passed'] for row in checks)
        assert len(limitations)==1 and not limitations[0]['whole_window_visually_verified']
        assert limitations[0]['path']=='window.png'
        for key in ('bar','range_bar'):
            broken=deepcopy(captures);broken[key]['non_flat']=False
            strict,_=pixel_gate_results(name,broken)
            assert not all(row['passed'] for row in strict)
