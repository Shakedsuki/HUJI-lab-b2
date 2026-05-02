"""
generate_roadmap.py
--------------------
Emit docs/tracking_roadmap.md — a per-clip status sheet with dropout %,
tracking quality, and notes — by reading experiments.json plus optional
sidecars from the most recent bulk_track / track_one runs.

Why this exists
~~~~~~~~~~~~~~~
`chaos status` prints a one-line summary (tracked vs pending) and
`chaos report` produces an Excel workbook for stakeholders. The roadmap
fills the gap between them: a markdown table that's diff-friendly,
checked into the repo, and gives the engineer a single page to see
which clips are PASS/WARN/FAIL/ABORT and what's outstanding.

Inputs read
~~~~~~~~~~~
- data/experiments.json           — tracking_quality, dropout_rate_pct,
                                    verification_date, verification_notes,
                                    n_free_frames, duration_s, init/release
- data/bulk_tracking_log.json     — per-clip return code from the most
                                    recent `chaos bulk` run (used to
                                    distinguish HSV-ABORT clips from
                                    "never attempted")
- measurements/<stem>/verification.csv (optional)
                                  — fresh peak |ω| + suspect count when
                                    available; falls back gracefully
                                    when the file is missing

Output
~~~~~~
docs/tracking_roadmap.md  — markdown with a summary block and per-clip
                            table. Re-runnable: overwrites in place.
"""

import argparse
import csv
import datetime
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT             = r"C:\dev\chaos"
DATA_DIR         = os.path.join(ROOT, "data")
MEAS_DIR         = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
BULK_LOG_FILE    = os.path.join(DATA_DIR, "bulk_tracking_log.json")
DEFAULT_OUT      = os.path.join(ROOT, "docs", "tracking_roadmap.md")


# Bucket priority — first match wins, in this order. Drives the summary
# counts and the per-clip Status column.
BUCKETS = [
    ("verified",         "PASS",        "passed verification, in registry as verified"),
    ("tracked-warn",     "WARN",        "tracking.csv exists, dropout/peak ω in WARN band"),
    ("tracked-fail",     "FAIL",        "tracking.csv exists but dropout > 10% or peak ω absurd"),
    ("hsv-abort",        "HSV-ABORT",   "ring_tracker bailed on the HSV adequacy probe — needs `chaos tune`"),
    ("needs-picker",     "NEEDS-PICKER","no init/release/tag_frame in registry — needs interactive picker"),
    ("never-attempted",  "PENDING",     "registry entry exists but no track_one run on record"),
]


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def has_tracking_csv(entry):
    md = entry.get("measurements_dir")
    if not md:
        return False
    return os.path.exists(os.path.join(ROOT, md, "tracking.csv"))


