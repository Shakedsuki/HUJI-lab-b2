# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 12:34:58 2026

@author: cohen
"""

import glob
import pandas as pd
import matplotlib.pyplot as plt
import os
import matplotlib.cm as cm
import numpy as np
import itertools
from tqdm import tqdm
from scipy.optimize import curve_fit
def inv_sqrt(x, a,c):
    return a / np.sqrt(x)+c
p=r"samples\square discharge"
file_list = glob.glob(p + '\\V_*_res_*.csv')
plt.figure(figsize=(10, 6))
plt.title("I for V")
C=[]
V=[]
for i, file_path in enumerate(tqdm(file_list)):

    if "noOff" in file_path:
        continue
    
    filename = os.path.basename(file_path)

    parts = filename.split('_')
    v_value = float(parts[1][:-1])
    res_value = parts[3].replace('.csv', '')
    window=100
    df = pd.read_csv(file_path,header=None, usecols=[3, 4, 9, 10])
    # samples_range=itertools.chain(range(100000,200000),range(380000,480000),range(660000,760000))
    diode_V=df[4][400000:600000]#[samples_range]
    # samples_range=itertools.chain(range(100000,200000),range(380000,480000),range(660000,760000))
    # resistor_V=diode_V-df[10]#.rolling(window=window).mean()#[samples_range]
    # resistor_I=resistor_V/470.0
    circuit_V=df[10][400000:600000]
    base=np.average(diode_V[:50000])
    top=np.average(diode_V[-50000:])
    v=np.average(circuit_V[-50000:])
    
    diode_V=np.array(diode_V.rolling(window=window).mean())
    startperc=0.03 if "noOff" in file_path else 0.001
    if "1.6" in file_path:
        startperc=0.0045
    
    amp=top-base
    riseind=np.where(diode_V<=base+amp*startperc)[-1][-1]
    tauind=np.where(diode_V<=base+amp*(1-np.exp(-1)))[-1][-1]
    

    
    # color = cm.turbo(i / max(1, len(file_list) - 1))
    # plt.plot(diode_V, label=f'V: {v_value} | Res: {res_value}',color=color)
    # plt.plot([0,len(diode_V)],[base,base])
    # plt.plot([0,len(diode_V)],[top,top])
    # plt.plot([riseind,riseind],[base,top])
    # plt.plot(tauind, diode_V[tauind], 'X', color=color, markersize=10, markeredgecolor='black')
    
    tau=(tauind-riseind)*4e-10
    capacitence=tau/470.0
    plt.plot(v, capacitence, 'o', color="red", markersize=10, markeredgecolor='black')
    # plt.text(v, capacitence, filename, color="red", fontsize=10, verticalalignment='center')
    C.append(capacitence)
    V.append(v)
    # plt.plot(diode_V, label=f'V: {v_value/1000} | Res: {res_value}')
    # label_text = f'   V: {v_value/1000} | Res: {res_value}'
    # plt.text(V[-1], I[-1], label_text, color=color, fontsize=10, verticalalignment='center')
#
# plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=12)
# plt.tight_layout()
plt.legend(fontsize=12)
plt.show()
x=np.linspace(min(V),max(V))
popt, pcov = curve_fit(inv_sqrt,V,C,p0=[5e-10,5e-10])
plt.plot(x, inv_sqrt(x, *popt))