# -*- coding: utf-8 -*-
"""
Created on Thu Apr 23 01:26:48 2026

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

p=r"samples\square"
file_list = glob.glob(p + '\\V_*_res_*.csv')
plt.figure(figsize=(10, 6))
plt.title("I for V")
I=[]
V=[]
for i, file_path in tqdm(enumerate(file_list)):
    filename = os.path.basename(file_path)

    parts = filename.split('_')
    v_value = int(parts[1][:-2])
    res_value = parts[3].replace('.csv', '')

    df = pd.read_csv(file_path,header=None, usecols=[3, 4, 9, 10])
    samples_range=itertools.chain(range(100000,200000),range(380000,480000),range(660000,760000))
    diode_V=df[4][samples_range]
    samples_range=itertools.chain(range(100000,200000),range(380000,480000),range(660000,760000))
    resistor_V=diode_V-df[10][samples_range]
    resistor_I=resistor_V/470.0
    
    I.append(np.average(resistor_I))
    V.append(-np.average(diode_V))
    
    color = cm.turbo(i / max(1, len(file_list) - 1))
    plt.plot([V[-1]],[I[-1]],'.', label=f'V: {v_value/1000} | Res: {res_value}',color=color,markersize=15)
    # plt.plot(resistor_I, label=f'V: {v_value/1000} | Res: {res_value}',color=color)
    # plt.plot(diode_V, label=f'V: {v_value/1000} | Res: {res_value}')
    label_text = f'   V: {v_value/1000} | Res: {res_value}'
    plt.text(V[-1], I[-1], label_text, color=color, fontsize=10, verticalalignment='center')
#
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=12)
# plt.tight_layout()
# plt.legend()
plt.show()