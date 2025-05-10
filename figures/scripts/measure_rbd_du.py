#!/usr/bin/env python3
"""Measure on a running test cluster (needs CEPH_CONF); writes JSON under figures/data/.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
import rados,rbd,random,subprocess,json
c=rados.Rados(conffile=CEPH_CONF);c.connect();io=c.open_ioctx('rbd')
R=rbd.RBD();G=1<<30;M=1<<20
W={'A_100x1K':[(i*4*M,1024) for i in range(100)],
   'B_1000x1K':[(i*4*M,1024) for i in range(1000)],
   'C_seq256M':[(i*4*M,4*M) for i in range(64)],
   'D_2000x4K_rand2G':None}
rnd=random.Random(42);W['D_2000x4K_rand2G']=[(rnd.randrange(0,2*G//4096)*4096,4096) for _ in range(2000)]
out={}
for n,ws in W.items():
    try: R.remove(io,n)
    except Exception: pass
    R.create(io,n,10*G,old_format=False)
    with rbd.Image(io,n) as im:
        for off,l in ws: im.write(b'x'*l,off)
    res={}
    for ex in ([],['--exact']):
        j=json.loads(subprocess.run(['rbd','-c',CEPH_CONF,'du','--format','json','rbd/'+n]+ex,capture_output=True,text=True).stdout)
        res['exact' if ex else 'default']=j['images'][0]['used_size']
    with rbd.Image(io,n) as im: res['features']=im.features(); res['objs']=len({o//(4*M) for o,_ in ws})
    out[n]=res;print(n,res,flush=True)
json.dump(out,open('figures/data/du_real.json','w'),indent=1)
