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
import matplotlib.pyplot as plt
plt.rcParams['font.family']='DejaVu Sans'
K=1024
pieces=[(1056,0,288,32),(1088,1,256,64),(1152,2,256,64),(1216,3,256,64),(1280,0,320,32)]
cols=['#9EC5FE','#B8E0C2','#FFE08A','#F4A3A3']
fig,(a1,a2)=plt.subplots(2,1,figsize=(16,7.5),dpi=110,gridspec_kw={'height_ratios':[1,1.6]})
for off,o,oo,x in pieces:
    a1.barh(0,x,left=off,color=cols[o],edgecolor='k',height=0.5); a1.text(off+x/2,0,f'obj {o}\n+{oo}K',ha='center',va='center',fontsize=12)
a1.set_xlim(1040,1330); a1.set_yticks([]); a1.set_xlabel('image offset (KiB): write of 256 KiB at 1056 KiB',fontsize=13)
a1.set_title('ceph_file_to_extents with stripe_unit=64K, stripe_count=4, object_size=4M',fontsize=14)
for o in range(4):
    a2.barh(3-o,4096,left=0,color='#F7F7F7',edgecolor='#bbb',height=0.6)
    for off,oo2,oo,x in pieces:
        if oo2==o: a2.barh(3-o,x,left=oo,color=cols[o],edgecolor='k',height=0.6)
a2.barh(3,64,left=288,fill=False,edgecolor='#C0392B',lw=3,height=0.75)
a2.text(400,3,'obj 0: two file pieces merged into one extent [288K, +64K] (last_ex->oe_off + oe_len == objoff)',fontsize=12,va='center',color='#C0392B')
for o in (1,2,3): a2.text(400,3-o,f'obj {o}: extent [256K, +64K]',fontsize=12,va='center')
a2.set_yticks(range(4)); a2.set_yticklabels([f'rbd_data.<id>.{3-i:016x}' for i in range(4)],fontsize=11)
a2.set_xlim(0,1200); a2.set_xlabel('offset inside object (KiB, first 1200 of 4096 shown)',fontsize=13)
plt.tight_layout(); plt.savefig('f08_extents.png'); plt.close()
# timeout timeline
fig,ax=plt.subplots(figsize=(16,5.5),dpi=110)
for t in range(0,31,5): ax.axvline(t,color='#4A72C4',ls=':',lw=1)
ax.text(0.2,3.6,'handle_timeout every osd_keepalive_timeout = 5 s',color='#4A72C4',fontsize=12)
reqs=[(1,2.2,'req A tid 101 -> osd.3 (done)'),(3,14,'req B tid 102 -> osd.7 (slow)')]
for i,(s,e,l) in enumerate(reqs):
    ax.plot([s,e],[2.6-i,2.6-i],lw=8,color=['#B8E0C2','#F4A3A3'][i],solid_capstyle='butt'); ax.text(s,2.85-i,l,fontsize=12)
for t in (10,):
    ax.annotate('r_stamp(B)=3 < cutoff=10-5 -> laggy -> osd.7 in slow list -> ceph_con_keepalive',(t,1.6),xytext=(10.3,0.8),fontsize=12,arrowprops=dict(arrowstyle='->'))
ax.plot([2.2,30],[0.2,0.2],lw=6,color='#D7C4F0'); ax.text(2.4,0.35,'osd.3 session idle since 2.2 s',fontsize=12)
ax.annotate('lru_ttl = 2.2 + 60 s; handle_osds_timeout (every osd_idle_ttl/4 = 15 s) closes it at first run after 62.2 s',(30,0.2),xytext=(9,-0.55),fontsize=12,arrowprops=dict(arrowstyle='->'))
ax.set_xlim(0,31); ax.set_ylim(-0.8,4); ax.set_yticks([]); ax.set_xlabel('time (s)',fontsize=13)
ax.set_title('libceph osd_client handle_timeout: laggy detection, keepalive, idle session reaping (osd_request_timeout=0: never abort)',fontsize=14)
plt.tight_layout(); plt.savefig('f11_timeout.png'); plt.close()
