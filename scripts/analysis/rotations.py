"""
rotations.py
------------
Per-arm rotation / accumulated-angle metrics for the double pendulum.

Counts how many times each arm loops the pivot and how much angle it
accumulates over a run, for one clip (``--stem``) or a parameter sweep
(``--sweep``).

The angles in tracking.csv / verification.csv are wrapped to (-180, 180]
(atan2 output), so every signal is re-unwrapped first. Three signals:

    upper      theta1               upper arm, lab frame
    lower_abs  theta2               lower arm, lab frame  <- where driven
                                    clips actually loop the pivot
    lower_rel  theta2 - theta1      lower arm relative to the upper arm
                                    (joint / elbow winding)

Per signal:
    net_turns           (theta_end - theta_start) / 360, signed
    total_turns         completed 360-deg revolutions, both directions
    turns_pos/turns_neg ... split by angle-increasing / -decreasing
    net_angle_deg       signed accumulated angle (= net_turns * 360)
    peak_abs_angle_deg  farthest the arm ever wound from its start
    path_turns          total angular path |d theta| / 360 (incl. oscillation)

Robustness
~~~~~~~~~~
Metrics use clean frames only (phase in {driven, free_swing},
dropout == 0, finite angles). np.unwrap caps per-step motion at 180 deg,
so a real >180-deg move hidden inside a dropout gap is undercounted. To
catch that, the smoothed omega from verification.csv is integrated
independently (omega_net_turns); if it disagrees with the unwrap net by
more than --suspect-turns (default 0.5) the clip is flagged suspect.

Usage
~~~~~
  python scripts/analysis/rotations.py --stem 3.2V_1.20Hz
  python scripts/analysis/rotations.py --sweep                # 3.2V family
  python scripts/analysis/rotations.py --sweep --voltage 4.0
  python scripts/analysis/rotations.py --selftest

Output
~~~~~~
  measurements/<stem>/rotations.json
  figures/rotations/<stem>_rotations.png
  figures/aggregate/rotations_sweep_<V>V.png   (--sweep)
  figures/aggregate/rotations_sweep_<V>V.csv   (--sweep)
"""

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

# numpy 2.0 renamed trapz -> trapezoid; support both.
_trapz = getattr(np, "trapezoid", getattr(np, "trapz"))

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import (clip_dir, iter_clip_dirs,          # noqa: E402
                   EXPERIMENTS_ROOT, PHASE_WEEK5, PHASE_WEEK6)
from figures_paths import figure_path, aggregate_path  # noqa: E402
from driven_helpers import parse_stem                  # noqa: E402

# week5/week6 are separate phases since the split; paths.py no longer
# exports MEAS_WEEK5/6, so reconstruct each phase's measurements dir here
# to keep _bucket_of's calibration-safety check working.
MEAS_WEEK5 = os.path.join(EXPERIMENTS_ROOT, PHASE_WEEK5, "measurements")
MEAS_WEEK6 = os.path.join(EXPERIMENTS_ROOT, PHASE_WEEK6, "measurements")


ARMS = ("upper", "lower_abs", "lower_rel")
RUN_PHASES = ("driven", "free_swing")

# Labels for rich tables (unicode) and matplotlib (mathtext).
ARM_LABELS = {
    "upper":     "upper  θ₁",
    "lower_abs": "lower  θ₂",
    "lower_rel": "lower  θ₂−θ₁ (rel)",
}
ARM_MATH = {
    "upper":     r"upper $\theta_1$",
    "lower_abs": r"lower $\theta_2$",
    "lower_rel": r"lower $\theta_2-\theta_1$ (rel)",
}
ARM_COLOR = {"upper": "tab:blue", "lower_abs": "tab:red", "lower_rel": "tab:green"}


# ─────────────────────────────────────────────
# CORE MATH
# ─────────────────────────────────────────────

