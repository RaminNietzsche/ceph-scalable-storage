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
import rados,os,json,subprocess,time
C=['ceph','-c',CEPH_CONF]
c=rados.Rados(conffile=CEPH_CONF);c.connect();io=c.open_ioctx('m33');b=os.urandom(128)
def snap(nw):
    r={'writes':nw,'osd':{}}
    for i in range(3):
        d=json.loads(subprocess.run(C+['daemon',f'osd.{i}','dump_mempools'],capture_output=True,text=True).stdout)['mempool']['by_pool']
        st=json.loads(subprocess.run(C+['daemon',f'osd.{i}','status'],capture_output=True,text=True).stdout)
        r['osd'][i]={k:(v['items'],v['bytes']) for k,v in d.items()};r['osd'][i]['num_pgs']=st['num_pgs']
    pg=json.loads(subprocess.run(C+['pg','ls-by-pool','m33','-f','json'],capture_output=True,text=True).stdout)
    pgs=pg['pg_stats'] if isinstance(pg,dict) else pg
    r['log_sizes']=[p['log_size'] for p in pgs];return r
out=[snap(0)];nw=0
for phase,count,objs in [('overwrite',120000,1000),('new',60000,None)]:
    while count>0:
        comps=[]
        for j in range(10000):
            name=f'w{(nw+j)%objs}' if objs else f'n{nw+j}'
            comps.append(io.aio_write_full(name,b))
        for x in comps: x.wait_for_complete()
        nw+=10000;count-=10000;time.sleep(6)
        s=snap(nw);s['phase']=phase;out.append(s)
        print(nw,phase,sum(s['log_sizes']),max(s['log_sizes']),[s['osd'][i]['osd_pglog'][1] for i in range(3)],[s['osd'][i]['bluestore_cache_onode'][0] for i in range(3)],flush=True)
json.dump(out,open('figures/data/mem33.json','w'))
