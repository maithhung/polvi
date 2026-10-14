"""Version 2: irrational torus flow -> QWP/HWP -> Poincare sphere.

Horizontal input -> QWP(q) -> HWP(h), with the conventions of poincare_scan.py.
The optical-angle torus has periods q=180 degrees and h=90 degrees.
u(t) = t mod 1; v(t) = sqrt(2)*t mod 1
q(t) = 180*u(t); h(t) = 90*v(t).
t is dimensionless: one unit is one 180-degree QWP rotation.
The normalized torus frequency ratio is sqrt(2); the physical motor speed
ratio h_dot/q_dot is 1/sqrt(2). Real motors can run unwrapped at constant
speed; modulo is used only for display and polarization calculations.

An irrational slope gives a dense continuous orbit on the torus. Its image
is dense on the sphere because the Stokes map is continuous and onto.
This is asymptotic density, not exact finite-time or equal-area coverage.
Uniform torus dwell time produces p(s3)=1/(pi*sqrt(1-s3**2)), concentrating
samples near the poles. Motor precision and floating point are finite.

Sampling also matters: an irrational frequency ratio alone does not imply
a dense discrete sequence. We choose dt=sqrt(3)/1000. In exact arithmetic,
1, dt, sqrt(2)*dt are rationally independent, so the sampled orbit is dense.
Sampling at integer t would instead freeze u and miss most of the sphere!

Run: python poincare_torus_scan.py
Optional: --samples 24000 --ratio irrational --save torus_scan.png
Optional: --csv torus_scan.csv (unwrapped angles, wrapped angles, and Stokes)
Dependencies: numpy, matplotlib, and the adjacent poincare_scan.py module.
"""

import argparse
import numpy as np
from poincare_scan import stokes, validate as validate_optics

DT = np.sqrt(3) / 1000
IRRATIONAL_RATIO = np.sqrt(2)


def trajectory(samples=24000, ratio=IRRATIONAL_RATIO):
    """Return t, wrapped q/h angles (degrees), torus XYZ, and Stokes XYZ."""
    if not isinstance(samples, (int, np.integer)) or samples < 1:
        raise ValueError('samples must be a positive integer')
    if not np.isfinite(ratio) or ratio <= 0:
        raise ValueError('ratio must be finite and positive')
    t = np.arange(samples + 1) * DT
    u, v = t % 1, (ratio * t) % 1
    q, h = 180*u, 90*v
    a, b = 2*np.pi*u, 2*np.pi*v
    torus = np.column_stack(((1+0.36*np.cos(b))*np.cos(a),
                             (1+0.36*np.cos(b))*np.sin(a), 0.36*np.sin(b)))
    return t, q, h, torus, stokes(q, h)


def validate():
    validate_optics()
    t, q, h, torus, s = trajectory(24000)
    np.testing.assert_allclose(s[0], [1,0,0], atol=1e-12)
    np.testing.assert_allclose(np.linalg.norm(s, axis=1), 1, atol=1e-12)
    np.testing.assert_allclose(s, stokes(180*t, 90*IRRATIONAL_RATIO*t), atol=2e-12)
    np.testing.assert_allclose((np.hypot(torus[:,0],torus[:,1])-1)**2
                               +torus[:,2]**2, 0.36**2, atol=1e-12)
    # Check the map closes continuously at each angle seam.
    np.testing.assert_allclose(stokes(q+180,h), s, atol=2e-12)
    np.testing.assert_allclose(stokes(q,h+90), s, atol=2e-12)
    # Rational 1:1 normalized frequencies close after one unit of t.
    probe = np.linspace(0,1,101)
    np.testing.assert_allclose(stokes(180*probe,90*probe),
                               stokes(180*(probe+1),90*(probe+1)), atol=1e-12)
    return 'PASS: Jones checks, initial H, unit sphere, torus geometry, seams, rational closure.'


