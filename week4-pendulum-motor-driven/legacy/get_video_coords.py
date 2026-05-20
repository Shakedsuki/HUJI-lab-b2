# -*- coding: utf-8 -*-
"""
Created on Wed May 20 15:03:57 2026

@author: cohen
"""

import cv2
import numpy as np
import pandas as pd
import time
from tqdm import tqdm
path=r"C:\Users\Nir\Documents\huji lab b2 chaos videos"+"\\"

# Open video
cap = cv2.VideoCapture(path+'4V_1.9Hz.mov')
data = []

# Define HSV color ranges for Green and Red
# Note: Red wraps around the hue channel (0-10 and 160-180)
green_lower, green_upper = np.array([0, 100, 0]), np.array([70, 255, 90])
red_lower1, red_upper1 = np.array([0, 0, 100]), np.array([45, 75, 255])
red_lower2, red_upper2 = np.array([0, 0, 110]), np.array([60, 80, 255])
red_lower3, red_upper3 = np.array([0, 0, 125]), np.array([75, 95, 255])
# red_lower2, red_upper2 = np.array([160, 100, 100]), np.array([180, 255, 255])

# skip_frames=1000

total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
pbar = tqdm(total=total_frames, desc="Processing Video")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret: 
        break
    # if skip_frames>0:
    #     skip_frames-=1
    #     continue
    
    pbar.update(1)

    time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
    # hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    frame=frame[:,350:950,:]
    # Create masks
    mask_g = cv2.inRange(frame, green_lower, green_upper)
    mask_r = cv2.inRange(frame, red_lower1, red_upper1)
    mask_r2 = cv2.inRange(frame, red_lower2, red_upper2)
    mask_r3 = cv2.inRange(frame, red_lower3, red_upper3)
    # mask_r = cv2.bitwise_or(cv2.inRange(hsv, red_lower1, red_upper1), 
                            # cv2.inRange(hsv, red_lower2, red_upper2))

    # Calculate centers using image moments
    M_g = cv2.moments(mask_g)
    M_r = cv2.moments(mask_r)
    M_r2 = cv2.moments(mask_r2)
    M_r3 = cv2.moments(mask_r3)

    # Avoid division by zero if the color is obscured/missing
    gx = int(M_g['m10']/M_g['m00']) if M_g['m00'] > 0 else None
    gy = int(M_g['m01']/M_g['m00']) if M_g['m00'] > 0 else None
    rx = int(M_r['m10']/M_r['m00']) if M_r['m00'] > 0 else None
    ry = int(M_r['m01']/M_r['m00']) if M_r['m00'] > 0 else None
    if rx is None or ry is None:
        rx = int(M_r2['m10']/M_r2['m00']) if M_r2['m00'] > 0 else None
        ry = int(M_r2['m01']/M_r2['m00']) if M_r2['m00'] > 0 else None
    if rx is None or ry is None:
        rx = int(M_r3['m10']/M_r3['m00']) if M_r3['m00'] > 0 else None
        ry = int(M_r3['m01']/M_r3['m00']) if M_r3['m00'] > 0 else None
        

    # # --- Draw the tracking circles on the frame ---
    # if gx is not None and gy is not None:
    #     cv2.circle(frame, (gx, gy), radius=8, color=(0, 255, 0), thickness=-1) # Solid Green
    # else:
    #     print("bad")
    #     break
    
    # if rx is not None and ry is not None:
    #     cv2.circle(frame, (rx, ry), radius=8, color=(0, 0, 255), thickness=-1) # Solid Red
    # else:
    #     print("bad")
    #     break

    # # Display the frame with the markers
    # cv2.imshow('Tracking Video - Press Q to Quit', frame)

    # # Wait 1ms between frames, break if 'q' is pressed
    # if cv2.waitKey(1) & 0xFF == ord('q'):
    #     break

    data.append([time_sec, gx, gy, rx, ry])
    
    # time.sleep(0.1)

# Clean up
cap.release()
cv2.destroyAllWindows()

# Save the results
# df = pd.DataFrame(data, columns=['Time (s)', 'Green X', 'Green Y', 'Red X', 'Red Y'])
# df.to_csv('pendulum_tracking.csv', index=False)

def find_circle_center(x, y):
    """
    Calculates the center and radius of a circle fitted to a set of 2D points.

    Parameters:
        x (array-like): x-coordinates of the points.
        y (array-like): y-coordinates of the points.

    Returns:
        tuple: (x_center, y_center, radius)
    """
    x = np.asarray(x)
    y = np.asarray(y)

    # 1. Set up the matrices for the least squares problem
    # M represents [x, y, 1]
    M = np.column_stack([x, y, np.ones(len(x))])

    # b represents -(x^2 + y^2)
    b = -(x**2 + y**2)

    # 2. Solve M * [A, B, C]^T = b
    # rcond=None suppresses a FutureWarning and uses machine precision
    coeff, _, _, _ = np.linalg.lstsq(M, b, rcond=None)

    A, B, C = coeff

    # 3. Convert back to center coordinates and radius
    x_c = -A / 2.0
    y_c = -B / 2.0
    radius = np.sqrt(x_c**2 + y_c**2 - C)

    return x_c, y_c, radius
    
# find_circle_center(x1,y1)
# plt.figure()
x0=312.78293187519023#312
y0=-331.7829060826372#-330

x1=np.array([i[1] for i in data])
y1=np.array([-i[2] for i in data])
x2=np.array([i[3] for i in data])
y2=np.array([-i[4] for i in data])


t1=np.arctan2(x1-x0,-(y1-y0))
t2=np.arctan2(x2-x1,-(y2-y1))