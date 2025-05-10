"""Simulation model dmc (library module, imported by figures/scripts/*.py)."""
INF=float('inf')
def sim(clients,cap=1000,secs=4,arr_rate=3000):
    # clients: name->(res,wgt,lim) in IOPS; cost=1, delta=rho=0 ; delayed tag calc (OSD uses IsDelayed=true)
    st={}
    for n,(r,w,l) in clients.items():
        st[n]=dict(ri=1/r if r else 0, wi=1/w if w else 0, li=1/l if l else 0, prev=(0.0,0.0,0.0), q=[], head=None, ready=False, served=[0]*secs, byres=[0]*secs)
    def tag(c,prev,t):
        R=max(t,prev[0]+c['ri']) if c['ri'] else INF
        P=max(t,prev[1]+c['wi']) if c['wi'] else INF
        L=max(t,prev[2]+c['li']) if c['li'] else 0.0
        return (R,P,L)
    dt=1/cap; t=0.0; nexta={n:0.0 for n in st}
    while t<secs:
        for n,c in st.items():
            while nexta[n]<=t:
                c['q'].append(nexta[n]); nexta[n]+=1/arr_rate
            if c['head'] is None and c['q']:
                a=c['q'].pop(0); c['head']=tag(c,c['prev'],a); c['ready']=False
        heads=[(c['head'][0],n) for n,c in st.items() if c['head']]
        pick=None; phase=None
        if heads:
            R,n=min(heads)
            if R<=t: pick=n; phase='res'
            else:
                for n2,c in st.items():
                    if c['head'] and not c['ready'] and c['head'][2]<=t: c['ready']=True
                rd=[(c['head'][1],n2) for n2,c in st.items() if c['head'] and c['ready'] and c['head'][1]<INF]
                if rd: pick=min(rd)[1]; phase='wgt'
        if pick:
            c=st[pick]; tg=c['head']; sec=int(t)
            c['served'][sec]+=1
            if phase=='res': c['byres'][sec]+=1
            c['prev']=tg; c['head']=None
            if phase=='wgt' and c['ri']:
                c['prev']=(tg[0]-c['ri'],tg[1],tg[2])
            if c['q']:
                a=c['q'].pop(0); c['head']=tag(c,c['prev'],a); c['ready']=False
        t+=dt
    return {n:(c['served'],c['byres']) for n,c in st.items()}
if __name__=='__main__':
    r=sim({'client':(300,1,0),'recovery':(100,1,200),'scrub':(0,2,0)})
    for k,v in r.items(): print(k,v)
    r=sim({'client':(300,1,0),'recovery':(100,1,200),'scrub':(0,2,0)},cap=350)
    for k,v in r.items(): print('cap350',k,v)
