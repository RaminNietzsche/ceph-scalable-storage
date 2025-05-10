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
D='figures/ch17/'
# f05 find_best_info table
rows=[('osd.1 (primary)',40,"41'120","41'20",'no','candidate; loses on tail'),
      ('osd.4',40,"41'118","40'10",'no','candidate; older last_update'),
      ('osd.7',38,"38'300","37'50",'no','OUT: les 38 < max_les 40'),
      ('osd.9',40,"41'120","40'90",'no','BEST: newest lu, longer tail')]
fig,ax=plt.subplots(figsize=(16,6.5)); ax.axis('off')
hdr=['shard','last_epoch_started','last_update','log_tail','missing?','find_best_info result']
colc=[]
for r in rows:
    c='#D5F5E3' if r[5].startswith('BEST') else '#FADBD8' if r[5].startswith('OUT') else '#FDFEFE'
    colc.append([c]*6)
t=ax.table(cellText=[[str(x) for x in r] for r in rows],colLabels=hdr,cellColours=colc,loc='upper center',cellLoc='center',colColours=['#D6EAF8']*6)
t.auto_set_font_size(False); t.set_fontsize(13); t.scale(1,2.6)
for (r,c),cell in t.get_celld().items(): cell.set_width([0.14,0.15,0.12,0.12,0.09,0.32][c])
ax.text(0.5,0.3,"step 1  max_les = max(history.les, les of complete infos) = 40\nstep 2  min_last_update_acceptable = min(last_update | les >= 40) = 41'118\nstep 3  filter (lu >= 41'118, les >= 40, not incomplete) -> osd.1, osd.4, osd.9\nstep 4  newest last_update (replicated pool) -> osd.1, osd.9   step 5  smaller log_tail wins: 40'90 < 41'20 -> osd.9",ha='center',va='center',fontsize=13,family='DejaVu Sans Mono',bbox=dict(fc='#FEF9E7',ec='#B7950B'))
ax.set_title("PeeringState::find_best_info on a replicated PG (eversion = epoch'version)",fontsize=15)
fig.tight_layout(); fig.savefig(D+'f05_bestinfo.png',dpi=110)
# f06 slow op backoff
fig,ax=plt.subplots(figsize=(16,5.5))
ct=30; m=1; warns=[]
for t in range(0,400):
    if t>ct*m: warns.append((t,m)); m*=2
ax.hlines(0,0,400,color='#5D6D7E',lw=6); ax.axvline(ct,color='#E67E22',ls='--'); ax.text(ct+3,0.75,'osd_op_complaint_time = 30 s (op counted as slow from here)',fontsize=12,color='#E67E22')
for k,(t,mm) in enumerate(warns):
    ax.plot([t],[0],'v',ms=16,color='#C0392B'); ax.text(t,-0.35 if k%2 else 0.2,f't={t}s\nlog warning\nmultiplier {mm} -> {mm*2}',ha='center',fontsize=11)
ax.set_ylim(-1,1); ax.set_yticks([]); ax.set_xlabel('seconds since op initiated (checks assumed every 1 s)')
ax.set_title('OpTracker::with_slow_ops_in_flight: an op stuck for 400 s is logged at ~31, 61, 121, 241 s (multiplier doubles; at most osd_op_log_threshold = 5 ops logged per check)',fontsize=12)
fig.tight_layout(); fig.savefig(D+'f06_slowop.png',dpi=110)
# f07 scrub schedule
rng=np.random.default_rng(7); day=1.0
sh=1*day+1*day*0.5*rng.random(100000)
sdv=7*0.2; dp=np.clip(rng.normal(7,sdv,100000),7-2*sdv,7+2*sdv)
fig,ax=plt.subplots(1,2,figsize=(16,6.5))
ax[0].hist(sh,bins=60,color='#2E86C1'); ax[0].set_title('shallow: last + min_interval*(1 + 0.5*U[0,1])'); ax[0].set_xlabel('days after last scrub'); ax[0].set_xlim(0.9,1.6)
ax[0].set_ylim(0,2400); ax[0].text(1.0,2200,'window [1.0, 1.5] days; osd_scrub_max_interval (7 d) forces a scrub if missed',fontsize=11)
ax[1].hist(dp,bins=80,color='#27AE60'); ax[1].set_title('deep: last + clamp(N(7d, 1.4d), 4.2d, 9.8d)'); ax[1].set_xlabel('days after last deep scrub')
inside=np.mean((dp>=5.6)&(dp<=8.4))
ax[1].axvspan(5.6,8.4,color='#F9E79F',alpha=.4); ax[1].text(5.65,2350,f'[0.8,1.2]x7d holds {inside*100:.0f}%',fontsize=12)
fig.suptitle('ScrubJob::adjust_shallow_schedule / adjust_deep_schedule with defaults (min 1 day, randomize 0.5, deep 7 days, cv 0.2), 100k samples',fontsize=13)
fig.tight_layout(); fig.savefig(D+'f07_scrubsched.png',dpi=110)
print(warns, inside, np.mean(dp==4.2)+np.mean(dp==9.8))
