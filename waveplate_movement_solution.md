# Reduce waveplate travel without changing the equal-area targets

The recommended solution is to keep the 4,096 version-3 target states and
reorder their measurement schedule in waveplate-angle space. Equal dwell time
at every target preserves the full scan's original approximately uniform
area distribution exactly, because no target is added, removed, or shifted.
The initial physical setting remains QWP = HWP = 0 degrees.

## Measured results

The movement metric below is the sum of the absolute physical rotations of
both plates: `abs(delta_q) + abs(delta_h)`. It is not angular distance on the
Poincare sphere. Averages cover the 4,095 transitions between 4,096 targets.

| Schedule | Total travel (deg) | Mean transition (deg) | Largest transition (deg) |
| --- | ---: | ---: | ---: |
| Original version-3 order, shortest period wrapping | 240,482.71 | 58.73 | 78.37 |
| Reordered, minimize total travel | 3,947.90 | 0.964 | 29.74 |
| Reordered, penalize large moves (recommended) | 4,047.82 | 0.988 | 6.21 |
| Reorder within original blocks of 256, minimize total travel | 25,826.24 | 6.307 | 72.88 |

The recommended route reduces total rotation by 98.32%. It uses 2.53% more
rotation than the route optimized for total travel, but reduces its largest
transition from 29.74 to 6.21 degrees. These are tested heuristic solutions,
not certified global minima. Changing the point count changes the results.

## Why the full-scan area distribution is preserved

Version 3 maps an equidistributed latent torus sequence to uniform sphere
area using `z = 2*u - 1` and `longitude = 2*pi*v`. The reordered schedule is
a permutation of precisely that existing finite point set. All area-bin
counts and all other order-independent statistics are therefore unchanged.
The 16 equal-area latitude bands still contain 255–258 targets each.

Arbitrary early prefixes of the globally optimized route are spatially
localized and can be less uniform than the original order. Batch ordering
retains the exact original prefix point set every 256 measurements, while
reducing movement within each block. It does not eliminate large moves
between blocks. It also does not make each finite prefix exactly uniform.

Uniformity applies to equal-dwell measurements after settling at the targets;
the elapsed time spent moving between them is not uniform sphere sampling.

## Physical equivalences and routing

With horizontal input followed by QWP(q) and HWP(h), a generic polarization
state has the following equivalent angle solutions (degrees):

```
A: (q, h)
B: (90 - q, h - q)
```

The QWP angle is periodic by 180 degrees and the HWP by 90 degrees for
the output polarization. Independent multiples of these periods can be
added to either solution. The equivalence follows by substituting into
`s = (cos(2q)*cos(4h-2q), cos(2q)*sin(4h-2q), sin(2q))` and was independently
verified using Jones matrices. Circular states have further degeneracy;
the present finite target sequence does not hit the poles exactly.

The implementation uses a nearest-neighbor route followed by open-path
2-opt improvements. Exact two-state dynamic programming chooses mutually
consistent A/B branches along each proposed order. Choosing an independent
minimum branch cost for every edge would not guarantee a realizable setting
at the intermediate target, so the algorithm avoids that shortcut.

Three cost functions are supported:

- `travel`: sum of `abs(delta_q) + abs(delta_h)`.
- `balanced`: sum of `(abs(delta_q) + abs(delta_h))**2`, penalizing long moves.
- `time`: sum of `max(abs(delta_q)/q_speed, abs(delta_h)/h_speed)`, assuming
  simultaneous constant-speed rotation. Acceleration, settling and dwell
  are excluded from this time proxy.

The balanced objective is not a mathematical minimax objective. A hard upper
bound on each move would require a different constrained routing problem.

## Files and usage

`src/optimize_waveplate_scan.py` depends on the existing `src/poincare_scan.py` and
`src/poincare_equal_area_scan.py`, plus NumPy. Matplotlib is needed for `--plot`.

```powershell
python src/optimize_waveplate_scan.py --objective balanced --output data/movement_balanced_results --plot
```

The recommended schedule is `data/movement_balanced_results/global_optimized.csv`.
It records step number, original target ID, chosen branch, unwrapped encoder
angles, relative moves, and the target Stokes vector. Do not force the
encoder angles back into 0–90 or 0–180 before commanding movement: this can
reintroduce long rotations. Use the documented unwrapped positions or the
relative increments according to the controller's command semantics.

Machine-readable benchmark details are in each output folder's `summary.json`.

## Assumptions and validation

The benchmarks assume freely rotating stages, ideal waveplate retardances,
an open scan with no required return to start, and equal target dwell time.
The recommended QWP encoder range is approximately -362.72 to 0.03 degrees;
the HWP range is approximately -383.16 to 217.48 degrees. Bounded stages need
their actual limits included in route and angle selection. Backlash and
acceleration can also change the preferred objective and route.

Checks included branch equivalence, exhaustive small-case branch optimization,
non-increasing 2-opt cost, exact target permutations, every output Stokes
vector, independent Jones propagation, batch-prefix preservation, and all
eight exported CSV schedules' angles and relative movements.

## References

- [University of Waterloo: nearest-neighbor and 2-opt route improvement](https://www.math.uwaterloo.ca/tsp/app/diy.html).
- [G. A. Croes, A Method for Solving Traveling-Salesman Problems (1958)](https://doi.org/10.1287/opre.6.6.791).

The waveplate branch identity, adaptation to an open path, and numerical
results above were derived and checked specifically for this optical model.

Optimization figures are stored separately under `fig/movement_balanced_results/`.
