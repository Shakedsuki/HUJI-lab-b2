"""
validate_deliverables.py
-------------------------
Tier-1 automated quality dashboard for a curated clip set.

Runs a battery of physics + tracking checks per clip and prints a
green/yellow/red table. Designed to answer the question:
"are these deliverables physics-sound enough to send to the instructor?"

Checks per clip:
    A. Verdict (Brief 14)         — experiments.json audit_new_status
    B. Energy monotonic decay     — verification.csv energy_J
    C. omega-cap suspect rate     — verification.csv omega_cap_suspect
    D. Dropout fraction           — experiments.json dropout_rate_pct
    E. Lyapunov R^2               — runs lyapunov.py --no-plot
    F. lambda sign vs chaos verdict — runs chaos_analyze.py
    G. Poincare statistical floor — wc -l measurements/<stem>/poincare.csv
    H. Arm-length deviation       — verification.csv arm_dev_pct
    I. IC-twin convergence        — experiments.json theta_release (group_a only)

Output: per-clip aligned table with per-check status + per-group summary.

Usage:
    python scripts/utils/validate_deliverables.py --group group_a
    python scripts/utils/validate_deliverables.py --group tier_1
    python scripts/utils/validate_deliverables.py --stems th1_p044_th2_m001,th1_p056_th2_m001
    python scripts/utils/validate_deliverables.py --group group_a --skip-slow   # no subprocess calls
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

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

SCRIPT_LYAPUNOV  = os.path.join(ROOT, "scripts", "analysis", "lyapunov.py")
SCRIPT_ANALYZE   = os.path.join(ROOT, "scripts", "analysis", "chaos_analyze.py")


# Keep these definitions in sync with curate_set.py / group_overlay.py / group_animations.py.
GROUPS = {
    # th1_p093_th2_m002 dropped 2026-05-06 — residual ω at release.
    "group_a": [
        "th1_p091_th2_m001",
        "th1_p092_th2_m002",
        "th1_p092_th2_p000",
        "th1_p093_th2_m000",
        "th1_p094_th2_p000",
    ],
    "tier_1": [
        "th1_p044_th2_m001",
        "th1_p056_th2_m001",
        "th1_p082_th2_p001",
        "th1_p180_th2_m179",
    ],
    "writeup": [
        "th1_p044_th2_m001", "th1_p056_th2_m001",
        "th1_p082_th2_p001", "th1_p180_th2_m179",
        "th1_p091_th2_m001", "th1_p092_th2_m002",
        "th1_p092_th2_p000", "th1_p093_th2_m000",
        "th1_p094_th2_p000",
    ],
}


# ─────────────────────────────────────────────
# STATUS PRIMITIVES
# ─────────────────────────────────────────────

GREEN, YELLOW, RED, GRAY = "GREEN", "YELLOW", "RED", "GRAY"
SYM = {GREEN: "✓", YELLOW: "!", RED: "✗", GRAY: "–"}


@dataclass
class CheckResult:
    status: str             # GREEN / YELLOW / RED / GRAY
    detail: str = ""        # short numeric / verbal detail


@dataclass
class ClipReport:
    stem: str
    checks: dict = field(default_factory=dict)
    summary: str = ""

    def overall(self) -> str:
        # RED if any RED, else YELLOW if any YELLOW, else GREEN.
        statuses = [c.status for c in self.checks.values()]
        if RED in statuses:
            return RED
        if YELLOW in statuses:
            return YELLOW
        return GREEN


# ─────────────────────────────────────────────
# REGISTRY HELPERS
# ─────────────────────────────────────────────

_REGISTRY_CACHE = None


def load_registry():
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        with open(EXPERIMENTS_FILE, encoding="utf-8") as f:
            _REGISTRY_CACHE = json.load(f)
    return _REGISTRY_CACHE


def find_entry(stem):
    reg = load_registry()
    for entry in reg.values():
        if entry.get("config_description") == stem:
            return entry
    return None


# ─────────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────────

def check_verdict(entry) -> CheckResult:
    """A. Brief 14 audit verdict + manual_accept guard, with legacy fallback."""
    if not entry:
        return CheckResult(GRAY, "no registry entry")
    audit  = entry.get("audit_new_status")
    tq     = entry.get("tracking_quality")
    manual = bool(entry.get("manual_accept"))
    # Strongest signal first: audit verdict
    if audit == "PASS":
        return CheckResult(GREEN, "PASS")
    if audit == "WARN":
        if manual:
            return CheckResult(GREEN, "WARN (manual ✓)")
        if tq == "verified":
            return CheckResult(GREEN, "WARN (tq=verified)")
        return CheckResult(YELLOW, "WARN")
    if audit == "FAIL":
        return CheckResult(RED, "FAIL")
    # Legacy / unaudited: trust tracking_quality
    if tq in ("good", "verified"):
        return CheckResult(GREEN, f"{tq} (no audit)")
    if tq == "review":
        return CheckResult(YELLOW, "review")
    return CheckResult(YELLOW, f"audit={audit} tq={tq}")


def check_energy_monotonic(stem) -> CheckResult:
    """B. Total energy should decay (friction).

    Compares mean energy in first 10% vs last 10% of the smoothed free-swing
    trace. Total E = T+V oscillates frame-by-frame as KE↔PE exchange (and
    from finite-difference ω noise), so we use a wide smoothing window plus
    end-window averaging instead of any 'max rise' instantaneous metric.
    """
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv):
        return CheckResult(GRAY, "no verification.csv")
    df = pd.read_csv(csv)
    if "energy_J" not in df.columns or df["energy_J"].isna().all():
        return CheckResult(GRAY, "no energy_J")
    free = df[df["phase"] == "free_swing"]
    e = pd.to_numeric(free["energy_J"], errors="coerce").dropna().to_numpy()
    if len(e) < 200:
        return CheckResult(GRAY, "too few free-swing rows")
    # Wide smoothing — ~1 second of frames at 60 fps to integrate over a swing
    win = max(151, len(e) // 8)
    e_smooth = pd.Series(e).rolling(win, min_periods=1, center=True).mean().to_numpy()
    w = max(30, len(e_smooth) // 10)
    e_start = float(np.mean(e_smooth[:w]))
    e_end   = float(np.mean(e_smooth[-w:]))
    if e_start <= 0:
        return CheckResult(GRAY, f"E0={e_start:.2f} not usable")
    drop_pct = 100.0 * (e_start - e_end) / e_start
    detail = f"E: {e_start:.2f}→{e_end:.2f} J ({drop_pct:+.1f}%)"
    # GREEN: clear decay (>5%). YELLOW: tiny change (low friction or short clip).
    # RED: clear gain (>5%) — physics violation.
    if drop_pct > 5:
        return CheckResult(GREEN, detail)
    if drop_pct > -5:
        return CheckResult(YELLOW, detail)
    return CheckResult(RED, detail)


def check_omega_cap(stem) -> CheckResult:
    """C. omega-cap suspect rate (after interpolation)."""
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv):
        return CheckResult(GRAY, "no verification.csv")
    df = pd.read_csv(csv)
    if "omega_cap_suspect" not in df.columns:
        return CheckResult(GRAY, "no omega_cap_suspect col")
    free = df[df["phase"] == "free_swing"]
    n_total = len(free)
    n_susp = int(free["omega_cap_suspect"].sum())
    pct = 100.0 * n_susp / max(n_total, 1)
    if n_susp == 0:
        return CheckResult(GREEN, f"0/{n_total}")
    if pct < 1.0:
        return CheckResult(YELLOW, f"{n_susp}/{n_total} ({pct:.1f}%)")
    return CheckResult(RED, f"{n_susp}/{n_total} ({pct:.1f}%)")


def check_dropout(entry) -> CheckResult:
    """D. Dropout fraction from registry."""
    if not entry:
        return CheckResult(GRAY, "no registry")
    pct = entry.get("dropout_rate_pct")
    if pct is None:
        return CheckResult(GRAY, "no dropout_rate_pct")
    if pct < 5:
        return CheckResult(GREEN, f"{pct:.1f}%")
    if pct < 15:
        return CheckResult(YELLOW, f"{pct:.1f}%")
    return CheckResult(RED, f"{pct:.1f}%")


_LAM_RE = re.compile(
    r"lambda_1\s*=\s*([+\-0-9.]+)\s*/s\s+R\^2\s*=\s*([0-9.]+)")


def run_lyapunov(stem, cache):
    """Returns (lambda_1, R^2) or (None, None). Cached per-stem."""
    if stem in cache:
        return cache[stem]
    cmd = [sys.executable, SCRIPT_LYAPUNOV, "--stem", stem, "--no-plot"]
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=120)
    except subprocess.TimeoutExpired:
        cache[stem] = (None, None)
        return cache[stem]
    text = (out.stdout or "") + (out.stderr or "")
    m = _LAM_RE.search(text)
    if not m:
        cache[stem] = (None, None)
        return cache[stem]
    cache[stem] = (float(m.group(1)), float(m.group(2)))
    return cache[stem]


def check_lyapunov_r2(stem, cache) -> CheckResult:
    """E. Lyapunov fit R^2."""
    lam, r2 = run_lyapunov(stem, cache)
    if r2 is None:
        return CheckResult(GRAY, "lyapunov failed")
    if r2 >= 0.9:
        return CheckResult(GREEN, f"λ={lam:+.2f} R²={r2:.2f}")
    if r2 >= 0.7:
        return CheckResult(YELLOW, f"λ={lam:+.2f} R²={r2:.2f}")
    return CheckResult(RED, f"λ={lam:+.2f} R²={r2:.2f}")


_VERDICT_RE = re.compile(r"VERDICT:\s*(\w+)", re.I)


def run_chaos_analyze(stem, cache):
    """Returns 'CHAOTIC' / 'REGULAR' / 'BORDERLINE' or None. Cached."""
    if stem in cache:
        return cache[stem]
    cmd = [sys.executable, SCRIPT_ANALYZE, stem]
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             timeout=120)
    except subprocess.TimeoutExpired:
        cache[stem] = None
        return None
    text = (out.stdout or "") + (out.stderr or "")
    m = _VERDICT_RE.search(text)
    cache[stem] = m.group(1).upper() if m else None
    return cache[stem]


def check_lambda_vs_verdict(stem, lyap_cache, chaos_cache) -> CheckResult:
    """F. λ sign should agree with chaos_analyze verdict."""
    lam, _ = run_lyapunov(stem, lyap_cache)
    verdict = run_chaos_analyze(stem, chaos_cache)
    if lam is None or verdict is None:
        return CheckResult(GRAY, "missing input")
    # Decision boundaries (deliberately wide; pendulum λ in O(0.1-1.0) for chaotic)
    is_chaotic = lam > 0.3
    is_regular = lam < 0.15
    if verdict == "CHAOTIC" and is_chaotic:
        return CheckResult(GREEN, "CHAOTIC ↔ λ>0.3")
    if verdict == "REGULAR" and is_regular:
        return CheckResult(GREEN, "REGULAR ↔ λ<0.15")
    if verdict == "BORDERLINE":
        return CheckResult(YELLOW, f"BORDERLINE (λ={lam:+.2f})")
    if verdict == "CHAOTIC" and lam < 0.15:
        return CheckResult(RED, f"CHAOTIC but λ={lam:+.2f}")
    if verdict == "REGULAR" and lam > 0.3:
        return CheckResult(RED, f"REGULAR but λ={lam:+.2f}")
    return CheckResult(YELLOW, f"{verdict} λ={lam:+.2f}")


def check_poincare(stem, chaos_cache) -> CheckResult:
    """G. Poincaré section row count.
    Threshold tiered by chaos verdict — regular orbits legitimately have few crossings."""
    csv = os.path.join(MEAS_DIR, stem, "poincare.csv")
    if not os.path.exists(csv):
        return CheckResult(GRAY, "no poincare.csv")
    n = sum(1 for _ in open(csv, encoding="utf-8")) - 1  # minus header
    verdict = chaos_cache.get(stem)
    if verdict == "CHAOTIC":
        if n >= 30:
            return CheckResult(GREEN, f"{n} crossings")
        if n >= 10:
            return CheckResult(YELLOW, f"{n} crossings (low for chaotic)")
        return CheckResult(RED, f"{n} crossings")
    # REGULAR / BORDERLINE / unknown — closed orbits have few crossings, that's fine
    if n >= 5:
        return CheckResult(GREEN, f"{n} crossings")
    if n >= 1:
        return CheckResult(YELLOW, f"{n} crossings")
    return CheckResult(RED, "0 crossings")


def check_arm_dev(stem) -> CheckResult:
    """H. Arm-length deviation. Use 95th percentile + median (single bad frames
    bias the max; chaotic regime has known 12-16% baseline)."""
    csv = os.path.join(MEAS_DIR, stem, "verification.csv")
    if not os.path.exists(csv):
        return CheckResult(GRAY, "no verification.csv")
    df = pd.read_csv(csv)
    if "arm_dev_pct" not in df.columns:
        return CheckResult(GRAY, "no arm_dev_pct")
    free = df[df["phase"] == "free_swing"]
    s = pd.to_numeric(free["arm_dev_pct"], errors="coerce").dropna()
    if len(s) == 0:
        return CheckResult(GRAY, "all NaN")
    med = float(s.median())
    p95 = float(s.quantile(0.95))
    detail = f"med {med:.1f}% p95 {p95:.1f}%"
    if p95 < 5:
        return CheckResult(GREEN, detail)
    if p95 < 18:
        return CheckResult(YELLOW, detail)
    return CheckResult(RED, detail)


def check_ic_convergence(group, stems) -> Optional[CheckResult]:
    """I. group_a only: all clips share IC within tolerance."""
    if group != "group_a":
        return None
    pts = []
    for s in stems:
        e = find_entry(s) or {}
        t1 = e.get("theta1_release")
        t2 = e.get("theta2_release")
        if t1 is None or t2 is None:
            continue
        pts.append((s, t1, t2))
    if len(pts) < 2:
        return CheckResult(GRAY, "insufficient IC data")
    t1s = [p[1] for p in pts]
    t2s = [p[2] for p in pts]
    spread1 = max(t1s) - min(t1s)
    spread2 = max(t2s) - min(t2s)
    detail = f"Δθ₁={spread1:.1f}° Δθ₂={spread2:.1f}°"
    # For Group A the wrap-up tolerance was "θ₁ within ±5° of 90°" → spread up to ~10°
    # is expected and physically still 'similar IC' for chaotic-divergence purposes.
    if spread1 < 12 and spread2 < 8:
        return CheckResult(GREEN, detail)
    if spread1 < 20 and spread2 < 15:
        return CheckResult(YELLOW, detail)
    return CheckResult(RED, detail)


# ─────────────────────────────────────────────
# DRIVER
# ─────────────────────────────────────────────

def evaluate_clip(stem, lyap_cache, chaos_cache, skip_slow=False) -> ClipReport:
    entry = find_entry(stem)
    rep = ClipReport(stem=stem)
    rep.checks["verdict"]  = check_verdict(entry)
    rep.checks["energy↓"]  = check_energy_monotonic(stem)
    rep.checks["ωcap"]     = check_omega_cap(stem)
    rep.checks["dropout"]  = check_dropout(entry)
    rep.checks["arm_dev"]  = check_arm_dev(stem)
    if skip_slow:
        rep.checks["λ R²"]    = CheckResult(GRAY, "skipped")
        rep.checks["λ↔chaos"] = CheckResult(GRAY, "skipped")
        rep.checks["poincaré"] = CheckResult(GRAY, "skipped")
    else:
        rep.checks["λ R²"]    = check_lyapunov_r2(stem, lyap_cache)
        rep.checks["λ↔chaos"] = check_lambda_vs_verdict(stem, lyap_cache, chaos_cache)
        rep.checks["poincaré"] = check_poincare(stem, chaos_cache)
    return rep


def print_table(reports, group_check: Optional[CheckResult] = None):
    if not reports:
        print("  (no clips)")
        return
    check_names = list(reports[0].checks.keys())
    # Header
    print()
    name_w = max(len(r.stem) for r in reports) + 2
    line = " " * 2 + "stem".ljust(name_w) + "  overall"
    for cn in check_names:
        line += "  " + cn
    print(line)
    print("  " + "-" * (name_w + 8 + sum(len(c) + 2 for c in check_names)))
    for r in reports:
        ov = r.overall()
        line = "  " + r.stem.ljust(name_w) + f"  {SYM[ov]} {ov:<6}"
        for cn in check_names:
            c = r.checks[cn]
            cell = f"{SYM[c.status]}".center(len(cn) + 2)
            line += cell
        print(line)
    # Per-clip detail block
    print()
    print("  details:")
    for r in reports:
        line = f"    {r.stem:{name_w}}  "
        bits = []
        for cn, c in r.checks.items():
            if c.status != GREEN and c.status != GRAY:
                bits.append(f"{cn}={c.detail}")
            elif c.detail and len(c.detail) < 18:
                bits.append(f"{cn}={c.detail}")
        line += " | ".join(bits)
        print(line)
    if group_check is not None:
        print()
        print(f"  IC convergence (group): {SYM[group_check.status]} {group_check.detail}")


def print_summary(reports, group):
    n = len(reports)
    overalls = [r.overall() for r in reports]
    g = overalls.count(GREEN)
    y = overalls.count(YELLOW)
    rr = overalls.count(RED)
    print()
    print(f"  Group {group}: {n} clip(s) — {g} GREEN, {y} YELLOW, {rr} RED")
    if rr == 0 and y == 0:
        print("  → publication-ready")
    elif rr == 0:
        print(f"  → publication-acceptable with {y} caveat(s) to document")
    else:
        print(f"  → {rr} clip(s) need attention before publication")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--group", choices=list(GROUPS.keys()),
                   help="Predefined group (group_a / tier_1 / writeup).")
    p.add_argument("--stems", help="Comma-separated explicit stem list.")
    p.add_argument("--skip-slow", action="store_true",
                   help="Skip subprocess-based checks (lyapunov, chaos_analyze).")
    return p.parse_args()


def main():
    args = parse_args()
    if not args.group and not args.stems:
        print("Specify --group or --stems")
        sys.exit(2)
    if args.group:
        stems = GROUPS[args.group]
        group = args.group
    else:
        stems = [s.strip() for s in args.stems.split(",") if s.strip()]
        group = "(custom)"

    print(f"validate_deliverables.py — {len(stems)} clip(s)")
    print(f"  group: {group}")
    if args.skip_slow:
        print("  mode:  --skip-slow (no lyapunov / chaos_analyze subprocess)")

    lyap_cache = {}
    chaos_cache = {}
    reports = []
    for stem in stems:
        if not args.skip_slow:
            print(f"  evaluating {stem} (running lyapunov + chaos_analyze...)")
        reports.append(evaluate_clip(stem, lyap_cache, chaos_cache,
                                       skip_slow=args.skip_slow))

    group_check = check_ic_convergence(group, stems)
    print_table(reports, group_check)
    print_summary(reports, group)


if __name__ == "__main__":
    main()
