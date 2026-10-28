"""Version 3: equal-area sampling from an irrational torus sequence.

Horizontal input -> QWP(q) -> HWP(h). Requires numpy, matplotlib, and the
adjacent poincare_scan.py module (which defines the Stokes convention).

For n=0,1,...,N-1:
    u = frac(1/2 + n*(sqrt(5)-1)/2)
    v = frac(n*(sqrt(2)-1))
    z = 2*u-1; longitude = 2*pi*v
    q = arcsin(z)/2
    h = (longitude+2*q)/4 mod (pi/2)
Angles in these equations are radians. The first sample has q=h=0 and is H.

1, (sqrt(5)-1)/2, sqrt(2)-1 are rationally independent, making (u,v)
equidistributed on the unit square in exact arithmetic. dOmega=dz*dlongitude
shows that the equal-area mapping is asymptotically uniform on the sphere.
Finite prefixes are approximately uniform; floating-point precision is finite.

This is a sequence of measurement targets, NOT a continuous motor trajectory.
Move to each pair, settle, then measure with equal dwell time. Connecting
the targets does not give uniform time sampling of the sphere. Animation
reveals discrete samples, without drawing fictitious paths between them.

The uniform-angle comparison uses the SAME latent torus samples, but the
version-2 mapping q=180*u, h=90*v. This isolates mapping bias from scheduling.
Its initial angles are (90,0) degrees (also H); version 3 starts at (0,0).

Run: python src/poincare_equal_area_scan.py
Save: python src/poincare_equal_area_scan.py --save fig/equal_area_scan.png
Export targets: python src/poincare_equal_area_scan.py --csv data/equal_area_scan.csv
Validate: python src/poincare_equal_area_scan.py --check
"""

import argparse
import numpy as np
from poincare_scan import stokes, jones_plate, validate as validate_optics

ALPHA = (np.sqrt(5)-1)/2
BETA = np.sqrt(2)-1
BAND_EDGES = np.linspace(-1,1,17)
MODES = ('equal-area','uniform-angle')


def inverse_stokes(z, longitude):
    """Convert target s3 and longitude (radians) into QWP/HWP degrees."""
    z, longitude = np.broadcast_arrays(np.asarray(z,dtype=float),
                                       np.asarray(longitude,dtype=float))
    if np.any(~np.isfinite(z)) or np.any(np.abs(z)>1) or np.any(~np.isfinite(longitude)):
        raise ValueError('z must be finite in [-1,1], and longitude must be finite')
    q = 0.5*np.arcsin(z)
    h = np.mod((longitude+2*q)/4, np.pi/2)
    return np.rad2deg(q), np.rad2deg(h)


def scan_targets(samples=4096, mode='equal-area'):
    """Return sample indices, latent u/v, QWP/HWP degrees, and Stokes XYZ."""
    if not isinstance(samples,(int,np.integer)) or samples<1:
        raise ValueError('samples must be a positive integer')
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    n = np.arange(samples)
    u = (0.5+n*ALPHA)%1
    v = (n*BETA)%1
    if mode=='equal-area':
        q,h = inverse_stokes(2*u-1,2*np.pi*v)
    else:
        q,h = 180*u,90*v
    return n,u,v,q,h,stokes(q,h)


def band_counts(points):
    """Counts in 16 bands, each with exactly 1/16 of the sphere area."""
    return np.histogram(points[:,2],bins=BAND_EDGES)[0]


