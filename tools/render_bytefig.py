#!/usr/bin/env python3
"""Render byte-layout / grid figures: fig/*.bf.json -> fig/*.png (HTML + headless Chrome).
spec: {title, sub, cols(16), unit_px, fields:[{n,s(int|'var'),t,v,c,u(var width units)} | {"row":"label"} (force new row)], notes:[...], legend:{c:label}}"""
import json,sys,os,glob,subprocess,html,tempfile,shutil
CHROME=os.environ.get("CHROME") or shutil.which("google-chrome") or shutil.which("chromium") or "chromium"
from PIL import Image, ImageChops
PAL={0:'#E8F0FE',1:'#FDE2E1',2:'#E3F4E8',3:'#FFF4D6',4:'#EFE6FA',5:'#E0F4F7',6:'#F1F1F1',7:'#FFE0F0'}
BOR={0:'#4A72C4',1:'#C0392B',2:'#2E8B57',3:'#C99A06',4:'#7B4FB8',5:'#1C8C9C',6:'#888',7:'#C2185B'}
FONT='''/* font "V" resolves to the system Vazirmatn (install fonts/ or see README) */
@font-face{font-family:V;src:local("Vazirmatn");font-weight:400}
@font-face{font-family:V;src:local("Vazirmatn Bold"),local("Vazirmatn-Bold");font-weight:700}'''
def esc(s): return html.escape(str(s))
def build(sp):
    cols=sp.get('cols',8); W=sp.get('width',1700); cw=(W-60-70-4*(cols+2))//cols
    rows=[]; cur=[]; used=0; off=0; fixed=True; rowlabels=[]; lab=None
    def flush():
        nonlocal cur,used,lab
        if cur: rows.append((lab,cur))
        cur=[]; used=0; lab=None
    for f in sp['fields']:
        if 'row' in f:
            flush(); lab=f['row']; continue
        var = f['s']=='var'
        units = f.get('u',4) if var else f['s']
        size_lbl = (f.get('sl') or ('var' if var else f"{f['s']} B"))
        offlbl = (f"@{off}" if fixed else '')
        first=True; rem=units
        while rem>0:
            if used==cols: flush()
            take=min(rem,cols-used)
            cur.append(dict(f=f,span=take,first=first,cont=(rem-take>0),var=var,size=size_lbl,off=offlbl))
            used+=take; rem-=take; first=False
        if var: fixed=False
        else: off+=f['s']
    flush()
    hdr=''.join(f'<td class="bi">{i}</td>' for i in range(cols))
    trs=[f'<tr><td class="rl"></td>{hdr}</tr>']
    for lab,cells in rows:
        tds=''
        for c in cells:
            f=c['f']; k=f.get('c',0)
            style=f"background:{PAL[k]};border-color:{BOR[k]};"+('border-style:dashed;' if c['var'] else '')
            sm=' sm' if c['span']<=1 else (' md' if c['span']==2 else '')
            if c['first']:
                inner=f'<div class="fn{sm}">{esc(f["n"])}</div><div class="ft{sm}">{esc(f.get("t",""))} · {esc(c["size"])} <span class="off">{esc(c["off"])}</span></div>'
                if f.get('v'): inner+=f'<div class="fv">{esc(f["v"])}</div>'
            else:
                inner=f'<div class="fn cont">… {esc(f["n"])}</div>'
            if c['cont']: inner+='<div class="more">↵</div>'
            tds+=f'<td class="fld" colspan="{c["span"]}" style="{style}">{inner}</td>'
        used=sum(c['span'] for c in cells)
        if used<cols: tds+=f'<td class="empty" colspan="{cols-used}"></td>'
        trs.append(f'<tr><td class="rl">{esc(lab or "")}</td>{tds}</tr>')
    leg=''.join(f'<span class="lg"><i style="background:{PAL[int(k)]};border-color:{BOR[int(k)]}"></i>{esc(v)}</span>' for k,v in sp.get('legend',{}).items())
    notes=''.join(f'<li>{esc(n)}</li>' for n in sp.get('notes',[]))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>{FONT}