def _count_turns(rel):
    """Count completed ±360° revolutions with hysteresis.

    One turn is logged each time the angle advances a full 360° past a
    moving reference R, which then ratchets.  This is chatter-free at
    every level: an arm oscillating below 360° amplitude — around the
    start *or* around an already-rotated position — logs zero turns,
    while a back-and-forth full loop logs one each way.

    Returns (turns_pos, turns_neg) = (angle-increasing, -decreasing).
    """
    R = float(rel[0])
    pos = neg = 0
    for x in rel.tolist():
        while x - R >= 360.0:
            pos += 1
            R += 360.0
        while R - x >= 360.0:
            neg += 1
            R -= 360.0
    return float(pos), float(neg)


def winding_metrics(phi_wrapped_deg):
    """Rotation metrics for one wrapped-angle signal (degrees).

    Re-unwraps defensively (np.unwrap caps per-step jumps at 180°), zeroes
    the trace at the start, then derives net winding, hysteresis turn
    counts, peak excursion, and angular path length.
    """
    phi = np.degrees(np.unwrap(np.radians(np.asarray(phi_wrapped_deg, float))))
    rel = phi - phi[0]                       # accumulated angle, zeroed at start
    net_deg = float(rel[-1])

    turns_pos, turns_neg = _count_turns(rel)

    return {
        "net_turns":          net_deg / 360.0,
        "net_angle_deg":      net_deg,
        "total_turns":        turns_pos + turns_neg,
        "turns_pos":          turns_pos,
        "turns_neg":          turns_neg,
        "peak_abs_angle_deg": float(np.max(np.abs(rel))),
        "path_turns":         float(np.sum(np.abs(np.diff(phi)))) / 360.0,
        "trace":              rel,
    }


def omega_net_turns(t, omega):
    """Independent net-winding estimate by integrating smoothed ω.

    Across a dropout gap the trapezoid uses the real dt, so it captures
    motion the angle-unwrap can't see — that's what makes it a useful
    cross-check.  Returns None when ω is unavailable.
    """
    if omega is None:
        return None
    om = np.asarray(omega, float)
    m = np.isfinite(om)
    if m.sum() < 2:
        return None
    return float(_trapz(om[m], t[m])) / 360.0


def gap_info(t):
    dt = np.diff(t)
    if len(dt) == 0:
        return {"dt_med": float("nan"), "fps_med": float("nan"),
                "n_gaps": 0, "max_gap_s": 0.0}
    med = float(np.median(dt))
    return {
        "dt_med":    med,
        "fps_med":   (1.0 / med) if med > 0 else float("nan"),
        "n_gaps":    int(np.count_nonzero(dt > 2.0 * med)),  # >1 frame missing
        "max_gap_s": float(np.max(dt)),
    }


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────

def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_clip(csv_path):
    """Read tracking/verification.csv into clean numpy arrays.

    Keeps rows with phase in RUN_PHASES, dropout == 0, finite angles.
    omega arrays are present only when the source has those columns
    (verification.csv).
    """
    t, th1, th2, om1, om2 = [], [], [], [], []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        has_omega = "omega1_deg_s" in fields and "omega2_deg_s" in fields
        for r in reader:
            if r.get("phase") not in RUN_PHASES:
                continue
            d = r.get("dropout", "0")
            try:
                if d not in ("", None) and int(float(d)) != 0:
                    continue
            except ValueError:
                pass
            a, b, tt = _f(r.get("theta1_deg")), _f(r.get("theta2_deg")), _f(r.get("time_s"))
            if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(tt)):
                continue
            t.append(tt); th1.append(a); th2.append(b)
            if has_omega:
                om1.append(_f(r.get("omega1_deg_s")))
                om2.append(_f(r.get("omega2_deg_s")))
    if len(t) < 30:
        raise ValueError(f"only {len(t)} clean frames in {csv_path}")
    out = {"t": np.array(t), "th1": np.array(th1), "th2": np.array(th2),
           "has_omega": has_omega}
    if has_omega:
        out["om1"] = np.array(om1)
        out["om2"] = np.array(om2)
    return out


