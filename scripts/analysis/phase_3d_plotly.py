#!/usr/bin/env python3
"""
phase_3d_plotly.py
------------------
Interactive 3D phase-portrait viewer for a single driven-pendulum clip.

Renders a full-screen Three.js scene (60 fps, WebGL) with smooth growing-
trace animation and orbit controls (drag to rotate, scroll to zoom, right-
drag to pan).  Two arms selectable via toggle buttons:

    Arm 1  (x = theta_1, y = omega_1, z = t)
    Arm 2  (x = theta_2, y = omega_2, z = t)

Features (all togglable in the HUD):
    Trail mode   -- Full (cumulative) or Window (last N seconds, comet-tail).
    Color mode   -- Time (viridis) or Speed |omega| (plasma).
    Shadow       -- 2D projection of the trajectory onto the floor plane,
                   building in real time (the phase portrait forming live).
    Strobes      -- Gold dots placed every drive period T = 1/f_drive.
                   These are exactly the stroboscopic Poincare points.
    Ghost        -- Faint preview of the full trajectory for context.

The HTML is an interactive, regenerable artifact (like the animations), so
it is written under animations/ and is git-ignored -- regenerate on demand.

Usage
~~~~~
  python scripts/analysis/phase_3d_plotly.py --stem 3.2V_1.20Hz
  python scripts/analysis/phase_3d_plotly.py --stem 3.2V_0.91Hz --transient 3

Output
~~~~~~
  animations/phase_3d_plotly/<stem>_phase_3d_plotly.html
"""

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import colormaps

from rich.console import Console
from rich.table import Table
import rich.box

console = Console()

sys.path.insert(0, os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "utils")))
from paths import EXPERIMENTS, clip_dir              # noqa: E402
from figures_paths import figure_path, mirror_to_ready  # noqa: E402
from driven_helpers import parse_stem, load_driven_csv   # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stem", required=True,
                   help="Clip stem, e.g. 3.2V_1.20Hz")
    p.add_argument("--transient", type=float, default=5.0,
                   help="Seconds to skip at start (default: 5).")
    p.add_argument("--subsample", type=int, default=2,
                   help="Take every Nth point (default: 2). Three.js handles "
                        "~3000 pts smoothly at 60 fps.")
    return p.parse_args()


def resolve_f_drive(stem, override=None):
    """Drive frequency from experiments.json, falling back to the stem name."""
    if override is not None:
        return override
    if os.path.exists(EXPERIMENTS):
        with open(EXPERIMENTS, encoding="utf-8") as f:
            exp = json.load(f)
        if stem in exp and "drive_freq_hz" in exp[stem]:
            return float(exp[stem]["drive_freq_hz"])
    try:
        return parse_stem(stem)["f_drive_hz"]
    except ValueError:
        return None


def _rgb3(cmap_name, values_01):
    """Map a 0-1 array through a matplotlib colormap -> list of [r,g,b]."""
    cm = colormaps[cmap_name]
    return [[round(c[0], 3), round(c[1], 3), round(c[2], 3)]
            for c in cm(values_01)]


