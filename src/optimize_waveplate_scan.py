"""Reduce motor travel while preserving every version-3 measurement target.

Requires numpy; matplotlib is used only with --plot. Uses the adjacent
poincare_scan.py and poincare_equal_area_scan.py modules.

Assumptions: ideal QWP then HWP, horizontal input, freely rotating stages,
fixed start (0,0), open scan (no return to start), equal dwell per target.
This creates a proposed schedule; it does not control hardware. Stage limits,
backlash, acceleration and settling are not modeled.

Equivalent solutions for a generic target, angles in degrees:
  A = (q, h)
  B = (90-q, h-q)
with independent periods (180,90). These produce the same normalized Stokes
vector, up to global Jones phase. Circular states have additional degeneracy;
the version-3 target set does not include exact poles.

The objective is sum(|dq|+|dh|) by default. --objective time uses
sum(max(|dq|/q_speed, |dh|/h_speed)) for simultaneous ideal constant-speed
moves. This is a motion-time proxy, excluding acceleration/settling/dwell.
--objective balanced minimizes sum((|dq|+|dh|)**2), penalizing large jumps.
It is a compromise, not an exact minimax optimization.

Nearest-neighbor ordering is improved by open-path 2-opt. Exact two-state
dynamic programming chooses compatible solution branches along each fixed
order. Pairwise minimum branch costs alone would be inconsistent at shared
vertices, so they are not used as independent edge costs.
The overall route is a heuristic, NOT a certified global minimum.

Batch mode only reorders inside successive original blocks. At each block
boundary the measured point set exactly equals the original prefix. Arbitrary
intermediate prefixes, and measurements taken while moving, are not promised
to be uniform. The entire scan retains exactly the original area distribution.

Run: python src/optimize_waveplate_scan.py --plot
Optional: --samples 4096 --batch-size 256 --passes 3 --output data/movement_results
"""

import argparse
import itertools
import json
from pathlib import Path
import numpy as np
from poincare_scan import stokes, jones_plate
from poincare_equal_area_scan import scan_targets, band_counts
from project_paths import FIG_DIR
from config import ConfigParser

PERIODS=np.array([180.,90.])


def wrapped_delta(a,b):
    return (np.asarray(b)-np.asarray(a)+PERIODS/2)%PERIODS-PERIODS/2


def move_cost(a,b,objective='travel',speeds=(1.,1.)):
    d=np.abs(wrapped_delta(a,b))
    if objective=='travel':return d.sum(axis=-1)
    if objective=='balanced':return (d.sum(axis=-1))**2
    if objective=='time':return (d/np.asarray(speeds)).max(axis=-1)
    raise ValueError('Unknown objective')


def equivalent_settings(q,h):
    return np.stack((np.column_stack((q,h)),np.column_stack((90-q,h-q))),axis=1)%PERIODS


def best_branches(order,candidates,start=(0.,0.),objective='travel',speeds=(1.,1.)):
    """Global optimum over the two branches for a specified target order."""
    order=np.asarray(order,dtype=int)
    if not len(order):return np.empty(0,dtype=int),0.
    states=candidates[order]
    parents=np.zeros((len(order),2),dtype=int)
    costs=move_cost(start,states[0],objective,speeds)
    if order[0]==0:costs[1]=np.inf  # Initial H must remain physically at (0,0).
    for k in range(1,len(order)):
        transitions=costs[:,None]+move_cost(states[k-1,:,None,:],states[k,None,:,:],objective,speeds)
        parents[k]=np.argmin(transitions,axis=0)
        costs=transitions[parents[k],np.arange(2)]
    branches=np.empty(len(order),dtype=int);branches[-1]=int(np.argmin(costs))
    total=float(costs[branches[-1]])
    for k in range(len(order)-1,0,-1):branches[k-1]=parents[k,branches[k]]
    return branches,total


def nearest_order(ids,candidates,start,objective,speeds):
    remaining=list(map(int,ids));order=[];current=np.asarray(start,dtype=float)
    if 0 in remaining:
        remaining.remove(0);order.append(0);current=candidates[0,0]
    while remaining:
        scores=move_cost(current,candidates[remaining],objective,speeds)
        row,branch=np.unravel_index(np.argmin(scores),scores.shape)
        item=remaining.pop(row);order.append(item);current=candidates[item,branch]
    return np.array(order,dtype=int)


def two_opt(order,branches,candidates,start,objective,speeds):
    """One sweep of improving segment reversals for a symmetric open path."""
    order=order.copy();branches=branches.copy();points=candidates[order,branches].copy()
    locked=1 if len(order) and order[0]==0 else 0
    for i in range(locked,len(order)-1):
        previous=np.asarray(start) if i==0 else points[i-1]
        js=np.arange(i+1,len(order))
        change=move_cost(previous,points[js],objective,speeds)-move_cost(previous,points[i],objective,speeds)
        # Reversing a suffix changes only the incoming edge; the end is free.
        if len(js)>1:
            change[:-1]+=move_cost(points[i],points[js[:-1]+1],objective,speeds)-move_cost(points[js[:-1]],points[js[:-1]+1],objective,speeds)
        k=int(np.argmin(change))
        if change[k]<-1e-10:
            j=js[k]
            order[i:j+1]=order[i:j+1][::-1]
            branches[i:j+1]=branches[i:j+1][::-1]
            points[i:j+1]=points[i:j+1][::-1]
    return order,branches


