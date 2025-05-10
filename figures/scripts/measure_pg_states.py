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
import subprocess,json,time,threading,collections
C=['ceph','-c',CEPH_CONF]
log=[];t0=time.time();stop=False;events=[]
def sample():
    while not stop:
        try:
            j=json.loads(subprocess.run(C+['pg','dump','pgs_brief','-f','json'],capture_output=True,text=True,timeout=10).stdout)
            pgs=j['pg_stats'] if isinstance(j,dict) else j
            cnt=collections.Counter(p['state'] for p in pgs)
            log.append((time.time()-t0,dict(cnt)))
        except Exception as e: pass
        time.sleep(1)
def allclean():
    return log and log[-1][1].get('active+clean',0)==32
th=threading.Thread(target=sample);th.start()
def ev(name,cmd):
    events.append((time.time()-t0,name));subprocess.run(cmd,shell=True,capture_output=True)
def wait_clean(min_s=8,maxs=300):
    t=time.time();time.sleep(min_s)
    while not allclean() and time.time()-t<maxs: time.sleep(1)
    time.sleep(6)
time.sleep(6)
ev('osd.0 out','ceph -c '+CEPH_CONF+' osd out 0');wait_clean()
ev('osd.0 in','ceph -c '+CEPH_CONF+' osd in 0');wait_clean()
ev('osd.1 stopped',"pkill -f 'ceph-osd -c ceph.conf -i 1$'");time.sleep(25)
ev('osd.1 started','ceph-osd -c '+CEPH_CONF+' -i 1');wait_clean()
stop=True;th.join()
json.dump(dict(log=log,events=events),open('figures/data/pgstates.json','w'))
print(events);print(len(log))
for t,c in log[::5]: print(round(t,1),c)
