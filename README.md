# Chaos — Double-Pendulum Tracking Lab

Turn fixed-camera videos of a double pendulum into per-frame angles + angular velocities, with verdicts on tracking quality.

## Setup

```bash
git clone <this repo> && cd chaos
pip install -r requirements.txt
python scripts/utils/download_videos.py    # raw .mov files from Drive
```

Drive: [כאוס on Google Drive](https://drive.google.com/drive/folders/1nB9rrpZ1UTdLrKEJudptLbawavkvXWj-). Tested on Python 3.13 / Windows 11 (macOS + Linux work).

PowerShell needs `.\chaos <cmd>`; cmd / Bash use `chaos <cmd>` or `./chaos.sh <cmd>`. To drop the `.\` in PowerShell, add `function chaos { & "C:\dev\chaos\chaos.ps1" @args }` to your `$PROFILE`.

## Commands

```
PIPELINE
  chaos next                       drive the pending queue end-to-end
  chaos next --stem <stem>         single-clip walkthrough
  chaos bulk [--dry-run] [--redo]  unattended pass over plannable clips

PER-CLIP
  chaos tune <stem>                HSV calibration (interactive)
  chaos track <stem> [--debug]     track + verify + interpolate + verdict
  chaos verify <stem>              standalone QA on existing tracking.csv
  chaos fix <stem>                 manual seed picker + re-track
  chaos override <stem> --frame N  patch one row of tracking.csv
  chaos auto-seed <stem>           interpolate seeds from violation clusters
  chaos render <stem>              render combined.mp4 (video + overlay)

INSPECTION
  chaos status                     who's tracked / pending
  chaos roadmap                    per-clip status table (docs/tracking_roadmap.md)
  chaos report                     Excel summary (data/status_report.xlsx)
  chaos suspects <stem>            decompose suspect counts by check
  chaos triage [--auto] [--once]   walk non-PASS clips, dispatch right tool

REGISTRY
  chaos audit                      re-validate verified clips against current logic
  chaos audit --apply              downgrade clips that no longer pass
  chaos audit --upgrade --apply    also promote new PASSes to verified

ANALYSIS
  chaos friction-fit <stem>        fit decay model to mechanical energy

  chaos help                       full cheat sheet
  chaos <cmd> --help               flags for any subcommand
```

`<stem>` is the `config_description` (e.g. `th1_p047_th2_m002`) — the folder name under `measurements/`.

## Verdict bands

- **PASS** — auto-marks `tracking_quality=verified`; ready for downstream analysis
- **WARN** — tracking probably fine but a physics check fired; review or run `chaos triage`
- **FAIL** — broken; needs `chaos fix`, `chaos tune` + `chaos track`, or `chaos override`

## Outputs per clip

`measurements/<stem>/`:

| File | Source | What it is |
|---|---|---|
| `tracking.csv` | `chaos track` | per-frame angles + marker pixels |
| `verification.csv` | `chaos verify` | + ω, suspect flags from 7 physics checks |
| `verification.png` | `chaos verify` | θ / ω timelines, suspect dots |
| `verification_meta.json` | `chaos verify` | run-level (pivot drift, E_release) |
| `seeds.json` | `chaos fix` / `auto-seed` | manual + interpolated seed positions |
| `combined.mp4` | `chaos render` | source video + marker overlay + phase plots |
| `phase_panels.png`, `phase_3d_*` | analysis scripts | post-tracking physics figures |
| `friction_fit.png` | `chaos friction-fit` | E(t) + decay-model fit |
| `debug.mp4` | `chaos track --debug` | tracker-internal annotated video (large) |

Plus the cross-clip rollup at `data/status_report.xlsx` (`chaos report`) and `docs/tracking_roadmap.md` (`chaos roadmap`).

## More

- [`docs/PIPELINE.md`](docs/PIPELINE.md) — keystroke-level walkthrough, HSV/fix-up keyboard refs, geometry calibration, troubleshooting
- `chaos help` — same cheat sheet on stdout
- `chaos <cmd> --help` — flag list for any subcommand
