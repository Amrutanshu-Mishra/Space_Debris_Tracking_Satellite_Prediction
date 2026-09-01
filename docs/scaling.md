# Conjunction-screening pipeline — scaling

How the `prahari_orbital` screening pipeline scales with catalogue size, from
**measured** runs at 1 000 / 2 000 / 4 000 objects, plus a power-law
**extrapolation** to the full 16 049-object active catalogue.

All runs: 72 h window, 60 s coarse step, `PRAHARI_DATA_SOURCE` cache
`active_20260829T120000Z.tle`, deterministic LEO-weighted sample
(`pipeline._select_leo_weighted`, seed 20260829), screening threshold 10 km,
`screen.py` linear-chord coarse bound (`_PASS2_SAGITTA_PAD_KM = 12`).

## Funnel — measured vs extrapolated

| size | objects usable | raw pairs | apogee/perigee survivors | pass 1 out | pass 2 → brentq | events | RED / AMBER / GREEN | wall | peak RSS |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **1 000** *(monolithic)* | 998 | 497 503 | 281 265 | 77 710 | 9 390 | **4 681** | 266 / 2 280 / 2 135 | ~79 s | ~0.9 GiB¹ |
| **2 000** *(block driver)* | 1 996 | 1 991 010 | 1 157 067 | 338 507 | 37 033 | **18 531** | 917 / 9 098 / 8 516 | 300 s | 2.38 GiB |
| **4 000** *(block driver)* | 3 995 | 7 978 015 | 4 581 177 | 1 380 211 | 146 427 | **72 939** | 3 576 / 35 702 / 33 661 | 1 566 s | 3.58 GiB |
| **16 049** *(extrapolated)* | ~16 000 | 128 777 176 | **~75.6 M** | **~25.0 M** | **~2.30 M** | **~1.14 M** | ~5 % / ~49 % / ~46 % | ~5–6 h² | ~3.6 GiB³ / ~10 GiB⁴ |

Rows 1 000 / 2 000 / 4 000 are **measured**. The 16 049 row is **extrapolated**
(method below) and is an over-estimate — see caveat 1.

¹ Monolithic run reports only the `tracemalloc` heap (628 MB per
`propagate_catalog` call); ~0.9 GiB whole-process is an estimate.
² Not a fit — see "Wall time" below.
³ Chunked block driver, `--block 2000` (peak is flat in total size: the largest
object union is always 2 blocks = 4 000 objects).
⁴ A single monolithic `propagate_catalog(16049)` at float64; ~5 GiB at float32.
This is why the block driver exists.

## Per-pair conversion rates (measured)

| size | apogee/perigee survival | pass 1 keep | pass 2 keep (of pass 1) | events / brentq pair | events / raw pair |
|---|--:|--:|--:|--:|--:|
| 1 000 | 0.5653 | 0.2763 | 0.1208 | 0.4985 | 0.009409 |
| 2 000 | 0.5811 | 0.2926 | 0.1094 | 0.5004 | 0.009307 |
| 4 000 | 0.5742 | 0.3013 | 0.1061 | 0.4981 | 0.009142 |

The rates are stable across a 16× span in pair count. `events / raw pair`
declines very slightly (0.00941 → 0.00931 → 0.00914); the tier split is
essentially constant at ~5 % RED / ~49 % AMBER / ~46 % GREEN.

## Method

**Fit.** For each funnel stage `y`, ordinary least squares of `ln y` on
`ln P` across the three measured points, where `P` = raw pair count
= `n·(n−1)/2`. Fitted exponents (`y ∝ P^b`):

| stage | b | note |
|---|--:|---|
| apogee/perigee survivors | 1.006 | ~linear in pair count |
| pass 1 out | 1.037 | mildly super-linear |
| pass 2 → brentq | 0.990 | ~linear |
| events | 0.990 | ~linear |

**Extrapolation.** Evaluate each fit at `P = 128 777 176` (the full 16 049
catalogue, `16049·16048/2`). Because every stage is ≈ linear in `P` and
`P ∝ n²`, all counts grow ≈ `n²`.

**Wall time** is **not** extrapolated from the block-driver runs: the driver
re-propagates each object once per block-pair it appears in, so its wall is
topology-dependent (N=2000 is one block with no redundancy; N=4000 is two
blocks / three screen calls). A shared-propagation full run is estimated
separately: pass 3 is the dominant cost, and the monolithic N=1000 run refined
9 390 pairs in 51.8 s (181 brentq pairs/s); ~2.30 M pairs at that rate is
~3.5 h, with pass 1 + pass 2 sweeps adding ~1–2 h, hence ~5–6 h total,
single-threaded.

## Caveats — read before quoting the 16 049 numbers

1. **The samples are LEO-oversampled; the full catalogue is not.**
   `_select_leo_weighted` draws objects with perigee < 2 000 km at 4× weight
   (`pipeline.LEO_OVERSAMPLE_WEIGHT`). The 1 000 / 2 000 / 4 000 samples are
   ~99 % LEO. The full 16 049-object catalogue is the whole population
   (~65–75 % LEO), so its LEO–LEO pair fraction — where nearly all conjunctions
   occur — is roughly **2× lower**. The mechanical extrapolation therefore
   **overshoots**: expect the true full-catalogue event count nearer
   **0.5–0.8 M** than the fitted 1.14 M, and `pass 2 → brentq` nearer
   ~1.2–1.6 M than 2.30 M.

2. **"Events" is a geometric close-approach count at 10 km, not actionable
   conjunctions.** Relative-velocity median ~10 km/s (genuine crossings), but
   the set is heavily Starlink-dominated and includes many multi-approach
   co-orbiting same-shell pairs (one N=1000 pair produced 82 approaches). There
   is no covariance / Pc gate (public TLEs carry no covariance — by project
   rule). Operational "hundreds of events" figures already exclude
   intra-constellation pairs and apply a probability gate.

3. **`apogee_perigee_filter` does not scale as written.** At 16 049 objects it
   builds `np.triu_indices(16049)` (2 × 129 M int64 ≈ 2 GB) and a sorted
   Python list of ~75 M `(int, int)` tuples (~5 GB). The block-vs-block driver
   (`tools/run_scaling_point.py`) side-steps this with an array-only
   block-pair sweep using the identical arithmetic; a full run needs that path,
   not the library function.

4. **Peak RSS for the block driver is flat in total size** (~3.6 GiB at
   `--block 2000`) because the largest object union screened at once is two
   blocks. Smaller `--block` lowers the ceiling further at the cost of more
   redundant re-propagation.

## Reproduce

```
# measured points (from services/orbital/)
python -m prahari_orbital.pipeline --objects 1000 --hours 72 --out ev_1000.json
python tools/run_scaling_point.py --objects 2000 --block 2000 --hours 72 \
    --max-mem-gb 4.0 --out ev_2000.json --summary sum_2000.json
python tools/run_scaling_point.py --objects 4000 --block 2000 --hours 72 \
    --max-mem-gb 4.0 --out ev_4000.json --summary sum_4000.json
```

`run_scaling_point.py` chunks propagation into `--block`-sized groups
(float32), runs the apogee/perigee filter block-vs-block, and drives
`screen.screen_candidates` once per block pair so its internal shared
re-propagation never exceeds two blocks. It prints the per-stage funnel,
conversion rates, wall time, and peak working-set size, and aborts if peak
crosses `--max-mem-gb`.
