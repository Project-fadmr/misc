"""HUD holder generator: writes hud_holder_left.stl / hud_holder_right.stl and a preview PNG."""
import struct
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import numpy as np
import manifold3d as mf

OUT_DIR = Path(__file__).resolve().parent
PREVIEW = OUT_DIR / "hud_holder_preview.png"

# Base block and bed (YZ profile, extruded along X)
BASE_X = (-185, 165)
BASE_Y = 100
BED_Z0 = 30
BED_ANGLE = np.radians(15)
# Display pocket (coordinates along the slope: s from front edge, d into the bed)
POCKET_X = 160.5
POCKET_S = (4, 85)
POCKET_D = 2.2
OVERSHOOT = 3  # cutters extend this far above the bed surface
DATA_PIT_X = (-170, -109)  # runs under the panel into the GPIO channel
DATA_PIT_S = (24.5, 64.5)
DATA_PIT_D = 10
# Electronics pockets (open at rear face)
MKR_BOX = (-177, -149, 38, 101, 2, 24)
BAT_BOX = (24, 108, 18, 101, 2, 24)
CHANNEL_BOX = (-178, -162, 38, 101, 2, 300)  # open-top GPIO channel exposing the MKR header row
POWER_SLOT_BOX = (-6, 6, 35, 101, 20, 300)  # display power wires out the rear, centred on the seam
# Glass (45 deg, top edge toward viewer)
GLASS_PB = np.array([84.0, 80.0])
GLASS_T = (0, 116)
GLASS_W = (-1, 1)
# Gussets and groove
GUS_X = (119, 127)
GROOVE_X = (119, 122)
GROOVE_PROFILE = [(0, -1.25), (95, -1.25), (110, -4), (200, -4), (200, 4), (110, 4), (95, 1.25), (0, 1.25)]  # (t, w)
# Alignment pins
PIN_D = 4.2
PIN_DEPTH = 10
PINS_YZ = [(15, 15), (85, 10)]

A15 = np.radians(15)
SLOPE_O = np.array([0.0, BED_Z0])
SLOPE_U = np.array([np.cos(A15), np.sin(A15)])
SLOPE_N = np.array([np.sin(A15), -np.cos(A15)])  # points into the bed
A45 = np.pi / 4
GU = np.array([-np.cos(A45), np.sin(A45)])
GN = np.array([np.cos(A45), np.sin(A45)])


def zbed(y):
    return BED_Z0 + y * np.tan(BED_ANGLE)


def slope_pt(s, d):
    return SLOPE_O + np.multiply.outer(s, SLOPE_U) + d * SLOPE_N


def glass_pt(t, w):
    return GLASS_PB + t * GU + w * GN


def prism_x(cs, x0, x1):
    """Extrude a (y,z) cross-section along X from x0 to x1."""
    return cs.extrude(x1 - x0).transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]])


def poly_x(pts, x0, x1):
    return prism_x(mf.CrossSection([np.array(pts, float)], mf.FillRule.EvenOdd), x0, x1)


def slope_prism(s0, s1, d0, d1, x0, x1):
    return poly_x([slope_pt(s, d) for s, d in [(s0, d0), (s1, d0), (s1, d1), (s0, d1)]], x0, x1)


def box(x0, x1, y0, y1, z0, z1):
    return mf.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def pin(x_start, y, z):
    return mf.Manifold.cylinder(PIN_DEPTH, PIN_D / 2, PIN_D / 2, 48).rotate([0, 90, 0]).translate((x_start, y, z))


