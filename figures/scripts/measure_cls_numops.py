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
import rados,struct,threading,time,json
c=rados.Rados(conffile=CEPH_CONF);c.connect()
def enc(s): b=s.encode();return struct.pack('<I',len(b))+b
def run(mode,N,K=300):
    obj=f'ctr_{mode}_{N}';io0=c.open_ioctx('m33')
    with rados.WriteOpCtx() as w:
        io0.set_omap(w,('n',),(b'0',));io0.operate_write_op(w,obj)
    lat=[]
    def worker():
        io=c.open_ioctx('m33')
        for _ in range(K):
            t=time.perf_counter()
            if mode=='cls':
                io.execute(obj,'numops','add',enc('n')+enc('1'))
            else:
                with rados.ReadOpCtx() as r:
                    it,ret=io.get_omap_vals_by_keys(r,('n',));io.operate_read_op(r,obj);v=int(dict(it)['n'])
                with rados.WriteOpCtx() as w:
                    io.set_omap(w,('n',),(str(v+1).encode(),));io.operate_write_op(w,obj)
            lat.append(time.perf_counter()-t)
    ths=[threading.Thread(target=worker) for _ in range(N)];t0=time.time()
    [t.start() for t in ths];[t.join() for t in ths];el=time.time()-t0
    with rados.ReadOpCtx() as r:
        it,ret=io0.get_omap_vals_by_keys(r,('n',));io0.operate_read_op(r,obj);v=int(dict(it)['n'])
    lat.sort()
    return dict(mode=mode,N=N,expected=N*K,final=v,lost=N*K-v,ops_s=N*K/el,p50=lat[len(lat)//2]*1e3,p99=lat[int(len(lat)*.99)]*1e3)
R=[]
for N in [1,2,4,8,16]:
    for m in ['cls','rmw']:
        r=run(m,N);R.append(r);print(r,flush=True)
json.dump(R,open('figures/data/cls15.json','w'))
