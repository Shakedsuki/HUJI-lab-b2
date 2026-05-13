"""
suspects_summary.py
-------------------
Decompose a clip's suspect count into per-check buckets + clusters,
so the engineer knows whether to manually seed every flagged frame
(rare) or just hit the underlying clusters (typical).

A 30k-frame chaotic recording with 221 suspect rows looks scary at
first glance, but after this decomposition it's typically:

  ~4 ω-cap survivors        → chaos override (per frame)
  ~10 arm-length clusters   → chaos fix (one seed per cluster)
  ~150 θ-residual / Δω      → σ_ω noise in chaotic regime; not
                              real tracker errors. Accept as noise.

The tool prints a per-check breakdown, cluster sizes, and a
recommended action plan.
"""

import argparse
import csv
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

def parse_args():
    p = argparse.ArgumentParser(
        description="Decompose a clip's suspect count into per-check "
                    "buckets and frame clusters.")
    p.add_argument("stem", help="config_description (the folder name "
                                "under measurements/)")
    p.add_argument("--gap", type=int, default=10, metavar="FRAMES",
                   help="frames within this gap count as the same "
                        "cluster (default 10)")
    return p.parse_args()

def clusterize(frames, gap):
    if not frames:
        return []
    frames = sorted(frames)
    out = [[frames[0]]]
    for f in frames[1:]:
        if f - out[-1][-1] <= gap:
            out[-1].append(f)
        else:
            out.append([f])
    return out

def main():
    args = parse_args()
    path = os.path.join(MEAS_DIR, args.stem, "verification.csv")
    if not os.path.exists(path):
        print(f"ERROR: {path} not found")
        return 1

    # Per-check counters and the frame lists we need for clustering.
    check_cols = [
        ("omega_cap_suspect",      "omega_cap"),
        ("delta_omega_suspect",    "delta_omega"),
        ("swap_suspect",           "swap"),
        ("residual_suspect",       "theta_residual"),
        ("energy_ceiling_suspect", "energy_ceiling"),
        ("energy_rolling_spike",   "energy_spike"),
        ("trend_arm_suspect",      "trend_arm"),
    ]
    counts = {label: 0 for _, label in check_cols}
    frames_per_check = {label: [] for _, label in check_cols}

    suspect_frames     = []
    arm_violation_rows = []   # (frame, dev_pct)
    n_total = 0

    with open(path, "r", newline="") as f:
        for r in csv.DictReader(f):
            n_total += 1
            if int(r.get("dropout") or 0):
                continue
            try:
                fr = int(r["frame"])
            except (KeyError, ValueError):
                continue
            if int(r.get("suspect") or 0) == 1:
                suspect_frames.append(fr)
            for col, label in check_cols:
                try:
                    if int(r.get(col) or 0) == 1:
                        counts[label] += 1
                        frames_per_check[label].append(fr)
                except (ValueError, TypeError):
                    pass
            try:
                dev = float(r.get("arm_dev_pct") or 0)
                if dev > 10:
                    arm_violation_rows.append((fr, dev))
            except ValueError:
                pass

    n_susp = len(suspect_frames)
    pct = (100.0 * n_susp / n_total) if n_total else 0.0

    print()
    print(f"  {args.stem}")
    print(f"  {n_total:,} total frames   |   "
          f"{n_susp:,} unique suspect frames ({pct:.2f}%)")
    print()
    print("  Per-check counts (a frame may be flagged by multiple checks):")
    print(f"    {'check':28s}  {'count':>6s}  {'clusters':>8s}  {'note'}")
    notes = {
        "omega_cap":      "interp-resistant tracker errors → chaos override / fix",
        "delta_omega":    "ω noise in chaotic regime; typically not real",
        "swap":           "marker labels exchanged → check HSV",
        "theta_residual": "ω noise; predicted-position mismatch",
        "energy_ceiling": "stable wrong-target latch → chaos fix",
        "energy_spike":   "transition events; ω noise or brief teleport",
        "trend_arm":      "long stable wrong-target episode → chaos fix",
    }
    for _, label in check_cols:
        cnt = counts[label]
        cl = clusterize(frames_per_check[label], gap=args.gap)
        cl_count = len(cl)
        if cnt == 0:
            print(f"    {label:28s}  {cnt:>6d}  {'—':>8s}")
            continue
        max_c = max(len(c) for c in cl) if cl else 0
        print(f"    {label:28s}  {cnt:>6d}  "
              f"{cl_count:>3d} ({max_c} max) "
              f"  {notes.get(label, '')[:50]}")

    # arm violations from the dev_pct column (separate from
    # trend_arm_suspect, which is a sliding-window signal).
    if arm_violation_rows:
        frames = [f for f, _ in arm_violation_rows]
        cl = clusterize(frames, gap=args.gap)
        max_dev = max(d for _, d in arm_violation_rows)
        print()
        print(f"  Arm-length violations (per-frame deviation > 10%):")
        print(f"    {len(arm_violation_rows)} frames in {len(cl)} cluster(s); "
              f"max deviation {max_dev:.1f}%")

    # ω-cap survivor list — call this out specifically because each
    # one is exactly one chaos override invocation.
    if frames_per_check["omega_cap"]:
        print()
        print(f"  ω-cap survivor frames (each is one chaos override):")
        for fr in sorted(set(frames_per_check["omega_cap"])):
            print(f"    chaos override {args.stem} --frame {fr}")

    # Recommended action plan.
    print()
    print("  Recommended actions:")
    n_om = counts["omega_cap"]
    n_arm = len(arm_violation_rows)
    n_arm_cl = len(clusterize([f for f, _ in arm_violation_rows], gap=args.gap))
    n_ec = counts["energy_ceiling"]
    n_tr = counts["trend_arm"]

    if n_om:
        print(f"    1. Override the {n_om} ω-cap survivor frame(s) above.")
    if n_arm and (n_arm_cl <= 30):
        print(f"    {2 if n_om else 1}. Run `chaos fix {args.stem}` and seed "
              f"the {n_arm_cl} arm-violation cluster(s) (use `n` to jump).")
    elif n_arm:
        print(f"    {2 if n_om else 1}. {n_arm_cl} arm-violation clusters is a lot — "
              f"`chaos tune {args.stem}` may be more efficient than seeding.")
    if n_ec or n_tr:
        print(f"    Stable wrong-target latch suspected (energy ceiling / "
              f"trend-arm flags). `chaos fix` or `chaos tune`.")
    if (counts["delta_omega"] + counts["theta_residual"] + counts["energy_spike"]) > 0 \
            and not (n_om or n_ec or n_tr or n_arm):
        print(f"    Remaining flags are likely σ_ω noise from chaotic "
              f"motion. If verification.png looks clean, mark verified.")
    print()
    return 0

if __name__ == "__main__":
    sys.exit(main())

from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
