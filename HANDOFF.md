# Handoff — driven-pipeline cleanup & 3.2V tracking triage

Session ended **2026-05-21**. The next session should be able to pick up exactly where this one left off without re-reading the chat.

---

## TL;DR — current state

- **Pipeline is fully cleaned and consistent** (binary PASS/FAIL verdict, dropout-only criterion, Cohen's BGR detection wrapped in pipeline I/O with X-only crop).
- **Baselines pass MATCH × 3** — `verify_bgr_baseline.py --all` confirms the wrapped tracker reproduces Cohen's standalone bit-for-bit on the 3 reference clips (4V_1.9Hz, 4V_0.6Hz, 3V_1Hz).
- **62 clips registered** in `week4-pendulum-motor-driven/data/experiments.json` (29 from earlier batches + 33 newly registered 3.2V sweep clips from 0.9–1.34 Hz).
- **Bulk re-track NOT done** under the final code state. Earlier bulks completed but with different code; the data on master from PR #40 was the last clean bulk-tracked snapshot before the Y-crop experiment.

## The open problem (next session's main task)

The **3.2V × 0.9-1.34 Hz sweep clips have a systemic wrong-blob tracking problem.** BGR finds two blobs every frame (0% dropout) but the red detection wanders into wall-fabric / curtain in the upper part of the frame whenever the actual red marker briefly blurs or dims.

Visual evidence:
- `week4-pendulum-motor-driven/measurements/3.2V_0.91Hz/diagnostic.png` — frame 995, peak \|ω₂\| = 5275 °/s
- `week4-pendulum-motor-driven/measurements/3.2V_0.93Hz/diagnostic.png` — frame 729, peak \|ω₂\| = 5608 °/s
- `week4-pendulum-motor-driven/measurements/3.2V_1.20Hz/diagnostic.png` — frame 3173, peak \|ω₂\| = 5902 °/s

Numerical signature on a failing clip:
- 0% dropout
- arm-length (green↔red pixel distance) varies 8–500 px instead of the constant ~153 px (rigid rod)
- peak \|ω₂\| 4000–8500 °/s (physically impossible; absurd cap is 4000)

This is **not** a problem with Cohen's BGR ranges per se — it's that BGR's "find brightest red blob in crop window" doesn't know a marker from a curtain when both happen to be in range. Cohen's standalone script has the same behaviour; he just never visualized it.

### Approaches considered, none committed

| Approach | Result |
|---|---|
| **Y crop [180, 780]** (tried in-session, reverted) | Cleaned wrong-blob on 3.2V but cut off legitimate inverted-marker positions on 4V_0.6Hz — dropped from 98% → 75% both-found. The Y bounds tight enough to exclude wall fabric also exclude full inversions. |
| **Wider Y crop e.g. [50, 850]** | Not tried. Likely a compromise — keeps some inversion but lets some wall fabric in. |
| **Geometry gate (post-detection sanity)** | Not tried. `\|distance(green,red) - 153\| > tolerance` → reject red, mark dropout. Mechanically clean. User was wary of "harnesses" but this is a *detection* filter not a *verdict* check. |
| **Tighter X crop** | Not tried. Wall fabric is in the upper-Y region, not on the right side, so X crop probably won't help. |
| **Tighter red BGR ranges** | Not tried. Would need per-clip color sampling. Cohen's ranges are intentionally loose for fallback. |
| **Drop 3.2V sweep from analysis** | Last-resort option. Loses the new high-resolution dataset. |

**My recommendation for next session:** start with the **geometry gate** (option C). It's the only one that mechanically *guarantees* a tracking error gets flagged, and it leaves Cohen's detection logic untouched at the BGR layer. About 4 lines added to `bgr_tracker.detect_markers_bgr`:

```python
# After computing gx, gy, rx, ry:
if gx is not None and rx is not None:
    arm_dist = ((gx - rx)**2 + (gy - ry)**2) ** 0.5
    if abs(arm_dist - ARM_LENGTH_PX) > ARM_LENGTH_PX * 0.30:
        rx = ry = None  # treat as dropout
```

Tolerance 30% (~46 px) is generous — allows for genuine marker position variation while rejecting blobs that are way off. Tune empirically.

After applying the gate:
1. Re-capture baselines (`capture_bgr_baseline.py` does NOT include the gate — would need to mirror, or the regression baselines become "before-gate" reference)
2. Bulk-track just the 33 new 3.2V clips
3. Run `scan_tracking_quality.py` to confirm dropout is now reasonable
4. If wrong-blob frames now become genuine dropouts and dropout-% stays under 5% → PASS, move on to analysis
5. If dropout-% blows past 5% → the BGR detector genuinely loses the marker on these clips; option E (skip) becomes the realistic call

## What landed on master in this session

Master tip: **`96ef146` Merge pull request #41 from Shakedsuki/claude/phase2-diagnose-frames**

Recent history (latest first):
```
96ef146 Merge PR #41 — diagnose_frames.py visual tracker sanity check
4c9b587 Merge PR #40 — bulk re-track 62 clips (revealed wrong-blob signal)
6038f11 Merge PR #39 — scan_tracking_quality.py
aa8ab45 Merge PR #38 — schema slim + stale-doc touch-ups
6478b6d Merge PR #37 — remove dead tools (triage, suspects, friction-*)
96cb2a5 Merge PR #36 — trim verify + drop interpolate
65d88c9 Merge PR #35 — remove HSV tracker stack
921f167 Merge PR #34 — repo restructure (week-based folders, parallel agent)
2f9243e Merge PR #33 — register 33 clips of 3.2V sweep
fb7da12 Merge PR #32 — integrate Cohen's BGR detection
```

Plus this session's wrap-up commit (PR-D-style verdict simplification + Y-crop revert + 2 new diagnostic PNGs as evidence) — see the next merge for the SHA.

## Active code paths

- **Tracker:** `scripts/processing/bgr_tracker.py` — Cohen's BGR detection (X-only crop, no Y crop, no geometry gate)
- **Verify:** `scripts/processing/verify_tracking.py` — ω via SG smoothing + dropout count only. No suspect detection.
- **Verdict:** `scripts/utils/track_one.py` `compute_verdict()` — binary PASS / FAIL on `dropout_pct > 5%`. One criterion, one threshold.
- **Bulk:** `scripts/utils/bulk_track.py` — loops track_one over registry entries
- **Scanner:** `scripts/utils/scan_tracking_quality.py` — per-clip PASS/FAIL table with dropout %
- **Diagnostics:** `scripts/utils/diagnose_frames.py` — renders sample frames with green/red crosshairs overlaid, the "visual sanity check" tool
- **Regression:** `scripts/utils/capture_bgr_baseline.py` + `verify_bgr_baseline.py` — bit-equality check against Cohen's standalone
- **Cohen's original:** `week4-pendulum-motor-driven/legacy/get_video_coords.py` — **never modify**

Registry schema for new entries (`bgr_tracker.update_registry_entry` and `register_phase2_videos.make_entry`):
- Frame-0 ICs use `theta1_initial` / `omega1_initial` (renamed from `*_release`)
- `n_frames` (not `n_free_frames`)
- Dropped: `init_frame`, `release_frame`, `tag_frame`, `t0_offset_s`, `energy_proxy`, `green_roi`, `red_roi`, `ring_tolerance`, `suspect_frames_interpolated`, `interpolation_date`

## What's queued / pending

| | | |
|---|---|---|
| **PR H** | Week-folder rename: `week3` → `week3-4`, `week4` → `week5-6` (to reflect actual 2-weeks-each lab schedule) | not started |
| **Wrong-blob fix** | See triage options above. Next session's main task. | open |
| **Bulk re-track all 62 clips** under final pipeline | Last done with old (multi-criterion) verdict; need to re-do once wrong-blob is fixed | open |
| **Analysis phase** | `chaos figures` + bifurcation diagrams + per-clip Poincaré / Lyapunov. The actual goal. Blocked on wrong-blob fix. | open |

## How to resume

```bash
cd C:/dev/chaos
git log --oneline -5                              # confirm at master tip
CHAOS_PHASE=week4-pendulum-motor-driven \
    python scripts/utils/verify_bgr_baseline.py --all
# Expect: 3/3 MATCH. If so, the pipeline state is clean.

# View the wrong-blob evidence:
# week4-pendulum-motor-driven/measurements/3.2V_0.91Hz/diagnostic.png
# week4-pendulum-motor-driven/measurements/3.2V_0.93Hz/diagnostic.png
# week4-pendulum-motor-driven/measurements/3.2V_1.20Hz/diagnostic.png

# When ready to apply the geometry gate fix:
# Edit scripts/processing/bgr_tracker.py detect_markers_bgr
# Re-capture baselines: for stem in 4V_1.9Hz 4V_0.6Hz 3V_1Hz; do
#     CHAOS_PHASE=week4-pendulum-motor-driven \
#         python scripts/utils/capture_bgr_baseline.py --stem $stem
# done
# Then bulk only new 3.2V clips:
#     CHAOS_PHASE=week4-pendulum-motor-driven \
#         python chaos.py bulk --redo --filter 3.2V_
# Then scan:
#     CHAOS_PHASE=week4-pendulum-motor-driven \
#         python scripts/utils/scan_tracking_quality.py --filter 3.2V_
```

## User preferences observed this session

- **Aggressive minimalism on the verdict layer.** "Only keep the dropout rate" was an explicit instruction. Don't reintroduce arm-length / peak-ω / swap checks as verdict criteria. The geometry gate I'm proposing is detection-layer, not verdict-layer — but be ready to defend the distinction.
- **Cohen's `get_video_coords.py` is untouchable.** It's at `week4-pendulum-motor-driven/legacy/`. New behavior goes into wrapper scripts that extend Cohen's logic.
- **Visual sanity-check over numerical safeguards.** Prefer `diagnose_frames.py` output as the trust signal rather than chains of automated checks.
- **PR-per-coherent-unit.** Each cleanup arc shipped as a small focused PR (#35–41 in this session). Same pattern going forward.
- **Lights-out autonomy when the plan is clear.** When the user says "execute uninterrupted," it means make the reasonable call and ship.
