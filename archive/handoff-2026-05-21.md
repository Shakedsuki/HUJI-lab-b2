# Handoff — 3.2V tracker rebuild + video-by-video verification

Session ended **2026-05-21** (third session of the day). This session
rebuilt the BGR tracker on top of the previous session's bbox/porthole
crop with three more layers of fixes, then began walking the 3.2V
family one clip at a time under the new pipeline. **9 of 34 3.2V clips
visually verified end-to-end** before handoff to the user, who is
running the remaining bulk re-track + render themselves in PowerShell.

---

## TL;DR — current state

- **Tracker pipeline is final for this phase.** Detection: tight
  4·arm bbox + inscribed disc mask + green-proximity disk for red.
  Centroids: sub-pixel floats (no int truncation). Rigid-arm
  constraint projection onto pivot-circle and green-circle. Light
  5-frame median smoother on positions, then re-project. Phase
  string in CSV is `"driven"` (was `"free_swing"`).
- **Overlay rendering is final.** Hard crop to 6·arm bbox around the
  pivot with `BORDER_REPLICATE` padding, circular porthole crop with
  corners filled by the median frame colour. Three constraint
  circles (yellow / green / red, each radius = arm length) drawn
  every frame. Clip-id header `<voltage>V  <freq>Hz` at the top-left.
  Filename: `<stem>_overlay.mp4` (not the old ambiguous `overlay.mp4`).
- **Verification tally was reset this session.** Old
  `tracking_quality=verified` flags were auto-derived from dropout%
  under the buggy tracker — not credible. Wiped clean; only clips
  watched end-to-end under the new tracker count as verified.
- **Tooling:** `scripts/utils/bulk_retrack_render.py` (sequential) and
  `scripts/utils/parallel_retrack_render.py` (worker pool) wrap the
  per-clip pipeline: copy video → re-track → render. Both honour
  `--filter`, `--skip-rendered`, `--skip <stems>`, `--workers N`.