def arm_signal(d, arm):
    if arm == "upper":     return d["th1"]
    if arm == "lower_abs": return d["th2"]                 # θ₂ is already lab-frame absolute
    if arm == "lower_rel": return d["th2"] - d["th1"]      # lower arm relative to upper
    raise ValueError(arm)


def arm_omega(d, arm):
    if not d.get("has_omega"):
        return None
    if arm == "upper":     return d["om1"]
    if arm == "lower_abs": return d["om2"]                 # ω of absolute lower angle θ₂
    if arm == "lower_rel": return d["om2"] - d["om1"]      # d(θ₂ − θ₁)/dt
    raise ValueError(arm)


# ─────────────────────────────────────────────
# PER-CLIP COMPUTE
# ─────────────────────────────────────────────

def compute_clip(d, suspect_turns=0.5):
    """Return (result_dict, traces_dict). result is JSON-safe (no arrays)."""
    t = d["t"]
    res = {
        "n_frames_clean": int(len(t)),
        "duration_s":     float(t[-1] - t[0]),
        "has_omega":      bool(d.get("has_omega")),
        **gap_info(t),
        "arms": {},
    }
    traces = {}
    for arm in ARMS:
        m = winding_metrics(arm_signal(d, arm))
        traces[arm] = m.pop("trace")
        ont = omega_net_turns(t, arm_omega(d, arm))
        m["omega_net_turns"] = ont
        if ont is None:
            m["cross_check_diff_turns"] = None
            m["suspect"] = None
        else:
            diff = abs(ont - m["net_turns"])
            m["cross_check_diff_turns"] = diff
            m["suspect"] = bool(diff > suspect_turns)
        res["arms"][arm] = m
    return res, traces


# ─────────────────────────────────────────────
# RENDER — single clip
# ─────────────────────────────────────────────

def print_table(stem, res):
    t = Table(title=f"rotations — {stem}", box=rich.box.SIMPLE_HEAD,
              title_style="bold cyan")
    t.add_column("arm", no_wrap=True)
    t.add_column("net", justify="right")
    t.add_column("total", justify="right")
    t.add_column("↑θ", justify="right")
    t.add_column("↓θ", justify="right")
    t.add_column("acc°", justify="right")
    t.add_column("peak°", justify="right")
    t.add_column("path", justify="right")
    t.add_column("ωΔ", justify="right")
    for arm in ARMS:
        m = res["arms"][arm]
        if m["suspect"] is True:
            chk = f"[red]Δ{m['cross_check_diff_turns']:.2f}[/]"
        elif m["suspect"] is False:
            chk = f"[green]Δ{m['cross_check_diff_turns']:.2f}[/]"
        else:
            chk = "[dim]—[/]"
        t.add_row(
            ARM_LABELS[arm],
            f"{m['net_turns']:+.2f}",
            f"{m['total_turns']:.0f}",
            f"{m['turns_pos']:.0f}",
            f"{m['turns_neg']:.0f}",
            f"{m['net_angle_deg']:+.0f}°",
            f"{m['peak_abs_angle_deg']:.0f}°",
            f"{m['path_turns']:.1f}",
            chk,
        )
    console.print(t)
    info = (f"clean frames {res['n_frames_clean']}, "
            f"dur {res['duration_s']:.1f}s, ~{res['fps_med']:.0f} fps")
    if res["n_gaps"]:
        info += f"  [yellow]{res['n_gaps']} gaps (max {res['max_gap_s']*1000:.0f} ms)[/]"
    console.print(f"  [dim]{info}[/]")
    console.print("  [dim](turns ↑θ/↓θ = full 360° revolutions by angle "
                  "direction; net = ↑−↓ as fraction)[/]")


