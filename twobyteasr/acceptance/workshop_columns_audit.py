"""Normal-entry table geometry across lazy creation and application zoom."""
import json,os,sys,time,traceback

def start(window,out):
    from PySide6.QtCore import QPoint,Qt,QTimer
    from PySide6.QtWidgets import QApplication,QLabel,QScrollArea
    from ..design.theme_manager import apply_theme
    from ..app.ui_zoom import px,effective_factor,zoom_factor,zoom_percent
    from ..design.ui_navigation import SIDEBAR_WIDTH
    from ..i18n import current_language,translate,save_language,apply_ui_language
    app=QApplication.instance();checks=[];geometry=[]
    def check(name,value,detail=None):checks.append(dict(name=name,passed=bool(value),detail=detail))
    def settle(seconds=.15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:app.processEvents();time.sleep(.005)
    def wait(fn):
        end=time.monotonic()+20
        while not fn() and time.monotonic()<end:settle(.03)
        if not fn():raise RuntimeError('Window content not ready')
    def rect(widget,host):
        p=widget.mapTo(host,QPoint());return [p.x(),p.y(),widget.width(),widget.height()]
    def measure(page,tag):
        scroll=page.findChild(QScrollArea,'workshopScroll');host=scroll.widget()
        expected_factor=zoom_factor()
        check(tag+' workshop follows user zoom',abs(effective_factor(page)-expected_factor)<.0001,dict(user_percent=zoom_percent(),effective_factor=effective_factor(page),page_width=page.width()))
        check(tag+' home and workshop share zoom',effective_factor(page)==effective_factor(window))
        if page.sidebar.isVisible():
            check(tag+' shared sidebar scale',page.sidebar.width()==round(SIDEBAR_WIDTH*expected_factor),dict(actual=page.sidebar.width(),expected=round(SIDEBAR_WIDTH*expected_factor)))
        names={'language':'支持语言','accuracy':'准确度','speed':'速度','action':'操作'}
        heads={key:next(w for w in page.list_header.findChildren(QLabel) if w.text()==translate(text,current_language())) for key,text in names.items()}
        cells={key:rect(w,host) for key,w in heads.items()};rows=[]
        for wrapper in page._cards.values():
            card=wrapper.__dict__.get('_card')
            if card is None or wrapper.isHidden():continue
            row=dict(key=card.model.key,last_sync=getattr(card,'_column_sync_sample',None),cell_factors=dict(language=effective_factor(card.language_row),metrics=effective_factor(card.metrics_host),action=effective_factor(card.action_host)),scope_factor=effective_factor(card),page_factor=effective_factor(page),frame=rect(card,host),language=rect(card.language_row,host),accuracy=rect(card.accuracy_bar,host),speed=rect(card.speed_bar,host),action=rect(card.action_host,host))
            for key in names:
                if key in ('accuracy','speed') and card.metrics_host.isHidden():continue
                actual=row[key];expected=cells[key]
                check(tag+' '+card.model.key+' '+key+' aligned',abs(actual[0]-expected[0])<=1 and abs(actual[2]-expected[2])<=1,dict(actual=actual,header=expected))
            shown={code:b for code,b in card.language_row.badges.items() if not b.isHidden()}
            badges=[rect(b,host) for b in shown.values()]
            row['badges']=badges
            for i,b in enumerate(badges):
                check(tag+' '+card.model.key+' badge '+str(i)+' contained',b[0]>=row['language'][0] and b[0]+b[2]<=row['language'][0]+row['language'][2]+1)
            for code,badge in shown.items():
                check(tag+' '+card.model.key+' '+code+' text fits',badge.fontMetrics().horizontalAdvance(badge.text())+px(18,card)+2<=badge.width(),dict(text=badge.text(),width=badge.width()))
            if card.metrics_host.isHidden():
                metrics=rect(card.metrics_host,host)
                check(tag+' '+card.model.key+' empty metric slots retained',abs(metrics[0]-cells['accuracy'][0])<=1 and abs(metrics[2]-(cells['speed'][0]+cells['speed'][2]-cells['accuracy'][0]))<=1)
            check(tag+' '+card.model.key+' card fits viewport',row['frame'][0]>=0 and row['frame'][0]+row['frame'][2]<=host.width()+1)
            rows.append(row)
        check(tag+' materialized rows exist',len(rows)>=2)
        content=scroll.parentWidget()
        check(tag+' list extends to left',scroll.x()<=1,scroll.x())
        check(tag+' list extends to right',content.width()-(scroll.x()+scroll.width())<=1,dict(content=content.width(),scroll=scroll.geometry().getRect()))
        if page._responsive_detail.isVisible():
            gap=page._responsive_detail.mapTo(page,QPoint()).x()-(scroll.mapTo(page,QPoint()).x()+scroll.width())
            check(tag+' scrollbar beside detail',0<=gap<=4, gap)
        geometry.append(dict(tag=tag,headers=cells,rows=rows,viewport=scroll.viewport().width(),window_width=window.width(),page_width=page.width(),user_percent=zoom_percent(),reading_factor=effective_factor(page),sidebar_width=page.sidebar.width()))
    def run():
        error=None
        try:
            window._ensure_recognition_page();window._return_to_settings();window.resize(3800,1600)
            window._open_model_workshop();page=window.workshop_page;wait(lambda:page._ui_built and len(page._cards)>5);settle(.4)
            measure(page,'cold-100');check('screenshot cold-100',window.grab().save(str(out/'cold-100.png')))
            app._ui_zoom_controller.request(120);settle(.55)
            scroll=page.findChild(QScrollArea,'workshopScroll')
            quick=os.environ.get('TWOBYTEASR_COLUMNS_QUICK')=='1'
            for theme in (('warm',) if quick else ('warm','grape')):
                apply_theme(theme,app);settle(.15)
                cases=((3800,100),(2200,150),(1920,100)) if quick else ((3800,100),(1920,100),(1366,100),(2000,120),(2200,150),(3800,100))
                for width,zoom in cases:
                    window.resize(min(width,window.screen().availableGeometry().width()),min(1600 if width==3800 else 1100,window.screen().availableGeometry().height()));app._ui_zoom_controller.request(zoom);settle(.55)
                    for role in (('primary',) if quick else ('primary','timeline','review','api')):
                        page._set_role(role);settle(.18)
                        for position in (0,scroll.verticalScrollBar().maximum(),0):
                            scroll.verticalScrollBar().setValue(position);settle(.25)
                        for index,wrapper in enumerate(w for w in page._cards.values() if not w.isHidden() and w.__dict__.get('_card') is not None):
                            card=wrapper._card
                            if index>=3:break
                            card.set_action_state('取消使用' if index==0 else '使用',True)
                            card.set_selected(index==0)
                            if card.model.api_preset:
                                card.sync_configure_button('selected');card.set_state_badge('已配置','ready')
                            else:
                                card.set_uninstall_available(True);card.set_state_badge('已安装','ready')
                        settle(.1)
                        tag=f'{theme}-{width}-{zoom}-{role}'
                        measure(page,tag)
                        if role=='primary':check('screenshot '+tag,window.grab().save(str(out/(tag+'.png'))))
                    if theme=='warm' and zoom==100:
                        window._return_to_settings();settle(.2)
                        check('screenshot home '+tag,window.grab().save(str(out/(f'home-{width}-100.png'))))
                        window._open_model_workshop();settle(.25)
                        check(tag+' reentry retains user scale',effective_factor(page)==zoom/100.)
            save_language('en');apply_ui_language(window,'en');app._ui_zoom_controller.apply_all();settle(.4)
            page._set_role('primary');settle(.25);measure(page,'english-100')
            check('screenshot english',window.grab().save(str(out/'english-100.png')))
            save_language('zh');apply_ui_language(window,'zh')
            app._ui_zoom_controller.request(100);settle(.25)
        except Exception:error=traceback.format_exc();(out/'audit-error.txt').write_text(error,'utf8')
        result=dict(passed=not error and bool(checks) and all(x['passed'] for x in checks),checks=checks,geometry=geometry,checks_passed=sum(x['passed'] for x in checks),error=error,executable=sys.executable,frozen=bool(getattr(sys,'frozen',False)))
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        app.exit(0 if result['passed'] else 1)
    QTimer.singleShot(600,run)
