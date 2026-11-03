#!/usr/bin/env python3
"""pv_boil.py — line-boil ("抖动") and sketch-texture pass for character-swap PVs.

Hand-drawn PVs often keep a held pose alive by alternating two (or more) slightly
different redraws of the whole picture every few frames ("line boil"). If you swap
the characters with clean, static art, the background keeps boiling while the new
characters freeze, which looks pasted-on. This tool:

  measure   Measure, per shot, on which source frames the picture is redrawn, and how
            far the lines move between redraws. Writes a boil schedule (JSON).
  variants  Turn one placed RGBA character layer into per-phase variants (A, B, ...):
            palette flattening, subtle stroke-width variation with sparse gaps, and a
            smooth, low-amplitude displacement field. Deterministic: the same
            (key, phase) always produces the same pixels.
  pick      Print which phase a given global frame uses, according to a schedule.

No image generation is involved; identity never drifts because every variant is a
small deterministic deformation of the same frozen drawing.

Conventions: frames are zero-based integers, ranges are half-open [start, end).
All pixel amplitudes are in OUTPUT pixels: run `variants` on the layer AFTER it has
been scaled and placed into the output frame, not on the raw master.

Requires: Python 3.9+, numpy, opencv-python (or -headless), Pillow. FFmpeg on PATH
for `measure` (frames are decoded with ffmpeg so that frame indices are exact).
License: MIT (see repository LICENSE).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# --------------------------------------------------------------------------- utils

def seed_for(*parts: str) -> int:
    """Stable uint32 seed from string parts (independent of Python's hash salt)."""
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def read_frames(video: str, start: int, end: int, width: int, height: int,
                ffmpeg: str = "ffmpeg") -> np.ndarray:
    """Decode frames [start, end) as uint8 RGB using exact frame-index selection."""
    vf = f"select='between(n\\,{start}\\,{end - 1})'"
    cmd = [ffmpeg, "-v", "error", "-i", video, "-vf", vf, "-vsync", "0",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, check=True, capture_output=True).stdout
    n = len(raw) // (width * height * 3)
    if n != end - start:
        raise RuntimeError(f"expected {end - start} frames, decoded {n}")
    return np.frombuffer(raw, np.uint8).reshape(n, height, width, 3)


def probe_size(video: str, ffprobe: str = "ffprobe") -> tuple[int, int]:
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "json", video],
                         check=True, capture_output=True, text=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"])


# ------------------------------------------------------------------------ measure

@dataclass
class ShotSchedule:
    shotId: str
    range: list
    boilFrames: list = field(default_factory=list)      # frames where a redraw starts
    holds: list = field(default_factory=list)            # [{startFrame,endFrameExclusive,phase}]
    phases: list = field(default_factory=list)
    displacementPx: dict = field(default_factory=dict)   # median / p90 between first two holds
    notes: str = ""


def _region_change(a: np.ndarray, b: np.ndarray, box) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    d = np.abs(a[y0:y1, x0:x1].astype(np.int16) - b[y0:y1, x0:x1].astype(np.int16))
    return float(d.mean()), float((d.max(axis=2) > 18).mean())


def _lk_displacement(a: np.ndarray, b: np.ndarray, box) -> dict:
    ga, gb = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    mask = np.zeros(ga.shape, np.uint8)
    x0, y0, x1, y1 = box
    mask[y0:y1, x0:x1] = 255
    pts = cv2.goodFeaturesToTrack(ga, 4000, 0.015, 5, mask=mask, blockSize=5)
    if pts is None or len(pts) < 10:
        return {"validPoints": 0}
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01)
    q, st, _ = cv2.calcOpticalFlowPyrLK(ga, gb, pts, None, winSize=(21, 21), maxLevel=3, criteria=crit)
    back, stb, _ = cv2.calcOpticalFlowPyrLK(gb, ga, q, None, winSize=(21, 21), maxLevel=3, criteria=crit)
    v = (q - pts).reshape(-1, 2)
    fb = np.linalg.norm((back - pts).reshape(-1, 2), axis=1)
    ok = (st.ravel() > 0) & (stb.ravel() > 0) & (fb < 1.0) & (np.linalg.norm(v, axis=1) < 15)
    d = np.linalg.norm(v[ok], axis=1)
    if d.size == 0:
        return {"validPoints": 0}
    return {"validPoints": int(d.size), "medianPx": round(float(np.median(d)), 3),
            "p90Px": round(float(np.percentile(d, 90)), 3)}


