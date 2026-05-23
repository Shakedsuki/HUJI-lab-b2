#!/usr/bin/env python3
"""throwaway: replicate build_gallery's redirect+size context for wfall."""
import os, sys, io, contextlib, traceback
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.normpath(os.path.join(_HERE, "..", "utils")))
import quick_insights as qi

d = qi.load_clip("3.2V_1.20Hz")
qi._GALLERY_SIZE = (80, 11)
buf = io.StringIO()
try:
    with contextlib.redirect_stdout(buf):
        qi.PLOTS["wfall"][2](d)
except Exception:
    qi._GALLERY_SIZE = None
    traceback.print_exc()
    print("EXC under redirect")
qi._GALLERY_SIZE = None
s = buf.getvalue()
print("captured len:", len(s))
print("first 160 repr:", repr(s[:160]))
print("last 160 repr:", repr(s[-160:]))
