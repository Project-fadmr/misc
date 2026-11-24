"""Radar enclosure generator: writes radar_enclosure_base.stl / radar_enclosure_lid.stl and a preview PNG."""
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
PREVIEW = OUT_DIR / "radar_enclosure_preview.png"

# Walls and floor
WALL = 1.6
FLOOR_T = 1.6
OUT_R = 3
PILOT_DEPTH = 8

# Radar board (frame: top-left corner origin, z up)
BOARD_X, BOARD_Y, BOARD_T = 114.3, 26.9, 1.6
BOARD_Z0 = FLOOR_T + 15
BOARD_TOP = BOARD_Z0 + BOARD_T
J5_H = 7.4  # tallest top part above board top
J5_Y = (8, 21)  # barrel jack span in y, notched out of the lid skirt
INNER_TOP = BOARD_TOP + J5_H + 1  # 1 mm headroom above J5, rim height
CLR = 1  # board to cavity wall clearance

# Cavity (x0, x1, y0, y1)
CAV_X0, CAV_X1 = -1, BOARD_X + CLR + 10  # +x extended 10 mm for connector J10
CAV_Y0, CAV_Y1 = -1, 51.5  # +y extended so the 1.2 mm ESP frame wall fits
OUT_X0, OUT_X1 = CAV_X0 - WALL, CAV_X1 + WALL
OUT_Y0, OUT_Y1 = CAV_Y0 - WALL, CAV_Y1 + WALL

# Standoffs (x, y, OD/2, pilot/2); M3 self-tapping into plastic: OD 6.5, pilot 2.5
M3_R, M3_PILOT_R = 3.25, 1.25
STANDOFFS = [
    (2.54, 3.51, M3_R, M3_PILOT_R),
    (2.54, 23.43, M3_R, M3_PILOT_R),
    (54.48, 3.43, M3_R, M3_PILOT_R),
    (90.31, 3.43, M3_R, M3_PILOT_R),
]

# ESP32-C3 SuperMini (pin headers point down, 3 mm below PCB)
ESP_X, ESP_Y, ESP_T = 23.9, 18, 1
ESP_X1 = CAV_X1 - CLR
ESP_X0 = ESP_X1 - ESP_X
ESP_Y0 = 31
ESP_CY = ESP_Y0 + ESP_Y / 2
ESP_Z0 = FLOOR_T + 3.5  # PCB bottom on central rail; pins reach FLOOR_T + 0.5
ESP_TOP = ESP_Z0 + ESP_T
RAIL_W = 6  # central support rail, centred on ESP_CY
FRAME_H = ESP_Z0 + ESP_T + 1 - FLOOR_T  # frame wall 1 mm above PCB top
FRAME_CLR = 0.5
FRAME_T = 1.2
FRAME_GAP_NX = 6  # -x side, for wires; the +x side is open-ended at the wall

# Openings through the walls
J1_Y, J1_Z = 13.47, BOARD_Z0 - 1.45  # main power input, -x wall
J1_W, J1_H = 12, 9
USBC_Y, USBC_Z = ESP_CY, ESP_TOP + 1.6  # +x wall
USBC_W, USBC_H = 12.5, 7.5
OPEN_R = 1.5  # corner radius for rounded openings (not in spec)

# Ventilation
FLOOR_VENT_W, FLOOR_VENT_L, FLOOR_VENT_PITCH = 2, 20, 4
FLOOR_VENT_Y = 13.45
FLOOR_VENT_XS = [7 + FLOOR_VENT_PITCH * i for i in range(8)]  # spans x 6..36, clear of standoffs
WALL_VENT_W, WALL_VENT_H, WALL_VENT_PITCH = 2, 10, 4
WALL_VENT_Z0 = FLOOR_T + 3
WALL_VENT_XS = [5 + WALL_VENT_PITCH * i for i in range(8)]  # spans x 4..34

# Snap groove
GROOVE_DEPTH, GROOVE_H = 0.6, 1.2
GROOVE_Z = INNER_TOP - 2.0