- **Master tip:** `04b778f` (PR #55 — gitignore tweak). Worktree
  branch: `claude/jolly-torvalds-e44a90`, also fully merged.

## 3.2V family tally (34 clips total)

```
verified  (9):  0.9Hz, 1.28Hz, 1.29Hz, 1.30Hz, 1.31Hz, 1.32Hz,
                1.33Hz_1, 1.33Hz_2, 1.34Hz
                — visually approved end-to-end under the new tracker

untracked (25): 0.91-0.99Hz (9), 1.00Hz, 1.09Hz, 1.15-1.27Hz (13),
                1Hz (failed pile; original-rig calibration)
```

22 of those 25 untracked already have overlay.mp4s rendered (pool ran
through them) — they just haven't been visually reviewed yet. 12 are
truly missing (overlay not yet rendered).

## Next session's main task

**Walk through the remaining 25 clips in the 3.2V family, in your
preferred order, and approve each via the overlay video.** Methodology:

```powershell
# In C:\dev\chaos (main repo, not the worktree — videos live here)
$env:CHAOS_PHASE = "week4-pendulum-motor-driven"

# 1. Re-track + render anything that needs it (skips already-verified
#    and already-rendered):
python scripts/utils/parallel_retrack_render.py --filter 3.2V_ `
    --order desc --skip-rendered --workers 2

# 2. Open an overlay
start week4-pendulum-motor-driven\measurements\3.2V_<stem>\3.2V_<stem>_overlay.mp4

# 3. Watch end-to-end. If clean, mark verified:
python -c "import json; p='week4-pendulum-motor-driven/data/experiments.json'; \
  r=json.load(open(p)); \
  [e.update(tracking_quality='verified', verification_date='2026-05-22', \
            verification_notes='Visually verified.') \
   for e in r.values() if e.get('config_description')=='3.2V_<stem>']; \
  json.dump(r, open(p,'w'), indent=2)"
```

Recommended order: highest frequency first (continuing the
descending-frequency walk from this session). The 1.20–1.27 range is
the most chaotic and the most likely to expose any remaining tracker
edge cases.

### Known race in parallel_retrack_render

If the user marks a clip verified WHILE the bulk pool is still running
and the pool's worker for that clip races, the pool's write will
clobber the verified flag back to `untracked`. **Workaround:** mark
clips verified only after the pool finishes (or kill the pool, mark,
restart with `--skip-rendered`). Happened once this session on
3.2V_1.29Hz — re-marked at end of session.

The fix is a real lock on `experiments.json` or a "re-tracking
verified clips downgrades them" rule — leave for next session.

## What landed this session (PRs #49 → #55)

```
04b778f Merge PR #55 — gitignore: exclude *_overlay_compressed.mp4
412e429 Merge PR #54 — bulk + parallel retrack-render helpers; 14 tracks
5bee46b Merge PR #53 — clip-id header + <stem>_overlay.mp4 naming; 5 verified
b25f71e Merge PR #52 — reset tracking_quality tally for new pipeline
f9e0a54 Merge PR #51 — 5-frame median smoothing on positions
df811c5 Merge PR #50 — sub-pixel float centroids + rigid-arm projection
37d45d2 Merge PR #49 — porthole crop, three constraint circles, driven phase
```

Key insight progression this session:

1. **Punchlist from the user's 3.2V_0.9Hz watch:** jitter at rest,
   FREE_SWING label wrong, three constraint circles missing, wrong-blob
   red at t≈12.796s, crop to physically-reachable disc, red short of
   sticker. Six items.
2. **Cosmetic block first** (PR #49 → PR #53 cosmetic parts): DRIVEN
   label, three circles, real bbox crop, then upgraded to circular
   porthole at user's request when the rectangle crop felt incomplete.
3. **Then physics block:** Jitter at rest had three layers —
   int-truncation noise (killed by sub-pixel float), arm-length noise
   (killed by rigid-arm projection), broadband detector noise
   (suppressed by 5-frame median). Each layer measured; ω std at rest
   went 3 → 1.7 → 1.33 °/s. Display rounds to 0 °/s at rest now.
4. **The projection layer also fixes the red-short-of-sticker bug**
   geometrically: radial projection onto the green circle pulls
   on-rod red detections out to the actual marker tip.
5. **The wrong-blob bug at t≈12.796s was NOT explicitly triaged.**
   The new bbox + green-proximity disc may already have killed it
   (the offending t=12.796s frame on the new 3.2V_0.9Hz overlay
   looked clean). Verify when you re-visit the punchlist.

## Active code paths

- **Tracker:** `scripts/processing/bgr_tracker.py`
  - `reachable_bbox(pivot, arm, frame_shape)` — tight 4·arm bbox.
  - `_project_to_circle(px, py, qx, qy, r)` — radial rigid-arm projection.
  - `detect_markers_bgr(frame, pivot, arm, red_search_r_sq)` — bbox
    crop + disc mask + green-proximity disc + projection + float centroids.
  - Post-loop: 5-frame median on (x_green, y_green, x_red, y_red),
    re-projection, theta recompute.
  - Writes phase="driven" to CSV.

- **Sanity-check render:** `scripts/analysis/overlay_video.py`
  → writes `<stem>_overlay.mp4` (was `overlay.mp4`).

- **Full render:** `scripts/analysis/combined_video.py`
  - `make_left_panel(frame, ..., stem=None)` — clip-id header parsed
    from stem, three constraint circles, circular porthole.
  - Worth a re-run on a Week-4 clip if you want a phase-portrait
    render after verification.

- **Helpers:**
  - `scripts/utils/bulk_retrack_render.py` — sequential
  - `scripts/utils/parallel_retrack_render.py` — worker pool

- **Cohen's original (never modify):**
  `week4-pendulum-motor-driven/legacy/get_video_coords.py`

## What's queued / pending

| | | |
|---|---|---|
| **3.2V remaining 25** | Re-track + render (if not done) + visual verify each | open, user driving |
| **Wrong-blob @ t≈12.796s (punchlist #4)** | Re-watch on the new 3.2V_0.9Hz overlay to confirm it's gone | likely already fixed, unverified |
| **Race in parallel_retrack_render** | Real file lock OR "re-track downgrades verified" rule | open |
| **Stale tools needing CROP_X_START rewrite** | `verify_bgr_baseline.py`, `diagnose_frames.py`, `capture_bgr_baseline.py` | open — also baseline check is no longer credible because new tracker diverges from Cohen by design |
| **3V / 4V clips** | Never re-tracked under new tracker; old `tracking_quality` cleared in PR #52. Will need same video-by-video pass before any cross-voltage analysis. | open |
| **Physics analysis** | Poincaré, bifurcation, Lyapunov on the verified clips. Use `driven_helpers.load_driven_csv` (accepts both "driven" and "free_swing" phase labels). | open, blocked on verification |

## How to resume

```powershell
cd C:\dev\chaos
git log --oneline -5                              # should top with 04b778f
$env:CHAOS_PHASE = "week4-pendulum-motor-driven"

# Render any remaining overlays:
python scripts/utils/parallel_retrack_render.py --filter 3.2V_ `
    --order desc --skip-rendered --workers 2

# Open one and watch:
start week4-pendulum-motor-driven\measurements\3.2V_1.27Hz\3.2V_1.27Hz_overlay.mp4

# When clean, mark verified (see snippet above in "Next session's main task")
```

## User preferences observed this session

- **Visual is the test.** Numerical 0% dropout means nothing if the
  overlay shows wrong-blob or wandering markers. Walk every clip
  end-to-end before approving.
- **No bulk verification.** The 21 clips PRs #46/#47 shipped UNVERIFIED
  are NOT trustworthy until each is watched. Tally reset enforces this.
- **"Render the next two ahead"** — pre-pipeline overlays so the user
  doesn't have to wait between approvals. Worker pool for the bulk.
- **Architectural fixes preferred over band-aids** — the int→float
  precision leak was fixed at the source (CSV stores floats), not
  patched in display rounding. The "filter at source for consistency"
  argument carried.
- **Push back on fixes that change physics.** The user explicitly
  challenged whether the constraint-circle projection was the right
  fix for jitter; turned out projection preserves angle so it
  doesn't actually move θ — but the challenge was right. Math out
  what each layer does to the data before shipping.
- **Self-identifying renders.** Filename includes the stem; header
  inside the video includes voltage + frequency. The user runs many
  clips in different players.
- **"Ship it" = push + PR + merge + pull-to-main.** Each coherent
  unit shipped as its own PR. 7 PRs (#49–#55) this session.
- **The user takes over when the work is mechanical.** Parallel pool
  was running on the user's machine and slowing it down; user opted
  to run it themselves in PowerShell with their own throttling. The
  agent stops, hands off the command line, gets out of the way.
