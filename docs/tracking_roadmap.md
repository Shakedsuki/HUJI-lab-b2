# Tracking Roadmap

_Generated 2026-05-22 22:01._ Re-run with `chaos roadmap`.

Lives at [`docs/tracking_roadmap.md`](tracking_roadmap.md). Every row reflects the current state of `data/experiments.json` plus the latest `data/bulk_tracking_log.json` and per-clip `measurements/<stem>/verification.csv`.

## Summary

| Status | Count | Meaning |
|---|---|---|
| **PASS** | 39 | passed verification, in registry as verified |
| **WARN** | 0 | tracking.csv exists, dropout/peak ω in WARN band |
| **FAIL** | 0 | tracking.csv exists but dropout > 10% or peak ω absurd |
| **PENDING** | 23 | registry entry exists but no track_one run on record |
| _total_ | 62 | every entry in `experiments.json` |

## Per-clip status

| Stem | Status | Drop% | Peak ω₂ | Susp | Trend (susp/win) | θ-resid | E-ceil/total | Pivot drift | Free | Last | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `2.45V_1Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `2.4V_1Hz_1` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `2.4V_1Hz_2` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `2.5V_1Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `2.6V_1Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.91Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.92Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.93Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.94Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.95Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.96Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.97Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.98Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.99Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_0.9Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under the new tracker (bbox/porthole crop, sub-pixe… |
| `3.2V_1.00Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.09Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.15Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.16Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.17Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.18Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.19Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.20Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.21Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.22Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.23Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.24Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.25Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.26Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.27Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `3.2V_1.28Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.29Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.30Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.31Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.32Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.33Hz_1` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.33Hz_2` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Perfect tracking. |
| `3.2V_1.34Hz` | ⚠ PASS _(pre-Brief-5)_ | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | Visually verified end-to-end under new tracker. Flawless. |
| `3.2V_1Hz` | PASS | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-22 | dropout 0.00% ≤ 5% |
| `2.8V_1Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3.4V_1Hz` | PENDING | 1.07% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3.6V_1Hz` | PENDING | 0.49% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_0.25Hz` | PENDING | 2.28% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_0.5Hz` | PENDING | 2.29% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_0.75Hz` | PENDING | 8.88% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_1.25Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_1.5Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `3V_1Hz` | PENDING | 0.29% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_0.6Hz` | PENDING | 1.85% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_0.7Hz` | PENDING | 3.29% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_0.8Hz` | PENDING | 2.84% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_0.9Hz` | PENDING | 8.60% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.1Hz` | PENDING | 2.50% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.2Hz` | PENDING | 0.81% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.3Hz` | PENDING | 0.14% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.4Hz` | PENDING | 0.20% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.5Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.6Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.8Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1.9Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_1Hz` | PENDING | 5.80% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |
| `4V_2Hz` | PENDING | 0.00% | — | — | 0/0 | 0 | 0/0 | — | — | 2026-05-21 | no record in bulk_tracking_log yet |

> **9 clip(s) marked ⚠** were verified before the Brief 5+6 physics checks landed (i.e. `verified_under_brief_version < 5`). Run `chaos audit --apply` or `chaos verify <stem>` to re-validate them against the current thresholds.

## What to do next

- **23 clips never tracked.** Run `chaos bulk` to attempt them all in one shot.