def validate():
    validate_optics()
    n,u,v,q,h,s = scan_targets()
    np.testing.assert_allclose([q[0],h[0]], [0,0], atol=1e-12)
    np.testing.assert_allclose(s[0], [1,0,0], atol=1e-12)
    z=2*u-1; r=np.sqrt(1-z*z); longitude=2*np.pi*v
    desired=np.column_stack((r*np.cos(longitude),r*np.sin(longitude),z))
    np.testing.assert_allclose(s,desired,atol=2e-12)
    np.testing.assert_allclose(np.linalg.norm(s,axis=1),1,atol=1e-12)
    # Jones propagation checks the inverse mapping independently of Stokes.
    for k in np.linspace(0,len(n)-1,101,dtype=int):
        ex,ey=jones_plate(h[k],np.pi)@jones_plate(q[k],np.pi/2)@[1,0]
        actual=[abs(ex)**2-abs(ey)**2,2*np.real(np.conj(ex)*ey),2*np.imag(np.conj(ex)*ey)]
        np.testing.assert_allclose(actual,desired[k],atol=2e-12)
    # Include poles and wrapped longitude in the inverse check.
    z_test=np.array([-1,-0.99,0,0.99,1]); lon=np.array([-9,0,2,7,20])
    qt,ht=inverse_stokes(z_test,lon)
    expected=np.column_stack((np.sqrt(1-z_test*z_test)*np.cos(lon),
                               np.sqrt(1-z_test*z_test)*np.sin(lon),z_test))
    np.testing.assert_allclose(stokes(qt,ht),expected,atol=1e-12)
    # Regression checks for area distribution, including joint z/longitude cells.
    np.testing.assert_allclose(s.mean(axis=0),0,atol=0.007)
    np.testing.assert_allclose((s*s).mean(axis=0),1/3,atol=0.007)
    joint=np.histogram2d(z,longitude,bins=[np.linspace(-1,1,9),np.linspace(0,2*np.pi,17)])[0]
    assert np.max(np.abs(joint-32))<16, 'Large equal-area cell discrepancy'
    equal=band_counts(s); biased=band_counts(scan_targets(mode='uniform-angle')[-1])
    assert equal.sum()==len(n) and np.ptp(equal)<12
    assert biased[[0,-1]].sum()>2*equal[[0,-1]].sum()
    return f'PASS: inverse/Jones mapping, initial H, poles, unit norm, joint-area cells; band counts {equal.min()}–{equal.max()} (ideal 256).'