# Lid
LID_CLR = 0.25
SKIRT_H, SKIRT_T = 3.5, 1.6
BUMP_H = 0.7  # outward protrusion of the ridge
WIN = (11, 43, 1, 26)  # radar window at plate underside, chamfered 45 deg
J7_HOLE, J7_R = (64.5, 91.5, 20, 27), 1  # lid opening over the J7 header (x0, x1, y0, y1)
ESP_HOLE, ESP_R = (ESP_X0 + 0.5, ESP_X1 - 2.3, 31.5, 48.5), 1.5  # lid opening over the ESP32 pin rows

BUMP_HALF = GROOVE_H / 2


def rrect_pts(a0, a1, b0, b1, r):
    pts = []
    for cx, cy, s in [(a1 - r, b1 - r, 0), (a0 + r, b1 - r, np.pi / 2),
                      (a0 + r, b0 + r, np.pi), (a1 - r, b0 + r, 3 * np.pi / 2)]:
        for t in np.linspace(s, s + np.pi / 2, 8):
            pts.append((cx + r * np.cos(t), cy + r * np.sin(t)))
    return np.array(pts)


def rrect_cs(a0, a1, b0, b1, r):
    return mf.CrossSection.hull_points(rrect_pts(a0, a1, b0, b1, r))


def prism_x(cs, x0, x1):
    """Extrude a (y,z) cross-section along X from x0 to x1."""
    return cs.extrude(x1 - x0).transform([[0, 0, 1, x0], [1, 0, 0, 0], [0, 1, 0, 0]])


def box(x0, x1, y0, y1, z0, z1):
    return mf.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def rect_pts3(rect, z, o):
    x0, x1, y0, y1 = rect
    return [(x0 - o, y0 - o, z), (x1 + o, y0 - o, z), (x1 + o, y1 + o, z), (x0 - o, y1 + o, z)]


def frustum(rect, z0, o0, z1, o1):
    return mf.Manifold.hull_points(np.array(rect_pts3(rect, z0, o0) + rect_pts3(rect, z1, o1), float))


def cyl(x, y, r, z0, h):
    return mf.Manifold.cylinder(h, r, r, 48).translate((x, y, z0))


def probe(x, y, z, s=0.5):
    return box(x - s / 2, x + s / 2, y - s / 2, y + s / 2, z - s / 2, z + s / 2)


def lid_hole(hole, r):
    """Tall rounded-rect cutter for a lid plate opening (hole = x0, x1, y0, y1)."""
    return rrect_cs(*hole, r).extrude(40).translate((0, 0, -10))


def disk_hits_rect(cx, cy, r, x0, x1, y0, y1):
    nx, ny = min(max(cx, x0), x1), min(max(cy, y0), y1)
    return (cx - nx) ** 2 + (cy - ny) ** 2 < r * r


