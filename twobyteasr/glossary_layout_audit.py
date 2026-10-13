"""Fixed glossary review audit, suitable for explicit freezing; never applies terms.

Call run(window, out) with a shown application window. out/checkpoint.json must
be an explicit local copied checkpoint. No source path or arbitrary code loader.
All snapshots and mutations are confined to the supplied test window and out.
"""
from pathlib import Path
import copy,hashlib,json
from collections import Counter

def run(window, out):
    ROOT=Path.cwd()
    OUT=Path(out).resolve();OUT.mkdir(parents=True,exist_ok=True)
    SOURCE=OUT/'checkpoint.json'
    from PySide6.QtWidgets import QApplication,QWidget,QPushButton,QLabel
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QFont
    from types import SimpleNamespace
    from twobyteasr.glossary_skill import SearchedTerm,TermDiff,is_core_recommendation
    from twobyteasr.glossary_skill_ui import GlossaryUpdateReviewDialog
    from twobyteasr import glossary_skill_ui as ui_module
    from twobyteasr.ui import ModalHost
    from twobyteasr.theme_manager import apply_theme
    app=QApplication.instance();original_host=getattr(window,'_modal_host',None)
    data=json.loads(SOURCE.read_text('utf8'));original_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    code_path=Path(ui_module.__file__)
    report={'scope':'production ModalHost + GlossaryUpdateReviewDialog, no application of candidates, no model/network','source':str(SOURCE),'source_sha256':original_hash,'real_candidate_count':len(data['candidates']),'requested_scale':window.devicePixelRatioF(),'states':[],'checks':[],'failures':[],'code_sha256':hashlib.sha256(code_path.read_bytes()).hexdigest() if code_path.is_file() else None,'code_path':str(code_path)}
    def save():(OUT/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    def settle():
     for _ in range(4):app.processEvents();QTest.qWait(30)
    def rect(widget,ancestor):
     p=widget.mapTo(ancestor,QPoint(0,0));return [p.x(),p.y(),widget.width(),widget.height()]
    def hit(owner,widget):
     point=widget.mapTo(owner,widget.rect().center());actual=owner.childAt(point)
     valid=actual is widget or actual is not None and widget.isAncestorOf(actual)
     return {'passed':bool(valid),'point':[point.x(),point.y()],'actual_class':type(actual).__name__ if actual else None,'actual_name':actual.objectName() if actual else None}
    def overlap(a,b):
     x=max(a[0],b[0]);y=max(a[1],b[1]);w=min(a[0]+a[2],b[0]+b[2])-x;h=min(a[1]+a[3],b[1]+b[3])-y
     return [x,y,max(0,w),max(0,h)]
    def record(dlg,owner,host,key):
     settle();widgets={'table':dlg.table,'detail_frame':dlg.detail_frame,'detail_toggle':dlg.detail_toggle,'apply':dlg.apply_button,'close':dlg.cancel_button,'bulk':dlg.select_none,'core':dlg.select_core,'search':dlg.search_box,'status':dlg.status_scroll}
     if dlg.detail.isVisible():widgets['detail']=dlg.detail
     if dlg.detail_summary.isVisible():widgets['detail_summary']=dlg.detail_summary
     item={'key':key,'owner_size':[owner.width(),owner.height()],'card':rect(host.card,owner),'dialog':rect(dlg,owner),'dpr':owner.devicePixelRatioF(),'rects':{k:rect(v,owner) for k,v in widgets.items()},'hits':{k:hit(owner,v.viewport() if k in {'table','detail'} else v) for k,v in widgets.items()},'intersections':{},'row_count':dlg.model.rowCount(),'detail_visible':dlg.detail.isVisible(),'detail_scroll_max':dlg.detail.verticalScrollBar().maximum(),'status_scroll_max':dlg.status_scroll.verticalScrollBar().maximum()}
     item['hits'].pop('status',None)
     viewport=dlg.status_scroll.viewport();panel=dlg.status_scroll.widget()
     item['status_content']={'viewport':rect(viewport,owner),'panel':rect(panel,owner),'panel_parent_is_viewport':panel.parentWidget() is viewport,'scroll_value':dlg.status_scroll.verticalScrollBar().value(),'children':[]}
     for child in panel.findChildren(QWidget):
      if isinstance(child,(QLabel,QPushButton)):
       item['status_content']['children'].append({'class':type(child).__name__,'text':child.text()[:200],'visible':child.isVisible(),'hidden':child.isHidden(),'rect':rect(child,viewport),'height_for_width':child.heightForWidth(child.width())})
     item['detail_summary_layout']={'height':dlg.detail_summary.height(),'height_for_width':dlg.detail_summary.heightForWidth(dlg.detail_summary.width()),'characters':len(dlg.detail_summary.text()),'line_spacing':dlg.detail_summary.fontMetrics().lineSpacing()}
     for left,right in [('table','detail_frame'),('table','apply'),('detail_frame','apply'),('detail_frame','close'),('status','table')]:item['intersections'][left+'/'+right]=overlap(item['rects'][left],item['rects'][right])
     failures=[k for k,r in item['intersections'].items() if r[2] and r[3]]
     failures += ['hit-'+k for k,v in item['hits'].items() if not v['passed']]
     head_labels=[c for c in item['status_content']['children'] if c['class']=='QLabel' and c['visible']][:2]
     for index,child in enumerate(head_labels):
      r=child['rect'];center_y=r[1]+r[3]/2
      if r[2]<50 or not 0<=center_y<viewport.height():failures.append('status-head-'+str(index)+'-not-readable-in-first-viewport')
     process_buttons=[b for b in panel.findChildren(QPushButton) if b.text()=='查看执行过程' and b.isVisible()]
     if process_buttons:
      process_button=process_buttons[0];r=rect(process_button,viewport)
      item['status_content']['process_hit']=hit(owner,process_button)
      if r[1]<0 or r[1]+r[3]>viewport.height() or not item['status_content']['process_hit']['passed']:failures.append('status-process-button-not-fully-reachable-in-first-viewport')
     if dlg.detail_summary.isVisible() and item['detail_summary_layout']['height_for_width']>dlg.detail_summary.height():failures.append('detail-summary-content-clipped')
     for k,r in item['rects'].items():
      if k=='status':continue
      if r[0]<0 or r[1]<0 or r[0]+r[2]>owner.width() or r[1]+r[3]>owner.height():failures.append('owner-clip-'+k)
     item['failures']=failures;path=OUT/(key+'.png');owner.grab().save(str(path));item['screenshot']=str(path)
     report['states'].append(item);report['failures'] += [{'state':key,'check':f} for f in failures];save()
    for size_name,requested in [('normal',(1460,920)),('short',(1180,650)),('narrow',(860,760))]:
     for dataset in ('real2034','stress2035'):
      rows=[TermDiff('new',term,checked_by_default=is_core_recommendation(term)) for term in [SearchedTerm(**r) for r in data['candidates']]]
      if dataset=='stress2035':
       stress=SearchedTerm(term='布局压力样本_长URL',category='机制',category_key='mechanic',priority='core',verification='catalog_verified',evidence='无空格描述'+('超长描述HASHabcdef0123456789'*260)+'<img src="https://example.invalid/do-not-load">',sources=({'url':'https://resources.download.minecraft.net/f2/'+('f22db18b03d23e406bdbe8df17ba6f2041035b5f'*90),'source_type':'official_catalog','registry_key':'block.minecraft.'+'a'*700,'task_id':'local-layout-stress-no-network','version':'26.3','language':'zh_cn'},))
       rows.append(TermDiff('new',stress,checked_by_default=False))
      owner=window;owner.resize(*requested);owner.setWindowTitle('2ByteASR 术语预览隔离验证')
      # The real MainWindow owns its host and consults it from resizeEvent.
      # Reuse that host, as ordinary dialogs do; never leave a deleted wrapper
      # on the window between size cases.
      host=original_host
      if host is None:
       host=ModalHost(owner);owner._modal_host=host;original_host=host
      result=dict(mode='full',task_id=data.get('task_id',''),diffs=rows,candidate_count=len(rows),service='grok_account',model='grok-4.7',elapsed_seconds=2.6,build_stats=dict(source_results=data['source_results'],catalogs=data['catalogs'],current_version=data.get('current_version',''),game_version_status=data.get('version_note',''),category_counts=dict(Counter(r.get('category','') for r in data['candidates'])),names_kept=len(data['candidates']),deterministic_count=len(data['candidates']),catalog_verified=len(data['candidates']),coverage_status='部分来源未完成；全游戏分母未知'),execution_events=[{'kind':'stage','payload':'实际2034候选checkpoint只读回放'}])
      dlg=GlossaryUpdateReviewDialog(owner,'我的世界',result,host.body);owner.show();host.show_content(dlg,title='联网更新预览 | 我的世界',size=(1100,760),min_size=(700,450));settle()
      target=next((i for i in range(dlg.model.rowCount()) if dataset=='stress2035' and dlg.model.row_identity(i)==stress.term),0)
      dlg.table.selectRow(target);dlg.table.scrollTo(dlg.model.index(target,1));settle()
      base=size_name+'-'+dataset
      record(dlg,owner,host,base+'-collapsed')
      QTest.mouseClick(dlg.detail_toggle,Qt.MouseButton.LeftButton);record(dlg,owner,host,base+'-expanded')
      if dataset=='stress2035':
       before=set(dlg.model._checked);current=dlg.detail.toPlainText();dlg.detail.verticalScrollBar().setValue(dlg.detail.verticalScrollBar().maximum());settle()
       report['checks'].append({'name':base+'-details-scroll-without-check-change','passed':before==dlg.model._checked and current==dlg.detail.toPlainText() and dlg.detail.verticalScrollBar().value()>0})
      # Actual row click and sorting/filtering on the production table, no apply.
      dlg.detail_toggle.setChecked(False);dlg.search_box.clear();dlg.table.scrollToTop();settle();index=dlg.model.index(0,dlg.model.COLUMN_TERM);p=dlg.table.visualRect(index).center();identity=dlg.model.row_identity(0);before=identity in dlg.model._checked
      QTest.mouseClick(dlg.table.viewport(),Qt.MouseButton.LeftButton,pos=p);settle();after=identity in dlg.model._checked
      report['checks'].append({'name':base+'-row-single-toggle','passed':before!=after})
      selected=set(dlg.model._checked);dlg.table.sortByColumn(dlg.model.COLUMN_TERM,Qt.SortOrder.DescendingOrder);settle();report['checks'].append({'name':base+'-sort-preserves-checked','passed':selected==dlg.model._checked})
      dlg.search_box.setText('钻石');settle();dlg.model.check_filtered(True);selected=set(dlg.model._checked);dlg.search_box.clear();settle();report['checks'].append({'name':base+'-filtered-bulk-survives-clear','passed':selected==dlg.model._checked})
      QTest.mouseClick(dlg.cancel_button,Qt.MouseButton.LeftButton);settle();report['checks'].append({'name':base+'-actual-close','passed':not host.isVisible()});save()
    report['source_unchanged']=hashlib.sha256(SOURCE.read_bytes()).hexdigest()==original_hash
    report['failures'] += [{'check':c['name']} for c in report['checks'] if not c['passed']]
    report['passed']=not report['failures'] and report['source_unchanged'];save();window._modal_host=original_host
    return report

def start(window, out):
    from PySide6.QtCore import QTimer
    from .theme_manager import apply_theme
    from .build_identity import load_build_identity
    import traceback
    def verify():
        try:
            apply_theme('grape')
            window.setMinimumSize(0,0)
            result=run(window,out)
            result.update(build=vars(load_build_identity()),completed=True)
        except Exception:
            result=dict(completed=False,passed=False,error=traceback.format_exc())
        (Path(out)/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
        window.result_exit_code=0 if result.get('passed') else 1
        window.close()
    QTimer.singleShot(3000,verify)
