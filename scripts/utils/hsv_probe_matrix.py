"""
hsv_probe_matrix.py
--------------------
Try every existing HSV calibration file against every clip that bailed
on the HSV adequacy probe, and report which combinations would pass.

Why this exists
~~~~~~~~~~~~~~~
The first pass through `chaos bulk` left N clips at HSV-ABORT — meaning
the global `data/hsv_values.json` doesn't fit them. The slow remedy is
to run `chaos tune <stem>` on each one (~1 min interactive). The fast
optimisation is to check whether any of the per-video HSV files we've
ALREADY tuned (e.g. for clips with similar lighting) would also clear
the adequacy bar on the ABORT clips. Every reused file is one tuning
session saved.

What this does
~~~~~~~~~~~~~~
1. Discovers every `data/hsv_*.json` file (global + per-video).
2. Discovers every clip currently classified HSV-ABORT — that is, has a
   registry entry but no tracking.csv, AND the most recent
   `bulk_tracking_log.json` entry shows returncode=2.
3. For each (clip, hsv-file) pair, opens the video and runs
   `hsv_adequacy_probe`, capturing the verdict + adequacy %.
4. Prints a matrix table and per-clip recommendations: when a non-self
   HSV file scores OK (≥70%) on a clip, suggest the copy command that
   would adopt it as that clip's per-video calibration.

Optionally with `--apply`, copy the highest-scoring OK match into
`data/hsv_<stem>.json` for each clip that has one. Without --apply
nothing on disk changes.

Runtime
~~~~~~~
Each probe samples 30 frames from one video. With M HSV files × N ABORT
clips that's M × N × ~30 frame reads ≈ a few seconds per pair on a
typical machine. For ~17 ABORTs × 4 HSV files that's ~1–3 minutes.

Usage
~~~~~
    python scripts/utils/hsv_probe_matrix.py
    python scripts/utils/hsv_probe_matrix.py --apply
    python scripts/utils/hsv_probe_matrix.py --filter th1_p09
    chaos hsv-probe                                 (after wrapper merge)
    chaos hsv-probe --apply
"""

import argparse
import datetime
import glob
import json
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _THIS_DIR)
from paths import DATA_DIR, MEAS_DIR, VIDEOS_DIR, EXPERIMENTS, REPO_ROOT  # noqa: E402
EXPERIMENTS_FILE = EXPERIMENTS
BULK_LOG_FILE    = os.path.join(DATA_DIR, "bulk_tracking_log.json")
GLOBAL_HSV_FILE  = os.path.join(DATA_DIR, "hsv_values.json")

# Make ring_tracker importable so we can call hsv_adequacy_probe directly.
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts", "processing"))
import ring_tracker as rt  # noqa: E402
import cv2  # noqa: E402


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def discover_hsv_files():
    """
    Return list of (label, path, stem) for every hsv calibration. The
    'stem' is None for the global file, otherwise the clip stem
    extracted from the filename (hsv_<stem>.json).
    """
    files = []
    if os.path.exists(GLOBAL_HSV_FILE):
        files.append(("global", GLOBAL_HSV_FILE, None))
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "hsv_*.json"))):
        if os.path.basename(path) == "hsv_values.json":
            continue
        stem = re.sub(r"^hsv_(.*)\.json$", r"\1", os.path.basename(path))
        files.append((stem, path, stem))
    return files


def has_tracking_csv(entry):
    md = entry.get("measurements_dir")
    if not md:
        return False
    return os.path.exists(os.path.join(REPO_ROOT, md, "tracking.csv"))


def discover_abort_clips(filter_substr=None):
    """
    Return list of (stem, video_path) for every clip currently in
    HSV-ABORT state: registry entry exists, no tracking.csv, and either
    bulk_tracking_log says returncode=2 OR there's no log entry yet
    (we'll still try — speculative, but cheap).
    """
    reg = load_json(EXPERIMENTS_FILE, default={})
    bulk_log = load_json(BULK_LOG_FILE, default={})
    out = []
    for key, entry in reg.items():
        stem = entry.get("config_description") or key
        if filter_substr and filter_substr not in stem:
            continue
        if has_tracking_csv(entry):
            continue
        video_file = entry.get("video_file")
        if not video_file:
            continue
        video_path = os.path.join(VIDEOS_DIR, video_file)
        if not os.path.exists(video_path):
            continue
        bulk_entry = bulk_log.get(stem)
        if bulk_entry is None or bulk_entry.get("returncode") == 2:
            out.append((stem, video_path))
    out.sort(key=lambda r: r[0])
    return out


def load_hsv_for_probe(path):
    """Read an hsv_*.json file and normalise it the same way
    ring_tracker.load_hsv_values does. Returns the dict + ring_tolerance."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k in ("green", "red"):
        if k not in data:
            raise ValueError(f"{path}: missing '{k}' section")
    data["red"].setdefault("h_min2", 170)
    data["red"].setdefault("h_max2", 180)
    ring_tol = int(data.get("ring_tolerance", rt.DEFAULT_RING_TOL))
    return data, ring_tol


def probe_one(video_path, hsv_values, ring_tol):
    """
    Run hsv_adequacy_probe and return (verdict, both_pct). On open
    failure return ("ERROR", 0.0).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return "ERROR", 0.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    try:
        verdict, both_pct, _, _ = rt.hsv_adequacy_probe(
            cap, total, hsv_values, ring_tol,
            use_filename_prior=True, video_path=video_path,
        )
    finally:
        cap.release()
    return verdict, both_pct


