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
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, numpy as np, sys
from matplotlib.patches import Rectangle
from collections import Counter
from rgw import *
plt.rcParams['font.family']='DejaVu Sans'
D='figures/ch04/'
# f08 shard distribution
fig,(a1,a2)=plt.subplots(1,2,figsize=(16,6.5),dpi=110)
c=Counter(shard(f'photos/2026/11/img_{i:06d}.jpg',11) for i in range(100000))
a1.bar(range(11),[c[i] for i in range(11)],color='#5DADE2',edgecolor='k'); a1.axhline(100000/11,color='k',ls='--')
a1.set_ylim(8500,9400); a1.set_xticks(range(11)); a1.set_xlabel('bucket index shard (.dir.<marker>.N)',fontsize=12); a1.set_ylabel('index entries',fontsize=12)
a1.set_title('100,000 sequential keys photos/2026/11/img_NNNNNN.jpg over 11 shards',fontsize=12)
for i in range(11): a1.text(i,c[i]+10,str(c[i]),ha='center',fontsize=10)
keys=['photos/2026/11/img_0001.jpg','photos/2026/11/img_0002.jpg','logs/app.log']
a2.axis('off'); y=0.9
a2.text(0,0.98,'bucket_shard_index(key, n) step by step',fontsize=13,weight='bold')
for k in keys:
    sid=h(k); sid2=(sid^((sid&0xff)<<24))&0xffffffff
    a2.text(0,y-0.06,f'key = "{k}"',fontsize=12,family='DejaVu Sans Mono')
    a2.text(0.04,y-0.13,f'ceph_str_hash_linux = {sid}',fontsize=11.5,family='DejaVu Sans Mono')
    a2.text(0.04,y-0.20,f'sid ^ ((sid & 0xFF) << 24) = {sid2}',fontsize=11.5,family='DejaVu Sans Mono')
    a2.text(0.04,y-0.27,f'% 7877 % 11 = {sid2%7877%11}    (% 7877 % 23 = {sid2%7877%23})',fontsize=11.5,family='DejaVu Sans Mono')
    y-=0.31
plt.tight_layout(); plt.savefig(D+'f08_bishard.png'); plt.close()
# f09 reshard staircase
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
for ms,col,lab in ((False,'#4A72C4','single zone (multiplier 2)'),(True,'#C0392B','multisite (multiplier 8)')):
    cur=11; xs=[0]; ys=[11]
    for n in range(0,300_000_001,100000):
        new=calc(n,cur,ms)
        if new!=cur: xs+=[n,n]; ys+=[cur,new]; cur=new
    xs.append(3e8); ys.append(cur)
    ax.plot(np.array(xs)/1e6,ys,color=col,lw=2.5,label=lab)
    for x,y in zip(xs[1::2],ys[2::2]): ax.text(x/1e6,y*1.08,str(y),color=col,fontsize=11,ha='center')
n=np.linspace(0.01,300,500); ax.plot(n,np.minimum(1999,n*1e6/100000),':',color='#555',label='objects / rgw_max_objs_per_shard (100000)')
ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlim(0.5,300); ax.set_ylim(8,3000)
ax.set_xlabel('objects in bucket (millions), checked every 100k objects',fontsize=12); ax.set_ylabel('bucket index shards',fontsize=12)
ax.set_title('RGWBucketReshard::calculate_preferred_shards: start 11, expand when objs > shards x 100000, new = nearest prime >= objs x m / 100000, max 1999',fontsize=12)
ax.legend(fontsize=12,loc='upper left'); ax.grid(alpha=.3,which='both')
plt.tight_layout(); plt.savefig(D+'f09_reshard.png'); plt.close()
# f10 listing amplification
fig,ax=plt.subplots(figsize=(16,6),dpi=110)
S=np.unique(np.logspace(0,np.log10(1999),200).astype(int))
for ne,col in ((1000,'#4A72C4'),(100,'#27AE60')):
    tot=[per_shard(ne,s)*s for s in S]; ax.loglog(S,tot,lw=2.5,color=col,label=f'max-keys = {ne}: entries requested from all shards')
    ax.axhline(ne,color=col,ls=':')
for s_ in (11,101,1999):
    v=per_shard(1000,s_)*s_; ax.plot([s_],[v],'ko'); ax.annotate(f'{s_} shards: {per_shard(1000,s_)} each -> {v}',(s_,v),xytext=(s_*0.45,v*2.2),fontsize=12,arrowprops=dict(arrowstyle='->'))
ax.set_xlabel('bucket index shards',fontsize=12); ax.set_ylabel('index entries read for one page',fontsize=12); ax.legend(fontsize=12,loc='upper left'); ax.grid(alpha=.3,which='both')
ax.set_title('calc_ordered_bucket_list_per_shard = max(8, 1 + n/s + sqrt(2 n ln s / s))  (first attempt, before expansion)',fontsize=12)
plt.tight_layout(); plt.savefig(D+'f10_listing.png'); plt.close()
# f11 manifest
fig,(a1,a2)=plt.subplots(2,1,figsize=(16,7.5),dpi=110)
def box(a,x,w,t,fc,y=0):
    a.add_patch(Rectangle((x,y),w,1,fc=fc,ec='k')); a.text(x+w/2,y+0.5,t,ha='center',va='center',fontsize=10.5)
box(a1,0,4,'HEAD  <marker>_photo.jpg\n0-4 MiB + xattrs (manifest, acl, etag)','#F7DC6F')
box(a1,4,4,'<marker>__shadow_.<rand32>_1\n4-8 MiB','#AED6F1'); box(a1,8,2,'..._2\n8-10 MiB','#AED6F1')
a1.set_xlim(-0.2,16.2); a1.set_ylim(-0.3,1.4); a1.axis('off')
a1.set_title('PUT 10 MiB (atomic): head max 4 MiB (rgw_max_chunk_size), stripes 4 MiB (rgw_obj_stripe_size), tail in ns "shadow"',fontsize=12)
x=0
box(a2,x,1.2,'HEAD <marker>_big.iso\n(0 bytes data,\nmanifest)','#F7DC6F'); x+=1.4
for p in (1,2):
    box(a2,x,2,f'__multipart_\nbig.iso.<upload>.{p}\n4 MiB','#F5B7B1'); box(a2,x+2,2,f'__shadow_\nbig.iso.<upload>.{p}_1\n4 MiB','#AED6F1'); box(a2,x+4,1,f'..._{p}_2\n2 MiB','#AED6F1'); x+=5.2
a2.text(1.4+5,1.15,'part 1 = 10 MiB',ha='center',fontsize=11); a2.text(1.4+5.2+2.5,1.15,'part 2 = 10 MiB',ha='center',fontsize=11)
a2.set_xlim(-0.2,16.2); a2.set_ylim(-0.3,1.4); a2.axis('off')
a2.set_title('multipart, 2 parts x 10 MiB: each part = ".N" object in ns "multipart" + "_N_S" stripes in ns "shadow"; ETag = md5(md5s)-2',fontsize=12)
plt.tight_layout(); plt.savefig(D+'f11_manifest.png'); plt.close()