def write_stl(path, mesh):
    v = mesh.vert_properties[:, :3][mesh.tri_verts]
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    keep = np.linalg.norm(n, axis=1) / 2 >= 1e-9  # drop zero-area slivers
    v, n = v[keep].astype(np.float32), n[keep]
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    rec = np.zeros(len(v), dtype=[("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, v
    with open(path, "wb") as f:
        f.write(bytes(80) + struct.pack("<I", len(v)))
        rec.tofile(f)


def main():
    # 1. Base block minus display pocket, notches and electronics pockets
    base = poly_x([(0, 0), (BASE_Y, 0), (BASE_Y, zbed(BASE_Y)), (0, zbed(0))], *BASE_X)
    pocket = slope_prism(*POCKET_S, -OVERSHOOT, POCKET_D, -POCKET_X, POCKET_X)
    data_pit = slope_prism(*DATA_PIT_S, -OVERSHOOT, DATA_PIT_D, *DATA_PIT_X)
    base = base - pocket - data_pit - box(*MKR_BOX) - box(*BAT_BOX) - box(*CHANNEL_BOX) - box(*POWER_SLOT_BOX)

    # 2. Right gusset (hull of glass-strip corners and foot), groove on its inner face; left is its mirror
    hull = mf.CrossSection.hull_points(np.array([
        glass_pt(-6, -6), glass_pt(-6, 6), glass_pt(110, -6), glass_pt(110, 6),
        (88, zbed(88) - 1), (100, zbed(100) - 1)]))
    groove = poly_x([glass_pt(t, w) for t, w in GROOVE_PROFILE], *GROOVE_X)
    gus_r = prism_x(hull, *GUS_X) - groove
    gus_l = gus_r.mirror((1, 0, 0))
    body = base + gus_r + gus_l

    # 3. Split at x=0 and cut the alignment pins
    halves = []
    for side, box_x in (("left", (-200, 0)), ("right", (0, 200))):
        half = body ^ box(box_x[0], box_x[1], -10, 200, -10, 300)
        x_start = -PIN_DEPTH if side == "left" else 0
        for y, z in PINS_YZ:
            half = half - pin(x_start, y, z)
        halves.append((side, half))

    # 4. Self-checks
    glass_shrunk = poly_x([glass_pt(GLASS_T[0], GLASS_W[0]), glass_pt(GLASS_T[1], GLASS_W[0]),
                           glass_pt(GLASS_T[1], GLASS_W[1]), glass_pt(GLASS_T[0], GLASS_W[1])],
                          -118.5, 118.5)
    slab = slope_prism(4.5, 84.5, 0, 2, -160, 160)
    bat_fit = box(26, 106, 19, 99, 3, 23)
    mkr_fit = box(-175, -150, 39, 99, 3, 23)
    dupont = box(-176, -170, 40, 98, 23, 80)  # plug clearance from above
    power_wire = box(-5, 5, 36, 100, 22, 60)
    data_clear = slope_prism(25, 64, 2.5, 9, -165, -110)
    assert (data_pit ^ box(*MKR_BOX)).volume() < 1e-6  # keeps a roof over the MKR pocket
    s = np.linspace(*POCKET_S, 200)
    p = slope_pt(s, 0)
    lam = ((GLASS_PB - p) @ GN) / GN[1]
    t = (p + np.outer(lam, [0, 1]) - GLASS_PB) @ GU
    print(f"ray check: lam>0 {np.all(lam > 0)}, t range [{t.min():.2f}, {t.max():.2f}] "
          f"(glass t {GLASS_T})")
    assert np.all(lam > 0) and t.min() >= GLASS_T[0] and t.max() <= GLASS_T[1]
    assert (gus_r ^ pocket).volume() < 1e-6 and (gus_l ^ pocket).volume() < 1e-6

    meshes = []
    for side, half in halves:
        assert not half.is_empty() and half.status() == mf.Error.NoError, side
        bb = np.array(half.bounding_box()).reshape(2, 3)  # (xmin,ymin,zmin),(xmax,ymax,zmax)
        print(f"{side}: status OK, volume {half.volume():.1f} mm^3, genus {half.genus()}, "
              f"bbox min {np.round(bb[0], 2)} max {np.round(bb[1], 2)}")
        assert bb[1][2] <= 200 and bb[1][1] <= 100.01 and bb[0][1] >= -0.01
        assert np.allclose(bb[:, 0], (-185, 0) if side == "left" else (0, 165), atol=0.01)
        for name, shape in [("glass shrunk", glass_shrunk), ("display slab", slab),
                            ("battery box", bat_fit), ("MKR box", mkr_fit), ("Dupont box", dupont),
                            ("power wire", power_wire), ("data wire", data_clear)]:
            vol = (half ^ shape).volume()
            print(f"  intersection {name}: {vol:.6f} mm^3")
            assert vol < 1e-6, name
        meshes.append(half.to_mesh())
    for y, z in PINS_YZ:
        for x_start in (-PIN_DEPTH, 0):
            for name, cutter in [("power slot", box(*POWER_SLOT_BOX)), ("MKR", box(*MKR_BOX)),
                                 ("battery", box(*BAT_BOX))]:
                assert (pin(x_start, y, z) ^ cutter).volume() < 1e-6, (name, y, z)
    print("  pin cylinders vs power slot / MKR / battery boxes: 0 mm^3")

    for (side, half), mesh in zip(halves, meshes):
        write_stl(OUT_DIR / f"hud_holder_{side}.stl", mesh)
        print(f"wrote {OUT_DIR / f'hud_holder_{side}.stl'}")
    # print 2: Ø3.9 in the Ø4.2 holes leaves room for glue, 1 mm shorter than both holes together
    pin_part = mf.Manifold.cylinder(2 * PIN_DEPTH - 1, 3.9 / 2, 3.9 / 2, 48)
    assert pin_part.status() == mf.Error.NoError
    write_stl(OUT_DIR / "hud_holder_pin.stl", pin_part.to_mesh())
    print(f"wrote {OUT_DIR / 'hud_holder_pin.stl'}")

    # 5. Preview: 3D, side (along X) and top
    tris = np.concatenate([m.vert_properties[:, :3][m.tri_verts] for m in meshes])
    fig = plt.figure(figsize=(15, 5))
    ax = fig.add_subplot(131, projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolor="#9aa", edgecolor="k", linewidth=0.1))
    ax.set_xlim(-190, 170); ax.set_ylim(0, 100); ax.set_zlim(0, 170)
    ax.set_box_aspect((360, 100, 170)); ax.view_init(25, -60)
    for sub, cols, labels, title in [(132, [1, 2], ("y (depth)", "z (up)"), "side view along X"),
                                     (133, [0, 1], ("x", "y (depth)"), "top view")]:
        a = fig.add_subplot(sub)
        a.add_collection(PolyCollection(tris[:, :, cols], facecolor="#9aa", edgecolor="k", linewidth=0.1))
        a.autoscale_view(); a.set_aspect("equal"); a.set_xlabel(labels[0]); a.set_ylabel(labels[1])
        a.set_title(title)
    fig.savefig(PREVIEW, dpi=110, bbox_inches="tight")
    print(f"wrote {PREVIEW}")


if __name__ == "__main__":
    main()
