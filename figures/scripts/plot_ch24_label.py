#!/usr/bin/env python3
"""Draw figure(s) for the chapter named in the file name.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
import matplotlib;matplotlib.use('Agg');import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams['font.family']='DejaVu Sans'
b=open(_os.environ.get('OSD_BLOCK', 'osd0/block'),'rb').read(588)
R=[(0,23,'#f9e79f','magic text "bluestore block device\\n" (23 B)'),(23,59,'#fad7a0','osd_uuid as text + "\\n" (37 B)'),
   (60,61,'#e74c3c','struct_v=2, compat=1'),(62,65,'#f1948a','struct_len=0x206=518 (LE u32)'),
   (66,81,'#85c1e9','osd_uuid (16 B binary)'),(82,89,'#82e0aa','size u64 = 0x280000000 = 10 GiB'),
   (90,97,'#bb8fce','btime utime_t: sec u32, nsec u32'),(98,105,'#76d7c4','description: len u32=4, "main"'),
   (106,109,'#d5dbdb','meta map: count u32 = 14 pairs'),(110,583,'#f2f3f4','meta pairs: (len,key)(len,value) ... (474 B)'),
   (584,587,'#2c3e50','crc32c(-1) of bytes 0..583, LE')]
def col(i):
    for a,z,c,_ in R:
        if a<=i<=z: return c
    return 'white'
rows=list(range(0,8))+[None]+list(range(35,37))
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110);y=0
for r in rows:
    if r is None:
        ax.text(8,-y-0.5,'... meta pairs continue (0x080 - 0x22f) ...',ha='center',va='center',fontsize=10,style='italic');y+=1;continue
    ax.text(-0.6,-y-0.5,f'{r*16:04x}',ha='right',va='center',family='DejaVu Sans Mono',fontsize=9)
    for c in range(16):
        i=r*16+c
        if i>=len(b)+4: continue
        fc=col(i) if i<588 else 'white'
        ax.add_patch(Rectangle((c,-y-1),1,1,facecolor=fc,edgecolor='#7f8c8d'))
        if i<588:
            ch=chr(b[i]) if 32<=b[i]<127 else '·'
            ax.text(c+0.5,-y-0.38,f'{b[i]:02x}',ha='center',va='center',family='DejaVu Sans Mono',fontsize=8,color='white' if fc in('#2c3e50','#e74c3c') else 'black')
            ax.text(c+0.5,-y-0.78,ch,ha='center',va='center',family='DejaVu Sans Mono',fontsize=6,color='#555' if fc!='#2c3e50' else 'white')
    y+=1
for k,(a,z,c,t) in enumerate(R):
    ax.add_patch(Rectangle((17.2,-k*0.95-1),0.6,0.6,facecolor=c,edgecolor='k'));ax.text(18.0,-k*0.95-0.7,f'{a:#05x}-{z:#05x}  {t}',va='center',fontsize=9)
ax.set_xlim(-2,31);ax.set_ylim(-y-0.3,0.3);ax.axis('off')
ax.set_title('First 588 bytes of a real BlueStore block label (osd.0, Ceph 18.2.7, read with python from the block file); crc verified = 0xb012c37d')
plt.tight_layout();plt.savefig('figures/ch24/f09_labelhex.png')