def read_verification_metrics(meas_dir):
    """Brief 6 — return a dict with the per-clip fields the roadmap
    needs. Falls back gracefully when verification.csv or
    verification_meta.json is absent or malformed.

    Schema: {peak_omega2, n_suspect_hidden, n_trend_arm_suspects,
             n_trend_arm_windows, n_residual_suspects,
             n_energy_suspects, n_energy_ceiling_suspects,
             pivot_drift_px}
    """
    out = {
        "peak_omega2":               None,
        "n_suspect_hidden":          None,
        "n_trend_arm_suspects":      0,
        "n_trend_arm_windows":       0,
        "n_residual_suspects":       0,
        "n_energy_suspects":         0,
        "n_energy_ceiling_suspects": 0,
        "pivot_drift_px":            None,
    }
    csv_path = os.path.join(meas_dir, "verification.csv")
    if os.path.exists(csv_path):
        peak = 0.0
        n_susp = 0
        n_trend = n_res = n_eng = n_eng_ceil = 0
        try:
            with open(csv_path, "r", newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        o2 = abs(float(r.get("omega2_deg_s") or 0))
                        if o2 > peak:
                            peak = o2
                    except ValueError:
                        pass
                    try:
                        if (int(r.get("suspect") or 0)
                                and not int(r.get("dropout") or 0)):
                            n_susp += 1
                    except ValueError:
                        pass
                    # Brief 6 columns — defensive (older CSVs lack them).
                    for col, key in (
                        ("trend_arm_suspect",      "n_trend_arm_suspects"),
                        ("residual_suspect",       "n_residual_suspects"),
                        ("energy_suspect",         "n_energy_suspects"),
                        ("energy_ceiling_suspect", "n_energy_ceiling_suspects"),
                    ):
                        try:
                            if int(r.get(col) or 0) == 1:
                                if key == "n_trend_arm_suspects":      n_trend  += 1
                                elif key == "n_residual_suspects":       n_res    += 1
                                elif key == "n_energy_suspects":         n_eng    += 1
                                elif key == "n_energy_ceiling_suspects": n_eng_ceil += 1
                        except (ValueError, TypeError):
                            pass
        except (OSError, csv.Error):
            return out
        out["peak_omega2"]               = peak
        out["n_suspect_hidden"]          = n_susp
        out["n_trend_arm_suspects"]      = n_trend
        out["n_residual_suspects"]       = n_res
        out["n_energy_suspects"]         = n_eng
        out["n_energy_ceiling_suspects"] = n_eng_ceil

    meta_path = os.path.join(meas_dir, "verification_meta.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                m = json.load(f)
            out["pivot_drift_px"]      = m.get("pivot_drift_px")
            out["n_trend_arm_windows"] = int(m.get("n_trend_arm_windows") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return out


def read_peak_omega_and_suspects(meas_dir):
    """Backwards-compatible wrapper. Call sites that only need the two
    headline numbers can keep using this signature."""
    m = read_verification_metrics(meas_dir)
    return m["peak_omega2"], m["n_suspect_hidden"]


def classify(entry, bulk_entry):
    """
    Return (bucket_id, label) for this clip. Order matters — see BUCKETS.

    `bulk_entry` is the row from data/bulk_tracking_log.json keyed by
    config_description, or None if the clip wasn't part of the latest
    bulk pass.
    """
    if entry.get("tracking_quality") == "verified":
        return "verified", "PASS"

    if has_tracking_csv(entry):
        # Has a CSV; bin by free-swing dropout % which is in the registry.
        d = entry.get("dropout_rate_pct")
        if d is not None and d > 10:
            return "tracked-fail", "FAIL"
        return "tracked-warn", "WARN"

    # No tracking CSV — has the bulk runner already attempted this clip?
    if bulk_entry is not None and bulk_entry.get("returncode") == 2:
        return "hsv-abort", "HSV-ABORT"

    if entry.get("tag_frame") is None and entry.get("init_frame") is None:
        return "needs-picker", "NEEDS-PICKER"

    return "never-attempted", "PENDING"


def first_attempt_iso(entry, bulk_entry):
    """When did we last touch this clip? Prefer verification_date, then
    interpolation_date, then bulk_log's ran_at, else '—'."""
    for k in ("verification_date", "interpolation_date", "last_override_date"):
        v = entry.get(k)
        if v:
            return str(v)
    if bulk_entry and bulk_entry.get("ran_at"):
        return bulk_entry["ran_at"][:10]
    return "—"


def short_note(entry, bulk_entry, bucket):
    """One-line note column. Pulls from the most diagnostic field for
    each bucket."""
    if bucket == "verified":
        n = entry.get("verification_notes") or ""
        return n[:80] + ("…" if len(n) > 80 else "")
    if bucket == "tracked-fail":
        return f"dropout {entry.get('dropout_rate_pct')}% — re-track or HSV tune"
    if bucket == "tracked-warn":
        bits = []
        d = entry.get("dropout_rate_pct")
        if d is not None and d > 5:
            bits.append(f"dropout {d:.1f}%")
        if entry.get("suspect_frames_interpolated"):
            bits.append(f"interp {entry['suspect_frames_interpolated']}")
        return "; ".join(bits) or "review verification.png"
    if bucket == "hsv-abort":
        return "global HSV doesn't fit; run `chaos tune <stem>`"
    if bucket == "needs-picker":
        return "no tag_frame/init_frame; run `chaos next` to pick init/release"
    if bucket == "never-attempted":
        return "no record in bulk_tracking_log yet"
    return ""


def build_table_rows(reg, bulk_log):
    """Return a list of dicts, one per clip, sorted: PASS first, then
    WARN, FAIL, HSV-ABORT, NEEDS-PICKER, PENDING — and within each bucket
    by stem."""
    bucket_order = {b[0]: i for i, b in enumerate(BUCKETS)}
    rows = []
    for key, entry in reg.items():
        stem = entry.get("config_description") or key
        bulk_entry = bulk_log.get(stem)
        bucket, label = classify(entry, bulk_entry)
        meas_dir = os.path.join(ROOT, entry.get("measurements_dir") or
                                f"measurements/{stem}")
        m = read_verification_metrics(meas_dir)
        # Brief 8: clips PASS-verified before Brief 5 are unverified
        # against the current physics checks. Mark them visually so the
        # engineer knows to re-audit.
        brief_ver = entry.get("verified_under_brief_version")
        needs_reaudit = (entry.get("tracking_quality") == "verified"
                         and (brief_ver is None or int(brief_ver) < 5))
        rows.append({
            "stem":     stem,
            "key":      key,
            "bucket":   bucket,
            "label":    label,
            "drop_pct": entry.get("dropout_rate_pct"),
            "peak_o2":  m["peak_omega2"],
            "n_susp":   m["n_suspect_hidden"],
            "n_free":   entry.get("n_free_frames"),
            "duration": entry.get("duration_s"),
            "th1_rel":  entry.get("theta1_release"),
            "th2_rel":  entry.get("theta2_release"),
            "init":     entry.get("init_frame"),
            "release":  entry.get("release_frame"),
            "last":     first_attempt_iso(entry, bulk_entry),
            "note":     short_note(entry, bulk_entry, bucket),
            # Brief 6 — physics-check counts
            "n_trend_arm_susp":      m["n_trend_arm_suspects"],
            "n_trend_arm_win":       m["n_trend_arm_windows"],
            "n_residual_susp":       m["n_residual_suspects"],
            "n_energy_susp":         m["n_energy_suspects"],
            "n_energy_ceil_susp":    m["n_energy_ceiling_suspects"],
            "pivot_drift_px":        m["pivot_drift_px"],
            # Brief 8 — re-audit flag
            "brief_version":         brief_ver,
            "needs_reaudit":         needs_reaudit,
        })
    rows.sort(key=lambda r: (bucket_order[r["bucket"]], r["stem"]))
    return rows


def fmt(v, kind):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.2f}%"
    if kind == "omega":
        return f"{v:.0f}"
    if kind == "int":
        return str(int(v))
    if kind == "deg":
        return f"{v:.1f}°"
    return str(v)


def render_markdown(rows, reg, bulk_log):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    bucket_counts = {b[0]: 0 for b in BUCKETS}
    for r in rows:
        bucket_counts[r["bucket"]] += 1

    lines = []
    lines.append("# Tracking Roadmap")
    lines.append("")
    lines.append(f"_Generated {now}._ Re-run with `chaos roadmap`.")
    lines.append("")
    lines.append("Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). "
                 "Every row reflects the current state of "
                 "`data/experiments.json` plus the latest "
                 "`data/bulk_tracking_log.json` and per-clip "
                 "`measurements/<stem>/verification.csv`.")
    lines.append("")

    # Summary block
    lines.append("## Summary")
    lines.append("")
    lines.append("| Status | Count | Meaning |")
    lines.append("|---|---|---|")
    for bucket_id, label, meaning in BUCKETS:
        lines.append(f"| **{label}** | {bucket_counts[bucket_id]} | {meaning} |")
    lines.append(f"| _total_ | {len(rows)} | every entry in `experiments.json` |")
    lines.append("")

    # Per-clip table — Brief 6 columns added; rows that need a Brief 6
    # re-audit are visually flagged in the Status cell.
    lines.append("## Per-clip status")
    lines.append("")
    lines.append("| Stem | Status | Drop% | Peak ω₂ | Susp | "
                 "Trend (susp/win) | θ-resid | E-ceil/total | "
                 "Pivot drift | Free | Last | Notes |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    n_reaudit = 0
    for r in rows:
        label = r["label"]
        if r.get("needs_reaudit"):
            label = f"⚠ {label} _(pre-Brief-5)_"
            n_reaudit += 1
        trend_cell = (f"{r['n_trend_arm_susp']}/{r['n_trend_arm_win']}"
                      if r['n_trend_arm_win'] else "0/0")
        eng_cell = (f"{r['n_energy_ceil_susp']}/{r['n_energy_susp']}"
                    if r['n_energy_susp'] else "0/0")
        drift = r.get("pivot_drift_px")
        drift_cell = f"{drift:.1f}px" if drift is not None else "—"
        lines.append(
            f"| `{r['stem']}` | {label} | "
            f"{fmt(r['drop_pct'], 'pct')} | "
            f"{fmt(r['peak_o2'], 'omega')} | "
            f"{fmt(r['n_susp'], 'int')} | "
            f"{trend_cell} | "
            f"{r['n_residual_susp']} | "
            f"{eng_cell} | "
            f"{drift_cell} | "
            f"{fmt(r['n_free'], 'int')} | "
            f"{r['last']} | "
            f"{r['note']} |"
        )
    lines.append("")

    if n_reaudit:
        lines.append(
            f"> **{n_reaudit} clip(s) marked ⚠** were verified before the "
            f"Brief 5+6 physics checks landed (i.e. "
            f"`verified_under_brief_version < 5`). Run `chaos audit "
            f"--apply` or `chaos verify <stem>` to re-validate them "
            f"against the current thresholds.")
        lines.append("")

    # What to do next
    lines.append("## What to do next")
    lines.append("")
    todos = []
    n_abort = bucket_counts["hsv-abort"]
    n_picker = bucket_counts["needs-picker"]
    n_pending = bucket_counts["never-attempted"]
    n_warn = bucket_counts["tracked-warn"]
    n_fail = bucket_counts["tracked-fail"]
    if n_abort:
        todos.append(f"- **{n_abort} clips need per-clip HSV tuning.** "
                     f"Run `chaos tune <stem>` then `chaos track <stem>` "
                     f"on each HSV-ABORT row above.")
    if n_picker:
        todos.append(f"- **{n_picker} clips need a manual init/release pick.** "
                     f"Run `chaos next --stem <stem>` to drop into the picker.")
    if n_pending:
        todos.append(f"- **{n_pending} clips never tracked.** "
                     f"Run `chaos bulk` to attempt them all in one shot.")
    if n_warn:
        todos.append(f"- **{n_warn} clips landed in WARN.** "
                     f"Inspect `measurements/<stem>/verification.png`; if "
                     f"acceptable, mark verified; otherwise `chaos fix <stem>`.")
    if n_fail:
        todos.append(f"- **{n_fail} clips landed in FAIL.** "
                     f"Re-tune HSV or run `chaos fix <stem>` with seeds.")
    if not todos:
        todos.append("- Everything is in PASS. Nothing pending.")
    lines.extend(todos)
    lines.append("")

    return "\n".join(lines)


def parse_args():
    p = argparse.ArgumentParser(
        description="Generate docs/tracking_roadmap.md from current registry state.")
    p.add_argument("--output", default=DEFAULT_OUT, metavar="PATH",
                   help=f"output path (default: {DEFAULT_OUT})")
    p.add_argument("--dry-run", action="store_true",
                   help="print the markdown to stdout instead of writing.")
    return p.parse_args()


def main():
    args = parse_args()
    reg = load_json(EXPERIMENTS_FILE, default={})
    bulk_log = load_json(BULK_LOG_FILE, default={})

    rows = build_table_rows(reg, bulk_log)
    md = render_markdown(rows, reg, bulk_log)

    if args.dry_run:
        print(md)
        return 0

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(md)

    bucket_counts = {b[0]: 0 for b in BUCKETS}
    for r in rows:
        bucket_counts[r["bucket"]] += 1
    print(f"Wrote: {args.output}")
    print(f"  PASS={bucket_counts['verified']}  "
          f"WARN={bucket_counts['tracked-warn']}  "
          f"FAIL={bucket_counts['tracked-fail']}  "
          f"HSV-ABORT={bucket_counts['hsv-abort']}  "
          f"NEEDS-PICKER={bucket_counts['needs-picker']}  "
          f"PENDING={bucket_counts['never-attempted']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
