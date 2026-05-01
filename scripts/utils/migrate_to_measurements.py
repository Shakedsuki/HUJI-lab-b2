"""
migrate_to_measurements.py
---------------------------
One-shot migration that collapses per-measurement outputs into a single
canonical folder per measurement under measurements/<config_description>/.

Before:
    data/<stem>_tracking.csv
    data/<stem>_tracking_verification.csv
    output/<stem>_debug.mp4
    output/<stem>_tracking_verification.png
    data/figures/<stem>_combined.mp4
    data/figures/<stem>_phase_animation.mp4
    data/figures/<stem>_*_3d_trajectory.png
    data/figures/<stem>_*_3d_rotation.mp4
    data/figures/<stem>_*_sanity.png

After:
    measurements/<config_description>/tracking.csv
    measurements/<config_description>/verification.csv
    measurements/<config_description>/debug.mp4
    measurements/<config_description>/verification.png
    measurements/<config_description>/combined.mp4
    measurements/<config_description>/phase_animation.mp4
    measurements/<config_description>/phase_3d_trajectory.png
    measurements/<config_description>/phase_3d_rotation.mp4
    measurements/<config_description>/phase_panels.png

Idempotent: rerunning is safe — destinations that already exist are
skipped without overwriting. Sources that don't exist are also skipped
(useful when a measurement only has some of the outputs).

This script also fixes registry bookkeeping in experiments.json:
  * removes stale entries that refer to missing video files
  * renames keys whose name disagrees with the config_description
  * registers the two unregistered repeat-trial videos
  * for every kept entry: populates config_description, sets
    measurements_dir to "measurements/<config_description>", and
    rewrites csv_file to the canonical "tracking.csv"

Usage:
    python scripts/utils/migrate_to_measurements.py
"""

import datetime
import glob
import json
import os
import re
import shutil
import sys


# ─────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────

ROOT             = r"C:\dev\chaos"
DATA_DIR         = os.path.join(ROOT, "data")
OUTPUT_DIR       = os.path.join(ROOT, "output")
FIGURES_DIR      = os.path.join(DATA_DIR, "figures")
MEAS_DIR         = os.path.join(ROOT, "measurements")
EXPERIMENTS_FILE = os.path.join(DATA_DIR, "experiments.json")
LOG_FILE         = os.path.join(DATA_DIR, "migration_log.txt")

CONFIG_RE = re.compile(r"^th1_[pm]\d+_th2_[pm]\d+(_r\d+)?$")


# Stale entries (their videos no longer exist; the underlying measurement
# is recorded under a different key, or the video was discarded).
STALE_ENTRIES = {
    "DSC_0142": "Points to th1_m030_th2_m118.mov which doesn't exist; covered by th1_m030_th2_m118 entry",
    "DSC_0147": "Points to th1_m001_th2_p093.mov which doesn't exist; covered by th1_m001_th2_p093 entry",
    "DSC_0155": "Duplicate untracked entry for th1_p180_th2_p180.mov; already tracked under th1_p180_th2_p180 key",
    "DSC_0163": "Points to DSC_0163.mov which doesn't exist; no equivalent found",
    "DSC_0164": "Points to DSC_0164.mov which doesn't exist; no equivalent found",
}

# Old key name → new key name. The old keys came from a tagging mistake
# where the registry key didn't match the underlying config_description.
KEY_RENAMES = {
    "th1_m001_th2_p093": "th1_p001_th2_p093",
    "th1_m030_th2_m118": "th1_p082_th2_p001",
}

# Unregistered repeat-trial videos. Both files exist in Videos/ but are
# missing from experiments.json — we register them here so they get a
# measurements/ folder and show up in --status output.
NEW_ENTRIES = {
    "th1_p090_th2_p000_r2": {
        "video_file":         "th1_p090_th2_p000_2.mov",
        "config_description": "th1_p090_th2_p000_r2",
        "video_label":        "th1_p090_th2_p000_r2",
        "theta1_measured":    90.36,
        "theta2_measured":    0.0,
        "repeat_number":      2,
        "notes":              "Repeat trial of th1_p090_th2_p000. Registered during measurements/ migration.",
    },
    "th1_p094_th2_p000_r2": {
        "video_file":         "th1_p094_th2_p000_2.mov",
        "config_description": "th1_p094_th2_p000_r2",
        "video_label":        "th1_p094_th2_p000_r2",
        "theta1_measured":    93.58,
        "theta2_measured":    0.35,
        "repeat_number":      2,
        "notes":              "Repeat trial of th1_p094_th2_p000. Registered during measurements/ migration.",
    },
}

