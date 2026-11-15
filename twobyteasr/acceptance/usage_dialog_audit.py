"""Normal-entry Windows checks using only a temporary real SQLite ledger."""
from pathlib import Path
import csv,json,os,time,traceback
from datetime import datetime,timedelta,timezone

def start(window,output):
 from PySide6.QtCore import QTimer,Qt
 from PySide6.QtWidgets import QApplication,QPushButton
 from PySide6.QtTest import QTest
 def run():
  app=QApplication.instance();checks=[];page=None;dialog=None
  def settle(s=.12):
   end=time.monotonic()+s
   while time.monotonic()<end:app.processEvents();time.sleep(.005)
  def wait(test):
   end=time.monotonic()+40
   while not test() and time.monotonic()<end:settle(.03)
   if not test():raise TimeoutError('normal entry did not become ready')
  def check(name,ok,detail=None):
   checks.append(dict(name=name,passed=bool(ok),detail=detail))
   if not ok:raise AssertionError(name+': '+str(detail))
  def click(b):QTest.mouseClick(b,Qt.LeftButton);settle()
  try:
   from ..design.theme_manager import save_theme_key,apply_theme
   theme=os.environ.get('TWOBYTEASR_USAGE_THEME','sand');save_theme_key(theme);apply_theme(theme,app)
   window.resize(1440,900);window.open_studio_project(str(output/'fixture.2byteproj'))
   wait(lambda:window.built_page('studio') is not None and window.built_page('studio').project is not None)
   page=window.built_page('studio')
   wait(lambda:getattr(window,'_studio_loading_session',None) is None or not window._studio_loading_session.active)
   wait(lambda:getattr(page.video,'_startup_state','')=='READY');page.video.set_paused(True)
   from ..providers import usage_ledger as ledger
   db=output/'usage.sqlite3';os.environ['TWOBYTEASR_USAGE_DB']=str(db)
   now=datetime.now().astimezone().replace(hour=12,minute=0,second=0,microsecond=0)
   def row(i,task,project,stage,days=0,status='received',cost=('0.001','0.001'),label=''):
    value=dict(request_id='r'+str(i),at=(now-timedelta(days=days,minutes=i)).astimezone(timezone.utc).isoformat(),
     task_id=task,project_id=project,media_fingerprint='',stage=stage,model='offline-audit',status=status,
     cost=dict(known=status=='received',currency='USD',low=cost[0],high=cost[1]),
     usage=dict(input_tokens=1000,output_tokens=200,cached_input_tokens=100) if status=='received' else None)
    if label:value['task_label']=label
    return value
   pid=page.project.project_id
   rows=[row(0,'t1',pid,'translation',label='第一话.mp4'),row(1,'t1',pid,'translation',status='usage_unknown'),
    row(2,'t1',pid,'sentence_grouping',cost=('0.002','0.004')),row(3,'t2',pid,'proofread',days=3),
    row(4,'t3','other','translation',days=10),row(5,'','','connection_test',days=1,status='rate_limited'),
    row(6,'t4','other','other_step',days=2),row(7,'t5',pid,'translation',days=4,status='cancelled')]
   for r in rows:ledger.enqueue(r,db)
   check('isolated ledger flushed',ledger.flush() and len(ledger.read_rows(db))==8)
   page.studio_usage_button.click();settle();dialog=page._usage_dialog
   wait(lambda:dialog._loaded_once and not dialog._loading)
   check('Studio usage entry opens real modeless dialog',dialog.isVisible() and not dialog.isModal())
   from .candy_prompt_audit import check_chrome
   check_chrome(dialog, check, settle)
   check('project context and unknown costs preserved',dialog.scope=='project' and len(dialog.visible_rows)==5 and '2 次用量未知' in dialog.badge.text,dialog.badge.text)
   def scope(key):
    index=next(i for i in range(dialog.tasks.count()) if dialog.tasks.item(i).data(Qt.UserRole)==key)
    item=dialog.tasks.item(index);dialog.tasks.scrollToItem(item);settle()
    QTest.mouseClick(dialog.tasks.viewport(),Qt.LeftButton,pos=dialog.tasks.visualItemRect(item).center());settle()
   scope('task:t1')
   check('real task click updates cost interval',len(dialog.visible_rows)==3 and '0.0030–0.0050' in dialog.money.text(),dialog.money.text())
   check('new and legacy task names remain readable',dialog.titles['t1']=='第一话.mp4' and dialog.titles['t3'].startswith('任务 '),dialog.titles)
   dialog.grab().save(str(output/'01-task.png'))
   def chip(prefix):return next(b for b in dialog.findChildren(QPushButton,'usageChip') if b.isVisible() and b.text().startswith(prefix))
   click(chip('翻译'));check('step click filters rows',[r['request_id'] for r in dialog.visible_rows]==['r0','r1'])
   click(dialog.todo);check('problem and step filters stack',[r['request_id'] for r in dialog.visible_rows]==['r1'])
   check('filtered unknown total is never shown as zero','未知' in dialog.money.text() and '1 次' in dialog.facts.text(),dialog.money.text())
   dialog.table.selectRow(0);settle()
   check('unknown selection explains missing cost','不算作零' in dialog.strip_text.text())
   click(dialog.copy_button);check('copy preserves raw request',json.loads(app.clipboard().text())['request_id']=='r1')
   click(dialog.todo);click(chip('翻译'))
   scope('all');check('all scope includes every request',len(dialog.visible_rows)==8)
   click(dialog.range_buttons['today']);check('today narrows the visible ledger',len(dialog.visible_rows)==3)
   click(dialog.range_buttons['7']);check('seven days includes recent requests',len(dialog.visible_rows)==7)
   cal=dialog.calendar
   a=cal._column(41).center().toPoint();b=cal._column(43).center().toPoint()
   QTest.mousePress(cal,Qt.LeftButton,pos=a);QTest.mouseMove(cal,b,100);QTest.mouseRelease(cal,Qt.LeftButton,pos=b);settle()
   check('Windows mouse drag selects date interval',dialog.span==(3,1) and {r['request_id'] for r in dialog.visible_rows}=={'r3','r5','r6'},dict(span=dialog.span,rows=[r['request_id'] for r in dialog.visible_rows]))
   dialog.grab().save(str(output/'02-dates.png'))
   click(dialog.range_buttons['all']);check('all restores old records',len(dialog.visible_rows)==8)
   for width,height in ((1200,760),(960,620)):
    margin=dialog.chrome.window.margin()
    dialog.resize(width+2*margin,height+2*margin);settle(.25)
    buttons=[b for b in dialog.findChildren(QPushButton) if b.isVisible()]
    outside=[b.text() for b in buttons if not dialog.rect().contains(b.mapTo(dialog,b.rect().topLeft())) or not dialog.rect().contains(b.mapTo(dialog,b.rect().bottomRight()))]
    check('controls fit requested width '+str(width),dialog.chrome.root.width()==width and not outside,dict(content=dialog.chrome.root.width(),outer=dialog.width(),outside=outside))
    boxes=[(b.text(),b.geometry().translated(b.parentWidget().mapTo(dialog,b.parentWidget().rect().topLeft()))) for b in buttons]
    overlap=[(a,c) for i,(a,b) in enumerate(boxes) for c,d in boxes[i+1:] if b.intersects(d)]
    check('filter controls do not overlap at '+str(width),not overlap,overlap)
    dialog.grab().save(str(output/('03-width-'+str(width)+'.png')))
   path=Path(dialog.export_csv(str(output/'usage.csv')))
   with path.open(encoding='utf-8-sig',newline='') as f:export=list(csv.reader(f))
   unknown=next(r for r in export[1:] if r[-1]=='r1')
   check('CSV includes filtered rows and blank unknown cost',len(export)==9 and unknown[8:11]==['','',''])
   click(dialog.refresh_button);wait(lambda:not dialog._loading)
   check('refresh retains range and scope',dialog.scope=='all' and len(dialog.visible_rows)==8)
   same=dialog;page.studio_usage_button.click();settle();check('reopen focuses one dialog',page._usage_dialog is same)
   dialog.close();settle();page.studio_usage_button.click();settle();dialog=page._usage_dialog;wait(lambda:dialog._loaded_once)
   check('closed view reopens from ledger',dialog.isVisible() and len(dialog.rows)==8)
   dialog.close();settle();page.undo_stack.setClean()
   result=dict(passed=True,checks=checks,checks_passed=len(checks),theme=theme,fixture='isolated SQLite; no API calls');code=0
  except Exception:
   result=dict(passed=False,checks=checks,error=traceback.format_exc());code=1
   for w in app.topLevelWidgets():
    if w.isVisible():w.grab().save(str(output/('failure-'+w.metaObject().className()+'.png')))
  (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
  if page is not None:page.undo_stack.setClean()
  app.exit(code)
 QTimer.singleShot(600,run)
