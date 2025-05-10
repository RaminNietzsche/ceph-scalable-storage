#!/usr/bin/env python3
"""Draw figure(s) for the chapter named in the file name.

Migrated from the v1.0-v1.4 working tree; paths are repository-relative.
Run from anywhere: the script changes into the repository root first.
"""
import os as _os, sys as _sys
_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), '..', '..'))
_os.chdir(_ROOT)
_sys.path.insert(0, _os.path.join(_ROOT, 'figures', 'scripts', 'lib'))
CEPH_CONF = _os.environ.get('CEPH_CONF', '/etc/ceph/ceph.conf')
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, numpy as np
plt.rcParams['font.family']='DejaVu Sans'
# aio retry backoff
n=np.arange(1,17); d=125*2**(n-1); cum=np.cumsum(d)
fig,ax=plt.subplots(figsize=(16,6.5),dpi=110)
ax.bar(n,d/1000,color='#9EC5FE',edgecolor='k',label='sleep before retry n (ms)')
ax2=ax.twinx(); ax2.plot(n,cum/1e6,'o-',color='#C0392B',lw=2,label='cumulative wait (s)')
for i in (1,4,8,12,16):
    ax2.annotate(f'{cum[i-1]/1e6:.3f} s' if cum[i-1]<1e6 else f'{cum[i-1]/1e6:.2f} s',(i,cum[i-1]/1e6),xytext=(i-0.4,cum[i-1]/1e6+0.7),fontsize=12,color='#C0392B')
ax.set_yscale('log'); ax.set_xlabel('retry number (bdev_aio_submit_retry_max = 16)',fontsize=13); ax.set_ylabel('sleep (ms, log)',fontsize=13); ax2.set_ylabel('cumulative (s)',fontsize=13)
ax.set_xticks(n)
h1,l1=ax.get_legend_handles_labels(); h2,l2=ax2.get_legend_handles_labels(); ax.legend(h1+h2,l1+l2,loc='upper left',fontsize=13)
ax.set_title('aio_queue_t::submit_batch on -EAGAIN: usleep(delay); delay *= 2, starting at bdev_aio_submit_retry_initial_delay_us = 125',fontsize=14)
plt.tight_layout(); plt.savefig('f07_aioretry.png'); plt.close()
# bufferlist growth: append 1 MiB in small encodes
sizes=[]; total=0; cap=4096
while total<1<<20:
    sizes.append(cap); total+=cap; cap=min(cap*2,256*1024)
fig,ax=plt.subplots(figsize=(16,5.5),dpi=110)
left=0
cols=['#9EC5FE','#B8E0C2','#FFE08A','#F4A3A3','#D7C4F0','#A9E3EA']
for i,s in enumerate(sizes):
    ax.barh(0,s/1024,left=left/1024,color=cols[i%6],edgecolor='k',height=0.5)
    ax.text((left+s/2)/1024,0,f'#{i+1}\n{s//1024}K - S',ha='center',va='center',fontsize=11 if s>=16384 else 8)
    left+=s
ax.axvline(1024,color='#C0392B',ls='--'); ax.text(1024,0.35,'1 MiB appended',color='#C0392B',fontsize=13,ha='right')
ax.set_xlabel('KiB of raw_combined buffers allocated (each = alloc unit incl. S = sizeof(raw_combined))',fontsize=13); ax.set_yticks([])
ax.set_title(f'bufferlist::refill_append_space: next = min(2 x round_up(prev, 4K), 256K). Appending 1 MiB -> {len(sizes)} ptr_nodes ({total//1024} KiB) instead of 256 x 4K',fontsize=14)
ax.set_xlim(0,total/1024+10)
plt.tight_layout(); plt.savefig('f09_appendgrow.png'); plt.close()
print(sizes,total)
