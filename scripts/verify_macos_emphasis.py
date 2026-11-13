"""Native negative/positive control for CoreText's real bundled UI faces."""
from pathlib import Path
import argparse,json,os,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();assert sys.platform=='darwin' and 'tmp' in out.parts and not out.exists()
    out.mkdir(parents=True);os.environ['TWOBYTEASR_TEST_ROOT']=str(out)
    from PySide6.QtWidgets import QApplication,QDialog,QLabel,QVBoxLayout
    from PySide6.QtGui import QFontDatabase,QFontInfo
    from twobyteasr.design import typography as t
    app=QApplication.instance() or QApplication([])
    registered=[]
    for name in ('SourceHanSansSC-Medium.otf','SourceHanSansSC-Heavy.otf'):
        identity=QFontDatabase.addApplicationFont(str(ROOT/'assets/fonts'/name));assert identity>=0
        registered.append(dict(file=name,families=QFontDatabase.applicationFontFamilies(identity)))
    app.setFont(t.application_font())
    sheet='QDialog#aiSettingsDialog QLabel#aiDialogTitle { font-size: 20px; font-weight: 600; font-family: '+t.TITLE_FONT_STACK+'; }'
    rows=[]
    for label,css in [('old',sheet),('fixed',t.emphasis_qss(sheet))]:
        dialog=QDialog();dialog.setObjectName('aiSettingsDialog');dialog.setStyleSheet(css)
        layout=QVBoxLayout(dialog);title=QLabel('AI 文字服务设置');title.setObjectName('aiDialogTitle');layout.addWidget(title)
        dialog.show();app.processEvents();info=QFontInfo(title.font())
        rows.append(dict(label=label,requested=int(title.font().weight()),family=info.family(),style=info.styleName(),weight=int(info.weight())))
        assert dialog.grab().save(str(out/(label+'.png')))
        dialog.close();dialog.deleteLater();app.processEvents()
    assert rows[0]['weight']<800,rows
    assert rows[1]['weight']>=800 and 'heavy' in (rows[1]['family']+' '+rows[1]['style']).lower(),rows
    result=dict(passed=True,platform=app.platformName(),registered=registered,rows=rows)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