def parse_args():
    p = argparse.ArgumentParser(
        description="Probe every existing HSV file against every "
                    "HSV-ABORT clip; report which combinations pass.")
    p.add_argument("--filter", metavar="SUBSTR",
                   help="only probe clips whose stem contains SUBSTR")
    p.add_argument("--apply", action="store_true",
                   help="for each clip with at least one OK match, copy "
                        "the highest-scoring file to data/hsv_<stem>.json")
    p.add_argument("--warn-also", action="store_true",
                   help="also recommend WARN matches (≥40%%, default OK only)")
    return p.parse_args()


def main():
    args = parse_args()

    hsv_files = discover_hsv_files()
    if not hsv_files:
        print("No HSV files found in data/. Run hsv_tuner first.")
        return 1

    clips = discover_abort_clips(filter_substr=args.filter)
    if not clips:
        print("No HSV-ABORT clips to probe.")
        return 0

    print(f"Probing {len(clips)} HSV-ABORT clips against "
          f"{len(hsv_files)} HSV files "
          f"(~{len(clips) * len(hsv_files)} probes total).")
    print()

    # ── Load every HSV file once ───────────────────────────────────────
    loaded = []
    for label, path, stem in hsv_files:
        try:
            data, ring_tol = load_hsv_for_probe(path)
            loaded.append((label, path, stem, data, ring_tol))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"  skipping {path}: {e}")
    if not loaded:
        return 1

    # ── Header row ─────────────────────────────────────────────────────
    label_w = max(28, max(len(s) for s, _ in clips) + 2)
    file_w  = max(8, max(len(l) for l, *_ in loaded))
    header_cols = [f"{l:>{file_w}}" for l, *_ in loaded]
    print(f"  {'clip':<{label_w}}  " + "  ".join(header_cols))
    print(f"  {'-' * label_w}  " + "  ".join("-" * file_w for _ in loaded))

    # ── Probe matrix ───────────────────────────────────────────────────
    results = {}            # results[stem] = list of (label, verdict, pct)
    for stem, video_path in clips:
        row = []
        for label, path, src_stem, data, ring_tol in loaded:
            verdict, pct = probe_one(video_path, data, ring_tol)
            row.append((label, path, verdict, pct))
        results[stem] = row

        cells = []
        for label, path, verdict, pct in row:
            tag = {"OK": "OK ", "WARN": "WRN", "ABORT": "—  ", "ERROR": "ERR"}[verdict]
            cells.append(f"{tag}{pct:>4.0f}".rjust(file_w))
        print(f"  {stem:<{label_w}}  " + "  ".join(cells))

    print()

    # ── Recommendations ─────────────────────────────────────────────────
    print("=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    threshold_str = "OK (≥70%)" if not args.warn_also else "OK or WARN (≥40%)"
    print(f"  Match criterion: best non-self HSV file scoring {threshold_str}.")
    print()

    actions = []          # (stem, src_path, src_label, pct)
    no_match = []
    for stem, video_path in clips:
        row = results[stem]
        # Skip self-match (a file named hsv_<this_stem>.json shouldn't
        # really exist for an ABORT clip, but be defensive).
        candidates = [(label, path, verdict, pct)
                      for label, path, verdict, pct in row
                      if label != stem]
        if not args.warn_also:
            candidates = [c for c in candidates if c[2] == "OK"]
        else:
            candidates = [c for c in candidates if c[2] in ("OK", "WARN")]

        if not candidates:
            no_match.append(stem)
            continue
        candidates.sort(key=lambda c: -c[3])      # highest pct first
        best_label, best_path, best_verdict, best_pct = candidates[0]
        actions.append((stem, best_path, best_label, best_pct, best_verdict))

    if actions:
        print(f"  REUSABLE — {len(actions)} clip(s) can adopt an existing HSV file:")
        for stem, src_path, src_label, pct, verdict in actions:
            dst_path = os.path.join(DATA_DIR, f"hsv_{stem}.json")
            print(f"    {stem:<28}  ←  {src_label}  "
                  f"({verdict} {pct:.0f}%)")
            print(f"      cp \"{os.path.relpath(src_path, REPO_ROOT)}\" "
                  f"\"{os.path.relpath(dst_path, REPO_ROOT)}\"")
    else:
        print("  No reusable matches found.")

    if no_match:
        print()
        print(f"  NEEDS-TUNE — {len(no_match)} clip(s) need fresh `chaos tune`:")
        for stem in no_match:
            print(f"    {stem}")

    # ── Apply (optional) ──────────────────────────────────────────────
    if args.apply and actions:
        print()
        print("=" * 70)
        print("APPLYING MATCHES")
        print("=" * 70)
        for stem, src_path, src_label, pct, verdict in actions:
            dst_path = os.path.join(DATA_DIR, f"hsv_{stem}.json")
            if os.path.exists(dst_path):
                # Don't clobber an existing per-video file (defensive —
                # shouldn't happen for ABORT clips, but be safe).
                print(f"  skip  {stem:<28}  (hsv_{stem}.json already exists)")
                continue
            shutil.copy2(src_path, dst_path)
            # Record the source so we can audit later.
            with open(dst_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_copied_from"] = src_label
            data["_copied_at"]   = datetime.datetime.now().strftime("%Y-%m-%d")
            data["_copied_probe_pct"] = round(pct, 1)
            data["_copied_probe_verdict"] = verdict
            with open(dst_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"  copy  {stem:<28}  ←  {src_label}  "
                  f"({verdict} {pct:.0f}%)")
        print()
        print("Next: re-run `chaos bulk --redo` (or `chaos track <stem>` "
              "per clip) to take advantage of the new HSV files.")
    elif actions and not args.apply:
        print()
        print("Re-run with --apply to copy the recommended HSV files into place.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