def measure_shot(frames: np.ndarray, start: int, shot_id: str, box, *,
                 mad_threshold: float, changed_threshold: float,
                 relative_threshold: float, recurrence_ratio: float,
                 pose_frames: set[int]) -> ShotSchedule:
    """Detect redraw frames in `box` and assign recurring phases (A, B, C...).

    A redraw changes most of the lines in the box at once, so it is much larger than
    the small animated bits (sparkles, sleep marks) that may share the box. We keep a
    candidate only if it passes the absolute thresholds AND is at least
    `relative_threshold` x the 75th-percentile candidate strength.
    Phases: a hold is the same drawing as an earlier phase if its difference to that
    phase is below `recurrence_ratio` x the typical difference between consecutive holds.
    """
    n = len(frames)
    end = start + n
    scored = []
    for i in range(1, n):
        mad, changed = _region_change(frames[i], frames[i - 1], box)
        if mad > mad_threshold and changed > changed_threshold:
            scored.append((start + i, mad))
    if scored:
        ref = float(np.percentile([m for _, m in scored], 75))
        scored = [(f, m) for f, m in scored if m >= relative_threshold * ref]
    boil = [f for f, _ in scored if f not in pose_frames]

    cuts = [start] + sorted(set(boil) | (pose_frames & set(range(start + 1, end)))) + [end]
    x0, y0, x1, y1 = box
    crops = [frames[s - start][y0:y1, x0:x1].astype(np.int16) for s in cuts[:-1]]
    consecutive = [float(np.abs(crops[i] - crops[i - 1]).mean()) for i in range(1, len(crops))]
    same_thr = recurrence_ratio * (float(np.median(consecutive)) if consecutive else 1.0)

    reps: list[np.ndarray] = []
    holds, names = [], []
    for (s, e), crop in zip(zip(cuts[:-1], cuts[1:]), crops):
        if s in pose_frames:
            reps = []                 # a genuine pose change starts a new drawing family
        dists = [float(np.abs(crop - r).mean()) for r in reps]
        if dists and min(dists) < same_thr:
            phase = chr(ord("A") + int(np.argmin(dists)))
        else:
            reps.append(crop)
            phase = chr(ord("A") + len(reps) - 1)
        holds.append({"startFrame": s, "endFrameExclusive": e, "phase": phase})
        names.append(phase)

    disp = {}
    if len(holds) >= 2:
        a = frames[holds[0]["startFrame"] - start]
        b = frames[holds[1]["startFrame"] - start]
        disp = _lk_displacement(a, b, box)
    return ShotSchedule(shotId=shot_id, range=[start, end], boilFrames=boil, holds=holds,
                        phases=sorted(set(names)), displacementPx=disp)


def cmd_measure(args) -> None:
    shots = json.loads(Path(args.shots).read_text(encoding="utf-8"))
    w, h = probe_size(args.video, args.ffprobe)
    out = {"schemaVersion": 1, "tool": "pv_boil.py measure", "video": Path(args.video).name,
           "frameConvention": "zero-based, half-open", "params": {
               "madThreshold": args.mad, "changedThreshold": args.changed,
               "relativeThreshold": args.relative, "recurrenceRatio": args.recurrence},
           "shots": {}}
    for sh in shots:
        sid, s, e = sh["shotId"], int(sh["startFrame"]), int(sh["endFrameExclusive"])
        if sh.get("noCharacter"):
            out["shots"][sid] = {"range": [s, e], "status": "no-character"}
            continue
        box = sh.get("box") or [0, 0, w, h]
        frames = read_frames(args.video, s, e, w, h, args.ffmpeg)
        res = measure_shot(frames, s, sid, box, mad_threshold=args.mad,
                           changed_threshold=args.changed,
                           relative_threshold=args.relative,
                           recurrence_ratio=args.recurrence,
                           pose_frames=set(int(f) for f in sh.get("poseChanges", [])))
        d = asdict(res)
        d["box"] = box
        gaps = np.diff(res.boilFrames) if len(res.boilFrames) > 1 else []
        d["typicalIntervalFrames"] = int(np.median(gaps)) if len(gaps) else None
        out["shots"][sid] = d
        print(f"{sid}: boil={len(res.boilFrames)} interval={d['typicalIntervalFrames']} "
              f"phases={res.phases} disp={res.displacementPx}", file=sys.stderr)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------- variants

