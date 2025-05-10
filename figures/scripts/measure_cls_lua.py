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
c=rados.Rados(conffile=CEPH_CONF);c.connect();io=c.open_ioctx('m33')
script='''
function count_lines(input, output)
  local size = objclass.stat()
  local data = objclass.read(0, size)
  local s = data:str()
  local _, n = s:gsub("\\n", "")
  output:append(tostring(n))
end
objclass.register(count_lines)
'''
req=json.dumps({'script':script,'handler':'count_lines','input':''}).encode()
line=b'x'*63+b'\n';R=[]
for sz in [64<<10,256<<10,1<<20,4<<20,16<<20]:
    io.write_full(f'L{sz}',line*(sz//64))
    for _ in range(3): io.execute(f'L{sz}','lua','eval_json',req,length=64)
    a=[];b=[];na=nb=None
    for _ in range(15):
        t=time.perf_counter();ret,out=io.execute(f'L{sz}','lua','eval_json',req,length=64);a.append(time.perf_counter()-t);na=int(out)
        t=time.perf_counter();d=io.read(f'L{sz}',sz);nb=d.count(b'\n');b.append(time.perf_counter()-t)
    r=dict(size=sz,lines=sz//64,lua=na,client=nb,lua_ms=st.median(a)*1e3,client_ms=st.median(b)*1e3,lua_reply=len(str(na)),client_bytes=sz,req_bytes=len(req))
    R.append(r);print(r,flush=True)
json.dump(R,open('figures/data/lua15.json','w'))
