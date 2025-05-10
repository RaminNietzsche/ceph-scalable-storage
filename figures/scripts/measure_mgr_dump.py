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
import rados,json,time,statistics as st,sys
c=rados.Rados(conffile=CEPH_CONF);c.connect()
def mon(cmd,**k): return c.mon_command(json.dumps(dict(prefix=cmd,**k)),b'')
def mgr(cmd,**k): return c.mgr_command(json.dumps(dict(prefix=cmd,**k)),b'')
def clean(n):
    for _ in range(900):
        j=json.loads(mgr('pg stat',format='json')[1])['pg_summary']
        if j['num_pgs']==n and sum(x['num'] for x in j['num_pg_by_state'] if x['name']=='active+clean')==n: return
        time.sleep(1)
def meas():
    row={'pgs':json.loads(mgr('pg stat',format='json')[1])['pg_summary']['num_pgs']}
    for name,f in [('pg dump',lambda:mgr('pg dump',format='json')),('pg dump pgs_brief',lambda:mgr('pg dump',dumpcontents=['pgs_brief'],format='json')),('status',lambda:mon('status',format='json'))]:
        t=[]
        for _ in range(10):
            t0=time.perf_counter();r,o,e=f();t.append(time.perf_counter()-t0)
        row[name]=dict(ms=st.median(t)*1e3,bytes=len(o))
    print(json.dumps(row),flush=True);return row
R=[{'pgs':32,'pg dump':{'ms':1.907,'bytes':90276},'pg dump pgs_brief':{'ms':0.178,'bytes':3054},'status':{'ms':0.206,'bytes':1275}},
   {'pgs':128,'pg dump':{'ms':4.059,'bytes':324167},'pg dump pgs_brief':{'ms':0.250,'bytes':12158},'status':{'ms':0.128,'bytes':1565}}]
R.append(meas())
mon('osd pool rm',pool='p09',pool2='p09',yes_i_really_really_mean_it=True);clean(32)
mon('osd pool create',pool='p09',pg_num=992,pgp_num=992);mon('osd pool set',pool='p09',var='pg_autoscale_mode',val='off')
clean(1024);time.sleep(12);R.append(meas())
mon('osd pool rm',pool='p09',pool2='p09',yes_i_really_really_mean_it=True)
json.dump(R,open('figures/data/mgr09_dump.json','w'));print('done')