DEFAULTS = {
    "line": {"maxChannelExclusive": 60, "maxChroma": 22, "alphaMinimum": 200,
             "broadFillOpeningPx": 9,
             "widthCellPx": 55, "widthRadiusMaxPx": 0.55,
             "gapRatePerInkPixel": 0.0012, "gapSigmaPx": 1.3, "gapAttenuation": 0.72},
    "flatten": {"clusters": 32, "maxSamples": 60000, "mergeRGBDistance": 28.0,
                "maxColorShift": 36.0,
                "lineProtectionDilation": 3, "alphaMinimum": 250},
    "warp": {"largeCellPx": 100, "smallCellPx": 18, "targetMedianPx": 1.6,
             "smallMedianPx": 0.5, "maxPx": 8.0, "faceStrength": 0.5, "faceFeatherPx": 12},
}


def _rgba(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"))


def line_mask(img: np.ndarray, p: dict) -> np.ndarray:
    """Near-black, low-chroma ink only. Dark irises / dark hair fills are NOT lines."""
    rgb = img[..., :3].astype(np.int16)
    chroma = rgb.max(-1) - rgb.min(-1)
    dark = (rgb.max(-1) < p["maxChannelExclusive"]) & (chroma < p["maxChroma"]) & \
           (img[..., 3] >= p["alphaMinimum"])
    # Broad black FILLS (hats, shorts, socks) are not strokes: whatever survives a
    # morphological opening of diameter `broadFillOpeningPx` is a fill, not a line.
    d = int(p["broadFillOpeningPx"])
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    broad = cv2.morphologyEx(dark.astype(np.uint8), cv2.MORPH_OPEN, k)
    broad = cv2.dilate(broad, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))).astype(bool)
    return dark & ~broad


def flatten_fills(img: np.ndarray, ink: np.ndarray, p: dict, seed: int) -> np.ndarray:
    """Quantize fills to a small shared palette (removes soft gradients); ink untouched."""
    out = img.copy()
    guard = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8),
                       iterations=p["lineProtectionDilation"]).astype(bool)
    fill = (img[..., 3] >= p["alphaMinimum"]) & ~guard
    px = img[..., :3][fill].astype(np.float32)
    if len(px) < p["clusters"] * 4:
        return out
    rng = np.random.default_rng(seed)
    sample = px[rng.choice(len(px), min(len(px), p["maxSamples"]), replace=False)]
    cv2.setRNGSeed(seed & 0x7FFFFFFF)
    _, _, centers = cv2.kmeans(sample, p["clusters"], None,
                               (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.05),
                               1, cv2.KMEANS_PP_CENTERS)
    # merge near-identical centers
    merged: list[np.ndarray] = []
    for c in centers:
        if all(np.linalg.norm(c - m) > p["mergeRGBDistance"] for m in merged):
            merged.append(c)
    pal = np.array(merged, np.float32)
    lab = np.argmin(((px[:, None, :] - pal[None]) ** 2).sum(-1), axis=1)
    # each cluster takes its median colour from the real pixels (keeps hue honest)
    med = np.array([np.median(px[lab == k], axis=0) if np.any(lab == k) else pal[k]
                    for k in range(len(pal))])
    out_px = med[lab].astype(np.float32)
    # Never let a pixel drift far from its own colour: small accents (blush, badges,
    # cheek marks) would otherwise be absorbed into a neighbouring cluster and turn muddy.
    shift = np.linalg.norm(out_px - px, axis=1)
    out_px[shift > p["maxColorShift"]] = px[shift > p["maxColorShift"]]
    tmp = out[..., :3].copy()
    tmp[fill] = np.clip(out_px, 0, 255).astype(np.uint8)
    out[..., :3] = tmp
    return out


def _smooth_noise(h: int, w: int, cell: float, rng) -> np.ndarray:
    gh, gw = int(np.ceil(h / cell)) + 3, int(np.ceil(w / cell)) + 3
    g = rng.standard_normal((gh, gw)).astype(np.float32)
    return cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)


