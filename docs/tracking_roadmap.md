# Tracking Roadmap

_Generated 2026-05-02 01:45._ Re-run with `chaos roadmap`.

Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). Every row reflects the current state of `data/experiments.json` plus the latest `data/bulk_tracking_log.json` and per-clip `measurements/<stem>/verification.csv`.

## Summary

| Status | Count | Meaning |
|---|---|---|
| **PASS** | 2 | passed verification, in registry as verified |
| **WARN** | 24 | tracking.csv exists, dropout/peak ω in WARN band |
| **FAIL** | 1 | tracking.csv exists but dropout > 10% or peak ω absurd |
| **HSV-ABORT** | 0 | ring_tracker bailed on the HSV adequacy probe — needs `chaos tune` |
| **NEEDS-PICKER** | 1 | no init/release/tag_frame in registry — needs interactive picker |
| **PENDING** | 0 | registry entry exists but no track_one run on record |
| _total_ | 28 | every entry in `experiments.json` |

## Per-clip status

| Stem | Status | Drop% (free) | Peak ω₂ (°/s) | Suspects | Free frames | Last touched | Notes |
|---|---|---|---|---|---|---|---|
| `th1_p044_th2_m001` | PASS | 0.00% | 626 | 0 | 1075 | 2026-05-01 | verify_tracking.py @ 2500 deg/s cap: 0 dropouts, 0 suspects across 1239 frames (… |
| `th1_p047_th2_m002` | PASS | 0.53% | 673 | 0 | 2652 | 2026-05-01 | PASS via manual_correction strict-physics flow. |
| `th1_m179_th2_p089` | WARN | 0.64% | 5387 | 1223 | 2647 | 2026-05-01 | interp 366 |
| `th1_p001_th2_p093` | WARN | 7.12% | 2426 | 16 | 983 | 2026-05-01 | dropout 7.1%; interp 1 |
| `th1_p037_th2_p094` | WARN | 1.51% | 705 | 12 | 1059 | 2026-05-01 | review verification.png |
| `th1_p056_th2_m001` | WARN | 0.00% | 825 | 1 | 1512 | 2026-05-01 | review verification.png |
| `th1_p067_th2_p096` | WARN | 0.00% | 2402 | 13 | 1438 | 2026-05-01 | review verification.png |
| `th1_p079_th2_p000` | WARN | 5.62% | 2113 | 18 | 178 | 2026-05-01 | dropout 5.6%; interp 6 |
| `th1_p082_th2_p001` | WARN | 0.00% | 1163 | 7 | 1573 | 2026-05-01 | review verification.png |
| `th1_p090_th2_p000` | WARN | 0.00% | 1635 | 22 | 88 | 2026-05-01 | interp 7 |
| `th1_p090_th2_p000_r2` | WARN | 1.49% | 2092 | 71 | 2681 | 2026-05-01 | interp 2 |
| `th1_p091_th2_m001` | WARN | 5.77% | 1205 | 62 | 1958 | 2026-05-01 | dropout 5.8% |
| `th1_p092_th2_m002` | WARN | 0.00% | 1106 | 26 | 2453 | 2026-05-02 | interp 32 |
| `th1_p092_th2_p000` | WARN | 0.20% | 1208 | 37 | 2496 | 2026-05-02 | interp 52 |
| `th1_p093_th2_m000` | WARN | 0.15% | 1112 | 46 | 2037 | 2026-05-02 | interp 82 |
| `th1_p093_th2_m002` | WARN | 0.38% | 1237 | 77 | 2599 | 2026-05-02 | interp 144 |
| `th1_p094_th2_p000` | WARN | 0.00% | 1072 | 45 | 2351 | 2026-05-02 | interp 73 |
| `th1_p116_th2_m001` | WARN | 0.00% | 1413 | 60 | 1966 | 2026-05-02 | interp 96 |
| `th1_p138_th2_m002` | WARN | 0.00% | 1371 | 110 | 2587 | 2026-05-02 | interp 187 |
| `th1_p140_th2_p089` | WARN | 1.65% | 1593 | 62 | 1094 | 2026-05-02 | interp 123 |
| `th1_p153_th2_p090` | WARN | 0.67% | 5376 | 1202 | 2685 | 2026-05-02 | interp 317 |
| `th1_p160_th2_m001` | WARN | 1.80% | 5320 | 863 | 1888 | 2026-05-02 | interp 250 |
| `th1_p176_th2_p180` | WARN | 0.85% | 5389 | 975 | 2112 | 2026-05-02 | interp 317 |
| `th1_p180_th2_m179` | WARN | 0.00% | 3466 | 251 | 30897 | 2026-05-01 | interp 20 |
| `th1_p180_th2_p090` | WARN | 1.15% | 5395 | 752 | 1652 | 2026-05-02 | interp 264 |
| `th1_p180_th2_p180` | WARN | 5.04% | 1824 | 116 | 1390 | 2026-05-01 | dropout 5.0%; interp 2 |
| `th1_m001_th2_p001` | FAIL | 22.18% | 127 | 5 | 983 | — | dropout 22.18% — re-track or HSV tune |
| `th1_p094_th2_p000_r2` | NEEDS-PICKER | — | — | — | — | — | no tag_frame/init_frame; run `chaos next` to pick init/release |

## What to do next

- **1 clips need a manual init/release pick.** Run `chaos next --stem <stem>` to drop into the picker.
- **24 clips landed in WARN.** Inspect `measurements/<stem>/verification.png`; if acceptable, mark verified; otherwise `chaos fix <stem>`.
- **1 clips landed in FAIL.** Re-tune HSV or run `chaos fix <stem>` with seeds.
