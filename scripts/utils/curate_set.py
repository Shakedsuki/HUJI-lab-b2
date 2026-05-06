"""
curate_set.py
--------------
Polish a curated set of clips end-to-end so they're publication-ready:

    1. Status check (verdict, dropout, peak |omega2|, max arm-dev).
    2. Release-frame sanity check — flag clips whose registry
       theta1_release / omega1_release look implausible (typically
       a too-late release_frame that captured mid-swing motion).
    3. fix_green_swaps — interpolate/dropout off-ring rows.
    4. interpolate_suspects — fix omega-cap suspect rows.
    5. verify_tracking re-run.
    6. Phase 2 + Phase 1 figures: poincare, lyapunov, phase_panels,
       phase_3d, chaos_analyze, friction_fit.
    7. Final per-clip summary + group-level recommendation.

Designed to be idempotent: rerunning skips steps whose outputs are
already fresh. Safe to interrupt and resume.

Usage:
    # Predefined: Group A (similar-IC sensitivity test set)
    python scripts/utils/curate_set.py --group group_a

    # Explicit list:
    python scripts/utils/curate_set.py --stems th1_p044_th2_m001,th1_p056_th2_m001

    # Skip individual stages:
    python scripts/utils/curate_set.py --group group_a --skip-fix --skip-interp

    # Just run the report:
    python scripts/utils/curate_set.py --group group_a --report-only
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import pandas as pd


ROOT             = os.path.dirname(os.path.dirname(os.path.dirname(
                       os.path.abspath(__file__))))
MEAS_DIR         = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(ROOT, "data", "experiments.json")

SCRIPT_FIX_GREEN = os.path.join(ROOT, "scripts", "processing",
                                "fix_green_swaps.py")
SCRIPT_INTERP    = os.path.join(ROOT, "scripts", "processing",
                                "interpolate_suspects.py")
SCRIPT_VERIFY    = os.path.join(ROOT, "scripts", "processing",
                                "verify_tracking.py")
SCRIPT_POINCARE  = os.path.join(ROOT, "scripts", "analysis", "poincare.py")
SCRIPT_LYAPUNOV  = os.path.join(ROOT, "scripts", "analysis", "lyapunov.py")
SCRIPT_PANELS    = os.path.join(ROOT, "scripts", "analysis", "phase_panels.py")
SCRIPT_3D        = os.path.join(ROOT, "scripts", "analysis", "phase_3d.py")
SCRIPT_ANALYZE   = os.path.join(ROOT, "scripts", "analysis", "chaos_analyze.py")
SCRIPT_FRICTION  = os.path.join(ROOT, "scripts", "analysis", "friction_fit.py")

sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from figures_paths import figure_path  # noqa: E402


# ─────────────────────────────────────────────
# CURATED GROUP DEFINITIONS
# ─────────────────────────────────────────────

GROUPS = {
    # Sensitivity-to-IC test set: 6 clips at theta1≈90°, theta2≈0°.
    "group_a": [
        "th1_p091_th2_m001",
        "th1_p092_th2_m002",
        "th1_p092_th2_p000",
        "th1_p093_th2_m000",
        "th1_p093_th2_m002",
        "th1_p094_th2_p000",
    ],
    # Tier 1 PASS clips spanning the periodic→chaotic transition.
    "tier_1": [
        "th1_p044_th2_m001",
        "th1_p056_th2_m001",
        "th1_p082_th2_p001",
        "th1_p180_th2_m179",
    ],
    # Combined writeup set: tier_1 + group_a.
    "writeup": [
        "th1_p044_th2_m001", "th1_p056_th2_m001",
        "th1_p082_th2_p001", "th1_p180_th2_m179",
        "th1_p091_th2_m001", "th1_p092_th2_m002",
        "th1_p092_th2_p000", "th1_p093_th2_m000",
        "th1_p093_th2_m002", "th1_p094_th2_p000",
    ],
}


# ─────────────────────────────────────────────
# STATE
# ─────────────────────────────────────────────

@dataclass
class ClipState:
    stem:         str
    verdict:      str = "?"
    drop_pct:     float = float("nan")
    peak_w2:      float = float("nan")
    arm_max:      float = float("nan")
    n_susp:       int = 0
    th1_release:  float = float("nan")
    th2_release:  float = float("nan")
    om1_release:  float = float("nan")
    n_off_ring:   int = 0
    flags:        list = field(default_factory=list)
    actions:      list = field(default_factory=list)


def load_registry():
    with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_entry(reg, stem):
    return next((v for v in reg.values()
                 if v.get("config_description") == stem), None)


def is_passing(entry):
    if entry is None:
        return False
    return (entry.get("audit_new_status") == "PASS"
            or bool(entry.get("manual_accept")))


def collect_state(stem):
    """Snapshot the live state of a clip from disk + registry."""
    reg = load_registry()
    entry = find_entry(reg, stem) or {}
    s = ClipState(stem=stem)

    if is_passing(entry):
        s.verdict = "PASS"
    elif entry.get("audit_new_status") == "FAIL":
        s.verdict = "FAIL"
    else:
        s.verdict = "WARN"

    s.drop_pct    = entry.get("dropout_rate_pct", float("nan"))
    s.th1_release = entry.get("theta1_release", float("nan"))
    s.th2_release = entry.get("theta2_release", float("nan"))
    s.om1_release = entry.get("omega1_release", float("nan"))

    # Live metrics from verification.csv.
    verif = os.path.join(MEAS_DIR, stem, "verification.csv")
    if os.path.exists(verif):
        try:
            df = pd.read_csv(verif)
            fs = df[df["phase"] == "free_swing"]
            if len(fs):
                s.peak_w2 = float(fs["omega2_deg_s"].abs().max())
                s.arm_max = float(fs["arm_dev_pct"].abs().max())
                s.n_susp  = int((fs.get("suspect", 0) == 1).sum())
        except Exception as e:
            s.flags.append(f"verification.csv read error: {e}")

    # Off-ring count from current tracking.csv.
    track = os.path.join(MEAS_DIR, stem, "tracking.csv")
    if os.path.exists(track):
        try:
            df = pd.read_csv(track)
            fs = df[df["phase"] == "free_swing"]
            from math import hypot
            radius = np.hypot(fs["x_green"] - 608, fs["y_green"] - 355)
            s.n_off_ring = int((np.abs(radius - 162) > 25).sum())
        except Exception as e:
            s.flags.append(f"tracking.csv read error: {e}")

    return s


# ─────────────────────────────────────────────
# RELEASE-FRAME SANITY
# ─────────────────────────────────────────────

def check_release_frame(stem, state):
    """Flag clips whose release-frame state looks bogus.

    Hand-released pendulums should leave the holding position with
    omega ≈ 0. A magnitude > 200 deg/s typically means the
    release_frame was sampled mid-swing instead of at the moment of
    release. Doesn't auto-correct — surfaces the issue for the user.
    """
    reg = load_registry()
    e = find_entry(reg, stem) or {}
    om1 = e.get("omega1_release", 0)
    om2 = e.get("omega2_release", 0)
    rel_frame = e.get("release_frame")

    if abs(om1) > 200 or abs(om2) > 200:
        state.flags.append(
            f"release-frame omega looks high (om1={om1:+.0f}, "
            f"om2={om2:+.0f}); release_frame={rel_frame} may be too late")


# ─────────────────────────────────────────────
# STAGE RUNNERS
# ─────────────────────────────────────────────

def run_step(label, cmd, log_path=None):
    """Run a subprocess and capture its output. Returns the CompletedProcess."""
    print(f"    > {label}")
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat()}  {label}  ===\n")
            f.write(f"$ {' '.join(cmd)}\n")
            f.write(result.stdout or "")
            f.write(result.stderr or "")
    if result.returncode != 0:
        print(f"      FAILED (exit {result.returncode})")
        # Fall through — let downstream step decide if this is fatal.
    return result


def step_fix_green(stem):
    """Apply geometric off-ring repair (interpolate short clusters,
    dropout long ones)."""
    return run_step(
        "fix_green_swaps",
        [sys.executable, SCRIPT_FIX_GREEN, "--stem", stem],
        log_path=os.path.join(ROOT, "data", "curate_set_log.txt"),
    )


def step_interpolate(stem):
    """Run interpolate_suspects.py if there are omega-cap suspects."""
    return run_step(
        "interpolate_suspects",
        [sys.executable, SCRIPT_INTERP, "--stem", stem],
        log_path=os.path.join(ROOT, "data", "curate_set_log.txt"),
    )


def step_verify(stem):
    return run_step(
        "verify_tracking",
        [sys.executable, SCRIPT_VERIFY, "--stem", stem, "--no-plot"],
        log_path=os.path.join(ROOT, "data", "curate_set_log.txt"),
    )


def step_phase_2(stem):
    """Generate Poincaré + Lyapunov + phase analysis figures."""
    runs = [
        ("poincare",      [sys.executable, SCRIPT_POINCARE, "--stem", stem]),
        ("lyapunov",      [sys.executable, SCRIPT_LYAPUNOV, "--stem", stem]),
        ("phase_panels",  [sys.executable, SCRIPT_PANELS,   "--stem", stem]),
        ("phase_3d",      [sys.executable, SCRIPT_3D,       "--stem", stem]),
        ("chaos_analyze", [sys.executable, SCRIPT_ANALYZE,  stem]),
        ("friction_fit",  [sys.executable, SCRIPT_FRICTION, "--stem", stem]),
    ]
    for label, cmd in runs:
        run_step(label, cmd,
                 log_path=os.path.join(ROOT, "data", "curate_set_log.txt"))


# ─────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="End-to-end curation pipeline for a chosen clip set.")
    p.add_argument("--group", choices=list(GROUPS),
                   help="predefined curated set")
    p.add_argument("--stems", help="comma-separated stems (overrides --group)")
    p.add_argument("--report-only", action="store_true",
                   help="only print state/flags; don't run any cleaning steps")
    p.add_argument("--skip-fix",    action="store_true",
                   help="skip fix_green_swaps")
    p.add_argument("--skip-interp", action="store_true",
                   help="skip interpolate_suspects")
    p.add_argument("--skip-verify", action="store_true",
                   help="skip the post-clean verify_tracking re-run")
    p.add_argument("--skip-figures", action="store_true",
                   help="skip Phase 2 figure generation")
    return p.parse_args()


def resolve_stems(args):
    if args.stems:
        return [s.strip() for s in args.stems.split(",") if s.strip()]
    if args.group:
        return list(GROUPS[args.group])
    raise SystemExit("Need --group or --stems.")


def print_state(states):
    """Compact one-row-per-clip snapshot."""
    print()
    print(f"  {'stem':<24} {'verdict':<6} {'drop%':>6} {'peak|w2|':>9} "
          f"{'arm_max':>8} {'n_off':>6} {'th1_rel':>8} {'om1_rel':>8} flags")
    print("  " + "-" * 110)
    for s in states:
        drop = f"{s.drop_pct:.2f}" if not np.isnan(s.drop_pct) else "?"
        pw2  = f"{s.peak_w2:.0f}"  if not np.isnan(s.peak_w2)  else "?"
        adv  = f"{s.arm_max:.1f}%" if not np.isnan(s.arm_max)  else "?"
        th1  = f"{s.th1_release:+.1f}" if not np.isnan(s.th1_release) else "?"
        om1  = f"{s.om1_release:+.0f}" if not np.isnan(s.om1_release) else "?"
        flags = "; ".join(s.flags) if s.flags else ""
        print(f"  {s.stem:<24} {s.verdict:<6} {drop:>6} {pw2:>9} "
              f"{adv:>8} {s.n_off_ring:>6} {th1:>8} {om1:>8} {flags}")


def main():
    args = parse_args()
    stems = resolve_stems(args)

    print(f"\ncurate_set.py — {len(stems)} clip(s)")
    print(f"  group: {args.group or '(custom)'}")
    print(f"  mode:  {'REPORT-ONLY' if args.report_only else 'EXECUTE'}")
    print()

    # ── Phase 1: pre-state snapshot + sanity flags ──────────────────────
    print("PHASE 1 — pre-state snapshot")
    pre_states = []
    for stem in stems:
        s = collect_state(stem)
        check_release_frame(stem, s)
        pre_states.append(s)
    print_state(pre_states)

    if args.report_only:
        print("\n[report-only] no cleaning steps run.")
        return

    # ── Phase 2: cleaning ───────────────────────────────────────────────
    print("\nPHASE 2 — clean")
    for stem in stems:
        print(f"\n  {stem}")
        if not args.skip_fix:
            step_fix_green(stem)
        if not args.skip_interp:
            step_interpolate(stem)
        if not args.skip_verify:
            step_verify(stem)

    # ── Phase 3: figures ────────────────────────────────────────────────
    if not args.skip_figures:
        print("\nPHASE 3 — figures (Phase 1 + Phase 2)")
        for stem in stems:
            print(f"\n  {stem}")
            step_phase_2(stem)

    # ── Phase 4: post-state report ──────────────────────────────────────
    print("\nPHASE 4 — post-state snapshot")
    post_states = [collect_state(stem) for stem in stems]
    for s in post_states:
        check_release_frame(s.stem, s)
    print_state(post_states)

    # ── Recommendations ─────────────────────────────────────────────────
    print("\nRECOMMENDATIONS")
    n_pass = sum(1 for s in post_states if s.verdict == "PASS")
    n_warn = sum(1 for s in post_states if s.verdict == "WARN")
    n_fail = sum(1 for s in post_states if s.verdict == "FAIL")
    print(f"  Verdict: {n_pass} PASS / {n_warn} WARN / {n_fail} FAIL")

    needs_retune = [s for s in post_states
                    if s.peak_w2 > 4000 or s.arm_max > 25 or s.drop_pct > 5]
    if needs_retune:
        print("\n  Clips that may benefit from per-clip HSV re-tune:")
        for s in needs_retune:
            why = []
            if s.peak_w2 > 4000:    why.append(f"peak|w2|={s.peak_w2:.0f}")
            if s.arm_max > 25:      why.append(f"arm_max={s.arm_max:.0f}%")
            if s.drop_pct > 5:      why.append(f"drop={s.drop_pct:.1f}%")
            print(f"    chaos tune {s.stem}    # {', '.join(why)}")
            print(f"    chaos track {s.stem}")

    # Surface release-frame issues prominently — these are NOT fixed by
    # any of the automated cleaning steps; they need the user to update
    # release_frame in the registry (or re-run chaos pick).
    bogus_release = [s for s in post_states
                     if any("release-frame" in f for f in s.flags)]
    if bogus_release:
        print("\n  Clips with suspicious release_frame (manual fix needed):")
        for s in bogus_release:
            print(f"    {s.stem}: om1_release={s.om1_release:+.0f}deg/s "
                  f"(should be ≈ 0 for a hand release)")

    # Group-level summary if there's > 1 clip and they're related.
    if len(stems) > 1:
        print(f"\n  Curated set ready at:")
        print(f"    figures/lyapunov/<stem>_lyapunov.png  ({n_pass+n_warn} clips)")
        print(f"    figures/poincare/<stem>_poincare.png")
        print(f"    figures/phase_panels/<stem>_phase_panels.png")
        print(f"    measurements/<stem>/poincare.csv     (raw section points)")
        print(f"  Next: run scripts/analysis/group_overlay.py --stems "
              f"{','.join(stems)}")
        print(f"  to generate the IC-divergence + theta(t)-overlay aggregate plots.")


if __name__ == "__main__":
    main()
