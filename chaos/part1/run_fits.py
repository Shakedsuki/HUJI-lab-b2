"""Run the three fitting scripts non-interactively and print fit parameters.

Each script is sourced inline (with plt.show patched out) to keep the original
fit logic intact. Fit values are printed in the LaTeX-ready format requested.
"""
import os
import sys
import matplotlib
matplotlib.use("Agg")  # no display, no blocking
import matplotlib.pyplot as _plt
_plt.show = lambda *a, **k: None  # neutralize show() so scripts return cleanly

import glob
import itertools
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from tqdm import tqdm

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(THIS_DIR)


# ---------------- Script A: IV graph_AI.py ----------------
def shockley_equation(V_D, I_S, n):
    V_T = 0.02585
    return I_S * (np.exp(V_D / (n * V_T)) - 1)


def run_script_a():
    p = r"samples\square"
    file_list = glob.glob(os.path.join(p, "V_*_res_*.csv"))

    def extract_v_value(file_path):
        filename = os.path.basename(file_path)
        parts = filename.split("_")
        try:
            return int(parts[1][:-2]) / 1000
        except Exception:
            return float("inf")

    file_list = sorted(file_list, key=extract_v_value)

    V_means, I_means, Source_Vs = [], [], []
    for file_path in file_list:
        filename = os.path.basename(file_path)
        parts = filename.split("_")
        try:
            v_value = int(parts[1][:-2]) / 1000
        except Exception:
            continue
        df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
        samples_range_list = list(itertools.chain(range(100000, 200000)))
        mask = df.index.isin(samples_range_list)
        diode_V = df.loc[mask, 4]
        circuit_V = df.loc[mask, 10]
        resistor_V = diode_V - circuit_V
        resistor_I = resistor_V / 470.0
        V_means.append(-np.average(diode_V))
        I_means.append(np.average(resistor_I))
        Source_Vs.append(v_value)

    valid_V_D = [v for idx, v in enumerate(V_means) if Source_Vs[idx] <= 2.0]
    valid_I_D = [i for idx, i in enumerate(I_means) if Source_Vs[idx] <= 2.0]

    excluded = sorted({Source_Vs[idx] for idx, _ in enumerate(V_means) if Source_Vs[idx] > 2.0})

    popt, pcov = curve_fit(
        shockley_equation, valid_V_D, valid_I_D,
        p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0])
    )
    perr = np.sqrt(np.diag(pcov))
    I_S_opt, n_opt = popt
    I_S_err, n_err = perr
    print(f"[Script A] points used: {len(valid_V_D)}, excluded source Vpp > 2.0V: {excluded}")
    print(f"[Script A] n   = {n_opt:.4f} +/- {n_err:.4f}")
    print(f"[Script A] I_S = {I_S_opt:.4e} +/- {I_S_err:.2e} A")
    return n_opt, I_S_opt


# ---------------- Script B: IV from triangle.py ----------------
def shockley(V_D, I_S, n):
    V_T = 0.02585
    return I_S * (np.exp(V_D / (n * V_T)) - 1)


def run_script_b():
    p = r"samples\triangle"
    file_list = glob.glob(p + "\\f_*_V_*_res_*.csv")
    if not file_list:
        print("[Script B] no triangle CSVs found")
        return None, None

    file_path = file_list[0]
    print(f"[Script B] using file (matches script's [:1] slice): {os.path.basename(file_path)}")

    df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
    window = 3000
    diode_V = df[4].rolling(window=window).mean()
    resistor_V = diode_V - df[10].rolling(window=window).mean()
    resistor_I = resistor_V / 470.0

    valid_mask = ~diode_V.isna() & ~resistor_I.isna()
    v_valid = -diode_V[valid_mask]
    i_valid = resistor_I[valid_mask]

    popt, pcov = curve_fit(
        shockley, v_valid, i_valid,
        p0=[1e-9, 1.5], bounds=([1e-15, 0.5], [1e-3, 5.0])
    )
    perr = np.sqrt(np.diag(pcov))
    I_S_opt, n_opt = popt
    I_S_err, n_err = perr
    print(f"[Script B] n   = {n_opt:.4f} +/- {n_err:.4f}")
    print(f"[Script B] I_S = {I_S_opt:.4e} +/- {I_S_err:.2e} A")
    return n_opt, I_S_opt


# ---------------- Script C: dischargetimes.py ----------------
def inv_sqrt(x, a, c):
    return a / np.sqrt(x) + c


def run_script_c():
    p = r"samples\square discharge"
    file_list = glob.glob(p + "\\V_*_res_*.csv") + glob.glob(p + "\\v_*_res_*.csv")
    file_list = sorted(set(file_list))

    C, V = [], []
    for file_path in file_list:
        if "noOff" in file_path:
            continue
        window = 100
        df = pd.read_csv(file_path, header=None, usecols=[3, 4, 9, 10])
        diode_V = df[4][400000:600000]
        circuit_V = df[10][400000:600000]
        base = np.average(diode_V[:50000])
        top = np.average(diode_V[-50000:])
        v = np.average(circuit_V[-50000:])

        diode_V = np.array(diode_V.rolling(window=window).mean())
        startperc = 0.03 if "noOff" in file_path else 0.001
        if "1.6" in file_path:
            startperc = 0.0045

        amp = top - base
        try:
            riseind = np.where(diode_V <= base + amp * startperc)[-1][-1]
            tauind = np.where(diode_V <= base + amp * (1 - np.exp(-1)))[-1][-1]
        except IndexError:
            continue

        tau = (tauind - riseind) * 4e-10
        capacitance = tau / 470.0
        C.append(capacitance)
        V.append(v)

    if len(V) < 2:
        print(f"[Script C] only {len(V)} points — cannot fit")
        return None, None

    popt, pcov = curve_fit(inv_sqrt, V, C, p0=[5e-10, 5e-10])
    perr = np.sqrt(np.diag(pcov))
    a_opt, c_opt = popt
    a_err, c_err = perr
    print(f"[Script C] points: {len(V)}")
    print(f"[Script C] a = {a_opt:.4e} +/- {a_err:.2e}  F*sqrt(V)")
    print(f"[Script C] c = {c_opt:.4e} +/- {c_err:.2e}  F")
    return a_opt, c_opt


if __name__ == "__main__":
    print("=" * 60)
    n_a, IS_a = run_script_a()
    print("=" * 60)
    n_b, IS_b = run_script_b()
    print("=" * 60)
    a_c, c_c = run_script_c()
    print("=" * 60)
    print()
    print("=== LaTeX-ready summary ===")
    print(f"Fig 1: n = {n_a:.3f}, I_S = {IS_a:.3e} A")
    print(f"Fig 2: n = {n_b:.3f}, I_S = {IS_b:.3e} A")
    print(f"Fig 3: a = {a_c:.3e} F*V^(1/2), c = {c_c:.3e} F")