def make_trace_figure(stem, res, traces, t, out_path):
    t0 = t - t[0]
    fig, ax = plt.subplots(figsize=(12, 6))
    for arm in ARMS:
        m = res["arms"][arm]
        ax.plot(t0, traces[arm] / 360.0, color=ARM_COLOR[arm], lw=1.0,
                label=f"{ARM_MATH[arm]}  (net {m['net_turns']:+.2f}, "
                      f"total {m['total_turns']:.0f})")
    ax.axhline(0, color="0.6", lw=0.6)
    ax.grid(True, axis="y", alpha=0.25)
    ax.set_xlabel("t (s)")
    ax.set_ylabel("accumulated angle (revolutions)")
    ax.set_title(f"Accumulated angle vs time — {stem}")
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def run_single(stem, args):
    cdir = clip_dir(stem)
    csv_path = None
    for name in ("verification.csv", "tracking.csv"):
        p = os.path.join(cdir, name)
        if os.path.exists(p):
            csv_path = p
            break
    if csv_path is None:
        raise SystemExit(f"no verification.csv / tracking.csv in {cdir}")

    d = load_clip(csv_path)
    res, traces = compute_clip(d, args.suspect_turns)
    res["stem"] = stem
    res["source"] = os.path.basename(csv_path)

    print_table(stem, res)

    out_json = os.path.join(cdir, "rotations.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    console.print(f"  [dim]→ {out_json}[/]")

    out_png = figure_path("rotations", stem)
    make_trace_figure(stem, res, traces, d["t"], out_png)
    console.print(f"  [dim]→ {out_png}[/]")


# ─────────────────────────────────────────────
# RENDER — sweep
# ─────────────────────────────────────────────

def _bucket_of(stem):
    """Which week bucket a clip physically lives in. Buckets use different
    pivot calibrations, so a sweep must not mix them."""
    d = os.path.abspath(clip_dir(stem))
    if d.startswith(os.path.abspath(MEAS_WEEK6)):
        return "week6"
    if d.startswith(os.path.abspath(MEAS_WEEK5)):
        return "week5"
    return "other"


def collect_sweep(voltage, suspect_turns):
    """Return sorted [(f_drive_hz, stem, res), ...] for clips at `voltage`.

    Clips at one voltage can straddle week buckets — e.g. 3.2V_1Hz lives
    in the week-5 survey while the rest of the 3.2V family is the week-6
    resonance sweep. The buckets use different pivot calibrations, so when
    the matches span more than one bucket we keep the dominant one and drop
    the stragglers rather than mixing calibrations into one sweep.
    """
    raw = []  # (f_hz, stem, res, bucket)
    for stem, _dir in iter_clip_dirs():
        try:
            meta = parse_stem(stem)
        except ValueError:
            continue
        if abs(meta["v_drill_v"] - voltage) > 1e-6:
            continue
        cdir = clip_dir(stem)
        csv_path = None
        for name in ("verification.csv", "tracking.csv"):
            p = os.path.join(cdir, name)
            if os.path.exists(p):
                csv_path = p
                break
        if csv_path is None:
            continue
        try:
            d = load_clip(csv_path)
            res, _ = compute_clip(d, suspect_turns)
        except (ValueError, SystemExit) as e:
            console.print(f"  [yellow]skip {stem}: {e}[/]")
            continue
        res["stem"] = stem
        raw.append((meta["f_drive_hz"], stem, res, _bucket_of(stem)))

    buckets = {}
    for r in raw:
        buckets.setdefault(r[3], []).append(r)
    if len(buckets) > 1:
        keep = max(buckets, key=lambda b: len(buckets[b]))
        for b, items in sorted(buckets.items()):
            if b == keep:
                continue
            for _f, stem, _res, _b in items:
                console.print(f"  [yellow]excluded {stem}[/] "
                              f"[dim](bucket {b}; sweep batch is {keep})[/]")
        raw = buckets[keep]

    rows = [(f_hz, stem, res) for f_hz, stem, res, _b in raw]
    rows.sort(key=lambda r: r[0])
    return rows


def make_sweep_figure(rows, voltage, out_path):
    f = np.array([r[0] for r in rows])
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), sharex=True)
    for arm in ARMS:
        net = np.array([r[2]["arms"][arm]["net_turns"] for r in rows])
        tot = np.array([r[2]["arms"][arm]["total_turns"] for r in rows])
        ax1.plot(f, net, "-o", color=ARM_COLOR[arm], ms=4, label=ARM_MATH[arm])
        ax2.plot(f, tot, "-o", color=ARM_COLOR[arm], ms=4, label=ARM_MATH[arm])
    # Shade clips flagged suspect on any arm.
    for fr, _stem, res in rows:
        if any(res["arms"][a]["suspect"] is True for a in ARMS):
            for ax in (ax1, ax2):
                ax.axvline(fr, color="0.85", lw=5, zorder=0)
    ax1.axhline(0, color="0.6", lw=0.6)
    ax1.set_ylabel("net winding (turns)")
    ax1.set_title(f"Rotation sweep — {voltage:g} V "
                  f"(grey band = ω cross-check suspect)")
    ax2.set_ylabel("total turns (both directions)")
    ax2.set_xlabel("drive frequency (Hz)")
    for ax in (ax1, ax2):
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def write_sweep_csv(rows, voltage, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["stem", "f_drive_hz", "v_drill_v", "arm",
                    "net_turns", "total_turns", "turns_pos", "turns_neg",
                    "net_angle_deg", "peak_abs_angle_deg", "path_turns",
                    "omega_net_turns", "cross_check_diff_turns", "suspect"])
        for f_hz, stem, res in rows:
            for arm in ARMS:
                m = res["arms"][arm]
                w.writerow([
                    stem, f"{f_hz:g}", f"{voltage:g}", arm,
                    f"{m['net_turns']:.4f}", f"{m['total_turns']:.0f}",
                    f"{m['turns_pos']:.0f}", f"{m['turns_neg']:.0f}",
                    f"{m['net_angle_deg']:.2f}", f"{m['peak_abs_angle_deg']:.2f}",
                    f"{m['path_turns']:.4f}",
                    "" if m["omega_net_turns"] is None else f"{m['omega_net_turns']:.4f}",
                    "" if m["cross_check_diff_turns"] is None else f"{m['cross_check_diff_turns']:.4f}",
                    "" if m["suspect"] is None else int(m["suspect"]),
                ])