# Explicit overrides for entries where the synthesis rules can't get the
# right answer (e.g. legacy entries with theta_release but no
# theta_measured). The brief specifies the resolution explicitly.
EXPLICIT_CONFIG_DESCRIPTIONS = {
    # DSC_0165 has empty config_description, a non-conforming video file
    # name, and no theta_measured fields. The brief mandates this result.
    "DSC_0165": "th1_m001_th2_p001",
}


# ─────────────────────────────────────────────
# LOG
# ─────────────────────────────────────────────

class Log:
    """Tee writer: prints to stdout and appends to LOG_FILE."""

    def __init__(self):
        self.lines = []

    def __call__(self, line=""):
        print(line)
        self.lines.append(line)

    def flush(self):
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")


# ─────────────────────────────────────────────
# CONFIG DESCRIPTION RESOLUTION
# ─────────────────────────────────────────────

def synthesize_config_description(entry):
    """
    Build a config_description from theta1/theta2 angles. Prefers
    *_measured fields (the canonical source); falls back to *_release
    when the entry only has tracking-derived ICs. Returns None when
    neither set is available.

    Rule: round to nearest int, "p" if >= 0 else "m", zero-pad to 3 digits.
    """
    th1 = entry.get("theta1_measured")
    th2 = entry.get("theta2_measured")
    if th1 is None or th2 is None:
        th1 = entry.get("theta1_release")
        th2 = entry.get("theta2_release")
    if th1 is None or th2 is None:
        return None

    def fmt(angle):
        n = int(round(float(angle)))
        sign = "p" if n >= 0 else "m"
        return f"{sign}{abs(n):03d}"

    return f"th1_{fmt(th1)}_th2_{fmt(th2)}"


def resolve_config_description(key, entry):
    """
    Returns the canonical config_description for an entry, or None when
    no rule matches (caller should skip).

    Precedence:
      1. EXPLICIT_CONFIG_DESCRIPTIONS[key] (hard-coded overrides)
      2. entry["config_description"] when non-empty
      3. video filename stem when it matches th1_[pm]NNN_th2_[pm]NNN(_rN)?
      4. synthesize from theta1/theta2 angles
    """
    if key in EXPLICIT_CONFIG_DESCRIPTIONS:
        return EXPLICIT_CONFIG_DESCRIPTIONS[key]

    cd = entry.get("config_description")
    if cd:
        return cd

    video = entry.get("video_file") or ""
    stem  = os.path.splitext(os.path.basename(video))[0]
    if CONFIG_RE.match(stem):
        return stem

    return synthesize_config_description(entry)


# ─────────────────────────────────────────────
# FILE MOVE
# ─────────────────────────────────────────────

def move_one(src, dst, log):
    """
    Move src → dst. Idempotent and tolerant of missing sources:
      * if src doesn't exist: log [SKIP] and return False
      * if dst already exists: log [DONE] and return True
                                (treat as already migrated)
      * otherwise: shutil.move and log [OK]; return True on success.
    Returns False on actual error (caller will count those).
    """
    if not os.path.exists(src):
        log(f"  [SKIP] {os.path.relpath(src, ROOT)} - source not found")
        return None      # neither moved nor errored

    if os.path.exists(dst):
        log(f"  [DONE] {os.path.relpath(dst, ROOT)} - destination already exists; "
            f"leaving source in place at {os.path.relpath(src, ROOT)}")
        return True

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.move(src, dst)
        log(f"  [OK]   {os.path.relpath(src, ROOT)} -> {os.path.relpath(dst, ROOT)}")
        return True
    except OSError as e:
        log(f"  [ERR]  {os.path.relpath(src, ROOT)} -> {os.path.relpath(dst, ROOT)}: {e}")
        return False