def build_html(t, th1, th2, om1, om2, stem, f_drive):
    """Return a self-contained HTML string (Three.js, no server needed)."""

    n = len(t)
    t_norm = (t - t.min()) / (t.max() - t.min() + 1e-12)

    time_colors = _rgb3("viridis", t_norm)

    def speed_col(om):
        s = np.abs(om)
        sn = (s - s.min()) / (s.max() - s.min() + 1e-12)
        return _rgb3("plasma", sn)

    speed_colors_1 = speed_col(om1)
    speed_colors_2 = speed_col(om2)

    strobe_indices = []
    if f_drive and f_drive > 0:
        T = 1.0 / f_drive
        strobe_times = np.arange(t[0] + T, t[-1], T)
        for st in strobe_times:
            idx = int(np.argmin(np.abs(t - st)))
            if abs(t[idx] - st) < 0.02:
                strobe_indices.append(idx)

    T_display = f"{1/f_drive:.3f}" if f_drive else "?"

    data = dict(
        stem=stem, f_drive=f_drive or 0, n=n,
        t=np.round(t, 4).tolist(),
        th1=np.round(th1, 2).tolist(), om1=np.round(om1, 1).tolist(),
        th2=np.round(th2, 2).tolist(), om2=np.round(om2, 1).tolist(),
        colors=time_colors,
        speed_colors_1=speed_colors_1, speed_colors_2=speed_colors_2,
        strobe_indices=strobe_indices,
    )
    data_json = json.dumps(data, separators=(",", ":"))

    # The HTML is built as an f-string.  JavaScript braces are doubled {{ }}.
    html = f'''<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>3D Phase Portrait — {stem}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#f5f5f0;color:#333;font-family:system-ui,sans-serif;overflow:hidden}}
#c{{width:100vw;height:100vh;display:block}}
#hud{{position:fixed;top:14px;left:14px;z-index:10;background:rgba(255,255,255,0.92);
  border-radius:10px;padding:12px 16px;backdrop-filter:blur(8px);min-width:240px;
  border:1px solid rgba(0,0,0,0.1);box-shadow:0 2px 12px rgba(0,0,0,0.07);font-size:12.5px}}
#hud h2{{font-size:14px;font-weight:500;color:#1a6;margin-bottom:6px}}
.row{{display:flex;align-items:center;gap:7px;margin:4px 0}}
.label{{color:#888;min-width:48px;font-size:12px}}
.val{{color:#222;font-variant-numeric:tabular-nums;font-size:12.5px}}
.btnrow{{display:flex;gap:4px;margin:5px 0;flex-wrap:wrap}}
.btnrow button,.ctrl button{{background:rgba(0,0,0,0.04);border:1px solid rgba(0,0,0,0.13);
  color:#444;border-radius:5px;padding:4px 10px;cursor:pointer;font-size:12px}}
.btnrow button:hover,.ctrl button:hover{{background:rgba(0,0,0,0.09)}}
.btnrow button.on,.ctrl button.on{{background:rgba(20,120,80,0.14);border-color:#1a6;color:#1a6;font-weight:600}}
.sep{{border-top:1px solid rgba(0,0,0,0.07);margin:7px 0}}
input[type=range]{{width:90px;accent-color:#1a6}}
#hint{{position:fixed;bottom:14px;left:50%;transform:translateX(-50%);font-size:11px;color:#aaa;z-index:10}}
.legend{{position:fixed;bottom:14px;right:14px;z-index:10;background:rgba(255,255,255,0.9);
  border-radius:8px;padding:8px 12px;border:1px solid rgba(0,0,0,0.08);font-size:11px;color:#666}}
.legend .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;vertical-align:middle}}
</style>
</head><body>
<canvas id="c"></canvas>
<div id="hud">
  <h2>{stem} <span style="color:#999;font-weight:400">f = {f_drive or '?'} Hz</span></h2>
  <div class="btnrow"><button class="on" onclick="setArm(1)" id="ab1">Arm 1</button>
    <button onclick="setArm(2)" id="ab2">Arm 2</button></div>
  <div class="sep"></div>
  <div style="font-size:11px;color:#999;margin-bottom:3px">trail</div>
  <div class="btnrow"><button class="on" onclick="setTrail('full')" id="tb_full">Full</button>
    <button onclick="setTrail('window')" id="tb_win">Window</button></div>
  <div class="row" id="winrow" style="display:none"><span class="label">window</span>
    <input type="range" id="winsize" min="1" max="25" step="0.5" value="6">
    <span class="val" id="vwin">6.0 s</span></div>
  <div class="sep"></div>
  <div style="font-size:11px;color:#999;margin-bottom:3px">color</div>
  <div class="btnrow"><button class="on" onclick="setColor('time')" id="cb_time">Time</button>
    <button onclick="setColor('speed')" id="cb_speed">Speed |&omega;|</button></div>
  <div class="sep"></div>
  <div style="font-size:11px;color:#999;margin-bottom:3px">layers</div>
  <div class="btnrow"><button class="on" onclick="toggleLayer('shadow')" id="lb_shadow">Shadow</button>
    <button class="on" onclick="toggleLayer('strobe')" id="lb_strobe">Strobes</button>
    <button class="on" onclick="toggleLayer('ghost')" id="lb_ghost">Ghost</button></div>
  <div class="sep"></div>
  <div class="row"><span class="label">t</span><span class="val" id="vt">0.0 s</span></div>
  <div class="row"><span class="label">pts</span><span class="val" id="vn">0</span></div>
  <div class="row"><span class="label">strobes</span><span class="val" id="vs">0</span></div>
  <div class="sep"></div>
  <div class="row"><button onclick="togglePlay()" id="playbtn" style="min-width:70px">&#9208; Pause</button>
    <button onclick="resetAnim()">&#8634; Reset</button></div>
  <div class="row"><span class="label">speed</span>
    <input type="range" id="speed" min="0.1" max="3" step="0.05" value="0.35">
    <span class="val" id="vspd">0.35&times;</span></div>
</div>
<div class="legend"><span class="dot" style="background:#FFD700"></span> strobe (T = {T_display} s)</div>
<div id="hint">drag to rotate &middot; scroll to zoom &middot; right-drag to pan</div>

<script type="importmap">
{{"imports":{{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js","three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}}}
</script>

<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

const DATA = {data_json};
const N = DATA.n;
const STROBE_IDX = DATA.strobe_indices;

let arm = 1, playing = true, drawCount = 1, accumT = 0;
let trailMode = "full", colorMode = "time";
let layers = {{ shadow: true, strobe: true, ghost: true }};

function norm(arr, pad) {{
  pad = pad || 1.05;
  var mn = Math.min.apply(null, arr), mx = Math.max.apply(null, arr);
  var r = (mx - mn) / 2 * pad, c = (mx + mn) / 2;
  return {{ scale: r || 1, center: c }};
}}
const norms = {{
  1: {{ x: norm(DATA.th1), y: norm(DATA.om1), z: norm(DATA.t) }},
  2: {{ x: norm(DATA.th2), y: norm(DATA.om2), z: norm(DATA.t) }}
}};
const Z_FLOOR = -1.0;

function posArray(aId) {{
  var th = aId===1?DATA.th1:DATA.th2, om = aId===1?DATA.om1:DATA.om2;
  var nx=norms[aId].x, ny=norms[aId].y, nz=norms[aId].z;
  var p = new Float32Array(N*3);
  for (var i=0;i<N;i++) {{
    p[i*3]=(th[i]-nx.center)/nx.scale;
    p[i*3+1]=(om[i]-ny.center)/ny.scale;
    p[i*3+2]=(DATA.t[i]-nz.center)/nz.scale;
  }}
  return p;
}}
function shadowPos(aId) {{
  var p = posArray(aId).slice();
  for (var i=0;i<N;i++) p[i*3+2] = Z_FLOOR;
  return p;
}}
function colArray(aId, mode) {{
  var src;
  if (mode==="speed") src = aId===1?DATA.speed_colors_1:DATA.speed_colors_2;
  else src = DATA.colors;
  var c = new Float32Array(N*3);
  for (var i=0;i<N;i++) {{ c[i*3]=src[i][0]; c[i*3+1]=src[i][1]; c[i*3+2]=src[i][2]; }}
  return c;
}}
function makeGeo(pa, ca) {{
  var g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pa, 3));
  g.setAttribute("color", new THREE.BufferAttribute(ca, 3));
  g.setDrawRange(0, 0);
  return g;
}}

var canvas = document.getElementById("c");
var renderer = new THREE.WebGLRenderer({{ canvas: canvas, antialias: true }});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setClearColor(0xf5f5f0);
var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(50, window.innerWidth/window.innerHeight, 0.01, 100);
camera.position.set(2.0, 1.3, 1.6);
var controls = new OrbitControls(camera, canvas);
controls.enableDamping = true; controls.dampingFactor = 0.08; controls.rotateSpeed = 0.6;

var grid = new THREE.GridHelper(2.4, 12, 0xcccccc, 0xdddddd);
grid.rotation.x = Math.PI/2; grid.position.z = Z_FLOOR; scene.add(grid);
var axMat = new THREE.LineBasicMaterial({{ color: 0xbbbbbb }});
function ax(a,b) {{
  scene.add(new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(a[0],a[1],a[2]), new THREE.Vector3(b[0],b[1],b[2])]), axMat));
}}
ax([-1.3,0,0],[1.3,0,0]); ax([0,-1.3,0],[0,1.3,0]); ax([0,0,Z_FLOOR],[0,0,1.3]);

function mkLbl(text, pos, color) {{
  var cv = document.createElement("canvas"); cv.width=256; cv.height=64;
  var cx = cv.getContext("2d"); cx.font="26px system-ui";
  cx.fillStyle = "#"+color.toString(16).padStart(6,"0");
  cx.textAlign = "center"; cx.fillText(text, 128, 40);
  var s = new THREE.Sprite(new THREE.SpriteMaterial({{ map: new THREE.CanvasTexture(cv), transparent: true }}));
  s.position.set(pos[0], pos[1], pos[2]); s.scale.set(0.55, 0.14, 1); return s;
}}
var lbls = {{ 1: [], 2: [] }};
function buildLbls(a) {{
  return [
    mkLbl(a===1?"\u03B8\u2081 (deg)":"\u03B8\u2082 (deg)", [1.45,0,0], 0x338855),
    mkLbl(a===1?"\u03C9\u2081 (\u00B0/s)":"\u03C9\u2082 (\u00B0/s)", [0,1.45,0], 0x885533),
    mkLbl("t (s)", [0,0,1.45], 0x335588)
  ];
}}
lbls[1] = buildLbls(1); lbls[2] = buildLbls(2);
lbls[1].forEach(function(l){{ scene.add(l); }});
lbls[2].forEach(function(l){{ l.visible=false; scene.add(l); }});

var objs = {{}};
[1,2].forEach(function(a) {{
  var pa=posArray(a), ca=colArray(a,"time"), spa=shadowPos(a);
  var sc=new Float32Array(N*3);
  for(var i=0;i<N;i++){{sc[i*3]=0.5;sc[i*3+1]=0.5;sc[i*3+2]=0.6;}}
  var ghost=new THREE.Points(makeGeo(pa.slice(),ca.slice()),
    new THREE.PointsMaterial({{size:1.2,vertexColors:true,opacity:0.06,transparent:true,sizeAttenuation:false}}));
  ghost.geometry.setDrawRange(0,N);
  var lineGeo=makeGeo(pa.slice(),ca.slice());
  var line=new THREE.Line(lineGeo, new THREE.LineBasicMaterial({{vertexColors:true}}));
  var dotGeo=makeGeo(pa.slice(),ca.slice());
  var dots=new THREE.Points(dotGeo,
    new THREE.PointsMaterial({{size:2.2,vertexColors:true,opacity:0.5,transparent:true,sizeAttenuation:false}}));
  var shadGeo=makeGeo(spa,sc);
  var shadow=new THREE.Points(shadGeo,
    new THREE.PointsMaterial({{size:1.5,vertexColors:true,opacity:0.12,transparent:true,sizeAttenuation:false}}));
  var stPA=new Float32Array(STROBE_IDX.length*3);
  for(var j=0;j<STROBE_IDX.length;j++){{var si=STROBE_IDX[j];
    stPA[j*3]=pa[si*3];stPA[j*3+1]=pa[si*3+1];stPA[j*3+2]=pa[si*3+2];}}
  var stGeo=new THREE.BufferGeometry();
  stGeo.setAttribute("position",new THREE.BufferAttribute(stPA,3));
  stGeo.setDrawRange(0,0);
  var strobes=new THREE.Points(stGeo,
    new THREE.PointsMaterial({{size:6,color:0xFFD700,opacity:0.9,transparent:true,sizeAttenuation:false}}));
  var stSPA=stPA.slice();
  for(var j=0;j<STROBE_IDX.length;j++) stSPA[j*3+2]=Z_FLOOR;
  var stSGeo=new THREE.BufferGeometry();
  stSGeo.setAttribute("position",new THREE.BufferAttribute(stSPA,3));
  stSGeo.setDrawRange(0,0);
  var strobeShadow=new THREE.Points(stSGeo,
    new THREE.PointsMaterial({{size:5,color:0xFFD700,opacity:0.25,transparent:true,sizeAttenuation:false}}));
  var nowMesh=new THREE.Mesh(new THREE.SphereGeometry(0.022,16,16),
    new THREE.MeshBasicMaterial({{color:a===1?0x11aa55:0xcc3333}}));
  var vis=a===1;
  [ghost,line,dots,shadow,strobes,strobeShadow,nowMesh].forEach(function(o){{o.visible=vis;scene.add(o);}});
  objs[a]={{ghost:ghost,line:line,lineGeo:lineGeo,dotGeo:dotGeo,dots:dots,
    shadow:shadow,shadGeo:shadGeo,strobes:strobes,strobeGeo:stGeo,
    strobeShadow:strobeShadow,strobeShadGeo:stSGeo,nowMesh:nowMesh,
    posArr:pa,timeCol:ca.slice(),speedCol:colArray(a,"speed")}};
}});

var $=function(id){{return document.getElementById(id)}};
var speedEl=$("speed"),vtEl=$("vt"),vnEl=$("vn"),vsEl=$("vs"),vspdEl=$("vspd");
var winEl=$("winsize"),vwinEl=$("vwin"),winrowEl=$("winrow");

window.setArm=function(a){{
  arm=a; $("ab1").className=a===1?"on":""; $("ab2").className=a===2?"on":"";
  [1,2].forEach(function(id){{
    var v=id===a, o=objs[id];
    o.line.visible=v; o.dots.visible=v; o.nowMesh.visible=v;
    o.ghost.visible=v&&layers.ghost; o.shadow.visible=v&&layers.shadow;
    o.strobes.visible=v&&layers.strobe;
    o.strobeShadow.visible=v&&layers.shadow&&layers.strobe;
    lbls[id].forEach(function(l){{l.visible=v;}});
  }});
}};
window.setTrail=function(m){{
  trailMode=m; $("tb_full").className=m==="full"?"on":"";
  $("tb_win").className=m==="window"?"on":"";
  winrowEl.style.display=m==="window"?"flex":"none";
}};
window.setColor=function(m){{
  colorMode=m; $("cb_time").className=m==="time"?"on":"";
  $("cb_speed").className=m==="speed"?"on":"";
  [1,2].forEach(function(a){{
    var o=objs[a], src=m==="time"?o.timeCol:o.speedCol;
    o.lineGeo.attributes.color.array.set(src); o.lineGeo.attributes.color.needsUpdate=true;
    o.dotGeo.attributes.color.array.set(src); o.dotGeo.attributes.color.needsUpdate=true;
  }});
}};
window.toggleLayer=function(name){{
  layers[name]=!layers[name]; $("lb_"+name).className=layers[name]?"on":"";
  var o=objs[arm];
  if(name==="ghost") o.ghost.visible=layers.ghost;
  if(name==="shadow"){{o.shadow.visible=layers.shadow;o.strobeShadow.visible=layers.shadow&&layers.strobe;}}
  if(name==="strobe"){{o.strobes.visible=layers.strobe;o.strobeShadow.visible=layers.shadow&&layers.strobe;}}
}};
window.togglePlay=function(){{
  playing=!playing;
  $("playbtn").textContent=playing?"\u23F8 Pause":"\u25B6 Play";
}};
window.resetAnim=function(){{ drawCount=1; accumT=0; }};

var lastTime=0, duration=120;
function animate(timestamp) {{
  requestAnimationFrame(animate);
  var dt=lastTime?(timestamp-lastTime)/1000:0; lastTime=timestamp;
  if(playing&&drawCount<N){{
    var spd=parseFloat(speedEl.value); vspdEl.textContent=spd.toFixed(2)+"\u00D7";
    accumT+=dt*spd; drawCount=Math.min(N,Math.max(1,Math.floor((accumT/duration)*N)));
  }}
  var winS=parseFloat(winEl.value); vwinEl.textContent=winS.toFixed(1)+" s";
  var startIdx=0;
  if(trailMode==="window"&&drawCount>1){{
    var tNow=DATA.t[drawCount-1], tCut=tNow-winS;
    for(var i=drawCount-1;i>=0;i--){{if(DATA.t[i]<tCut){{startIdx=i+1;break;}}}}
  }}
  var count=drawCount-startIdx;
  [1,2].forEach(function(a){{
    var o=objs[a];
    o.lineGeo.setDrawRange(startIdx,count); o.dotGeo.setDrawRange(startIdx,count);
    o.shadGeo.setDrawRange(0,drawCount);
    var nStr=0;
    for(var j=0;j<STROBE_IDX.length;j++){{if(STROBE_IDX[j]<drawCount)nStr=j+1;else break;}}
    o.strobeGeo.setDrawRange(0,nStr); o.strobeShadGeo.setDrawRange(0,nStr);
    var idx=Math.max(0,drawCount-1), p=o.lineGeo.attributes.position;
    o.nowMesh.position.set(p.getX(idx),p.getY(idx),p.getZ(idx));
  }});
  var ti=Math.max(0,drawCount-1);
  vtEl.textContent=DATA.t[ti].toFixed(1)+" s"; vnEl.textContent=count+" / "+N;
  var nS=0; for(var j=0;j<STROBE_IDX.length;j++){{if(STROBE_IDX[j]<drawCount)nS++;else break;}}
  vsEl.textContent=nS+" / "+STROBE_IDX.length;
  controls.update(); renderer.render(scene,camera);
}}
window.addEventListener("resize",function(){{
  camera.aspect=window.innerWidth/window.innerHeight;
  camera.updateProjectionMatrix(); renderer.setSize(window.innerWidth,window.innerHeight);
}});
requestAnimationFrame(animate);
</script>
</body></html>'''
    return html


