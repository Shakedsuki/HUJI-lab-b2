# Tracking Roadmap

_Generated 2026-05-02 05:00._ Re-run with `chaos roadmap`.

Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). Every row reflects the current state of `data/experiments.json` plus the latest `data/bulk_tracking_log.json` and per-clip `measurements/<stem>/verification.csv`.

## Summary

| Status | Count | Meaning |
|---|---|---|
| **PASS** | 3 | passed verification, in registry as verified |
| **WARN** | 16 | tracking.csv exists, dropout/peak ω in WARN band |
| **FAIL** | 9 | tracking.csv exists but dropout > 10% or peak ω absurd |
| **HSV-ABORT** | 0 | ring_tracker bailed on the HSV adequacy probe — needs `chaos tune` |
| **NEEDS-PICKER** | 0 | no init/release/tag_frame in registry — needs interactive picker |
| **PENDING** | 0 | registry entry exists but no track_one run on record |
| _total_ | 28 | every entry in `experiments.json` |

## Per-clip status

| Stem | Status | Drop% | Peak ω₂ | Susp | Trend (susp/win) | θ-resid | E-ceil/total | Pivot drift | Free | Last | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `th1_p044_th2_m001` | PASS | 0.00% | 619 | 0 | 0/0 | 0 | 0/0 | 2.8px | 1075 | 2026-05-02 | dropout, suspects, and ω all within thresholds |
| `th1_p056_th2_m001` | PASS | 0.00% | 773 | 0 | 0/0 | 0 | 0/0 | 2.8px | 1512 | 2026-05-02 | dropout, suspects, and ω all within thresholds |
| `th1_p082_th2_p001` | PASS | 0.00% | 1042 | 0 | 0/0 | 0 | 0/0 | 3.1px | 1573 | 2026-05-02 | dropout, suspects, and ω all within thresholds |
| `th1_p001_th2_p093` | WARN | 7.12% | 2015 | 17 | 0/0 | 11 | 10/13 | 0.7px | 983 | 2026-05-01 | dropout 7.1%; interp 1 |
| `th1_p037_th2_p094` | WARN | 0.38% | 727 | 4 | 0/0 | 2 | 4/4 | 4.0px | 1059 | 2026-05-01 | interp 8 |
| `th1_p047_th2_m002` | WARN | 0.53% | 653 | 3 | 0/0 | 0 | 0/3 | 0.9px | 2652 | 2026-05-01 | review verification.png |
| `th1_p067_th2_p096` | WARN | 0.00% | 816 | 1 | 0/0 | 1 | 0/0 | 5.5px | 1438 | 2026-05-01 | interp 3 |
| `th1_p090_th2_p000` | WARN | 0.00% | 165 | 0 | 0/0 | 0 | 0/0 | 35.7px | 88 | 2026-05-02 | interp 7 |
| `th1_p090_th2_p000_r2` | WARN | 1.45% | 1249 | 5 | 0/0 | 1 | 0/2 | 3.0px | 2681 | 2026-05-01 | interp 35 |
| `th1_p092_th2_m002` | WARN | 0.00% | 1015 | 0 | 0/0 | 0 | 0/0 | 5.0px | 2453 | 2026-05-02 | interp 32 |
| `th1_p092_th2_p000` | WARN | 0.20% | 1114 | 1 | 0/0 | 0 | 0/1 | 1.2px | 2496 | 2026-05-02 | interp 51 |
| `th1_p093_th2_m000` | WARN | 0.15% | 1022 | 0 | 0/0 | 0 | 0/0 | 2.2px | 2037 | 2026-05-02 | interp 82 |
| `th1_p093_th2_m002` | WARN | 0.04% | 1137 | 15 | 0/0 | 9 | 0/3 | 1.7px | 2599 | 2026-05-02 | interp 141 |
| `th1_p094_th2_p000` | WARN | 0.00% | 1022 | 0 | 0/0 | 0 | 0/0 | 2.4px | 2351 | 2026-05-02 | interp 73 |
| `th1_p094_th2_p000_r2` | WARN | 0.00% | 1286 | 15 | 0/0 | 3 | 0/0 | 4.8px | 1353 | 2026-05-02 | interp 11 |
| `th1_p116_th2_m001` | WARN | 0.00% | 1274 | 3 | 0/0 | 0 | 0/3 | 4.7px | 1966 | 2026-05-02 | interp 95 |
| `th1_p138_th2_m002` | WARN | 0.00% | 1370 | 4 | 0/0 | 0 | 0/3 | 6.0px | 2587 | 2026-05-02 | interp 186 |
| `th1_p180_th2_m179` | WARN | 0.00% | 2710 | 221 | 0/0 | 128 | 0/28 | 1.2px | 30897 | 2026-05-01 | interp 20 |
| `th1_p180_th2_p180` | WARN | 5.04% | 1769 | 54 | 0/0 | 15 | 0/9 | 19.8px | 1390 | 2026-05-01 | dropout 5.0%; interp 2 |
| `th1_m001_th2_p001` | FAIL | 22.18% | 81 | 19 | 0/0 | 0 | 0/19 | 1.4px | 983 | — | dropout 22.18% — re-track or HSV tune |
| `th1_m179_th2_p089` | FAIL | 0.64% | 10221 | 2617 | 2450/47 | 1567 | 253/590 | 20.5px | 2647 | 2026-05-01 | dropout 0.64% — re-track or HSV tune |
| `th1_p079_th2_p000` | FAIL | 5.62% | 1513 | 120 | 118/2 | 12 | 0/2 | 31.4px | 178 | 2026-05-01 | dropout 5.62% — re-track or HSV tune |
| `th1_p091_th2_m001` | FAIL | 5.77% | 1090 | 1796 | 1795/35 | 8 | 0/7 | 3.5px | 1958 | 2026-05-01 | dropout 5.77% — re-track or HSV tune |
| `th1_p140_th2_p089` | FAIL | 1.65% | 1452 | 1026 | 1026/20 | 2 | 2/13 | 7.9px | 1094 | 2026-05-02 | dropout 1.65% — re-track or HSV tune |
| `th1_p153_th2_p090` | FAIL | 0.67% | 5192 | 1848 | 367/5 | 1504 | 278/615 | 23.8px | 2685 | 2026-05-02 | dropout 0.67% — re-track or HSV tune |
| `th1_p160_th2_m001` | FAIL | 1.80% | 8715 | 1330 | 404/6 | 1072 | 11/365 | 17.7px | 1888 | 2026-05-02 | dropout 1.8% — re-track or HSV tune |
| `th1_p176_th2_p180` | FAIL | 0.85% | 5010 | 1959 | 1550/24 | 1263 | 15/402 | 21.6px | 2112 | 2026-05-02 | dropout 0.85% — re-track or HSV tune |
| `th1_p180_th2_p090` | FAIL | 1.15% | 5610 | 1148 | 0/0 | 987 | 14/347 | 15.5px | 1652 | 2026-05-02 | dropout 1.15% — re-track or HSV tune |

## What to do next

- **16 clips landed in WARN.** Inspect `measurements/<stem>/verification.png`; if acceptable, mark verified; otherwise `chaos fix <stem>`.
- **9 clips landed in FAIL.** Re-tune HSV or run `chaos fix <stem>` with seeds.
