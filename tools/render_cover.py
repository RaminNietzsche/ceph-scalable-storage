#!/usr/bin/env python3
"""Generate the front and back cover HTML for one edition and screenshot them.

Usage: tools/render_cover.py --lang fa|en [--out build/fa] [--no-screenshot]

Writes <out>/cover.html and <out>/back.html. If Chrome/Chromium is available
(CHROME env var or google-chrome / chromium on PATH) it also writes
<out>/cover.png and <out>/back.png (1760x2500). Otherwise the committed
assets/cover.<lang>.png is used by the book build.
"""
import argparse, math, os, random, shutil, subprocess, yaml
ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'..'))
ap=argparse.ArgumentParser();ap.add_argument('--lang',default='fa',choices=['fa','en']);ap.add_argument('--out');ap.add_argument('--no-screenshot',action='store_true')
A=ap.parse_args();OUT=os.path.abspath(A.out or os.path.join(ROOT,'build',A.lang));os.makedirs(OUT,exist_ok=True)
T=yaml.safe_load(open(os.path.join(ROOT,'templates','cover',f'cover.{A.lang}.yaml'),encoding='utf-8'))
random.seed(7)
W,H=1760,2500
def hexpath(cx,cy,r):
    pts=[(cx+r*math.cos(math.radians(60*k-30)),cy+r*math.sin(math.radians(60*k-30))) for k in range(6)]
    return 'M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in pts)+' Z'
def svg_net(seed, h0, h1):
    random.seed(seed); s=[]
    r=70; dx=r*math.sqrt(3); dy=r*1.5
    cells=[]
    for row in range(int((h1-h0)/dy)+2):
        for col in range(int(W/dx)+2):
            cx=col*dx+(dx/2 if row%2 else 0); cy=h0+row*dy
            cells.append((cx,cy))
    for cx,cy in cells:
        v=random.random()
        if v<0.16: s.append(f'<path d="{hexpath(cx,cy,r-8)}" fill="#E74C3C" fill-opacity="{random.uniform(.25,.75):.2f}"/>')
        elif v<0.26: s.append(f'<path d="{hexpath(cx,cy,r-8)}" fill="#F5A097" fill-opacity="{random.uniform(.15,.35):.2f}"/>')
        elif v<0.6: s.append(f'<path d="{hexpath(cx,cy,r-8)}" fill="none" stroke="#e07a6f" stroke-opacity=".28" stroke-width="2"/>')
    # links
    lit=[c for c in cells if random.random()<0.12]
    for a in lit:
        b=random.choice(lit)
        if a!=b and math.dist(a,b)<520:
            s.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="#f7b9b1" stroke-opacity=".35" stroke-width="2.5"/>')
            for p in (a,b): s.append(f'<circle cx="{p[0]:.0f}" cy="{p[1]:.0f}" r="9" fill="#fde3df"/>')
    return ''.join(s)
FONT='''html,body{margin:0;width:%dpx;height:%dpx;overflow:hidden}body{font-family:%s;direction:%s;position:relative;background:linear-gradient(160deg,#1a0b0b 0%%,#3a1212 45%%,#5c1a17 100%%);color:#fff}
.net{position:absolute;left:0;width:%dpx}.en{font-family:Roboto,'DejaVu Sans',sans-serif;direction:ltr;unicode-bidi:embed}
'''%(W,H,T['font'],T['dir'],W)
front=f'''<!doctype html><html><head><meta charset="utf-8"><style>{FONT}
.top{{position:absolute;top:150px;{T["side"]}:140px;left:140px}}
.kick{{font-size:44px;font-weight:700;color:#f7b9b1;letter-spacing:1px}}
.bar{{width:220px;height:14px;background:#E74C3C;border-radius:7px;margin:40px 0 50px}}
h1{{font-size:150px;font-weight:900;line-height:1.35;margin:0;text-shadow:0 6px 30px rgba(0,0,0,.35)}}
.sub{{font-size:58px;font-weight:300;margin-top:40px;color:#fdeeee}}
.sub b{{font-weight:700}}
.desc{{font-size:38px;color:#f1c6c0;margin-top:60px;line-height:1.8;font-weight:300}}
.foot{{position:absolute;bottom:0;left:0;right:0;height:330px;background:rgba(25,6,6,.72);border-top:6px solid #E74C3C}}
.auth{{position:absolute;bottom:150px;{T["side"]}:140px;font-size:66px;font-weight:700}}
.authl{{position:absolute;bottom:245px;{T["side"]}:140px;font-size:34px;color:#f7b9b1}}
.ed{{position:absolute;bottom:160px;{T["oside"]}:140px;font-size:34px;color:#f7b9b1;text-align:{T["oside"]}}}
.tag{{position:absolute;bottom:70px;{T["side"]}:140px;font-size:28px;color:#c99a94}}
</style></head><body>
<svg class="net" style="top:1080px" width="{W}" height="1150" viewBox="0 1080 {W} 1150">{svg_net(3,1080,2240)}</svg>
<div class="top"><div class="kick">{T["kicker"]}</div><div class="bar"></div>
<h1>{T["title_html"]}</h1>
<div class="sub">{T["subtitle_html"]}</div>
<div class="desc"><span class="en">RADOS · CRUSH · BlueStore · RBD · RGW · CephFS</span><br/>{T["topics2"]}</div></div>
<div class="foot"></div><div class="authl">{T["author_label"]}</div><div class="auth">{T["author"]}</div>
<div class="ed">{T["edition_html"]}</div>
<div class="tag">{T["tagline"]}</div>
</body></html>'''
backc=f'''<!doctype html><html><head><meta charset="utf-8"><style>{FONT}
.box{{position:absolute;top:260px;right:150px;left:150px;font-size:44px;line-height:1.95;text-align:justify;color:#fdeeee;font-weight:300}}
.box h2{{font-size:72px;font-weight:900;color:#fff;margin:0 0 50px}}
.box ul{{padding-{T["side"]}:50px;margin:30px 0}}.box li{{margin-bottom:12px}}
.note{{position:absolute;bottom:170px;right:150px;left:150px;font-size:30px;color:#f7b9b1;line-height:1.8;border-top:3px solid #E74C3C;padding-top:40px;text-align:justify}}
</style></head><body>
<svg class="net" style="top:1500px;opacity:.5" width="{W}" height="700" viewBox="0 1500 {W} 700">{svg_net(11,1500,2200)}</svg>
<div class="box"><h2>{T["back_title"]}</h2>
{T["back_body_html"]}</div>
<div class="note">{T["back_note_html"]}</div>
</body></html>'''

open(os.path.join(OUT,'cover.html'),'w',encoding='utf-8').write(front)
open(os.path.join(OUT,'back.html'),'w',encoding='utf-8').write(backc)
chrome=os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser')
if chrome and not A.no_screenshot:
    for n in ('cover','back'):
        subprocess.run([chrome,'--headless=new','--no-sandbox','--disable-gpu','--hide-scrollbars',f'--window-size={W},{H}',f'--screenshot={OUT}/{n}.png',f'file://{OUT}/{n}.html'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    print('cover: rendered',OUT)
else:
    print('cover: html only (no chrome); using assets/cover.%s.png' % A.lang)