def main():
    args = parse_args()
    stem = args.stem

    t, th1, th2, om1, om2 = load_driven_csv(
        os.path.join(clip_dir(stem), "verification.csv"))
    f_drive = resolve_f_drive(stem)

    mask = t >= args.transient
    t, th1, th2, om1, om2 = t[mask], th1[mask], th2[mask], om1[mask], om2[mask]
    s = max(1, args.subsample)
    t, th1, th2 = t[::s], th1[::s], th2[::s]
    om1, om2 = om1[::s], om2[::s]
    if len(t) < 10:
        raise SystemExit(f"only {len(t)} points after transient+subsample.")

    info = Table(box=rich.box.SIMPLE_HEAD, show_header=False)
    info.add_column(style="dim", min_width=18)
    info.add_column(style="white", justify="right")
    info.add_row("stem",     f"[cyan]{stem}[/]")
    info.add_row("f_drive",  f"{f_drive:.3f} Hz" if f_drive else "[dim]unknown[/]")
    info.add_row("points",   f"{len(t)}  [dim](subsample {s})[/]")
    info.add_row("t range",  f"{t[0]:.1f} \u2013 {t[-1]:.1f} s  "
                              f"[dim](transient {args.transient:.0f} s cut)[/]")
    info.add_row("\u03B8\u2081 range", f"{th1.min():.1f} .. {th1.max():.1f}\u00B0")
    info.add_row("\u03C9\u2081 range", f"{om1.min():.0f} .. {om1.max():.0f} \u00B0/s")
    info.add_row("\u03B8\u2082 range", f"{th2.min():.1f} .. {th2.max():.1f}\u00B0")
    info.add_row("\u03C9\u2082 range", f"{om2.min():.0f} .. {om2.max():.0f} \u00B0/s")
    n_strobe = 0
    if f_drive and f_drive > 0:
        n_strobe = int((t[-1] - t[0]) * f_drive)
    info.add_row("strobes",  f"~{n_strobe}  [dim](T = {1/f_drive:.3f} s)[/]"
                              if f_drive else "[dim]\u2014[/]")
    console.print(info)

    html = build_html(t, th1, th2, om1, om2, stem, f_drive)

    out_path = figure_path("phase_3d_plotly", stem, ext="html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    mirror_to_ready(out_path)
    console.print(f"\n  [green]Saved \u2192[/] {out_path}")
    console.print("  [dim]Open in browser to interact (rotate / zoom / play).[/]")


if __name__ == "__main__":
    main()
