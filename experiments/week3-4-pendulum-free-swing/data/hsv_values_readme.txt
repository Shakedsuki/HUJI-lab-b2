hsv_values.json
===============

Calibrated HSV ranges and ring parameters for ring_tracker.py.

Fields
------
green / red       per-marker HSV ranges. OpenCV uses H in [0, 179],
                  S and V in [0, 255].
  h_min, h_max    hue range
  s_min, s_max    saturation range
  v_min, v_max    value (brightness) range
  h_min2, h_max2  (red only) second hue range to handle wraparound
                  near 0/180. Detection mask = (H in [h_min,h_max])
                  OR (H in [h_min2,h_max2]), AND saturation/value
                  within the configured range.

ring_tolerance    width (in pixels) of the search annulus around
                  the expected arm length. Detection only considers
                  pixels within +/- this tolerance of the radius.

arm_length_px     fixed arm length in pixels for both arms (~188).
