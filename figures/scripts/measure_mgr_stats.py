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
import rados,json,time,random
c=rados.Rados(conffile=CEPH_CONF);c.connect();io=c.open_ioctx('m33')
def mc(cmd,**k):
    r,o,e=c.mon_command(json.dumps(dict(prefix=cmd,**k)),b'');return r,o,e
def objs():
    r,o,e=c.mgr_command(json.dumps({'prefix':'pg dump','dumpcontents':['pools'],'format':'json'}),b'')
    j=json.loads(o);P=j if isinstance(j,list) else j.get('pool_stats',j)
    return sum(p['stat_sum']['num_objects'] for p in P if p['poolid']==pid)
pid=c.pool_lookup('m33');R={}
for per in [1,2,5,10]:
    mc('config set',who='global',name='mgr_stats_period',value=str(per));time.sleep(per*2+2)
    lags=[]
    for t in range(15):
        time.sleep(random.uniform(0,per))
        b=objs();io.write_full(f'lag{per}_{t}_{random.random()}',b'x');t0=time.time()
        while objs()<=b: time.sleep(0.05)
        lags.append(time.time()-t0)
    R[per]=lags;print(per,sorted(round(x,2) for x in lags),flush=True)
mc('config rm',who='global',name='mgr_stats_period')
json.dump(R,open('figures/data/mgr09_lag.json','w'))
