"""Simulation model tb (library module, imported by figures/scripts/*.py)."""
def run(avg,burst,bsec,secs=8,demand=10**9,idle_until=0,tmin=50):
    tick=max(1000//avg,tmin); tps=1000//tick
    mx=burst or avg; cap=mx*max(bsec,1); remain=cap; avail=0
    ratio=mx/avg if mx>avg else 1.0
    f=lambda x:int(x/tps*avg)
    cur=0; out=[]; want=0
    for t in range(secs*tps):
        if cur>=tps: cur=0
        cur+=1; tok=f(cur)-f(cur-1)
        remain=min(cap,remain+tok)
        inc=int(tok*ratio) if ratio>1 else tok
        up=min(remain,mx); avail=min(avail+inc,up)
        if t>=idle_until*tps:
            g=min(avail,demand); avail-=g; remain-=g; out.append(g)
        else: out.append(0)
    return tick,tps,out
if __name__=='__main__':
    tk,tps,o=run(100,300,2)
    import itertools
    print(tk,tps,[sum(o[i*tps:(i+1)*tps]) for i in range(8)])
    tk,tps,o=run(100,0,1); print([sum(o[i*tps:(i+1)*tps]) for i in range(8)])
    tk,tps,o=run(100,300,2,idle_until=3); print([sum(o[i*tps:(i+1)*tps]) for i in range(8)])
