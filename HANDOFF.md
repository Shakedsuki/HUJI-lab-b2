# Handoff — 3.2V family video-by-video visual triage

Session ended **2026-05-21** (second session of the day). The first session of the day fixed the wall-fabric wrong-blob problem (see `git log` PR #43); this session added per-batch rig calibration (PR #45) and shipped most of the 3.2V data refresh (PRs #46, #47). The session was halted after the user spotted a **visible problem in 3.2V_0.9Hz's overlay video that the numerical stats did not reveal**. Next session must triage video-by-video with visual verification as the primary acceptance bar.

---

## TL;DR — current state

- **Code is solid and shipped.** ROI replaces the wall-fabric gate (PR #43). Per-batch pivot/arm resolver (PR #45) is correct on 3.2V_1.34Hz visually. `overlay_video.py` exists for fast sanity-check renders (PR #44).
- **21 of 33 3.2V clips re-tracked with new pivot, all 0.00% dropout numerically.** Shipped in PRs #46 (0.9–1.15 Hz, 13 clips) and #47 (1.16–1.23 Hz, 8 clips, UNVERIFIED).
- **12 clips still un-tracked with the new pivot**: 1.24, 1.25, 1.26, 1.27, 1.28, 1.29, 1.30, 1.31, 1.32, 1.33_1, 1.33_2, 1.34.
- **3.2V_1Hz is in the failed pile** — 1.36% dropout, predates the 3.2V rig (matches the 3V/4V calibration). Needs dedicated triage.
- **Master tip:** `ab45570` (PR #47 merge). Worktree branch: `claude/gifted-yalow-74debc` (now merged + presumably already in main via `git pull origin master`).

## The open problem (next session's main task)

The user identified a **visual problem in 3.2V_0.9Hz's overlay** that the numerical checks all passed:
- 0% dropout
- Green circle fit matches the canonical 3.2V pivot (583, 331) within sub-pixel
- Arm-length distribution healthy (median 154, max 164)
- Detection residual std 0.58 px

**The user didn't describe what they saw yet — ask them first.** Possible failure modes the stats can't catch:
- Red marker visibly landing on the wrong physical object on some frames despite passing geometry checks
- Yellow pivot dot off the joint (rendering issue, not tracking)
- Theta1/theta2 jumps not reflected in dropout
- Time-localized issue (specific frames have markers in wrong places)

**The methodology this session got wrong** was "stats look good → ship". Next session's bar: **visual verification of the overlay video is the primary acceptance criterion**, not dropout %.

### Process for each clip (video-by-video, no bulk)

```powershell
$stem = "<clip>"
cd C:\dev\chaos
$env:CHAOS_PHASE = "week4-pendulum-motor-driven"
python scripts/processing/bgr_tracker.py week4-pendulum-motor-driven/videos/$stem.mov --force
python scripts/analysis/overlay_video.py --stem $stem
start week4-pendulum-motor-driven/measurements/$stem/overlay.mp4
# ── user watches the full overlay ──
# If visual problem: stop, triage with diagnose_frames.py / direct frame inspection.
# If clean: move to next clip.
```

**Do not run more than one clip at a time.** Do not batch. Do not ship until each clip is individually approved by the user.

### Recommended starting order

1. **3.2V_0.9Hz** (re-render and inspect; figure out what the user saw)
2. Then walk the previously-shipped clips that have NOT been visually verified yet:
   - PR #46's 13 clips (0.91–1.15 Hz) — only 1.34Hz was visually verified before shipping
   - PR #47's 8 clips (1.16–1.23 Hz) — none visually verified
3. Then the 12 still-un-tracked clips (1.24–1.34Hz including 1.33×2)
4. Then 3.2V_1Hz from the failed pile

## What landed this session

```
ab45570 Merge PR #47 — data: 3.2V part 2 (1.16-1.23 Hz, UNVERIFIED)
57c448c Merge PR #46 — data: 3.2V part 1 (0.9-1.15 Hz, 13 clips, all 0% dropout)
cb81296 Merge PR #45 — per-batch rig calibration + left-column overlay strip
97ab436 Merge PR #44 — overlay_video: standalone tracking-overlay renderer
4ad3eeb Merge PR #43 — bgr_tracker: replace geometry gate with green-proximity ROI
```

Key insights from this session:
- **Calibration mismatch on 3.2V**: rig was repositioned between 3V/4V calibration and 3.2V sweep recording. Pivot moved ~80 px left, arm length ~5% longer. Now handled by `thresholds.get_pivot_arm(stem)`.
- **3.2V_1Hz is from the OLD rig** — its arm-length signature (median 152, max 159) matches the 3V/4V calibration, not the 3.2V rig (median 156, max 165). It's excluded from the new branch in `get_pivot_arm`.
- **The wall-fabric ROI works on every clip we tested numerically** — the issue surfaced this session is something different (visual, possibly off-marker detection passing the ROI gate).

## Active code paths

- **Tracker:** `scripts/processing/bgr_tracker.py` — BGR detection + green-proximity ROI + per-batch pivot
- **Sanity-check render:** `scripts/analysis/overlay_video.py` — fast overlay-only render (~10–20 s/clip)
- **Full render:** `scripts/analysis/combined_video.py` — overlay + 3 phase-space panels (slow, ~1–2 min/clip)
- **Frame-level diagnostic:** `scripts/utils/diagnose_frames.py` — grid of N frames with crosshairs
- **Regression:** `scripts/utils/verify_bgr_baseline.py` — 3/3 MATCH on 3V_1Hz / 4V_0.6Hz / 4V_1.9Hz reference clips
- **Per-batch resolver:** `scripts/utils/thresholds.py::get_pivot_arm(stem)` — pivot/arm constants per batch
- **Cohen's original (never modify):** `week4-pendulum-motor-driven/legacy/get_video_coords.py`

## What's queued / pending

| | | |
|---|---|---|
| **3.2V_0.9Hz visual problem** | User saw something. Ask, reproduce, classify, fix. | open |
| **Re-verify PR #46 + #47 data** | 21 clips shipped without visual check. Walk each via overlay. | open |
| **Track remaining 12 3.2V clips** | 1.24-1.34Hz + 1.33×2 still on the old (pre-pivot-fix) data | open |
| **Failed pile** | 3.2V_1Hz (1.36% dropout, original rig). Dedicated triage. | open |
| **3V/4V clips** | Use canonical pivot, never re-tracked this session. Should still be correct but unverified for visual issues. | open |

## How to resume

```powershell
cd C:\dev\chaos
git log --oneline -8                              # confirm at master tip ab45570 or later
$env:CHAOS_PHASE = "week4-pendulum-motor-driven"

# Verify the pipeline is intact
python scripts/utils/verify_bgr_baseline.py --all  # expect 3/3 MATCH

# Re-render the overlay the user reported a problem with
python scripts/analysis/overlay_video.py --stem 3.2V_0.9Hz
start week4-pendulum-motor-driven/measurements/3.2V_0.9Hz/overlay.mp4

# Then ask the user: "What did you see in 3.2V_0.9Hz's overlay?"
```

## User preferences observed this session

- **Visual sanity check IS the test.** Numerical 0% dropout means nothing if the overlay shows wrong-blob frames or off-marker detections. This is the lesson of this session — don't ship without visually verifying.
- **No bulk.** Per the user's explicit cadence: track one clip → triage if <99% → fix → re-track → next clip. The user broke their own rule for efficiency once we'd seen many clean clips, and that's what bit us.
- **Failed pile is OK.** Clips below 99% get parked in a documented "failed pile" rather than blocking progress. They're triaged separately at the end.
- **Per-batch calibration is hardcoded constants, not auto-fit per-clip.** `get_pivot_arm(stem)` uses stem prefix. New batches → add new constants + update the resolver.
- **Cohen's `get_video_coords.py` is untouchable.** New behavior goes into wrapper scripts (`bgr_tracker.py`).
- **"Ship it" = push + PR + merge + pull-to-main.** Standard cycle. PRs are auto-merged once user gives the word.
- **Aggressive minimalism.** Don't add new gates/thresholds/safeguards unless absolutely needed. ROI removed the old gate — strictly better single mechanism.
- **Conversation cadence:** user wants short, focused updates per action. Long-form planning OK when proposing a strategy change.

## Quick reference: per-batch constants in thresholds.py

```python
# Canonical 3V/4V batch (and 3.2V_1Hz which predates the 3.2V sweep)
PIVOT         = (663, 332)
ARM_LENGTH_PX = 153

# 3.2V sweep batch (rig was repositioned ~80 px left)
PIVOT_3_2V         = (583, 331)
ARM_LENGTH_PX_3_2V = 161

# Resolver: get_pivot_arm(stem) -> (pivot, arm_length_px)
# - if stem.startswith("3.2V_") and stem != "3.2V_1Hz": returns PIVOT_3_2V, ARM_LENGTH_PX_3_2V
# - else: returns PIVOT, ARM_LENGTH_PX
```
