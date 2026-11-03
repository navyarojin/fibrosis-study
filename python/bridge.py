"""Browser worker bridge. No network or persistent filesystem access."""
import base64, csv, io, json, re, tempfile, zipfile
from pathlib import Path
from research import validate_participant, analysis, flat, pbac_score, ufs_score, clean, VERSION
from imaging import measure

def verify_assets(p, assets):
    for m in p.get('measurements', []):
        if m.get('source') == 'image':
            ident=m.get('asset','')
            if not re.fullmatch('[a-f0-9]{32}',ident): raise ValueError('Invalid image reference.')
            for suffix in ['.json','.original','.png','.mask.png','.overlay.png']:
                if ident+suffix not in assets: raise ValueError('Image reference is missing.')
            if not m.get('reviewed'): raise ValueError('Review the overlay before saving.')
            meta=json.loads(base64.b64decode(assets[ident+'.json']))
            m.update(meta)
    return validate_participant(p)

def dispatch(req):
    op=req['op']; b=req.get('body') or {}
    if op=='score/pbac': return pbac_score(b['days'],b.get('complete',False))
    if op=='score/ufs': return ufs_score(b['answers'],b.get('confirmed',False))
    if op=='validate': return verify_assets(b['participant'],b['assets'])
    if op=='analysis': return analysis(b['participants'],b['options'])
    if op=='measure':
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); result=measure(b,folder)
            return {'measurement':result,'assets':{p.name:base64.b64encode(p.read_bytes()).decode() for p in folder.iterdir()}}
    if op=='backup':
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('study.json',json.dumps(dict(version=VERSION,created=b['created'],participants=b['participants'],audit=b['audit'])))
            for name,value in b['assets'].items(): z.writestr('images/'+name,base64.b64decode(value))
        return base64.b64encode(out.getvalue()).decode()
    if op=='restore':
        raw=base64.b64decode(b['backup'].split(',')[-1],validate=True)
        if len(raw)>90_000_000: raise ValueError('Backup exceeds the 90 MB restore limit.')
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            entries=z.infolist()
            if sum(x.file_size for x in entries)>400_000_000: raise ValueError('Unpacked backup exceeds 400 MB.')
            if len(set(z.namelist()))!=len(entries): raise ValueError('Duplicate backup entries.')
            for entry in entries:
                if entry.filename!='study.json' and not re.fullmatch(r'images/[a-f0-9]{32}\.(original|png|overlay\.png|mask\.png|json)',entry.filename): raise ValueError('Unexpected file in backup.')
            content=json.loads(z.read('study.json'))
            assets={Path(e.filename).name:base64.b64encode(z.read(e)).decode() for e in entries if e.filename.startswith('images/')}
            ps=[verify_assets(p,assets) for p in content['participants']]
            if len({p['id'] for p in ps})!=len(ps): raise ValueError('Duplicate participant IDs.')
            return dict(participants=ps,assets=assets,audit=content.get('audit',[]))
    if op in ['master.csv','measurements.csv']:
        rows=[flat(p) for p in b['participants']] if op=='master.csv' else [dict(m,participant=p['id']) for p in b['participants'] for m in p.get('measurements',[])]
        fields=list(flat({'id':''})) if op=='master.csv' else ['participant','region','reviewer','field','source','blue','pink','eligible','bluePixels','pinkPixels','reviewed','created','sha256']
        out=io.StringIO(); writer=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for row in rows:writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()})
        return '\ufeff'+out.getvalue()
    raise ValueError('Unknown calculation.')

def dispatch_json(raw):
    return json.dumps(clean(dispatch(json.loads(raw))),allow_nan=False)
