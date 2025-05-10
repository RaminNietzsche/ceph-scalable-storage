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
import rados,json,time,statistics as st
c=rados.Rados(conffile=CEPH_CONF);c.connect()
def mon(cmd,**k): return c.mon_command(json.dumps(dict(prefix=cmd,**k)),b'')
def mgr(cmd,**k): return c.mgr_command(json.dumps(dict(prefix=cmd,**k)),b'')
mon('config set',who='global',name='mon_max_pg_per_osd',value='2000')
def wait_clean(n):
    for _ in range(600):
        r,o,e=mgr('pg stat',format='json');j=json.loads(o)['pg_summary']
        tot=j['num_pgs'];ac=sum(x['num'] for x in j['num_pg_by_state'] if x['name']=='active+clean')
        if tot==n and ac==n: return
        time.sleep(1)
    raise SystemExit('not clean')
R=[]
for extra in [0,96,480,992]:
    if extra:
        mon('osd pool create',pool='p09',pg_num=extra,pgp_num=extra);mon('osd pool set',pool='p09',var='pg_autoscale_mode',val='off')
    wait_clean(32+extra);time.sleep(12)
    row={'pgs':32+extra}
    for name,f in [('pg dump',lambda:mgr('pg dump',format='json')),('pg dump pgs_brief',lambda:mgr('pg dump',dumpcontents=['pgs_brief'],format='json')),('status',lambda:mon('status',format='json'))]:
        t=[];sz=0
        for _ in range(10):
            t0=time.perf_counter();r,o,e=f();t.append(time.perf_counter()-t0);sz=len(o)
        row[name]=dict(ms=st.median(t)*1e3,bytes=sz)
    R.append(row);print(row,flush=True)
    if extra: mon('osd pool rm',pool='p09',pool2='p09',yes_i_really_really_mean_it=True);wait_clean(32)
json.dump(R,open('figures/data/mgr09_dump.json','w'))