def print_sweep_table(rows, voltage):
    # Thin vertical rules between the per-arm column pairs give each arm its
    # own bounded area. collapse_padding + pad_edge keep the 13 columns within
    # ~80 cols so the net values never truncate.
    bar = "[grey50]│[/]"
    t = Table(title=f"rotation sweep — {voltage:g} V   (net winding · loops ↻, per arm)",
              box=rich.box.SIMPLE_HEAD, title_style="bold cyan",
              collapse_padding=True, pad_edge=False)
    t.add_column("f (Hz)", justify="right")
    t.add_column("stem")
    t.add_column("│", style="grey50")
    t.add_column("θ₁ net", justify="right", header_style="blue")
    t.add_column("θ₁ ↻",   justify="right", header_style="blue bold")
    t.add_column("│", style="grey50")
    t.add_column("θ₂ net", justify="right", header_style="red")
    t.add_column("θ₂ ↻",   justify="right", header_style="red bold")
    t.add_column("│", style="grey50")
    t.add_column("rel net", justify="right", header_style="green")
    t.add_column("rel ↻",   justify="right", header_style="green bold")
    t.add_column("│", style="grey50")
    t.add_column("ω-check", justify="right")

    for f_hz, stem, res in rows:
        suspect = any(res["arms"][a]["suspect"] is True for a in ARMS)
        has_chk = any(res["arms"][a]["suspect"] is not None for a in ARMS)
        chk = ("[red]suspect[/]" if suspect
               else "[green]ok[/]" if has_chk else "[dim]—[/]")
        u, lo, rel = (res["arms"]["upper"], res["arms"]["lower_abs"],
                      res["arms"]["lower_rel"])
        t.add_row(
            f"{f_hz:g}", stem, bar,
            f"{u['net_turns']:+.2f}",   f"[bold]{u['total_turns']:.0f}[/]", bar,
            f"{lo['net_turns']:+.2f}",  f"[bold]{lo['total_turns']:.0f}[/]", bar,
            f"{rel['net_turns']:+.2f}", f"[bold]{rel['total_turns']:.0f}[/]", bar,
            chk,
        )
    console.print(t)
    console.print("  [dim]net = signed net winding (turns) · ↻ = loop count (full 360° "
                  "turns, either way);  θ₁ upper · θ₂ lower (lab) · rel = θ₂−θ₁[/]")


