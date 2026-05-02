"""Canonical v2 runner: regenerates Fig 1, Fig 2, Fig 3 v2 PNGs + JSONs.

Run from C:\\dev\\chaos\\chaos\\part1\\:
    python run_fits_v2.py

Outputs:
    C:\\dev\\chaos-report\\figures\\v2\\graph1IV_v2.png + .fit.json
    C:\\dev\\chaos-report\\figures\\v2\\graph2IV_Triangle_v2.png + .fit.json
    C:\\dev\\chaos-report\\figures\\v2\\graph3C_V_v2.png + .fit.json
"""
from __future__ import annotations

import json
import os
import sys
import traceback

import IV_graph_v2 as fig1
import IV_from_triangle_v2 as fig2
import dischargetimes_v2 as fig3


def banner(s):
    print("=" * 72)
    print(s)
    print("=" * 72)


def run_safely(name, fn):
    banner(name)
    try:
        return fn()
    except Exception:
        print(f"[{name}] FAILED")
        traceback.print_exc()
        return None


def main():
    s1 = run_safely("Fig 1 v2 -- square IV with Lambert-W series-resistance", fig1.run)
    s2 = run_safely("Fig 2 v2 -- triangle IV with forward/reverse averaging", fig2.run)
    s3 = run_safely("Fig 3 v2 -- C(V) from direct exponential discharge fit", fig3.run)

    print()
    banner("LaTeX-ready summary  (v2)")

    if s1:
        a = s1["fit_a"]
        b = s1["fit_b"]
        print(f"Fig 1 (a) plain Shockley, Vpp <= 2 V: "
              f"n = {a['n']:.3f} +/- {a['n_sigma']:.3f}, "
              f"I_S = ({a['I_S']*1e9:.3f} +/- {a['I_S_sigma']*1e9:.3f}) e-9 A, "
              f"chi2/dof = {a['chi2_per_dof']:.2f}")
        print(f"Fig 1 (b) Shockley + lumped R_total, V_gen-axis: "
              f"n = {b['n']:.3f} +/- {b['n_sigma']:.3f}, "
              f"I_S = ({b['I_S']*1e9:.3f} +/- {b['I_S_sigma']*1e9:.3f}) e-9 A, "
              f"R_total = {b['R_total']:.1f} +/- {b['R_total_sigma']:.1f} Ohm "
              f"(R_lab=470, excess={b['R_total']-470:.0f} Ohm), "
              f"chi2/dof = {b['chi2_per_dof']:.2f}")

    if s2:
        e = s2["ensemble"]
        print(f"Fig 2 per-cycle ensemble (low-freq cycles only): "
              f"n = {e['n_mean']:.3f} +/- {e['n_std']:.3f}, "
              f"I_S = ({e['I_S_mean']*1e9:.3f} +/- {e['I_S_std']*1e9:.3f}) e-9 A")

    if s3:
        ph = s3["fit_phenom"]
        jc = s3["fit_junction"]
        print(f"Fig 3 phenom (a/sqrt|V| + c): "
              f"a = ({ph['a']*1e12:.2f} +/- {ph['a_sigma']*1e12:.2f}) pF V^1/2, "
              f"c = ({ph['c']*1e12:.2f} +/- {ph['c_sigma']*1e12:.2f}) pF, "
              f"chi2/dof = {ph['chi2_per_dof']:.2f}")
        print(f"Fig 3 junction (C0/sqrt(1+V/phi) + c): "
              f"C_0 = ({jc['C_0']*1e12:.2f} +/- {jc['C_0_sigma']*1e12:.2f}) pF, "
              f"phi_bi = ({jc['phi_bi']:.3f} +/- {jc['phi_bi_sigma']:.3f}) V, "
              f"c = ({jc['c_stray']*1e12:.2f} +/- {jc['c_stray_sigma']*1e12:.2f}) pF, "
              f"chi2/dof = {jc['chi2_per_dof']:.2f}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
