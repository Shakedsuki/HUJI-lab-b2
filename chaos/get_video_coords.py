# -*- coding: utf-8 -*-
"""
Created on Wed May 20 15:03:57 2026

@author: cohen
"""
from glob import glob
import cv2
import numpy as np
import pandas as pd
import time
from tqdm import tqdm
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
path=r"C:\Users\Nir\Documents\huji lab b2 chaos videos"+"\\"

# Open video


# Define HSV color ranges for Green and Red
# Note: Red wraps around the hue channel (0-10 and 160-180)
green_lower, green_upper = np.array([0, 87, 0]), np.array([40, 255, 80])
green_lower2, green_upper2 = np.array([0, 102, 0]), np.array([60, 255, 102])
red_lower1, red_upper1 = np.array([0, 0, 100]), np.array([45, 75, 255])
red_lower2, red_upper2 = np.array([0, 0, 110]), np.array([60, 80, 255])
red_lower3, red_upper3 = np.array([0, 0, 125]), np.array([75, 95, 255])
# red_lower2, red_upper2 = np.array([160, 100, 100]), np.array([180, 255, 255])

# skip_frames=1000
for file in tqdm(glob(path+'*.mov')[28:], desc="Overall Progress"):
    base_name=file.split('\\')[-1][:-4]
    cap = cv2.VideoCapture(file)
    data = []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    # pbar = tqdm(total=total_frames,desc=f"Processing {base_name}", leave=False)
    
    while cap.isOpened():
        ret, full_frame = cap.read()
        if not ret: 
            break
        # if skip_frames>0:
        #     skip_frames-=1
        #     continue
        
        # pbar.update(1)
    
        time_sec = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        # hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        frame=full_frame[20:650,350:980,:]
        # Create masks
        mask_g = cv2.inRange(frame, green_lower, green_upper)
        mask_g2 = cv2.inRange(frame, green_lower2, green_upper2)
        mask_r = cv2.inRange(frame, red_lower1, red_upper1)
        mask_r2 = cv2.inRange(frame, red_lower2, red_upper2)
        mask_r3 = cv2.inRange(frame, red_lower3, red_upper3)
        # mask_r = cv2.bitwise_or(cv2.inRange(hsv, red_lower1, red_upper1), 
                                # cv2.inRange(hsv, red_lower2, red_upper2))
    
        # Calculate centers using image moments
        M_g = cv2.moments(mask_g)
        M_r = cv2.moments(mask_r)
       
       
    
        # Avoid division by zero if the color is obscured/missing
        gx = int(M_g['m10']/M_g['m00']) if M_g['m00'] > 0 else None
        gy = int(M_g['m01']/M_g['m00']) if M_g['m00'] > 0 else None
        if gx is None or gy is None:
            M_g2 = cv2.moments(mask_g2)
            gx = int(M_g2['m10']/M_g2['m00']) if M_g2['m00'] > 0 else None
            gy = int(M_g2['m01']/M_g2['m00']) if M_g2['m00'] > 0 else None
        rx = int(M_r['m10']/M_r['m00']) if M_r['m00'] > 0 else None
        ry = int(M_r['m01']/M_r['m00']) if M_r['m00'] > 0 else None
        if rx is None or ry is None:
            M_r2 = cv2.moments(mask_r2)
            rx = int(M_r2['m10']/M_r2['m00']) if M_r2['m00'] > 0 else None
            ry = int(M_r2['m01']/M_r2['m00']) if M_r2['m00'] > 0 else None
        if rx is None or ry is None:
            M_r3 = cv2.moments(mask_r3)
            rx = int(M_r3['m10']/M_r3['m00']) if M_r3['m00'] > 0 else None
            ry = int(M_r3['m01']/M_r3['m00']) if M_r3['m00'] > 0 else None
        
        if rx is None or ry is None or gx is None or gy is None:
            1/0
    
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
    
        # time.sleep(0.05)
        
        data.append([time_sec, gx, gy, rx, ry])
        
        
    
    # Clean up
    cap.release()
    cv2.destroyAllWindows()
    # pbar.close()
    # Save the results
    
    
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
        
    
    
    x1=np.array([i[1] for i in data])
    y1=np.array([-i[2] for i in data])
    x2=np.array([i[3] for i in data])
    y2=np.array([-i[4] for i in data])
    
    x0,y0,_=find_circle_center(x1,y1)
    # plt.figure()
    # x0=312.78293187519023#312
    # y0=-331.7829060826372#-330
    t_array = np.array([i[0] for i in data])
    t1=np.arctan2(x1-x0,-(y1-y0))
    t2=np.arctan2(x2-x1,-(y2-y1))
    df=pd.DataFrame(np.concatenate(([t_array],[t1],[t2])).T,columns=['time','t1','t2'])
    df.to_csv(fr"C:\Users\Nir\Documents\Courses\year 2 semester b\Lab b2\chaos\driven pendulum data\{base_name}_{x0:.3f}_{y0:.3f}.csv", index=False)
    # df = pd.DataFrame(data, columns=['Time', 'x1', 'y1', 'x2', 'y2'])

# # --- Interactive Spectrogram Section ---
# t_array = np.array([i[0] for i in data])
# dt = np.mean(np.diff(t_array))
# fs = 1.0 / dt if dt > 0 else 30.0

# # Create figure and axis objects, leaving space at the bottom for the slider
# fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
# plt.subplots_adjust(bottom=0.20, hspace=0.3)

# init_nfft = 128

# # Function to draw the spectrograms, so we can recall it when the slider moves
# def draw_spectrograms(nfft_val):
#     ax1.clear()
#     ax2.clear()
    
#     # We dynamically set overlap to 50% of the selected NFFT size
#     overlap_val = int(nfft_val // 2)

#     ax1.specgram(t1, Fs=fs, NFFT=nfft_val, noverlap=overlap_val, cmap='viridis')
#     ax1.set_title(f'Spectrogram of t1 (Inner Angle) - NFFT: {nfft_val}')
#     ax1.set_ylabel('Frequency (Hz)')

#     ax2.specgram(t2, Fs=fs, NFFT=nfft_val, noverlap=overlap_val, cmap='viridis')
#     ax2.set_title(f'Spectrogram of t2 (Outer Angle) - NFFT: {nfft_val}')
#     ax2.set_xlabel('Time (s)')
#     ax2.set_ylabel('Frequency (Hz)')
    
#     fig.canvas.draw_idle()

# # Draw initial plots
# draw_spectrograms(init_nfft)

# # Add the Slider axes and object
# ax_nfft = plt.axes([0.15, 0.05, 0.70, 0.03])
# slider_nfft = Slider(
#     ax=ax_nfft,
#     label='NFFT Size',
#     valmin=32,
#     valmax=512,
#     valinit=init_nfft,
#     valstep=32 # Steps of 32 to keep it tidy
# )

# # Update function for when the slider changes
# def update(val):
#     current_nfft = int(slider_nfft.val)
#     draw_spectrograms(current_nfft)

# slider_nfft.on_changed(update)

# plt.show()