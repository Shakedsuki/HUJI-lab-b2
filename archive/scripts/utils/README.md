# Archived scripts

These scripts were once part of `scripts/utils/` but were moved out
because they're **not part of the routine workflow**. They fall into
four categories:

| Category | Scripts |
|---|---|
| **Bootstrap / setup** (run once per fresh checkout) | `download_videos.py`, `register_phase2_videos.py` |
| **Workflow tools from the 3.2V verification pass** (that pass is done) | `bulk_retrack_render.py`, `parallel_retrack_render.py`, `scan_tracking_quality.py` |
| **Regression fixture for Cohen's BGR detection** (re-run only if `scripts/processing/bgr_tracker.py` is materially edited) | `capture_bgr_baseline.py`, `verify_bgr_baseline.py` |
| **Maintenance / debugging utilities** (use when something goes wrong) | `override_frame.py`, `recompute_theta.py`, `diagnose_frames.py` |

## How to use one

All of these were standalone CLIs at their original location. To run
one from `archive/`, either invoke it directly:

```bash
python archive/scripts/utils/download_videos.py
```

…or `git mv` it back to `scripts/utils/` if you anticipate using it
repeatedly. The originals' import paths (`from paths import …`) are
relative to `scripts/utils/`, so they keep working from the archive
location because `scripts/utils/` is still on `sys.path` via the same
`sys.path.insert(0, …)` pattern they all use.

## Restoring one to the active set

```bash
git mv archive/scripts/utils/<name>.py scripts/utils/<name>.py
```

If the script was wired into `chaos.py` (like `override_frame.py` was
to `chaos override`), restore the corresponding `SCRIPT_<NAME>` constant,
the `cmd_<name>` function, the `add_parser("<name>", …)` block, and
the dispatch entry in the `CMDS` dict.

## Per-script notes

### `override_frame.py`
Was wired to `chaos override <stem> --frame N`. Manually rewrites one
row of `tracking.csv` after interactive marker re-positioning, then
re-verifies. Useful when one frame is wrong but the rest of the trace
is good. Archived because the BGR tracker is now producing clean
output end-to-end — manual overrides haven't been needed in the
current generation of clips.

### `download_videos.py`
Pulls all raw `.mov` files from the public Google Drive folder via
`gdown`. Run once per fresh checkout. The README quickstart points
at this archived location.

### `register_phase2_videos.py`
Scans `experiments/week5-6-…/videos/` for new `.mov` files and adds
pre-tracking entries to `experiments.json`. Idempotent — re-run when a
new batch of clips arrives. All 62 current videos are already registered.

### `bulk_retrack_render.py` / `parallel_retrack_render.py`
Wrappers that copy a video from the main checkout into a worktree,
re-track it with the current `bgr_tracker.py`, then render
`<stem>_overlay.mp4` for visual review. Sequential and worker-pool
variants. Used heavily during the 3.2V verification pass (2026-05-21);
unused since then.

### `capture_bgr_baseline.py` / `verify_bgr_baseline.py`
Regression fixture: `capture_*` writes per-frame centroid baselines
from Cohen's verbatim detection logic; `verify_*` asserts that the
production `bgr_tracker.py` produces matching output. Baselines live in
`experiments/week5-6-…/baselines/`. Re-run only if `bgr_tracker.py` is
materially edited and you want to confirm no behavioural drift from
[`archive/cohen_get_video_coords.py`](../../cohen_get_video_coords.py).

### `scan_tracking_quality.py`
One-shot quality scan that walks every clip with `verification.csv`
and emits a PASS/FAIL table. Output is tracked at
`experiments/week5-6-…/data/tracking_quality_post_bulk.csv`.

### `diagnose_frames.py`
Renders a grid of source frames with the tracked markers drawn on
top — a debugging tool for inspecting the tracker output without
producing a full overlay video.

### `recompute_theta.py`
Recomputes `theta1_deg` in `tracking.csv` files after a PIVOT or
ARM_LENGTH calibration change, without a full re-track. Rotates the
old CSV to `.prepivotfix.bak` first.