def run_sweep(args):
    voltage = args.voltage
    rows = collect_sweep(voltage, args.suspect_turns)
    if not rows:
        raise SystemExit(f"no parseable clips found at {voltage:g} V")

    print_sweep_table(rows, voltage)

    csv_out = aggregate_path(f"rotations_sweep_{voltage:g}V.csv")
    write_sweep_csv(rows, voltage, csv_out)
    png_out = aggregate_path(f"rotations_sweep_{voltage:g}V.png")
    make_sweep_figure(rows, voltage, png_out)
    console.print(f"  [dim]{len(rows)} clips → {csv_out}[/]")
    console.print(f"  [dim]→ {png_out}[/]")


# ─────────────────────────────────────────────
# SELF-TEST (synthetic, no data needed)
# ─────────────────────────────────────────────

def selftest():
    def wrap(phi):
        return ((phi + 180.0) % 360.0) - 180.0

    # Pure ramp: 3 full revolutions up.
    ramp = np.linspace(0.0, 3 * 360.0, 1000)
    m = winding_metrics(wrap(ramp))
    assert abs(m["net_turns"] - 3.0) < 0.05, m["net_turns"]
    assert abs(m["total_turns"] - 3.0) <= 1.0, m["total_turns"]
    assert m["turns_neg"] == 0.0, m["turns_neg"]

    # Triangle: 2 turns up then back to start → net 0, total ~4.
    tri = np.concatenate([np.linspace(0, 2 * 360.0, 500),
                          np.linspace(2 * 360.0, 0.0, 500)])
    m2 = winding_metrics(wrap(tri))
    assert abs(m2["net_turns"]) < 0.1, m2["net_turns"]
    assert abs(m2["total_turns"] - 4.0) <= 1.0, m2["total_turns"]
    assert m2["turns_pos"] > 0 and m2["turns_neg"] > 0

    # Bounded oscillation (±80°) never completes a turn.
    osc = 80.0 * np.sin(np.linspace(0, 40 * np.pi, 2000))
    m3 = winding_metrics(wrap(osc))
    assert m3["total_turns"] == 0.0, m3["total_turns"]
    assert abs(m3["net_turns"]) < 0.01, m3["net_turns"]

    # ω integral matches a constant-rate ramp.
    t = np.linspace(0, 10, 1000)
    om = np.full_like(t, 360.0)            # 1 rev/s → 10 turns
    assert abs(omega_net_turns(t, om) - 10.0) < 0.05

    console.print("[green]selftest passed[/] — ramp, triangle, oscillation, ω-integral")


# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", help="single clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--sweep", action="store_true",
                   help="aggregate over all clips at --voltage")
    p.add_argument("--voltage", type=float, default=3.2,
                   help="drive voltage for --sweep (default: 3.2)")
    p.add_argument("--suspect-turns", type=float, default=0.5,
                   dest="suspect_turns",
                   help="flag clip if |ω-integral − unwrap| net turns exceeds "
                        "this (default: 0.5)")
    p.add_argument("--selftest", action="store_true",
                   help="run synthetic unit checks and exit")
    return p.parse_args()


def main():
    args = parse_args()
    if args.selftest:
        selftest()
    elif args.sweep:
        run_sweep(args)
    elif args.stem:
        run_single(args.stem, args)
    else:
        raise SystemExit("provide --stem <stem>, --sweep, or --selftest")


if __name__ == "__main__":
    main()