def build_figure(samples=24000, ratio=IRRATIONAL_RATIO, animate=True, initial=None):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Slider, Button
    from matplotlib.animation import FuncAnimation

    fig = plt.figure(figsize=(12,7))
    fig.suptitle('Irrational waveplate rotation: torus → Poincaré sphere', fontsize=16)
    tor_ax = fig.add_axes([0.02,0.29,0.45,0.58], projection='3d')
    sph_ax = fig.add_axes([0.52,0.29,0.45,0.58], projection='3d')
    tor_ax.set_title('Angle torus: q mod 180°, h mod 90°')
    sph_ax.set_title('Polarization: H → QWP(q) → HWP(h)')
    a,b=np.meshgrid(np.linspace(0,2*np.pi,65),np.linspace(0,2*np.pi,25))
    tor_ax.plot_wireframe((1+0.36*np.cos(b))*np.cos(a),
                          (1+0.36*np.cos(b))*np.sin(a),0.36*np.sin(b),
                          rstride=3,cstride=4,color='0.65',alpha=0.4,lw=0.6)
    tor_ax.set(xlim=(-1.5,1.5),ylim=(-1.5,1.5),zlim=(-0.8,0.8))
    tor_ax.set_box_aspect((3,3,1.6)); tor_ax.set_axis_off()
    a,b=np.meshgrid(np.linspace(0,2*np.pi,65),np.linspace(-np.pi/2,np.pi/2,25))
    sph_ax.plot_wireframe(np.cos(b)*np.cos(a),np.cos(b)*np.sin(a),np.sin(b),
                          rstride=3,cstride=4,color='0.65',alpha=0.4,lw=0.6)
    sph_ax.set(xlabel='$s_1$',ylabel='$s_2$',zlabel='$s_3$',
               xlim=(-1.15,1.15),ylim=(-1.15,1.15),zlim=(-1.15,1.15))
    for setter in (sph_ax.set_xticks,sph_ax.set_yticks,sph_ax.set_zticks):
        setter([-1,0,1])
    sph_ax.set_box_aspect((1,1,1))
    for p,label in [((1,0,0),'H'),((-1,0,0),'V'),((0,0,1),'+s₃'),((0,0,-1),'−s₃')]:
        sph_ax.text(*(np.array(p)*1.13),label)
    for ax in (tor_ax,sph_ax): ax.view_init(elev=26,azim=35)
    traces=[]
    for ax in (tor_ax,sph_ax):
        past,=ax.plot([],[],[],color='#0072B2',lw=0.7,alpha=0.48)
        recent,=ax.plot([],[],[],color='#D55E00',lw=1.8)
        dot,=ax.plot([],[],[],'o',color='#D55E00',ms=7)
        traces.append((past,recent,dot))
    readout=fig.text(0.5,0.23,'',ha='center',fontsize=11)
    mode=fig.text(0.5,0.927,'',ha='center',fontsize=11)
    fig.text(0.5,0.02,'Blue: accumulated path   •   Orange: recent path and current state\n'
             'Dense in the infinite-time limit; finite scans are approximate and not equal-area.',
             ha='center',fontsize=10)
    slider=Slider(fig.add_axes([0.17,0.14,0.54,0.03]),'Sample n',0,samples,
                  valinit=0 if initial is None else min(samples,max(0,initial)),valstep=1,valfmt='%d')
    play=Button(fig.add_axes([0.80,0.12,0.16,0.065]),'Play scan')
    compare=Button(fig.add_axes([0.08,0.065,0.33,0.05]),'Compare rational 1:1')
    state={'running':False,'internal':False,'ratio':ratio,'data':trajectory(samples,ratio)}

    def update(_=None):
        n=int(slider.val)
        t,q,h,torus,s=state['data']
        for points,(past,recent,dot) in zip((torus,s),traces):
            past.set_data_3d(*points[:n+1].T)
            recent.set_data_3d(*points[max(0,n-100):n+1].T)
            dot.set_data_3d(*points[n:n+1].T)
        readout.set_text(f't = {t[n]:.3f}   |   q = {q[n]:.2f}°   h = {h[n]:.2f}°   |   '
                         f's = ({s[n,0]:+.3f}, {s[n,1]:+.3f}, {s[n,2]:+.3f})')
        irrational=state['ratio']!=1
        mode.set_text('Normalized frequency ratio √2: dense orbit' if irrational
                      else 'Normalized frequency ratio 1: closed orbit (period t = 1)')
        compare.label.set_text('Compare rational 1:1' if irrational else 'Use irrational √2')
        fig.canvas.draw_idle()

    def scrub(_):
        if not state['internal']:
            state['running']=False; play.label.set_text('Play scan')
        update()

    def toggle(_):
        if int(slider.val)==samples: slider.set_val(0)
        state['running']=not state['running']
        play.label.set_text('Pause' if state['running'] else 'Play scan')
        fig.canvas.draw_idle()

    def change_ratio(_):
        state['ratio']=1.0 if state['ratio']!=1 else IRRATIONAL_RATIO
        state['data']=trajectory(samples,state['ratio'])
        state['running']=False; play.label.set_text('Play scan'); update()

    def tick(_):
        if state['running']:
            state['internal']=True
            slider.set_val(min(samples,int(slider.val)+30))
            state['internal']=False
            if int(slider.val)==samples:
                state['running']=False;play.label.set_text('Replay')

    slider.on_changed(scrub);play.on_clicked(toggle);compare.on_clicked(change_ratio)
    update()
    fig._torus_controls=(slider,play,compare,state,tick,change_ratio)
    if animate: fig._torus_animation=FuncAnimation(fig,tick,interval=40,cache_frame_data=False)
    return fig


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--samples',type=int,default=24000)
    parser.add_argument('--ratio',choices=['irrational','rational'],default='irrational')
    parser.add_argument('--save',metavar='PNG')
    parser.add_argument('--csv',metavar='CSV')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.samples<1: parser.error('--samples must be positive')
    ratio=IRRATIONAL_RATIO if args.ratio=='irrational' else 1.0
    if args.check:
        print(validate())
    else:
        if args.csv:
            t,q,h,_,s=trajectory(args.samples,ratio)
            np.savetxt(args.csv,np.column_stack((t,180*t,90*ratio*t,q,h,s)),delimiter=',',
                       header='t,q_unwrapped_deg,h_unwrapped_deg,q_deg,h_deg,s1,s2,s3',comments='')
        if args.save:
            import matplotlib
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig=build_figure(args.samples,ratio,animate=not args.save,
                         initial=args.samples if args.save else 0)
        if args.save: fig.savefig(args.save,dpi=160);plt.close(fig)
        else: plt.show()
