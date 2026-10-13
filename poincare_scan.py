"""Interactive Poincare-sphere scan: horizontal input -> QWP(q) -> HWP(h).

Run: python poincare_scan.py
Dependencies: python -m pip install numpy matplotlib
Save a static plot without opening a window:
    python poincare_scan.py --save poincare_scan.png

Angles are fast-axis angles from +x toward +y in a fixed transverse basis.
J(theta, delta) = R(theta) diag(1, exp(i delta)) R(-theta).
Normalized Stokes convention: s1=|Ex|^2-|Ey|^2, s2=2 Re(Ex* Ey),
s3=2 Im(Ex* Ey), for a unit Jones vector; * means complex conjugation.
This convention explicitly fixes the circular-polarization sign; we avoid
R/L labels, which depend on viewing and time conventions.

An ideal waveplate cannot polarize unpolarized light. A horizontal linear
polarizer (or an already horizontally polarized source) is required upstream.
Both rotatable fast axes are horizontal at q=h=0. No offsets are assumed.
Reversing the plate order changes the mapping.

For q in [-45,45] degrees, latitude=2q and longitude=4h-2q.
h in [0,90] degrees closes a full latitude circle. Boundaries coincide and
all h values coincide at either pole. Equal angle steps are NOT equal-area:
dOmega = 8 cos(2q) dq dh, with q,h in radians.
"""

import argparse
import numpy as np


def stokes(q_deg, h_deg):
    """Return (..., 3) normalized Stokes coordinates; broadcast input arrays."""
    q, h = np.broadcast_arrays(np.deg2rad(q_deg), np.deg2rad(h_deg))
    lon = 4 * h - 2 * q
    return np.stack((np.cos(2*q)*np.cos(lon),
                     np.cos(2*q)*np.sin(lon), np.sin(2*q)), axis=-1)


def jones_plate(theta_deg, retardance):
    """Independent Jones-matrix implementation for physical validation."""
    t = np.deg2rad(theta_deg)
    r = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    return r @ np.diag([1, np.exp(1j*retardance)]) @ r.T