def optimize_block(ids,candidates,start,objective,speeds,passes):
    # Keep the original order as a fallback, so this block cannot worsen it.
    original=np.asarray(ids,dtype=int)
    original_branches,original_cost=best_branches(original,candidates,start,objective,speeds)
    order=nearest_order(ids,candidates,start,objective,speeds)
    branches,cost=best_branches(order,candidates,start,objective,speeds)
    for _ in range(passes):
        trial,_=two_opt(order,branches,candidates,start,objective,speeds)
        trial_branches,trial_cost=best_branches(trial,candidates,start,objective,speeds)
        if trial_cost>=cost-1e-9:break
        order,branches,cost=trial,trial_branches,trial_cost
    return (original,original_branches) if original_cost<cost else (order,branches)


def make_route(candidates,block_size,objective='travel',speeds=(1.,1.),passes=3):
    order=[];branches=[];start=np.zeros(2)
    for lo in range(0,len(candidates),block_size):
        ids=np.arange(lo,min(lo+block_size,len(candidates)))
        o,b=optimize_block(ids,candidates,start,objective,speeds,passes)
        order.extend(o);branches.extend(b);start=candidates[o[-1],b[-1]]
    return np.asarray(order),np.asarray(branches)


def unwrap_route(order,branches,candidates):
    """Actual relative moves and continuous encoder angles; never rewrap commands."""
    settings=candidates[order,branches]
    prior=np.vstack((np.zeros((1,2)),settings[:-1]))
    delta=wrapped_delta(prior,settings)
    return delta.cumsum(axis=0),delta


def route_summary(order,branches,candidates,objective,speeds):
    angles,delta=unwrap_route(order,branches,candidates)
    travel=np.abs(delta).sum(axis=1)
    proxy=(np.abs(delta)/speeds).max(axis=1)
    return {'q_total_deg':float(np.abs(delta[:,0]).sum()),
            'h_total_deg':float(np.abs(delta[:,1]).sum()),
            'total_deg':float(travel.sum()),
            'mean_transition_deg':float(travel[1:].mean()) if len(travel)>1 else 0.,
            'max_transition_deg':float(travel.max()),
            'simultaneous_time_proxy_s':float(proxy.sum()),
            'objective_value':float((travel**2).sum() if objective=='balanced' else travel.sum() if objective=='travel' else proxy.sum()),
            'encoder_min_deg':angles.min(axis=0).tolist(),
            'encoder_max_deg':angles.max(axis=0).tolist()}


def validate_route(order,branches,candidates,expected,block_size=None):
    np.testing.assert_array_equal(np.sort(order),np.arange(len(expected)))
    assert order[0]==0 and branches[0]==0
    angles,_=unwrap_route(order,branches,candidates)
    np.testing.assert_allclose(angles[0],[0,0],atol=1e-12)
    np.testing.assert_allclose(stokes(angles[:,0],angles[:,1]),expected[order],atol=2e-11)
    np.testing.assert_array_equal(band_counts(expected),band_counts(expected[order]))
    if block_size:
        for end in range(block_size,len(order)+1,block_size):
            np.testing.assert_array_equal(np.sort(order[:end]),np.arange(end))
    for k in np.linspace(0,len(order)-1,min(100,len(order)),dtype=int):
        q,h=angles[k];ex,ey=jones_plate(h,np.pi)@jones_plate(q,np.pi/2)@[1,0]
        s=[abs(ex)**2-abs(ey)**2,2*np.real(np.conj(ex)*ey),2*np.imag(np.conj(ex)*ey)]
        np.testing.assert_allclose(s,expected[order[k]],atol=2e-11)


def self_check():
    _,_,_,q,h,s=scan_targets(8);candidates=equivalent_settings(q,h)
    for b in (0,1):np.testing.assert_allclose(stokes(candidates[:,b,0],candidates[:,b,1]),s,atol=1e-12)
    order=np.array([0,4,3,2,1,5,7,6])
    for objective in ('travel','time','balanced'):
        speeds=np.array([4.,2.])
        b,actual=best_branches(order,candidates,objective=objective,speeds=speeds)
        exhaustive=[]
        for bits in itertools.product((0,1),repeat=7):
            branch=np.array((0,)+bits);p=candidates[order,branch]
            exhaustive.append(move_cost(np.vstack((np.zeros((1,2)),p[:-1])),p,objective,speeds).sum())
        np.testing.assert_allclose(actual,min(exhaustive),atol=1e-10)
        trial,tb=two_opt(order,b,candidates,np.zeros(2),objective,speeds)
        p=candidates[trial,tb]
        assert move_cost(np.vstack((np.zeros((1,2)),p[:-1])),p,objective,speeds).sum()<=actual+1e-10
    # Near a period boundary, commands take the short physical route.
    np.testing.assert_allclose(wrapped_delta([179,89],[1,1]),[2,2])
    for size in (1,8):
        o,b=make_route(candidates,size)
        validate_route(o,b,candidates,s,size)