def write_stl(path, mesh):
    v = mesh.vert_properties[:, :3][mesh.tri_verts].astype(np.float32)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    rec = np.zeros(len(v), dtype=[("n", "<f4", (3,)), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, v
    with open(path, "wb") as f:
        f.write(bytes(80) + struct.pack("<I", len(v)))
        rec.tofile(f)


def bbox(m):
    return np.round(np.array(m.bounding_box()).reshape(2, 3), 3)


def main():
    # Opening cutters, each through one wall (x-range covers wall only)
    j1_cut = box(OUT_X0 - 1, CAV_X0 + 1, J1_Y - J1_W / 2, J1_Y + J1_W / 2, J1_Z - J1_H / 2, J1_Z + J1_H / 2)
    usbc_cut = prism_x(rrect_cs(USBC_Y - USBC_W / 2, USBC_Y + USBC_W / 2,
                                USBC_Z - USBC_H / 2, USBC_Z + USBC_H / 2, OPEN_R), CAV_X1 - 3, OUT_X1 + 1)
    openings = j1_cut + usbc_cut

    floor_vents = mf.Manifold()
    for x in FLOOR_VENT_XS:
        floor_vents += box(x - FLOOR_VENT_W / 2, x + FLOOR_VENT_W / 2,
                           FLOOR_VENT_Y - FLOOR_VENT_L / 2, FLOOR_VENT_Y + FLOOR_VENT_L / 2, -1, FLOOR_T + 1)
    for x in WALL_VENT_XS:
        floor_vents += box(x - WALL_VENT_W / 2, x + WALL_VENT_W / 2, -5, 0,
                           WALL_VENT_Z0, WALL_VENT_Z0 + WALL_VENT_H)

    # Base shell, cavity, snap groove
    outer = rrect_cs(OUT_X0, OUT_X1, OUT_Y0, OUT_Y1, OUT_R).extrude(INNER_TOP)
    cavity = box(CAV_X0, CAV_X1, CAV_Y0, CAV_Y1, FLOOR_T, INNER_TOP + 1)
    groove_out = box(CAV_X0 - GROOVE_DEPTH, CAV_X1 + GROOVE_DEPTH, CAV_Y0 - GROOVE_DEPTH,
                     CAV_Y1 + GROOVE_DEPTH, GROOVE_Z - BUMP_HALF, GROOVE_Z + BUMP_HALF)
    groove = groove_out - box(CAV_X0, CAV_X1, CAV_Y0, CAV_Y1, GROOVE_Z - 1, GROOVE_Z + 1)
    base = outer - cavity - groove - openings - floor_vents

    # Standoffs, rails, ESP frame, zip-tie loop
    vent_rects = [(x - FLOOR_VENT_W / 2, x + FLOOR_VENT_W / 2, FLOOR_VENT_Y - FLOOR_VENT_L / 2,
                   FLOOR_VENT_Y + FLOOR_VENT_L / 2) for x in FLOOR_VENT_XS]
    standoffs = mf.Manifold()
    pilots = mf.Manifold()
    for x, y, r, pr in STANDOFFS:
        assert not any(disk_hits_rect(x, y, r, *rect) for rect in vent_rects), (x, y)
        s = cyl(x, y, r, FLOOR_T - 1, BOARD_Z0 - (FLOOR_T - 1))
        assert abs(s.bounding_box()[5] - BOARD_Z0) < 1e-9
        standoffs += s
        pilots += cyl(x, y, pr, BOARD_Z0 - PILOT_DEPTH, PILOT_DEPTH + 1)

    rail = box(ESP_X0 + 2, ESP_X1 - 2, ESP_CY - RAIL_W / 2, ESP_CY + RAIL_W / 2, FLOOR_T - 0.5, ESP_Z0)

    # Frame: -x, -y and +y sides only; the +x side is absent (wall and USB-C opening hold that end)
    f_out = box(ESP_X0 - FRAME_CLR - FRAME_T, ESP_X1,
                ESP_Y0 - FRAME_CLR - FRAME_T, ESP_Y0 + ESP_Y + FRAME_CLR + FRAME_T,
                FLOOR_T - 0.5, FLOOR_T + FRAME_H)
    f_in = box(ESP_X0 - FRAME_CLR, ESP_X1 + FRAME_CLR + 1, ESP_Y0 - FRAME_CLR,
               ESP_Y0 + ESP_Y + FRAME_CLR, FLOOR_T - 1, FLOOR_T + FRAME_H + 1)
    gap_nx = box(ESP_X0 - 5, ESP_X0, ESP_CY - FRAME_GAP_NX / 2, ESP_CY + FRAME_GAP_NX / 2, 0, 10)
    frame = f_out - f_in - gap_nx

    base = (base + standoffs + rail + frame) - pilots

    # Lid: plate, skirt, bump, window, J5 notch
    plate = rrect_cs(OUT_X0, OUT_X1, OUT_Y0, OUT_Y1, OUT_R).extrude(WALL).translate((0, 0, INNER_TOP))
    window = mf.Manifold.hull_points(np.array(
        rect_pts3(WIN, INNER_TOP - 0.1, -0.1) + rect_pts3(WIN, INNER_TOP + WALL + 0.5, WALL + 0.5), float))
    plate = plate - window - lid_hole(J7_HOLE, J7_R) - lid_hole(ESP_HOLE, ESP_R)

    SK = (CAV_X0 + LID_CLR, CAV_X1 - LID_CLR, CAV_Y0 + LID_CLR, CAV_Y1 - LID_CLR)
    SK_IN = (SK[0] + SKIRT_T, SK[1] - SKIRT_T, SK[2] + SKIRT_T, SK[3] - SKIRT_T)
    SK_Z0 = INNER_TOP - SKIRT_H
    assert SK[0] - BUMP_H >= CAV_X0 - GROOVE_DEPTH, "bump tip leaves the groove"
    print(f"snap engagement: {CAV_X0 - (SK[0] - BUMP_H):.2f} mm")
    skirt_outer = box(*SK, SK_Z0, INNER_TOP)
    assert np.allclose(bbox(skirt_outer)[1, :2] - bbox(skirt_outer)[0, :2],
                       [CAV_X1 - CAV_X0 - 2 * LID_CLR, CAV_Y1 - CAV_Y0 - 2 * LID_CLR])
    skirt_in = box(*SK_IN, SK_Z0 - 1, INNER_TOP + 0.1)
    bump = frustum(SK, GROOVE_Z - BUMP_HALF, 0, GROOVE_Z, BUMP_H) \
        + frustum(SK, GROOVE_Z, BUMP_H, GROOVE_Z + BUMP_HALF, 0)
    j5_notch = box(CAV_X1 - 5, CAV_X1 + WALL, J5_Y[0], J5_Y[1], SK_Z0 - 1, INNER_TOP + 0.1)
    skirt = (skirt_outer + bump) - skirt_in - j5_notch

    lid_asm = plate + skirt

    # Export: plate top on z=0, skirt up (rotate 180 about x, lift)
    lid = lid_asm.rotate([180, 0, 0]).translate((0, 0, INNER_TOP + WALL))

    # Checks
    assert CAV_X0 <= -CLR and CAV_X1 >= BOARD_X + CLR and CAV_Y0 <= -CLR and BOARD_Y + CLR <= CAV_Y1
    assert WALL - GROOVE_DEPTH >= 0.8, "groove leaves too little wall"
    assert CAV_X0 <= ESP_X0 and ESP_X1 <= CAV_X1 and CAV_Y0 <= ESP_Y0 and ESP_Y0 + ESP_Y <= CAV_Y1
    assert ESP_Y0 > BOARD_Y + CLR, "ESP overlaps radar board in XY"
    assert CAV_Y0 <= ESP_Y0 - FRAME_CLR - FRAME_T and ESP_Y0 + ESP_Y + FRAME_CLR + FRAME_T <= CAV_Y1, \
        "ESP frame does not fit the cavity"
    j5_box = box(100, BOARD_X, 9.5, 19, 18.6, 26)
    assert (lid_asm ^ j5_box).volume() < 1e-6, "lid skirt collides with barrel jack J5"
    for hole, r in [(J7_HOLE, J7_R), (ESP_HOLE, ESP_R)]:
        assert (lid_hole(hole, r) ^ skirt).volume() < 1e-6, f"lid hole {hole} cuts the skirt"
    assert J7_HOLE[1] < ESP_HOLE[0] and ESP_HOLE[1] < SK_IN[1], "lid holes overlap or reach the skirt"
    assert J7_HOLE[0] > WIN[1] + 2, "J7 lid hole reaches the radar window"
    for m, name in [(base, "base"), (lid, "lid")]:
        assert not m.is_empty() and m.status() == mf.Error.NoError, name
        assert m.volume() > 0, name
    assert bbox(base)[0][2] == 0, "base must sit flat on z=0"
    for part_name, m in [("base", base), ("lid", lid)]:
        print(f"{part_name}: status OK, volume {m.volume():.1f} mm^3, bbox min {bbox(m)[0]} max {bbox(m)[1]}")

    def solid_probe(m, p, name, want_solid):
        vol = (m ^ p).volume()
        pv = p.volume()
        if want_solid:
            assert vol > 0.99 * pv, f"{name}: expected solid, got {vol:.4f} of {pv:.4f}"
        else:
            assert vol < 1e-6, f"{name}: expected open, intersection {vol:.6f}"
        print(f"  {name}: intersection {vol:.6f} mm^3 ({'solid' if want_solid else 'open'})")

    print("probes:")
    solid_probe(base, probe(CAV_X0 - WALL / 2, J1_Y, J1_Z), "J1 opening (-x wall)", False)
    solid_probe(base, probe(CAV_X1 + WALL / 2, USBC_Y, USBC_Z), "USB-C opening (+x wall)", False)
    solid_probe(base, probe(5, CAV_Y0 - WALL / 2, 10), "-y wall vent slot (x 4..6)", False)
    solid_probe(base, probe(7, CAV_Y0 - WALL / 2, 10), "-y wall between vent slots", True)
    solid_probe(base, probe(CAV_X0 - WALL / 2, J1_Y, J1_Z + J1_H / 2 + 1), "J1 wall material above opening", True)
    for x, y, r, pr in STANDOFFS:
        solid_probe(base, probe(x + (r + pr) / 2, y, 12, 0.4), f"standoff ring at ({x},{y})", True)
        solid_probe(base, probe(x, y, 12), f"standoff pilot at ({x},{y})", False)
    solid_probe(lid_asm, probe(27, 13.5, INNER_TOP + WALL / 2), "radar window (lid plate, assembled)", False)
    solid_probe(lid_asm, probe(60, 13.5, INNER_TOP + WALL / 2), "lid plate away from window", True)
    solid_probe(lid_asm, probe(CAV_X1 - LID_CLR - SKIRT_T / 2, 40, 25), "lid skirt at +x wall", True)
    solid_probe(lid_asm, probe(sum(J7_HOLE[:2]) / 2, sum(J7_HOLE[2:]) / 2, INNER_TOP + WALL / 2),
                "J7 lid opening", False)
    solid_probe(lid_asm, probe(sum(ESP_HOLE[:2]) / 2, sum(ESP_HOLE[2:]) / 2, INNER_TOP + WALL / 2),
                "ESP32 lid opening", False)
    solid_probe(base, probe(ESP_X0 + ESP_X / 2, ESP_Y0 + 1.3, FLOOR_T + 1.5), "under ESP pin row", False)
    solid_probe(base, probe(ESP_X0 + ESP_X / 2, ESP_CY, FLOOR_T + 1), "ESP central rail", True)

    # Export
    meshes = {}
    for name, m in [("base", base), ("lid", lid)]:
        out = OUT_DIR / f"radar_enclosure_{name}.stl"
        mesh = m.to_mesh()
        write_stl(out, mesh)
        meshes[name] = mesh
        print(f"wrote {out}")

    # Preview: base and lid side by side, plus base top and side views
    def tris(mesh):
        return mesh.vert_properties[:, :3][mesh.tri_verts]
    bt, lt = tris(meshes["base"]), tris(meshes["lid"])
    fig = plt.figure(figsize=(16, 11))
    ax = fig.add_subplot(221, projection="3d")
    ax.add_collection3d(Poly3DCollection(bt, facecolor="#9aa", edgecolor="k", linewidth=0.05))
    ax.set_xlim(-6, 130); ax.set_ylim(-5, 55); ax.set_zlim(-3, 30)
    ax.set_box_aspect((125, 60, 33)); ax.view_init(25, -60); ax.set_title("base (assembled frame)")
    ax = fig.add_subplot(222, projection="3d")
    ax.add_collection3d(Poly3DCollection(lt, facecolor="#caa", edgecolor="k", linewidth=0.05))
    ax.set_xlim(-6, 130); ax.set_ylim(-55, 5); ax.set_zlim(0, 10)
    ax.set_box_aspect((125, 60, 10)); ax.view_init(25, -60); ax.set_title("lid (exported, plate on z=0)")
    for sub, cols, labels, title in [(223, [0, 1], ("x", "y"), "base top view"),
                                     (224, [0, 2], ("x", "z"), "base side view from -y")]:
        a = fig.add_subplot(sub)
        a.add_collection(PolyCollection(bt[:, :, cols], facecolor="#9aa", edgecolor="k", linewidth=0.1))
        a.set_xlim(-6, 130)
        if cols == [0, 1]:
            a.set_ylim(-6, 55)
        else:
            a.set_ylim(-4, 30)
        a.set_aspect("equal"); a.set_xlabel(labels[0]); a.set_ylabel(labels[1]); a.set_title(title)
    fig.savefig(PREVIEW, dpi=100, bbox_inches="tight")
    print(f"wrote {PREVIEW}")


if __name__ == "__main__":
    main()