def validate():
    """Check the mapping against Jones propagation, including known states."""
    np.testing.assert_allclose(stokes(0, 0), [1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(stokes(0, 45), [-1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(stokes(0, 22.5), [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(stokes(45, 0), [0, 0, 1], atol=1e-12)
    rng = np.random.default_rng(42)
    for q, h in rng.uniform(-360, 360, (100, 2)):
        ex, ey = jones_plate(h, np.pi) @ jones_plate(q, np.pi/2) @ [1, 0]
        expected = [abs(ex)**2-abs(ey)**2,
                    2*np.real(np.conj(ex)*ey), 2*np.imag(np.conj(ex)*ey)]
        np.testing.assert_allclose(stokes(q, h), expected, atol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(stokes(q, h)), 1, atol=1e-12)


def build_figure(animate=True):
    import matplotlib.pyplot as plt
    from matplotlib.widgets import Slider, Button
    from matplotlib.animation import FuncAnimation

    fig = plt.figure(figsize=(12, 8))
    ax = fig.add_axes([0.02, 0.31, 0.62, 0.61], projection='3d')
    angle_ax = fig.add_axes([0.73, 0.36, 0.23, 0.46])
    fig.suptitle('Horizontal input → QWP(q) → HWP(h)', fontsize=16)
    ax.set(xlabel='$s_1$ (H − V)', ylabel='$s_2$ (+45° − −45°)',
           zlabel='$s_3$', xlim=(-1.15, 1.15), ylim=(-1.15, 1.15),
           zlim=(-1.15, 1.15))
    ax.set_box_aspect((1, 1, 1))
    ax.set_xticks([-1, -0.5, 0, 0.5, 1])
    ax.set_yticks([-1, -0.5, 0, 0.5, 1])
    ax.set_zticks([-1, -0.5, 0, 0.5, 1])
    ax.view_init(elev=22, azim=35)

    # The grid is parameterized by actual motor angles, not sphere longitude.
    for q in np.linspace(-45, 45, 13):
        points = stokes(q, np.linspace(0, 90, 241))
        ax.plot(*points.T, color='0.65', lw=0.6, alpha=0.55)
    for h in np.linspace(0, 90, 13)[:-1]:
        points = stokes(np.linspace(-45, 45, 181), h)
        ax.plot(*points.T, color='0.65', lw=0.6, alpha=0.55)
    for xyz, label in [((1,0,0),'H'), ((-1,0,0),'V'), ((0,1,0),'+45°'),
                       ((0,-1,0),'−45°'), ((0,0,1),'+s₃'), ((0,0,-1),'−s₃')]:
        ax.text(*(np.array(xyz)*1.10), label, ha='center')

    latitude_line, = ax.plot([], [], [], color='#0072B2', lw=2,
                             label='Sweep h; fixed q')
    meridian_line, = ax.plot([], [], [], color='#D55E00', lw=2,
                             label='Sweep q; fixed h')
    trail, = ax.plot([], [], [], color='#009E73', lw=1.6, label='Scan trail')
    marker, = ax.plot([1], [0], [0], 'o', color='#CC79A7', ms=9)
    radial, = ax.plot([0,1], [0,0], [0,0], color='#CC79A7', lw=1.5)
    ax.legend(loc='upper left', fontsize=9)

    angle_ax.set(xlim=(0,90), ylim=(-45,45), xlabel='HWP h (degrees)',
                 ylabel='QWP q (degrees)', title='Waveplate-angle coordinates')
    angle_ax.set_xticks([0,22.5,45,67.5,90])
    angle_ax.set_yticks([-45,-22.5,0,22.5,45])
    angle_ax.grid(alpha=0.25)
    horizontal = angle_ax.axhline(0, color='#0072B2')
    vertical = angle_ax.axvline(0, color='#D55E00')
    angle_marker, = angle_ax.plot([0], [0], 'o', color='#CC79A7', ms=8)
    readout = fig.text(0.5, 0.245, '', ha='center', fontsize=12)
    fig.text(0.5, 0.015, 'Drag the sphere to rotate the view. Equal angle steps '
             'give denser sampling near the poles.', ha='center', fontsize=10)

    q_slider = Slider(fig.add_axes([0.19,0.16,0.61,0.025]), 'QWP q (°)', -45,45,
                      valinit=0, valfmt='%1.1f°')
    h_slider = Slider(fig.add_axes([0.19,0.10,0.61,0.025]), 'HWP h (°)', 0,90,
                      valinit=0, valfmt='%1.1f°')
    button = Button(fig.add_axes([0.84,0.10,0.13,0.075]), 'Start scan')
    # Serpentine raster in motor-angle coordinates, continuous at row changes.
    scan = [(q,h) for i,q in enumerate(np.linspace(-45,45,31))
            for h in np.linspace(0,90,61)[::1 if i % 2 == 0 else -1]]
    state = {'running': False, 'i': 0, 'trail': [], 'updating': False}

    def update(_=None):
        q, h = q_slider.val, h_slider.val
        p = stokes(q,h)
        latitude_line.set_data_3d(*stokes(q,np.linspace(0,90,241)).T)
        meridian_line.set_data_3d(*stokes(np.linspace(-45,45,181),h).T)
        marker.set_data_3d(*p[:,None])
        radial.set_data_3d(*np.array([[0,0,0],p]).T)
        horizontal.set_ydata([q,q]); vertical.set_xdata([h,h])
        angle_marker.set_data([h],[q])
        readout.set_text(f'(q, h) = ({q:.1f}°, {h:.1f}°)    '
                         f'(s₁, s₂, s₃) = ({p[0]:+.3f}, {p[1]:+.3f}, {p[2]:+.3f})')
        fig.canvas.draw_idle()

    def slider_changed(_):
        if not state['updating']:
            state['running'] = False
            button.label.set_text('Resume scan' if state['i'] else 'Start scan')
        update()

    def toggle(_):
        if state['i'] == len(scan):
            state.update(i=0, trail=[])
            trail.set_data_3d([],[],[])
        state['running'] = not state['running']
        button.label.set_text('Pause scan' if state['running'] else 'Resume scan')
        fig.canvas.draw_idle()

    def tick(_):
        if not state['running']:
            return
        q,h = scan[state['i']]
        state['updating'] = True
        q_slider.set_val(q); h_slider.set_val(h)
        state['updating'] = False
        state['trail'].append(stokes(q,h))
        trail.set_data_3d(*np.asarray(state['trail']).T)
        state['i'] += 1
        if state['i'] == len(scan):
            state['running'] = False
            button.label.set_text('Scan again')

    q_slider.on_changed(slider_changed); h_slider.on_changed(slider_changed)
    button.on_clicked(toggle)
    update()
    # Keep widgets and animation alive for the lifetime of the figure.
    fig._scan_controls = (q_slider, h_slider, button, tick, state)
    if animate:
        fig._scan_animation = FuncAnimation(fig, tick, interval=35, cache_frame_data=False)
    return fig


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--save', metavar='PATH', help='Save a static figure and exit')
    parser.add_argument('--check', action='store_true', help='Validate physics and exit')
    args = parser.parse_args()
    validate()
    if args.check:
        print('PASS: reference states, unit norm, and 100 Jones-matrix comparisons.')
    else:
        if args.save:
            import matplotlib
            matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        figure = build_figure(animate=not args.save)
        if args.save:
            figure.savefig(args.save, dpi=160)
            plt.close(figure)
        else:
            plt.show()
