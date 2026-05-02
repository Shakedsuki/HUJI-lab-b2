"""
audit.py
---------
Re-validate every clip currently marked ``tracking_quality=verified``
against the *current* verdict logic.

Why this matters
~~~~~~~~~~~~~~~~
A clip's verification status is stamped at track time. The verdict
checks have grown since then — Briefs 3 and 5 added arm-length
rigidity, phase-separated ω, Δω acceleration, and marker-swap
detection. A clip marked PASS before those checks existed never had
its tracker output stress-tested. This script reruns verification
with the current logic and reports which PASS marks survive scrutiny.

Read-only by default. With ``--apply`` it downgrades the
``tracking_quality`` of any clip whose new verdict is no longer PASS,
and records the reasons in ``verification_notes``.

Usage
~~~~~
    chaos audit                      # report only
    chaos audit --apply              # downgrade clips that no longer PASS
    chaos audit --filter th1_p1      # subset by stem substring
    chaos audit --skip-reverify      # skip running verify_tracking; trust
                                     # whatever verification.csv is on disk

Pipeline per clip
~~~~~~~~~~~~~~~~~
1. Locate measurements/<stem>/.
2. (default) Re-run verify_tracking --no-plot to refresh
   verification.csv with current-schema columns.
3. read_verification_metrics → compute_verdict → compare to old.
4. Tabulate; optionally write back to the registry.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

# UTF-8 stdout for the rich glyphs.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


ROOT             = r"C:\dev\chaos"
DATA_DIR         = os.path.join(ROOT, "data")
MEAS_DIR         = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
VERIFY_SCRIPT    = os.path.join(ROOT, "scripts", "processing",
                                "verify_tracking.py")

# In-process imports — track_one + render live in the same dir.
sys.path.insert(0, os.path.join(ROOT, "scripts", "utils"))
from track_one import (  # noqa: E402
    read_verification_metrics,
    compute_verdict,
)

import rich.box  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

console = Console()


# ─────────────────────────────────────────────
# REGISTRY
# ─────────────────────────────────────────────

def load_registry():
    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(reg):
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)


def has_tracking_csv(entry):
    md = entry.get("measurements_dir")
    if not md:
        return False
    return os.path.exists(os.path.join(ROOT, md, "tracking.csv"))


# ─────────────────────────────────────────────
# AUDIT CORE
# ─────────────────────────────────────────────

def gather_verified_clips(reg, filter_substr=None):
    """Yield (key, entry) for clips currently marked tracking_quality=verified
    and with a tracking.csv on disk."""
    for key, entry in reg.items():
        if entry.get("tracking_quality") != "verified":
            continue
        if not has_tracking_csv(entry):
            continue
        cd = entry.get("config_description") or key
        if filter_substr and filter_substr not in cd:
            continue
        yield key, entry


def reverify(stem, omega_cap=2500.0):
    """Run verify_tracking --no-plot for this stem. Returns rc."""
    cmd = [sys.executable, VERIFY_SCRIPT,
           "--stem", stem,
           "--omega-cap", str(omega_cap),
           "--no-plot"]
    # verify_tracking emits θ/ω/Δ unicode chars on stdout, which break
    # subprocess's default cp1252 decoder on Windows. Force UTF-8 on
    # both reads and pass it via the child's PYTHONIOENCODING so
    # nothing in the chain crashes on these glyphs.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, cwd=ROOT,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=env).returncode


def audit_one(stem, *, skip_reverify=False, omega_cap=2500.0):
    """
    Returns a dict per-clip with:
      stem, old_status, new_status, reasons, metrics
    or {"stem": stem, "error": "..."} on failure.
    """
    meas_dir = os.path.join(MEAS_DIR, stem)
    if not os.path.exists(os.path.join(meas_dir, "tracking.csv")):
        return {"stem": stem, "error": "no tracking.csv"}

    if not skip_reverify:
        rc = reverify(stem, omega_cap=omega_cap)
        if rc != 0:
            return {"stem": stem,
                    "error": f"verify_tracking exited {rc}"}

    metrics = read_verification_metrics(meas_dir)
    if metrics is None:
        return {"stem": stem, "error": "no verification.csv"}

    n_susp_post = metrics.get("n_suspect_hidden", 0)
    new_status, reasons = compute_verdict(metrics, n_susp_post)

    return {
        "stem":        stem,
        "old_status":  "PASS",   # by definition — only verified clips audited
        "new_status":  new_status,
        "reasons":     reasons,
        "metrics":     metrics,
    }


# ─────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────

_BADGE = {
    "PASS":  "[bold green]PASS[/]",
    "WARN":  "[bold yellow]WARN[/]",
    "FAIL":  "[bold red]FAIL[/]",
    "ERROR": "[dim red]ERROR[/]",
}


def render_audit_table(rows):
    t = Table(title="Verification Audit  (re-run with current verdict logic)",
              box=rich.box.SIMPLE_HEAD)
    t.add_column("Stem",       style="white")
    t.add_column("Old → New",  justify="center")
    t.add_column("Drop %",     justify="right")
    t.add_column("Susp",       justify="right")
    t.add_column("Δω",         justify="right")
    t.add_column("Swap",       justify="right")
    t.add_column("ArmDev%",    justify="right")
    t.add_column("ω₂ peak",    justify="right")
    t.add_column("Reason",     style="white", max_width=40)

    for r in rows:
        if "error" in r:
            t.add_row(r["stem"],
                      f"PASS → {_BADGE['ERROR']}",
                      "—", "—", "—", "—", "—", "—",
                      f"[dim red]{r['error']}[/]")
            continue
        m = r["metrics"]
        old = r["old_status"]
        new = r["new_status"]
        new_badge = _BADGE.get(new, new)
        if old == new:
            arrow = f"[green]✓ {new_badge}[/]"
        else:
            arrow = f"[yellow]⚠[/] {old} → {new_badge}"
        drop = m.get("free_swing_dropout_pct")
        drop_cell = f"{drop:.2f}" if drop is not None else "—"
        susp = m.get("n_suspect_hidden", 0)
        susp_cell = (f"[red]{susp}[/]" if susp > 5
                     else f"[yellow]{susp}[/]" if susp > 0
                     else "0")
        ace = m.get("n_accel_suspects", 0)
        ace_cell = (f"[red]{ace}[/]" if ace > 5
                    else f"[yellow]{ace}[/]" if ace > 0
                    else "0")
        swap = m.get("n_swap_suspects", 0)
        swap_cell = (f"[red]{swap}[/]" if swap > 0
                     else "0")
        arm = m.get("arm_length_dev_max_pct")
        if arm is None:
            arm_cell = "—"
        elif arm > 10:
            arm_cell = f"[red]{arm:.1f}[/]"
        elif arm > 5:
            arm_cell = f"[yellow]{arm:.1f}[/]"
        else:
            arm_cell = f"[green]{arm:.1f}[/]"
        peak2 = m.get("peak_omega2", 0.0)
        if peak2 > 4000:
            peak_cell = f"[red]{peak2:.0f}[/]"
        elif peak2 > 1500:
            peak_cell = f"[yellow]{peak2:.0f}[/]"
        else:
            peak_cell = f"[green]{peak2:.0f}[/]"
        # Concatenate reasons for display.
        reason = ("; ".join(r["reasons"]) if r["reasons"]
                  else "—")[:60]
        t.add_row(r["stem"], arrow,
                  drop_cell, susp_cell, ace_cell, swap_cell,
                  arm_cell, peak_cell, reason)

    console.print(t)


def render_summary(rows):
    n_total   = len(rows)
    n_ok      = sum(1 for r in rows
                    if "error" not in r and r["new_status"] == "PASS")
    n_warn    = sum(1 for r in rows
                    if "error" not in r and r["new_status"] == "WARN")
    n_fail    = sum(1 for r in rows
                    if "error" not in r and r["new_status"] == "FAIL")
    n_error   = sum(1 for r in rows if "error" in r)
    console.print(
        f"\n  [green]{n_ok} still PASS[/]  ·  "
        f"[yellow]{n_warn} would now WARN[/]  ·  "
        f"[red]{n_fail} would now FAIL[/]  ·  "
        f"[dim]{n_error} errored[/]  "
        f"(of {n_total} audited)")


# ─────────────────────────────────────────────
# DOWNGRADE
# ─────────────────────────────────────────────

def downgrade_clip(reg, key, new_status, reasons):
    """Update tracking_quality on a clip whose new verdict isn't PASS."""
    entry = reg[key]
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    note = (f"DOWNGRADED via chaos audit on {today}: was 'verified'; "
            f"new verdict {new_status}. Reasons: {'; '.join(reasons)}")
    # Map new_status → tracking_quality; FAIL becomes 'failed', WARN
    # becomes 'review' (kept distinct from the legacy 'good' default).
    new_quality = {"FAIL": "failed", "WARN": "review"}.get(new_status, "good")
    entry["tracking_quality"]   = new_quality
    entry["verification_notes"] = note
    entry["audit_date"]         = today
    entry["audit_old_status"]   = "verified"
    entry["audit_new_status"]   = new_status


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Re-validate verified clips against current verdict logic.")
    p.add_argument("--apply", action="store_true",
                   help="downgrade tracking_quality on clips whose new "
                        "verdict is no longer PASS (read-only by default)")
    p.add_argument("--filter", metavar="SUBSTR",
                   help="only audit clips whose stem contains SUBSTR")
    p.add_argument("--skip-reverify", action="store_true",
                   help="trust existing verification.csv; skip the "
                        "verify_tracking re-run (faster but stale)")
    p.add_argument("--omega-cap", type=float, default=2500.0,
                   help="ω cap passed to verify_tracking (default 2500)")
    return p.parse_args()