body{{margin:0;background:#fff;font-family:V;width:{W}px}}
.wrap{{padding:28px 30px}}
h1{{font-size:34px;margin:0 0 4px;color:#1F3864;direction:rtl;text-align:right}}
.sub{{font-size:23px;color:#444;direction:rtl;text-align:right;margin-bottom:16px}}
table{{border-collapse:separate;border-spacing:4px;direction:ltr;table-layout:fixed;width:100%}}
td.bi{{font:20px "DejaVu Sans Mono",V;color:#777;text-align:center;width:{cw}px}}
td.rl{{width:70px;font-size:19px;color:#555;text-align:center;direction:rtl}}
td.fld{{border:2.5px solid;border-radius:8px;padding:8px 6px;vertical-align:top;text-align:center;height:92px;overflow:hidden}}
td.empty{{border:2px dotted #ddd;border-radius:8px}}
.fn{{font:bold 23px "DejaVu Sans Mono",V;color:#111;word-break:normal;overflow-wrap:anywhere}}
.fn.sm{{font-size:20px}}.fn.md{{font-size:22px}}.ft.sm{{font-size:17px}}.ft.md{{font-size:18px}}
.fn.cont{{color:#666;font-weight:normal}}
.ft{{font:19px "DejaVu Sans Mono",V;color:#333;margin-top:4px}}
.off{{color:#C0392B}}
.fv{{font:19px "DejaVu Sans Mono",V;color:#1F3864;margin-top:5px;background:#ffffffaa;border-radius:4px;word-break:normal;overflow-wrap:anywhere}}
.more{{font-size:20px;color:#999;text-align:right}}
.legend{{direction:rtl;text-align:right;margin-top:14px;font-size:22px}}
.lg{{margin-left:44px;display:inline-block;white-space:nowrap}}.lg i{{display:inline-block;width:24px;height:18px;border:2px solid;border-radius:4px;margin-left:8px;vertical-align:middle}}
ul{{direction:rtl;text-align:right;font-size:22px;line-height:1.75;margin:12px 0 0;padding-right:30px;color:#222}}
</style></head><body><div class="wrap"><h1>{esc(sp["title"])}</h1><div class="sub">{esc(sp.get("sub",""))}</div>
<table>{"".join(trs)}</table><div class="legend">{leg}</div><ul>{notes}</ul></div></body></html>'''
def shot(htmltext,out,W):
    with tempfile.NamedTemporaryFile('w',suffix='.html',delete=False,encoding='utf-8') as t: t.write(htmltext); p=t.name
    subprocess.run([CHROME,'--headless','--no-sandbox','--disable-gpu','--hide-scrollbars',f'--window-size={W},4000',f'--screenshot={out}','file://'+p],capture_output=True,timeout=120)
    im=Image.open(out).convert('RGB'); bg=Image.new('RGB',im.size,'white'); bb=ImageChops.difference(im,bg).getbbox()
    if bb: im=im.crop((0,0,im.width,min(im.height,bb[3]+24)))
    im.save(out); os.unlink(p); return im.size
if __name__=='__main__':
    if len(sys.argv)<2 or sys.argv[1] in ('-h','--help'): print('usage: render_bytefig.py figures/chNN [...]'); sys.exit(0)
    # usage: render_bytefig.py figures/chNN [...]  (renders *.bf.json -> .png when the spec is newer)
    for d in sys.argv[1:]:
        for f in sorted(glob.glob(os.path.join(d,'*.bf.json'))):
            out=f[:-8]+'.png'
            if os.path.exists(out) and os.path.getmtime(out)>=os.path.getmtime(f): continue
            sp=json.load(open(f,encoding='utf-8')); print(os.path.relpath(out), shot(build(sp),out,sp.get('width',1700)))
