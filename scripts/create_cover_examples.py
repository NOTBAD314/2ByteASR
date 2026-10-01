"""Build editable PSD examples from a locally supplied authorized image."""
import argparse,json,os,sys,uuid
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser();inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--source-cover',type=Path);inputs.add_argument('--source-image',type=Path)
    args=parser.parse_args();sys.path.insert(0,str(root))
    os.environ.setdefault('TWOBYTEASR_TEST_ROOT',str(root/'tmp/cover-photopea/create-examples'))
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    import twobyteasr
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtCore import Qt
    from twobyteasr.cover_document import CoverDocument
    from twobyteasr.cover_samples import sample_documents,demo_character
    from twobyteasr.cover_psd import save_psd
    from twobyteasr.cover_render import CoverRenderer,export_image
    app=QApplication([])
    for font in (root/'assets/fonts').glob('*.otf'):QFontDatabase.addApplicationFont(str(font))
    if args.source_image:
        frame=args.source_image.read_bytes()
    else:
        source=CoverDocument.load(args.source_cover)
        frame=source.assets[source.layer(source.background_id).asset]
    out=root/'assets/cover-templates';out.mkdir(parents=True,exist_ok=True)
    preview=root/'tmp/cover-photopea/examples';preview.mkdir(parents=True,exist_ok=True)
    index=[]
    for i,(name,doc,slots) in enumerate(sample_documents(frame)):
        key=uuid.uuid5(uuid.NAMESPACE_URL,'2byteasr-cover-sample-v1-'+str(i)).hex
        filename=f'sample-{i+1}'
        save_psd(doc,out/(filename+'.psd'))
        thumb=CoverRenderer().render(doc).scaled(480,300,Qt.KeepAspectRatio,Qt.SmoothTransformation)
        thumb.save(str(out/(filename+'.png')))
        export_image(doc,preview/(filename+'.png'))
        doc.save(preview/(filename+'.2bytecover'))
        index.append(dict(id=key,name=name,psd=filename+'.psd',thumbnail=filename+'.png',slots=slots,strategy='fill',focus=[.5,.5]))
        print(name,(out/(filename+'.psd')).stat().st_size,flush=True)
    (out/'index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf8')
    (preview/'示例角色.png').write_bytes(demo_character())
    # Provenance is reviewed separately; this generator cannot grant rights to
    # an arbitrary input or overwrite the shipped material's rights record.


if __name__=='__main__':main()
