"""Normal-window checks of VM2 menu, search sheet, letter and speaker cards."""
from __future__ import annotations
import json, os, sys, time, traceback
from pathlib import Path
from unittest.mock import patch

def start(window, output):
 from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, QItemSelectionModel
 from PySide6.QtTest import QTest
 from PySide6.QtWidgets import QApplication, QLabel, QPushButton
 from ..design.theme_manager import apply_theme
 from ..glossary import multilingual_terms as m, multilingual_terms_ui as terms
 from ..glossary.name_search_sheet import NameSearchSheet
 from .blank_project_audit import _capture
 app=QApplication.instance();output=Path(output)
 result=dict(passed=False,checks=[],screenshots=[],dpr=window.devicePixelRatioF(),scope='Normal MainWindow with private data; no paid search/model calls or physical DPI claim.')
 def check(name,value,detail=None):
  result['checks'].append(dict(name=name,passed=bool(value),detail=detail))
  if not value:raise AssertionError(name+': '+str(detail))
 def settle(seconds=.15):
  end=time.monotonic()+seconds
  while time.monotonic()<end:app.processEvents();time.sleep(.005)
 def wait(predicate,seconds=15):
  end=time.monotonic()+seconds
  while not predicate() and time.monotonic()<end:settle(.02)
  check('wait for ready visible state',predicate())
 def shot(widget,name):
  p=output/(name+'.png');_capture(widget,p)
  check('captured '+name,p.is_file() and p.stat().st_size>1000);result['screenshots'].append(str(p))
 def fits(widget,label):
  problems=[]
  for child in widget.findChildren(QLabel)+widget.findChildren(QPushButton):
   if not child.isVisible() or child.window()!=widget:continue
   a=child.mapTo(widget,QPoint());b=child.mapTo(widget,child.rect().bottomRight())
   if not widget.rect().contains(a) or not widget.rect().contains(b):problems.append([child.objectName(),'outside'])
   if isinstance(child,QLabel) and child.wordWrap() and child.height()+2<child.heightForWidth(child.width()):problems.append([child.objectName(),'clipped height',child.height(),child.heightForWidth(child.width())])
  check(label+' contains readable text and controls',not problems,problems)
 def contrast(a,b):
  from PySide6.QtGui import QColor
  def lum(v):
   c=QColor(v);rgb=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in (c.redF(),c.greenF(),c.blueF())]
   return sum(x*y for x,y in zip(rgb,(.2126,.7152,.0722)))
  x,y=sorted((lum(a),lum(b)));return (y+.05)/(x+.05)
 class Shows(QObject):
  def __init__(self):super().__init__();self.flash=[];self.drawer_events=[];self.drawer=None
  def eventFilter(self,obj,event):
   if event.type()==QEvent.Type.Show and isinstance(obj,QPushButton) and obj.isWindow():self.flash.append(obj.objectName())
   if obj is self.drawer and event.type() in (QEvent.Type.Show,QEvent.Type.Hide):self.drawer_events.append(int(event.type()))
   return False
 tracker=Shows();app.installEventFilter(tracker)

 def run():
  try:
   check('private configuration root',Path(os.environ['TWOBYTEASR_TEST_ROOT']).resolve().is_relative_to(output))
   window.showNormal();window.resize(1440,900);window._return_to_settings();settle(.5)
   window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))
   from ..app.support_letter import letter_colors, StampButton, _PaintedText
   from ..app import support_entry
   opened=[]
   with patch.object(support_entry.QDesktopServices,'openUrl',side_effect=lambda u:opened.append(u.toString()) or True):
    for theme in ('warm','grape'):
     apply_theme(theme,app);settle(.2);window.support_button.click();settle(.3)
     dialog=window._support_entry_dialog
     check('letter opens from home '+theme,dialog is not None and dialog.isVisible())
     colors=letter_colors();ratio=contrast(colors['ink'],colors['paper'])
     check('letter text contrast '+theme,ratio>=4.5,ratio)
     check('stamp buttons retained '+theme,len(dialog.channel_buttons)==2 and all(isinstance(b,StampButton) for b in dialog.channel_buttons))
     for language in ('zh','en','ja'):
      window.language_combo.setCurrentIndex(window.language_combo.findData(language));dialog.resize(dialog.minimumWidth(),dialog.height());settle(.25)
      fits(dialog,theme+'-'+language+' letter');shot(dialog,'letter-'+theme+'-'+language)
      for label in dialog.findChildren(_PaintedText):check('painted paragraph fits '+language,label.height()+2>=label.heightForWidth(label.width()))
     dialog.hide_button.click();settle(.2);confirmation=dialog._confirmation
     check('hide confirmation is reversible',confirmation is not None and confirmation.isVisible() and not support_entry.support_entry_hidden())
     fits(confirmation,theme+' confirmation');shot(confirmation,'letter-'+theme+'-confirmation');confirmation.cancel_button.click();settle(.1)
     check('cancel preserves support entry',window.support_button.isVisible() and not support_entry.support_entry_hidden())
     if theme=='grape':
      for button in dialog.channel_buttons:button.click()
     dialog.close_button.click();settle(.2)
    check('only deliberate support links requested',opened==[u for _,u in support_entry.SUPPORT_CHANNELS],opened)
   window.language_combo.setCurrentIndex(window.language_combo.findData('zh'))
   legacy=window.legacy;library=legacy.create_learned_content('本次菜单窗口验收',create_new=True)
   rows=[m.concept('验收概念'+str(i),'zh-Hans',category='角色') for i in range(45)]
   m.mutate(legacy,library,lambda dest,entry:dest.extend(rows));ids=[c['id'] for c in m.read_concepts(legacy,library)]
   window._manage_terms();settle(.3);page=window.term_library_page._ensure_library()
   page.add_game_item('本次菜单窗口验收',select=True,library_id=library)
   wait(lambda:page._library_key()==library and page._term_model.rowCount()==45)
   page.term_display_language.setCurrentIndex(page.term_display_language.findData('ja'));settle(.3)
   check('missing-name strip offers lookup',page.name_search_strip_button.isVisible() and '日文' in page.name_search_strip_button.text())
   before=m.read_concepts(legacy,library)
   caps=[('offline',dict(provider_search=False,tool_search=False,reason='owned offline fixture',transport='openai_compatible_chat',model='fixture')),
         ('deepseek',dict(provider_search=False,tool_search=True,reason='owned DeepSeek fixture',transport='openai_compatible_chat',model='fixture')),
         ('provider',dict(provider_search=True,tool_search=False,reason='owned provider fixture',transport='grok_cli',model='fixture'))]
   for theme in ('warm','grape'):
    apply_theme(theme,app);settle(.2)
    for label,cap in caps:
     with patch('twobyteasr.glossary.glossary_skill.detect_search_capability',return_value=cap):
      page._refresh_ai_capability_label();page.ai_popup.show_below();settle(.2)
      check('plain menu label',page.ai_menu_button.text().startswith('AI 帮忙'))
      entries=[page.ai_update_button,page.ai_full_button,page.smart_build_button,page.name_completion_button,page.name_review_button]
      # Current named buttons remain the production task objects.
      positions=[page.ai_popup._layout.indexOf(b) for b in entries]
      check('menu groups retain task order '+label,positions==sorted(positions) and min(positions)>=0,positions)
      fits(page.ai_popup,theme+' '+label+' menu');shot(page.ai_popup,'menu-'+theme+'-'+label)
      check('AI bar states web capability '+label,page.ai_bar.property('web')==('no' if label=='offline' else 'yes'))
      errors=[]
      def inspect_sheet():
       sheet=app.activeModalWidget()
       try:
        check('real menu opens search sheet',isinstance(sheet,NameSearchSheet) and sheet.isVisible())
        sheet.language_buttons['en'].click();settle(.15)
        check('default trial limits work',sheet.trial.isChecked() and len(sheet.chosen()[1])==20)
        sheet.trial.setChecked(False);sheet.scope_buttons['all'].click();settle(.1)
        check('all scope retains exact source IDs',set(sheet.chosen()[1])==set(ids))
        check('selected scope disabled without selection',not sheet.scope_buttons['selected'].isEnabled())
        check('search capability wording '+label,('只靠猜' in sheet.start.text())==(label=='offline'))
        check('DeepSeek cost shown only for tool search',('美元' in sheet.estimate.text())==(label=='deepseek'))
        fits(sheet,theme+' '+label+' sheet');shot(sheet,'search-'+theme+'-'+label)
       except Exception:errors.append(traceback.format_exc())
       finally:
        if sheet is not None:sheet.reject()
      QTimer.singleShot(250,inspect_sheet);page.name_completion_button.click();settle(.15)
      check('search sheet inspection completed '+label,not errors,errors)
   check('cancelled search never changes names',m.read_concepts(legacy,library)==before)
   page.ai_popup.hide()
   terms.open_editor(page,ids[0]);settle(.25);tracker.drawer=page.names_drawer
   geometry=page.names_drawer.geometry().getRect();tracker.drawer_events=[]
   for identity in ids[1:12]:
    terms.open_editor(page,identity);settle(.04);editor=page._names_editor
    check('switch retains selected concept',editor.draft['id']==identity)
    check('drawer nav stays parented',all(b.parent() is not None and not b.isWindow() for b in (editor.prev_button,editor.next_button,editor.close_button)))
   check('switch leaves drawer geometry stable',page.names_drawer.geometry().getRect()==geometry)
   check('switch does not close and reopen drawer',not tracker.drawer_events,tracker.drawer_events)
   check('no blank top-level button windows',not tracker.flash,tracker.flash);shot(window,'drawer-switched')
   page._names_editor.close();settle(.2)
   from ..projects.studio_project import SubtitleProject, StudioMedia, StudioCue, StudioSpeaker, save_project
   from ..playback.audio_engine import studio_ffmpeg_path
   from ..system.processes import run_hidden_subprocess
   media=output/'speakers.mp4'
   ff=run_hidden_subprocess([str(studio_ffmpeg_path()),'-y','-f','lavfi','-i','color=c=0x342b40:s=640x360:r=25:d=3','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(media)],purpose='owned UI speaker fixture',capture_output=True,timeout=40)
   check('private speaker media created',ff.returncode==0)
   project=SubtitleProject(media=StudioMedia(path=str(media),duration_ms=3000,width=640,height=360),speakers=[StudioSpeaker('first','这是一个很长的说话人名字用于测试头像是否被挤压'),StudioSpeaker('second','第二位')],cues=[StudioCue('first-cue',0,2000,'头像完整可见',speaker_id='first'),StudioCue('second-cue',2000,2900,'第二位',speaker_id='second')])
   path=save_project(project,output/'speakers.2byteproj');window._open_subtitle_studio()
   wait(lambda:window.built_page('studio') is not None,30);studio=window.built_page('studio')
   studio.open_project(path,skip_dirty_guard=True);wait(lambda:studio._readiness.ready,30)
   from ..studio.studio_speaker_manager import SpeakerManagerDialog
   for theme in ('warm','grape'):
    apply_theme(theme,app);settle(.2);errors=[]
    def inspect_speakers():
     dialog=app.activeModalWidget()
     try:
      check('normal speaker command opens manager',isinstance(dialog,SpeakerManagerDialog))
      first=dialog._visible_order()[0]
      check('first speaker detail selected on opening',dialog.inspector.currentWidget() is dialog.cards[first])
      dialog.resize(dialog.minimumWidth(),dialog.height());settle(.2)
      for key,tile in dialog.tiles.items():
       if not tile.isVisible():continue
       a=tile.avatar.geometry()
       check('speaker avatar stays inside tile '+key,tile.rect().contains(a) and a.width()>=28 and a.height()==a.width(),dict(tile=tile.geometry().getRect(),avatar=a.getRect()))
      shot(dialog,'speakers-'+theme)
     except Exception:errors.append(traceback.format_exc())
     finally:
      if dialog is not None:dialog.reject()
    QTimer.singleShot(300,inspect_speakers);studio._open_speaker_manager()
    check('speaker inspection completed '+theme,not errors,errors)
   result['passed']=True
  except Exception:
   result['error']=traceback.format_exc()
   try:shot(app.activeModalWidget() or window,'failure')
   except Exception:pass
  finally:
   app.removeEventFilter(tracker)
   from ..diagnostics.build_identity import load_build_identity
   result.update(pid=os.getpid(),executable=sys.executable,identity=load_build_identity().to_dict())
   def stopped():
    result['gui_shutdown']=True;(output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
   app.aboutToQuit.connect(stopped)
   (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
   app.exit(0 if result['passed'] else 1)
 QTimer.singleShot(600,run)
