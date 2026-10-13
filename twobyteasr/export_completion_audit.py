"""Opt-in completion checks on a just-published real source/frozen export."""
import ctypes
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolTip


def verify(ui, out):
    panel = ui.success_page
    output = ui._success_output
    receipt = dict(ui._last_job.completion_metadata)
    result = {'receipt': receipt, 'checks': {}, 'layouts': [], 'screenshots': []}
    def check(name, condition):
        result['checks'][name] = bool(condition)
    def pump(seconds=.15):
        end = time.perf_counter()+seconds
        while time.perf_counter() < end:
            QApplication.processEvents(); time.sleep(.005)
    def rect(widget):
        r = widget.rect().translated(widget.mapTo(panel.card, QPoint()))
        return [r.x(), r.y(), r.width(), r.height()]
    user32 = ctypes.windll.user32
    hwnd = int(ui.winId())
    user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    def shot(name):
        user32.SetWindowPos(hwnd,ctypes.c_void_p(-1),0,0,0,0,0x0001|0x0002|0x0010)
        ui.raise_(); ui.activateWindow(); pump(.08)
        from ctypes import wintypes
        bounds = wintypes.RECT()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(bounds))
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = ctypes.c_void_p
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        owner = user32.WindowFromPoint(wintypes.POINT(bounds.left+40,bounds.top+60))
        check(name+' owned HWND', int(user32.GetAncestor(owner,2) or 0)==hwnd)
        ui.screen().grabWindow(hwnd).save(str(out/(name+'.png')))
        result['screenshots'].append(name+'.png')
    try:
        expected = float(os.environ.get('TWOBYTEASR_COMPLETION_DPR','1.5'))
        result['dpr'] = ui.devicePixelRatioF()
        check('actual DPR',abs(result['dpr']-expected)<.02)
        check('receipt matches output',receipt.get('output_path')==str(output.resolve()))
        check('receipt has actual elapsed',receipt.get('elapsed_seconds',0)>0)
        check('receipt size matches file',receipt.get('size_bytes')==output.stat().st_size)
        rate=receipt.get('average_bitrate_bps')
        calculated=output.stat().st_size*8/receipt['duration_seconds']
        check('container bitrate validated',rate is not None and abs(rate-calculated)/calculated<=.01)
        check('real preview loaded',not panel.preview.image.isNull())
        available=ui.screen().availableGeometry()
        sizes=((min(1440,available.width()-24),min(830,available.height()-50)),
               (1040,min(760,available.height()-50)),(710,min(780,available.height()-50)))
        for label,size in zip(('wide','medium','narrow'),sizes):
            ui.resize(*size);ui.move(available.x()+8,available.y()+8);pump(.25)
            panel.scroll.verticalScrollBar().setValue(0);pump()
            layout={'label':label,'window':[ui.width(),ui.height()],
                    'card':[panel.card.width(),panel.card.height()],
                    'preview':rect(panel.preview),'path':rect(panel.path),
                    'play':rect(panel.play),'reveal':rect(panel.reveal),
                    'back':rect(panel.back),'again':rect(panel.again),
                    'info':rect(panel.info),
                    'scroll_max':panel.scroll.verticalScrollBar().maximum()}
            wide=ui.width()>=1000
            # 2026-10-08 (M13): result workspace hierarchy — play (primary)
            # above show-in-folder (secondary), both spanning the facts
            # column; back / export-again equal in the page header.
            check(label+' preview 16:9',abs(panel.preview.height()-panel.preview.width()*9/16)<=1)
            check(label+' primary height',56<=panel.play.height()<=64)
            check(label+' secondary below primary',rect(panel.reveal)[1]>rect(panel.play)[1]
                  and panel.reveal.height()<panel.play.height())
            a,b,info=rect(panel.play),rect(panel.reveal),layout['info']
            check(label+' actions span facts column',a[0]==b[0]==info[0] and a[2]==b[2]==info[2])
            check(label+' no horizontal scroll',panel.scroll.horizontalScrollBar().maximum()==0)
            if wide:
                p=layout['preview']
                check(label+' poster and facts share the top edge',abs(p[1]-info[1])<=2)
                # 2026-10-09 (M15): the two actions end on the poster's bottom edge.
                check(label+' actions end on the poster bottom',abs((b[1]+b[3])-(p[1]+p[3]))<=2)
            check(label+' navigation in header',rect(panel.back)[1]<0 and rect(panel.again)[1]<0)
            check(label+' secondary same form',panel.back.objectName()==panel.again.objectName() and panel.back.height()==panel.again.height())
            shot('completion-'+label)
            panel.scroll.ensureWidgetVisible(panel.again);pump()
            for button in (panel.play,panel.reveal,panel.back,panel.again,panel.copy):
                panel.scroll.ensureWidgetVisible(button);pump(.03)
                point=button.mapTo(panel.scroll.viewport(),button.rect().center())
                check(label+' reachable '+button.text(),panel.scroll.viewport().rect().contains(point))
            panel.scroll.ensureWidgetVisible(panel.again);pump()
            shot('completion-'+label+'-actions')
            result['layouts'].append(layout)
        ui.resize(*sizes[0]);pump(.25)
        panel.scroll.ensureWidgetVisible(panel.copy);pump()
        QTest.mouseClick(panel.copy,Qt.MouseButton.LeftButton)
        check('copy path',QApplication.clipboard().text()==str(output.parent))
        check('full name tooltip',panel.name.toolTip()==output.name)
        check('full path tooltip',panel.path.toolTip()==str(output.parent))
        check('long name elided','…' in panel.name.text())
        QToolTip.showText(panel.name.mapToGlobal(QPoint(4,panel.name.height())),panel.name.toolTip(),panel.name)
        pump();check('tooltip visible',QToolTip.isVisible());shot('completion-name-tooltip');QToolTip.hideText()
        with patch('twobyteasr.studio_export_ui.QDesktopServices.openUrl',return_value=False) as opened:
            panel.play.setFocus();QTest.keyClick(panel.play,Qt.Key.Key_Return);pump()
            check('Enter triggers one playback',opened.call_count==1)
            check('player launch failure visible',panel.error.isVisible() and '播放器' in panel.error.text())
        with patch('twobyteasr.processes.popen_hidden_subprocess',side_effect=OSError('audit unavailable')):
            QTest.mouseClick(panel.reveal,Qt.MouseButton.LeftButton)
            check('Explorer launch failure visible',panel.error.isVisible() and '资源管理器' in panel.error.text())
        # Invoke the production reveal and ask Explorer itself which item is selected.
        # The query emits one boolean; unrelated Explorer paths never leave the process.
        QTest.mouseClick(panel.reveal,Qt.MouseButton.LeftButton);pump(.8)
        from .processes import run_hidden_subprocess
        path_literal=str(output.resolve()).replace("'","''")
        script=("$selected=$false; $shell=New-Object -ComObject Shell.Application; "
                "foreach($w in $shell.Windows()){try{foreach($i in $w.Document.SelectedItems()){"
                "if($i.Path -eq '"+path_literal+"'){$selected=$true}}}catch{}}; "
                "if($selected){'true'}else{'false'}")
        explorer=run_hidden_subprocess(['powershell','-NoProfile','-NonInteractive','-Command',script],
            purpose='verify selected completed export in Explorer',capture_output=True,text=True,timeout=15)
        check('Explorer actually selected final file',explorer.stdout.strip()=='true')
        # Only this newly-created fixture is moved, then restored, to exercise missing-file feedback.
        moved=output.with_suffix(output.suffix+'.audit-moved')
        output.replace(moved)
        try:
            QTest.mouseClick(panel.play,Qt.MouseButton.LeftButton)
            check('moved output playback error',panel.error.isVisible() and '移动' in panel.error.text())
            QTest.mouseClick(panel.reveal,Qt.MouseButton.LeftButton)
            check('moved output reveal error',panel.error.isVisible() and '移动' in panel.error.text())
        finally:
            moved.replace(output)
        panel.error.hide()
        QTest.mouseClick(panel.again,Qt.MouseButton.LeftButton);pump()
        check('again opens export settings',ui.pages.currentWidget() is ui.setup_page)
        ui.pages.setCurrentWidget(panel);pump()
        back=[];ui.back_requested.connect(lambda:back.append(True))
        QTest.mouseClick(panel.back,Qt.MouseButton.LeftButton);pump()
        check('back to editing',len(back)==1)
        panel.play.setFocus();QTest.keyClick(panel.play,Qt.Key.Key_Escape);pump()
        check('Escape to editing',len(back)==2)
        result['passed']=all(result['checks'].values())
    finally:
        user32.SetWindowPos(hwnd,ctypes.c_void_p(-2),0,0,0,0,0x0001|0x0002|0x0010)
        (out/'completion-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