def main():
    args = parse_args()

    reg = load_registry()
    targets = list(gather_verified_clips(reg, filter_substr=args.filter))
    if not targets:
        print("No verified clips matched.")
        return 0

    print(f"Auditing {len(targets)} verified clips "
          f"({'in-place verify' if not args.skip_reverify else 'no re-verify'})…")
    print()

    rows = []
    for i, (key, entry) in enumerate(targets, start=1):
        stem = entry.get("config_description") or key
        print(f"  [{i}/{len(targets)}]  {stem}", end="", flush=True)
        result = audit_one(stem,
                           skip_reverify=args.skip_reverify,
                           omega_cap=args.omega_cap)
        result["key"] = key
        rows.append(result)
        if "error" in result:
            print(f"   [ERROR: {result['error']}]")
        else:
            print(f"   {result['new_status']}")

    print()
    render_audit_table(rows)
    render_summary(rows)

    if args.apply:
        # Re-load the registry in case anything mutated it during audit
        # (background tracker subprocesses might still be running).
        reg = load_registry()
        n_downgraded = 0
        for r in rows:
            if "error" in r:
                continue
            if r["new_status"] == "PASS":
                continue
            downgrade_clip(reg, r["key"], r["new_status"], r["reasons"])
            n_downgraded += 1
        save_registry(reg)
        print(f"\n  Applied: {n_downgraded} clip(s) downgraded.")
    elif any(r.get("new_status") in ("WARN", "FAIL") for r in rows
             if "error" not in r):
        print("\n  Re-run with [bold]--apply[/] to downgrade clips that no "
              "longer PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