def build_figure(samples=4096, mode='equal-area', animate=True, initial=None):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Slider, Button
    from matplotlib.animation import FuncAnimation

    scans={m:scan_targets(samples,m) for m in MODES}
    fig=plt.figure(figsize=(12,7.5))
    fig.suptitle('Version 3 · equal-area Poincaré sampling',fontsize=16)
    ax=fig.add_axes([0.02,0.29,0.52,0.58],projection='3d')
    hist=fig.add_axes([0.65,0.39,0.31,0.37])
    a,b=np.meshgrid(np.linspace(0,2*np.pi,65),np.arcsin(np.linspace(-1,1,9)))
    ax.plot_wireframe(np.cos(b)*np.cos(a),np.cos(b)*np.sin(a),np.sin(b),
                      rstride=1,cstride=8,color='0.6',alpha=0.3,lw=0.6)
    ax.set(xlabel='$s_1$',ylabel='$s_2$',zlabel='$s_3$',
           xlim=(-1.15,1.15),ylim=(-1.15,1.15),zlim=(-1.15,1.15))
    ax.set_box_aspect((1,1,1));ax.view_init(elev=22,azim=35)
    for setter in (ax.set_xticks,ax.set_yticks,ax.set_zticks): setter([-1,0,1])
    for p,label in [((1,0,0),'H'),((-1,0,0),'V'),((0,0,1),'+s₃'),((0,0,-1),'−s₃')]:
        ax.text(*(np.array(p)*1.13),label)
    cloud=ax.scatter([],[],[],s=6,color='#0072B2',alpha=0.45,depthshade=False)
    selected,=ax.plot([],[],[],'o',color='#D55E00',ms=7)
    centers=(BAND_EDGES[:-1]+BAND_EDGES[1:])/2
    bars_eq=hist.bar(centers-0.027,np.zeros(16),width=0.05,color='#0072B2',label='Equal-area (v3)')
    bars_old=hist.bar(centers+0.027,np.zeros(16),width=0.05,color='#D55E00',label='Uniform angles')
    ideal=hist.axhline(0,color='0.3',ls='--',lw=1,label='Uniform-area ideal')
    hist.set(xlim=(-1.03,1.03),ylim=(0,1),xlabel='$s_3$ (equal-area bands)',ylabel='Samples per band',
             title='Pole density comparison · same sample count')
    hist.set_xticks([-1,-0.5,0,0.5,1]);hist.legend(fontsize=9,loc='lower center',bbox_to_anchor=(0.5,1.12))
    readout=fig.text(0.5,0.23,'',ha='center',fontsize=11)
    fig.text(0.5,0.025,'Discrete measurement targets: move → settle → equal dwell time.\n'
             'Finite scans approximate uniform area; motor travel between targets is excluded.',ha='center',fontsize=10)
    slider=Slider(fig.add_axes([0.18,0.15,0.52,0.03]),'Samples shown',1,samples,
                  valinit=1 if initial is None else max(1,min(samples,initial)),valstep=1,valfmt='%d') if samples>1 else None
    play=Button(fig.add_axes([0.82,0.13,0.14,0.06]),'Play scan')
    compare=Button(fig.add_axes([0.16,0.075,0.36,0.05]),'View uniform-angle mapping')
    state={'running':False,'internal':False,'mode':mode,'count':1 if initial is None else max(1,min(samples,initial))}

    def update(_=None):
        count=int(slider.val) if slider else 1
        state['count']=count
        _,u,v,q,h,points=scans[state['mode']]
        p=points[:count]
        cloud._offsets3d=(p[:,0],p[:,1],p[:,2]);selected.set_data_3d(*points[count-1:count].T)
        ax.set_title('Equal-area targets (v3)' if state['mode']=='equal-area' else 'Uniform-angle targets (comparison)')
        eq=band_counts(scans['equal-area'][-1][:count]);old=band_counts(scans['uniform-angle'][-1][:count])
        for bars,counts in ((bars_eq,eq),(bars_old,old)):
            for bar,height in zip(bars,counts): bar.set_height(height)
        ideal.set_ydata([count/16,count/16]);hist.set_ylim(0,max(1,eq.max(),old.max())*1.18)
        k=count-1;s=points[k]
        readout.set_text(f'n = {k}   |   q = {q[k]:.2f}°   h = {h[k]:.2f}°   |   '
                         f's = ({s[0]:+.3f}, {s[1]:+.3f}, {s[2]:+.3f})')
        compare.label.set_text('View uniform-angle mapping' if state['mode']=='equal-area' else 'View equal-area mapping')
        fig.canvas.draw_idle()

    def scrub(_):
        if not state['internal']: state['running']=False;play.label.set_text('Play scan')
        update()

    def toggle(_):
        if slider is None:return
        if int(slider.val)==samples:slider.set_val(1)
        state['running']=not state['running'];play.label.set_text('Pause' if state['running'] else 'Play scan')
        fig.canvas.draw_idle()

    def change_mode(_):
        state['mode']='uniform-angle' if state['mode']=='equal-area' else 'equal-area'
        update()

    def tick(_):
        if state['running'] and slider:
            state['internal']=True;slider.set_val(min(samples,int(slider.val)+16));state['internal']=False
            if int(slider.val)==samples:state['running']=False;play.label.set_text('Replay')

    if slider:slider.on_changed(scrub)
    play.on_clicked(toggle);compare.on_clicked(change_mode);update()
    fig._equal_area_controls=(slider,play,compare,state,tick,change_mode)
    if animate and slider:fig._equal_area_animation=FuncAnimation(fig,tick,interval=40,cache_frame_data=False)
    return fig


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--samples',type=int,default=4096,help='Total targets, including initial H')
    parser.add_argument('--mode',choices=MODES,default='equal-area')
    parser.add_argument('--save',metavar='PNG')
    parser.add_argument('--csv',metavar='CSV',help='Export targets; with no --save, export and exit')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.samples<1:parser.error('--samples must be positive')
    if args.check:print(validate())
    else:
        if args.csv:
            n,u,v,q,h,s=scan_targets(args.samples,args.mode)
            np.savetxt(args.csv,np.column_stack((n,u,v,q,h,s)),delimiter=',',
                       header='n,u,v,q_deg,h_deg,s1,s2,s3',comments='',fmt=['%d']+['%.12g']*7)
            print(f'Exported {args.samples} targets to {args.csv}')
        if args.save or not args.csv:
            if args.save:
                import matplotlib
                matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig=build_figure(args.samples,args.mode,animate=not args.save,
                             initial=args.samples if args.save else 1)
            if args.save:fig.savefig(args.save,dpi=160);plt.close(fig)
            else:plt.show()