def plan_moves_for_entry(stems, dest_dir):
    """
    Build (source, destination) pairs for an entry given a list of
    candidate stems to try. Outputs were historically named after the
    stem, but the "stem" depends on the entry's history: legacy entries
    (e.g. DSC_0136) keep DSC-style names even after the underlying video
    file was renamed to a th1_pNNN_th2_pMMM form. So we try every
    candidate (registry key, video filename stem) and use the first one
    that actually exists on disk for each destination.

    Each destination appears at most once in the result. When no
    candidate stem yields an existing source, the destination is still
    emitted with the first-tried source so that move_one() logs [SKIP].

    Glob patterns are used for the 3D and sanity figures because their
    historical names embed an arbitrary middle token like
    "_v2_tracking_" or "_tracking_" that depends on which CSV was passed
    to the analysis script.
    """
    pairs = []
    seen_dests = set()

    # Deduplicate stems while preserving order — first occurrence wins
    # when picking the SKIP-source to log. Empty/None stems are dropped.
    candidates = []
    for s in stems:
        if s and s not in candidates:
            candidates.append(s)

    def add_pair(rel_dir, suffix_template, dest_basename):
        """
        Try every candidate stem in order; first existing source wins.
        Falls back to the first candidate's path so move_one logs [SKIP]
        for the more representative name.
        """
        dst = os.path.join(dest_dir, dest_basename)
        if dst in seen_dests:
            return
        seen_dests.add(dst)

        chosen_src = None
        for stem in candidates:
            cand = os.path.join(rel_dir, suffix_template.format(stem=stem))
            if os.path.exists(cand):
                chosen_src = cand
                break
        if chosen_src is None:
            chosen_src = os.path.join(
                rel_dir, suffix_template.format(stem=candidates[0]))
        pairs.append((chosen_src, dst))

    def add_glob_pair(rel_dir, glob_templates, dest_basename):
        """
        Like add_pair but for glob patterns — analysis scripts embed
        unpredictable middle tokens. Iterate stems × patterns; first
        match wins.
        """
        dst = os.path.join(dest_dir, dest_basename)
        if dst in seen_dests:
            return
        seen_dests.add(dst)

        for stem in candidates:
            for pat_tmpl in glob_templates:
                pat = os.path.join(rel_dir, pat_tmpl.format(stem=stem))
                matches = sorted(glob.glob(pat))
                if matches:
                    pairs.append((matches[-1], dst))
                    return
        # No match anywhere: leave nothing in pairs (no [SKIP] noise for
        # globbed sources that simply don't exist for this measurement).

    # Direct one-to-one mappings.
    add_pair(DATA_DIR,   "{stem}_tracking.csv",                "tracking.csv")
    add_pair(DATA_DIR,   "{stem}_tracking_verification.csv",   "verification.csv")
    add_pair(OUTPUT_DIR, "{stem}_tracking_verification.png",   "verification.png")
    add_pair(OUTPUT_DIR, "{stem}_debug.mp4",                   "debug.mp4")
    add_pair(FIGURES_DIR, "{stem}_combined.mp4",               "combined.mp4")
    add_pair(FIGURES_DIR, "{stem}_phase_animation.mp4",        "phase_animation.mp4")

    # Glob-based mappings.
    add_glob_pair(FIGURES_DIR, [
        "{stem}_*_3d_trajectory.png",
        "{stem}_3d_trajectory.png",
    ], "phase_3d_trajectory.png")

    add_glob_pair(FIGURES_DIR, [
        "{stem}_*_3d_rotation.mp4",
        "{stem}_3d_rotation.mp4",
    ], "phase_3d_rotation.mp4")

    add_glob_pair(FIGURES_DIR, [
        "{stem}_*_sanity.png",
        "{stem}_sanity.png",
        "{stem}_panels.png",
    ], "phase_panels.png")

    return pairs


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    log = Log()
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log("MIGRATION LOG - " + timestamp)
    log("=" * 56)
    log()

    # ── Load registry ────────────────────────────────────────────────
    if not os.path.exists(EXPERIMENTS_FILE):
        log(f"ERROR: registry not found: {EXPERIMENTS_FILE}")
        log.flush()
        return 2

    with open(EXPERIMENTS_FILE, "r", encoding="utf-8") as f:
        reg = json.load(f)
    log(f"Loaded registry: {len(reg)} entries from {os.path.relpath(EXPERIMENTS_FILE, ROOT)}")
    log()

    # ── Stage A: remove stale entries ─────────────────────────────────
    log(f"STALE entries removed: {len(STALE_ENTRIES)}")
    for key, reason in STALE_ENTRIES.items():
        if key in reg:
            del reg[key]
            log(f"  - {key} ({reason})")
        else:
            log(f"  - {key} (already absent — skipping)")
    log()

    # ── Stage B: key renames ─────────────────────────────────────────
    log("KEY renames:")
    for old, new in KEY_RENAMES.items():
        if old in reg and new not in reg:
            reg[new] = reg.pop(old)
            log(f"  - {old} -> {new}")
        elif old not in reg and new in reg:
            log(f"  - {old} -> {new} (already renamed)")
        elif old in reg and new in reg:
            log(f"  - {old} -> {new} (WARN: both keys present; keeping {new}, dropping {old})")
            del reg[old]
        else:
            log(f"  - {old} -> {new} (neither present — skipping)")
    log()

    # ── Stage C: register new entries ─────────────────────────────────
    log(f"NEW entries registered:")
    n_new = 0
    for key, payload in NEW_ENTRIES.items():
        if key in reg:
            log(f"  - {key} (already present — leaving in place)")
            continue
        reg[key] = dict(payload)   # shallow copy so future edits don't bleed
        log(f"  - {key}  (video={payload['video_file']})")
        n_new += 1
    log()

    # ── Stage D: resolve config_description for every entry ──────────
    resolutions = {}
    skipped = []
    for key, entry in reg.items():
        cd = resolve_config_description(key, entry)
        if not cd:
            skipped.append(key)
            log(f"WARN: could not resolve config_description for '{key}' "
                f"(video_file={entry.get('video_file')!r}); skipping.")
            continue
        resolutions[key] = cd

    # ── Stage E: create folders ───────────────────────────────────────
    log()
    folders_created = 0
    for cd in sorted(set(resolutions.values())):
        path = os.path.join(MEAS_DIR, cd)
        existed = os.path.isdir(path)
        os.makedirs(path, exist_ok=True)
        if not existed:
            folders_created += 1
    log(f"FOLDERS created: {folders_created}  "
        f"(total now: {len(set(resolutions.values()))} under measurements/)")
    log()

    # ── Stage F: move files ──────────────────────────────────────────
    log("FILE MOVES:")
    n_ok = n_skip = n_done = n_err = 0

    for key in sorted(resolutions.keys()):
        entry = reg[key]
        cd    = resolutions[key]
        video = entry.get("video_file") or ""
        video_stem = os.path.splitext(os.path.basename(video))[0]

        # Try the registry key first (legacy DSC-style names match here)
        # then the video filename stem. plan_moves_for_entry dedupes and
        # picks the first candidate that exists for each destination.
        candidate_stems = [s for s in (key, video_stem) if s]
        if not candidate_stems:
            continue
        dest_dir = os.path.join(MEAS_DIR, cd)

        pairs = plan_moves_for_entry(candidate_stems, dest_dir)
        for src, dst in pairs:
            result = move_one(src, dst, log)
            if result is None:
                n_skip += 1
            elif result is True:
                # Distinguish [OK] from [DONE] by checking whether src
                # still exists (move removes it; "already exists" leaves
                # it). The log already differentiated visually; here we
                # just bucket them together as "successful".
                if os.path.exists(src):
                    n_done += 1
                else:
                    n_ok += 1
            else:
                n_err += 1

    log()

    # ── Stage G: rewrite registry fields ─────────────────────────────
    for key, cd in resolutions.items():
        entry = reg[key]
        entry["config_description"] = cd
        entry["measurements_dir"]   = f"measurements/{cd}"
        entry["csv_file"]           = "tracking.csv"

    log(f"experiments.json updated: {len(resolutions)} entries "
        f"(skipped {len(skipped)})")

    # Write registry back.
    with open(EXPERIMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2)

    # ── Summary ──────────────────────────────────────────────────────
    log()
    log("SUMMARY:")
    log(f"  {n_ok} files moved")
    log(f"  {n_done} destinations already existed (idempotent)")
    log(f"  {n_skip} sources not found (likely never produced)")
    log(f"  {n_err} errors")
    log()
    log(f"Log written to: {os.path.relpath(LOG_FILE, ROOT)}")

    log.flush()
    return 1 if n_err > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
