# Tracking Roadmap

_Generated 2026-05-02 04:17._ Re-run with `chaos roadmap`.

Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). Every row reflects the current state of `data/experiments.json` plus the latest `data/bulk_tracking_log.json` and per-clip `measurements/<stem>/verification.csv`.

## Summary

| Status | Count | Meaning |
|---|---|---|
| **PASS** | 2 | passed verification, in registry as verified |
| **WARN** | 25 | tracking.csv exists, dropout/peak ω in WARN band |
| **FAIL** | 1 | tracking.csv exists but dropout > 10% or peak ω absurd |
| **HSV-ABORT** | 0 | ring_tracker bailed on the HSV adequacy probe — needs `chaos tune` |
| **NEEDS-PICKER** | 0 | no init/release/tag_frame in registry — needs interactive picker |
| **PENDING** | 0 | registry entry exists but no track_one run on record |
| _total_ | 28 | every entry in `experiments.json` |

## Per-clip status

| Stem | Status | Drop% (free) | Peak ω₂ (°/s) | Suspects | Free frames | Last touched | Notes |
|---|---|---|---|---|---|---|---|
| `th1_p044_th2_m001` | PASS | 0.00% | 603 | 0 | 1075 | 2026-05-01 | verify_tracking.py @ 2500 deg/s cap: 0 dropouts, 0 suspects across 1239 frames (… |
| `th1_p047_th2_m002` | PASS | 0.53% | 653 | 3 | 2652 | 2026-05-01 | PASS via manual_correction strict-physics flow. |
| `th1_m179_th2_p089` | WARN | 0.64% | 8051 | 2617 | 2647 | 2026-05-01 | interp 366 |
| `th1_p001_th2_p093` | WARN | 7.12% | 2015 | 17 | 983 | 2026-05-01 | dropout 7.1%; interp 1 |
| `th1_p037_th2_p094` | WARN | 1.23% | 757 | 3 | 1059 | 2026-05-01 | interp 8 |
| `th1_p056_th2_m001` | WARN | 0.00% | 777 | 0 | 1512 | 2026-05-01 | review verification.png |
| `th1_p067_th2_p096` | WARN | 0.00% | 844 | 3 | 1438 | 2026-05-01 | interp 11 |
| `th1_p079_th2_p000` | WARN | 5.62% | 1513 | 120 | 178 | 2026-05-01 | dropout 5.6%; interp 6 |
| `th1_p082_th2_p001` | WARN | 0.00% | 1048 | 0 | 1573 | 2026-05-01 | review verification.png |
| `th1_p090_th2_p000` | WARN | 0.00% | 165 | 0 | 88 | 2026-05-02 | interp 7 |
| `th1_p090_th2_p000_r2` | WARN | 1.45% | 1857 | 22 | 2681 | 2026-05-01 | interp 35 |
| `th1_p091_th2_m001` | WARN | 5.77% | 1090 | 1796 | 1958 | 2026-05-01 | dropout 5.8% |
| `th1_p092_th2_m002` | WARN | 0.00% | 1106 | 26 | 2453 | 2026-05-02 | interp 32 |
| `th1_p092_th2_p000` | WARN | 0.20% | 1208 | 37 | 2496 | 2026-05-02 | interp 51 |
| `th1_p093_th2_m000` | WARN | 0.15% | 1112 | 46 | 2037 | 2026-05-02 | interp 82 |
| `th1_p093_th2_m002` | WARN | 0.04% | 1237 | 78 | 2599 | 2026-05-02 | interp 141 |
| `th1_p094_th2_p000` | WARN | 0.00% | 1072 | 45 | 2351 | 2026-05-02 | interp 73 |
| `th1_p094_th2_p000_r2` | WARN | 0.00% | 3523 | 11 | 1353 | 2026-05-02 | interp 16 |
| `th1_p116_th2_m001` | WARN | 0.00% | 1413 | 60 | 1966 | 2026-05-02 | interp 95 |
| `th1_p138_th2_m002` | WARN | 0.00% | 1371 | 111 | 2587 | 2026-05-02 | interp 186 |
| `th1_p140_th2_p089` | WARN | 1.65% | 1452 | 1026 | 1094 | 2026-05-02 | interp 123 |
| `th1_p153_th2_p090` | WARN | 0.67% | 5281 | 1848 | 2685 | 2026-05-02 | interp 317 |
| `th1_p160_th2_m001` | WARN | 1.80% | 7403 | 1330 | 1888 | 2026-05-02 | interp 250 |
| `th1_p176_th2_p180` | WARN | 0.85% | 6448 | 1959 | 2112 | 2026-05-02 | interp 317 |
| `th1_p180_th2_m179` | WARN | 0.00% | 2710 | 221 | 30897 | 2026-05-01 | interp 20 |
| `th1_p180_th2_p090` | WARN | 1.15% | 7004 | 1148 | 1652 | 2026-05-02 | interp 264 |
| `th1_p180_th2_p180` | WARN | 5.04% | 1769 | 54 | 1390 | 2026-05-01 | dropout 5.0%; interp 2 |
| `th1_m001_th2_p001` | FAIL | 22.18% | 81 | 19 | 983 | — | dropout 22.18% — re-track or HSV tune |

## What to do next

- **25 clips landed in WARN.** Inspect `measurements/<stem>/verification.png`; if acceptable, mark verified; otherwise `chaos fix <stem>`.
- **1 clips landed in FAIL.** Re-tune HSV or run `chaos fix <stem>` with seeds.