def stroke_texture(img: np.ndarray, ink: np.ndarray, p: dict, seed: int,
                   strength: np.ndarray) -> np.ndarray:
    """Low-frequency stroke-width change (+/- r px) and sparse soft gaps."""
    h, w = ink.shape
    rng = np.random.default_rng(seed)
    r = _smooth_noise(h, w, p["widthCellPx"], rng)
    r = r / (np.abs(r).max() + 1e-6) * p["widthRadiusMaxPx"] * strength
    out = img.copy()
    dist_out = cv2.distanceTransform((~ink).astype(np.uint8), cv2.DIST_L2, 3)  # outside ink
    thicken = (~ink) & (dist_out <= np.maximum(r, 0)) & (img[..., 3] > 0)
    out[thicken, :3] = (out[thicken, :3] * 0.25 + 20 * 0.75).astype(np.uint8)
    dist_in = cv2.distanceTransform(ink.astype(np.uint8), cv2.DIST_L2, 3)       # inside ink
    thin = ink & (dist_in <= np.maximum(-r, 0))
    if thin.any():
        fill_col = cv2.inpaint(img[..., :3], ink.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
        out[thin, :3] = fill_col[thin]
    # sparse gaps
    ys, xs = np.nonzero(ink)
    k = rng.binomial(len(ys), p["gapRatePerInkPixel"])
    if k:
        idx = rng.choice(len(ys), k, replace=False)
        g = np.zeros((h, w), np.float32)
        g[ys[idx], xs[idx]] = 1.0
        g = cv2.GaussianBlur(g, (0, 0), p["gapSigmaPx"])
        g = np.clip(g / (g.max() + 1e-6), 0, 1) * p["gapAttenuation"] * strength
        fill_col = cv2.inpaint(img[..., :3], ink.astype(np.uint8) * 255, 3, cv2.INPAINT_TELEA)
        m = ink & (g > 0.02)
        out[m, :3] = (out[m, :3] * (1 - g[m, None]) + fill_col[m] * g[m, None]).astype(np.uint8)
    return out


def displacement_field(h: int, w: int, p: dict, seed: int, opaque: np.ndarray,
                       strength: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    fx = _smooth_noise(h, w, p["largeCellPx"], rng)
    fy = _smooth_noise(h, w, p["largeCellPx"], rng)
    sx = _smooth_noise(h, w, p["smallCellPx"], rng)
    sy = _smooth_noise(h, w, p["smallCellPx"], rng)

    def norm(ax, ay, target):
        mag = np.hypot(ax, ay)[opaque]
        m = float(np.median(mag)) if mag.size else 1.0
        return ax * (target / (m + 1e-6)), ay * (target / (m + 1e-6))

    fx, fy = norm(fx, fy, p["targetMedianPx"])
    sx, sy = norm(sx, sy, p["smallMedianPx"])
    dx, dy = (fx + sx) * strength, (fy + sy) * strength
    mag = np.hypot(dx, dy)
    scale = np.minimum(1.0, p["maxPx"] / (mag + 1e-6))
    return dx * scale, dy * scale


def warp_rgba(img: np.ndarray, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
    """Remap with premultiplied alpha so edges do not pick up dark/white fringes."""
    h, w = img.shape[:2]
    a = img[..., 3:4].astype(np.float32) / 255.0
    pre = np.concatenate([img[..., :3].astype(np.float32) * a, a * 255.0], axis=2)
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    res = cv2.remap(pre, xs + dx.astype(np.float32), ys + dy.astype(np.float32),
                    cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    alpha = np.clip(res[..., 3:4], 0, 255)
    rgb = np.where(alpha > 0, res[..., :3] / np.maximum(alpha / 255.0, 1e-6), 0)
    return np.concatenate([np.clip(rgb, 0, 255), alpha], axis=2).astype(np.uint8)


def strength_map(h: int, w: int, faces: list, face_strength: float, feather: float) -> np.ndarray:
    s = np.ones((h, w), np.float32)
    if not faces:
        return s
    m = np.zeros((h, w), np.float32)
    for x0, y0, x1, y1 in faces:
        m[int(y0):int(y1), int(x0):int(x1)] = 1.0
    if feather > 0:
        m = cv2.GaussianBlur(m, (0, 0), feather)
    return 1.0 - (1.0 - face_strength) * np.clip(m, 0, 1)


def make_variants(img: np.ndarray, key: str, phases: list[str], params: dict,
                  faces: list | None = None, protect: np.ndarray | None = None) -> dict:
    """Return {phase: RGBA uint8}. Phases share one palette; each phase has its own
    stroke texture and displacement. With two phases the displacement is split
    symmetrically (+F/2, -F/2) so the average stays on the frozen drawing."""
    p = {k: {**DEFAULTS[k], **params.get(k, {})} for k in DEFAULTS}
    h, w = img.shape[:2]
    ink = line_mask(img, p["line"])
    flat = flatten_fills(img, ink, p["flatten"], seed_for(key, "palette"))
    strength = strength_map(h, w, faces or [], p["warp"]["faceStrength"], p["warp"]["faceFeatherPx"])
    if protect is not None:
        strength = np.where(protect, 0.0, strength).astype(np.float32)
    opaque = img[..., 3] > 128
    out = {}
    if len(phases) == 2:
        dx, dy = displacement_field(h, w, p["warp"], seed_for(key, "pair", "warp"), opaque, strength)
        fields = {phases[0]: (dx / 2, dy / 2), phases[1]: (-dx / 2, -dy / 2)}
    else:
        fields = {ph: displacement_field(h, w, p["warp"], seed_for(key, ph, "warp"), opaque, strength)
                  for ph in phases}
    for ph in phases:
        tex = stroke_texture(flat, ink, p["line"], seed_for(key, ph, "stroke"), strength)
        out[ph] = warp_rgba(tex, *fields[ph])
    return out


def cmd_variants(args) -> None:
    img = _rgba(args.layer)
    params = json.loads(Path(args.params).read_text(encoding="utf-8")) if args.params else {}
    if args.target_median is not None:
        params.setdefault("warp", {})["targetMedianPx"] = args.target_median
    faces = json.loads(args.faces) if args.faces else []
    protect = None
    if args.protect:
        protect = np.array(Image.open(args.protect).convert("L")) > 127
    phases = args.phases.split(",")
    res = make_variants(img, args.key, phases, params, faces, protect)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for ph, arr in res.items():
        Image.fromarray(arr, "RGBA").save(outdir / f"{args.key}.{ph}.png")
    print(f"wrote {len(res)} variants to {outdir}", file=sys.stderr)


# --------------------------------------------------------------------------- pick

def phase_at(schedule: dict, shot_id: str, frame: int) -> str:
    for hold in schedule["shots"][shot_id]["holds"]:
        if hold["startFrame"] <= frame < hold["endFrameExclusive"]:
            return hold["phase"]
    raise KeyError(f"frame {frame} not in shot {shot_id}")


def cmd_pick(args) -> None:
    sch = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    print(phase_at(sch, args.shot, args.frame))


# ---------------------------------------------------------------------------- cli

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="measure per-shot boil schedule from the source video")
    m.add_argument("--video", required=True)
    m.add_argument("--shots", required=True,
                   help="JSON list: [{shotId,startFrame,endFrameExclusive,box?,poseChanges?,noCharacter?}]")
    m.add_argument("--out", required=True)
    m.add_argument("--mad", type=float, default=0.32, help="mean abs diff threshold in box")
    m.add_argument("--changed", type=float, default=0.001, help="fraction of pixels changed >18")
    m.add_argument("--relative", type=float, default=0.5,
                   help="keep candidates >= this x 75th-percentile candidate strength")
    m.add_argument("--recurrence", type=float, default=0.5,
                   help="same drawing if diff < this x typical consecutive-hold diff")
    m.add_argument("--ffmpeg", default="ffmpeg")
    m.add_argument("--ffprobe", default="ffprobe")
    m.set_defaults(func=cmd_measure)

    v = sub.add_parser("variants", help="make per-phase texture variants of one placed layer")
    v.add_argument("--layer", required=True, help="RGBA PNG already placed in output space")
    v.add_argument("--key", required=True, help="stable id, e.g. s060.duo (drives the seeds)")
    v.add_argument("--phases", default="A,B")
    v.add_argument("--params", help="JSON overriding DEFAULTS (line/flatten/warp)")
    v.add_argument("--target-median", type=float, help="warp median px; use the measured source value")
    v.add_argument("--faces", help='JSON list of face boxes [[x0,y0,x1,y1],...] (strength halved)')
    v.add_argument("--protect", help="grayscale PNG mask; white = do not deform (props, contact hands)")
    v.add_argument("--outdir", required=True)
    v.set_defaults(func=cmd_variants)

    k = sub.add_parser("pick", help="phase used at a global frame")
    k.add_argument("--schedule", required=True)
    k.add_argument("--shot", required=True)
    k.add_argument("--frame", type=int, required=True)
    k.set_defaults(func=cmd_pick)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
