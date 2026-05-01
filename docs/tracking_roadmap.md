# Tracking Roadmap

_Generated 2026-05-01 22:47._ Re-run with `chaos roadmap`.

Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). Every row reflects the current state of `data/experiments.json` plus the latest `data/bulk_tracking_log.json` and per-clip `measurements/<stem>/verification.csv`.

## Summary

| Status | Count | Meaning |
|---|---|---|
| **PASS** | 5 | passed verification, in registry as verified |
| **WARN** | 3 | tracking.csv exists, dropout/peak ω in WARN band |
| **FAIL** | 1 | tracking.csv exists but dropout > 10% or peak ω absurd |
| **HSV-ABORT** | 17 | ring_tracker bailed on the HSV adequacy probe — needs `chaos tune` |
| **NEEDS-PICKER** | 2 | no init/release/tag_frame in registry — needs interactive picker |
| **PENDING** | 0 | registry entry exists but no track_one run on record |
| _total_ | 28 | every entry in `experiments.json` |

## Per-clip status

| Stem | Status | Drop% (free) | Peak ω₂ (°/s) | Suspects | Free frames | Last touched | Notes |
|---|---|---|---|---|---|---|---|
| `th1_p037_th2_p094` | PASS | 1.51% | 705 | 0 | 1059 | 2026-05-01 | dropout, suspects, and ω all within thresholds |
| `th1_p044_th2_m001` | PASS | 0.00% | 626 | 0 | 1075 | 2026-05-01 | verify_tracking.py @ 2500 deg/s cap: 0 dropouts, 0 suspects across 1239 frames (… |
| `th1_p047_th2_m002` | PASS | 0.53% | 673 | 0 | 2652 | 2026-05-01 | PASS via manual_correction strict-physics flow. |
| `th1_p180_th2_m179` | PASS | 0.00% | 3466 | 12 | 30897 | 2026-05-01 | PASS via WARN-band manual triage 2026-05-01. 12 residual suspects post-interpola… |
| `th1_p180_th2_p180` | PASS | 5.04% | 1824 | 0 | 1390 | 2026-05-01 | verify_tracking.py @ 2500 deg/s cap: 70 dropouts (4.98%, mostly early high-energ… |
| `th1_p001_th2_p093` | WARN | 2.14% | 2426 | 1 | 983 | 2026-05-01 | interp 1 |
| `th1_p079_th2_p000` | WARN | 0.00% | 2660 | 2 | 178 | 2026-05-01 | interp 6 |
| `th1_p090_th2_p000` | WARN | 0.00% | 1635 | 0 | 88 | 2026-05-01 | interp 7 |
| `th1_m001_th2_p001` | FAIL | 22.18% | — | — | 983 | — | dropout 22.18% — re-track or HSV tune |
| `th1_m179_th2_p089` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p056_th2_m001` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p067_th2_p096` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p082_th2_p001` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p091_th2_m001` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p092_th2_m002` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p092_th2_p000` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p093_th2_m000` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p093_th2_m002` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p094_th2_p000` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p116_th2_m001` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p138_th2_m002` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p140_th2_p089` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p153_th2_p090` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p160_th2_m001` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p176_th2_p180` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p180_th2_p090` | HSV-ABORT | — | — | — | — | 2026-05-01 | global HSV doesn't fit; run `chaos tune <stem>` |
| `th1_p090_th2_p000_r2` | NEEDS-PICKER | — | — | — | — | — | no tag_frame/init_frame; run `chaos next` to pick init/release |
| `th1_p094_th2_p000_r2` | NEEDS-PICKER | — | — | — | — | — | no tag_frame/init_frame; run `chaos next` to pick init/release |

## What to do next

- **17 clips need per-clip HSV tuning.** Run `chaos tune <stem>` then `chaos track <stem>` on each HSV-ABORT row above.
- **2 clips need a manual init/release pick.** Run `chaos next --stem <stem>` to drop into the picker.
- **3 clips landed in WARN.** Inspect `measurements/<stem>/verification.png`; if acceptable, mark verified; otherwise `chaos fix <stem>`.
- **1 clips landed in FAIL.** Re-tune HSV or run `chaos fix <stem>` with seeds.
