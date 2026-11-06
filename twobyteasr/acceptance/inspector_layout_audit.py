"""Normal-window geometry and text audit for the inspector and shared picker."""
from __future__ import annotations
import json
from pathlib import Path


def run(a,window,out):
    from PySide6.QtCore import QPoint,QRectF,Qt,QTimer
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QAbstractButton,QAbstractSpinBox,QComboBox,QLabel,QScrollArea,QToolButton,QWidget,QPushButton,QStyle,QStyleOptionButton
    p=a.page;app=QApplication.instance();out=Path(out)
    window.resize(1440,900);p._set_major_panel_visible('context',True);p.context_drawer.setCurrentIndex(1)
    root=p.context_drawer.widget(1).widget()
    for header in root.findChildren(QToolButton,'styleSectionHeader'):
        if header.isVisibleTo(root):header.setChecked(True)
    yield .3
    fields=('style_scope','style_preset','style_font','style_font_size','style_fill_swatch','style_outline_swatch',
        'style_back_swatch','style_shadow_swatch','style_glow_swatch','style_alignment','style_position_x')
    facts=[]
    for width in (360,440,640):
        total=p.upper_splitter.width();p.upper_splitter.setSizes([280,max(200,total-280-width),width]);yield .2
        controls={name:getattr(p,name) for name in fields}
        row=dict(requested=width,drawer=p.context_drawer.width(),root=root.width(),dpr=window.devicePixelRatioF(),
            controls={name:dict(x=w.mapTo(root,QPoint()).x(),width=w.width(),height=w.height(),visible=w.isVisibleTo(root)) for name,w in controls.items()},
            labels=[dict(text=w.text(),x=w.mapTo(root,QPoint()).x(),width=w.width(),extra=extra) for w,extra in p._style_label_column._labels])
        overflow=[]
        for widget in root.findChildren(QWidget):
            if not isinstance(widget,(QAbstractButton,QAbstractSpinBox,QComboBox)):continue
            if not widget.isVisibleTo(root) or widget.parentWidget() is None:continue
            parent=widget.parentWidget()
            if not parent.rect().contains(widget.geometry()):
                overflow.append(dict(name=widget.objectName(),cls=type(widget).__name__,text=widget.text() if isinstance(widget,QAbstractButton) else '',
                    rect=widget.geometry().getRect(),parent=[parent.objectName(),parent.width(),parent.height()]))
        selected=p.style_scope.findData('selected')
        original_label=p.style_scope._items[selected][0]
        p.style_scope.setItemText(selected,'已选择 6962 条字幕')
        yield .08
        row['large_scope']=[dict(text=b.text(),rect=b.geometry().getRect()) for b in p.style_scope._buttons]
        a.check('large selection labels stay inside '+str(width),all(p.style_scope.rect().contains(b.geometry()) and QFontMetrics(b.font()).horizontalAdvance(b.text())+14<=b.width() for b in p.style_scope._buttons))
        p.style_scope.setItemText(selected,original_label)
        row['overflow']=overflow;facts.append(row)
        a.check('primary fields share a control column '+str(width),len({v['x'] for v in row['controls'].values() if v['visible']})==1)
        a.check('labels align against their fields '+str(width),len({v['x']+v['width'] for v in row['labels']})==1)
        p.context_panel.grab().save(str(out/f'inspector-layout-{width}.png'))
    from ..app.ui_zoom import zoom_percent
    a.result['ui_zoom_percent']=zoom_percent()
    a.result['inspector_layout']=facts
    (out/'inspector-layout.json').write_text(json.dumps(facts,ensure_ascii=False,indent=2),'utf8')
    a.check('inspector controls stay within their containers',not any(row['overflow'] for row in facts))
    # Each property editor is opened from its actual swatch. Validate every
    # visible button/number and all segmented-selection positions inside it.
    p.upper_splitter.setSizes([280,700,440]);yield .2
    result={};a.timer.stop()
    def drive():
        dialog=QApplication.activeModalWidget()
        if dialog is None:QTimer.singleShot(40,drive);return
        try:
            from ..design.fill_picker import PillSegment,PillField
            checks=[]
            for mode in (0,1,2):
                dialog.mode_combo.setCurrentIndex(mode)
                app.processEvents()
                for segment in dialog.findChildren(PillSegment):
                    if not segment.isVisibleTo(dialog):continue
                    for index in range(segment.count()):
                        button=segment.button(index)
                        segment.setCurrentIndex(index)
                        checks.append(dict(kind='segment',text=button.text(),inside=segment.rect().contains(button.geometry()),
                            pill=segment._pill==QRectF(button.geometry()),width=button.width(),text_width=QFontMetrics(button.font()).horizontalAdvance(button.text())))
                        option=QStyleOptionButton();button.initStyleOption(option)
                        area=button.style().subElementRect(QStyle.SE_PushButtonContents,option,button)
                        required=QFontMetrics(button.font()).horizontalAdvance(button.text())+(button.iconSize().width()+4 if not button.icon().isNull() else 0)
                        checks.append(dict(kind='button_text',text=button.text(),inside=required<=area.width() and QFontMetrics(button.font()).height()<=area.height(),pill=True,needed=required,available=area.width()))
                for field in dialog.findChildren(PillField):
                    if not field.isVisibleTo(dialog):continue
                    for child in field.findChildren(QWidget):
                        if not isinstance(child,(QLabel,QAbstractSpinBox,QComboBox)):continue
                        if child.parentWidget() is field and child.isVisibleTo(dialog):
                            checks.append(dict(kind='field',text=child.text() if isinstance(child,QLabel) else '',inside=field.rect().contains(child.geometry()),pill=True))
            for spin in dialog.findChildren(QAbstractSpinBox):
                if not spin.isVisibleTo(dialog):continue
                edit=spin.lineEdit()
                values=[spin.textFromValue(spin.minimum()),spin.textFromValue(spin.maximum())]
                needed=max(QFontMetrics(edit.font()).horizontalAdvance(t) for t in values)
                checks.append(dict(kind='numeric_extremes',text=values,inside=needed<=edit.contentsRect().width(),pill=True,needed=needed,available=edit.contentsRect().width()))
            for button in dialog.findChildren(QAbstractButton):
                if not button.isVisibleTo(dialog) or button.parentWidget() is None:continue
                checks.append(dict(kind='button_frame',text=button.text(),name=button.objectName(),cls=type(button).__name__,rect=button.geometry().getRect(),parent=[button.parentWidget().objectName(),button.parentWidget().width(),button.parentWidget().height()],inside=button.parentWidget().rect().contains(button.geometry()),pill=True))
            result['checks']=checks
            result['passed']=all(c['inside'] and c['pill'] for c in checks)
            dialog.grab().save(str(out/'picker-layout.png'))
            dialog.reject()
        except Exception:
            import traceback
            result['error']=traceback.format_exc();dialog.reject()
    QTimer.singleShot(100,drive)
    try:p._open_style_color_dialog(p.style_outline_color)
    finally:a.timer.start()
    a.result['picker_layout']=result
    a.check('picker segments and numeric fields remain within frames',result.get('passed',False))
    # Popup surfaces clamp to the actual screen, with the selected entry intact.
    p.style_layer.showPopup();yield .15
    popup=p.style_layer.view().window()
    bounds=popup.frameGeometry();screen=popup.screen().availableGeometry()
    a.result['layer_popup']=dict(frame=bounds.getRect(),screen=screen.getRect())
    a.check('language layer popup stays on screen',screen.contains(bounds))
    p.style_layer.hidePopup()