def make_plot(routes,candidates,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.8))
    colors=['0.5','#CC79A7','#0072B2','#D55E00']
    labels=['Original order + wrapping','Original order + branch choice','Global route','Batches of 256']
    # The actual batch size is supplied by the caller through the key.
    labels[-1]=list(routes)[-1].replace('_',' ')
    for (name,(o,b)),label,color in zip(routes.items(),labels,colors):
        _,delta=unwrap_route(o,b,candidates);distance=np.abs(delta).sum(axis=1)
        axes[0].plot(np.arange(len(o)),np.cumsum(distance),label=label,color=color,lw=1.6)
        axes[1].plot(np.arange(len(o)),np.sort(distance),label=label,color=color,lw=1.6)
    axes[0].set(xlabel='Measurement index',ylabel='Cumulative combined motor travel (°)')
    axes[1].set(xlabel='Transitions sorted by size',ylabel='Combined move per transition (°)')
    for ax in axes:ax.grid(alpha=0.2)
    axes[0].legend(fontsize=9)
    fig.suptitle('Same equal-area target set · less waveplate travel')
    fig.text(0.5,0.015,'Open scan from (0°, 0°); free rotation; equal measurement dwell; heuristic routes.',ha='center',fontsize=9)
    fig.tight_layout(rect=(0,0.055,1,0.94));fig.savefig(output,dpi=160);plt.close(fig)


def main(argv=None):
    parser=ConfigParser(description=__doc__,config_kind='optimization',formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--samples',type=int)
    parser.add_argument('--batch-size',type=int)
    parser.add_argument('--passes',type=int)
    parser.add_argument('--objective',choices=['travel','time','balanced'])
    parser.add_argument('--q-speed',type=float)
    parser.add_argument('--h-speed',type=float)
    parser.add_argument('--output',help='Directory for CSV and JSON data')
    parser.add_argument('--figure-output',help='Plot path (default: fig/<output directory name>/movement_comparison.png)')
    parser.add_argument('--plot',action=argparse.BooleanOptionalAction)
    args=parser.parse_args(argv)
    speeds=np.array([args.q_speed,args.h_speed])
    self_check()
    n,u,v,q,h,s=scan_targets(args.samples);candidates=equivalent_settings(q,h)
    original=np.arange(args.samples)
    branches,_=best_branches(original,candidates,objective=args.objective,speeds=speeds)
    routes={'original_wrapped':(original,np.zeros(args.samples,dtype=int)),
            'original_branch_optimized':(original,branches)}
    print('Optimizing full route...',flush=True)
    routes['global_optimized']=make_route(candidates,args.samples,args.objective,speeds,args.passes)
    print('Optimizing batches...',flush=True)
    batch_name=f'batches_of_{args.batch_size}'
    routes[batch_name]=make_route(candidates,args.batch_size,args.objective,speeds,args.passes)
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    summaries={}
    for name,(order,branch) in routes.items():
        validate_route(order,branch,candidates,s,args.batch_size if name==batch_name else None)
        angles,delta=unwrap_route(order,branch,candidates)
        data=np.column_stack((np.arange(args.samples),order,branch,angles,delta,s[order]))
        np.savetxt(output/f'{name}.csv',data,delimiter=',',comments='',
                   header='step,target_id,branch,q_encoder_deg,h_encoder_deg,delta_q_deg,delta_h_deg,s1,s2,s3',
                   fmt=['%d']*3+['%.17g']*7)
        exported=np.loadtxt(output/f'{name}.csv',delimiter=',',skiprows=1,ndmin=2)
        np.testing.assert_allclose(stokes(exported[:,3],exported[:,4]),s[order],atol=2e-11)
        np.testing.assert_allclose(np.diff(exported[:,3:5],axis=0),exported[1:,5:7],atol=2e-11)
        summaries[name]=route_summary(order,branch,candidates,args.objective,speeds)
    result={'samples':args.samples,'objective':args.objective,'speeds_deg_s':speeds.tolist(),
            'settings':vars(args),
            'batch_size':args.batch_size,'assumptions':'Free rotation, fixed (0,0) start, open path, no return, ideal optics, equal measurement dwell. No stage dynamics or bounds.',
            'routes':summaries,'validation':'Target permutations, every Stokes vector, Jones checks and batch checkpoints passed.'}
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if args.plot:
        figure_output=Path(args.figure_output) if args.figure_output else FIG_DIR/output.name/'movement_comparison.png'
        figure_output.parent.mkdir(parents=True,exist_ok=True)
        make_plot(routes,candidates,figure_output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
