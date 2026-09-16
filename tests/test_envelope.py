"""Tests for the geometry classification passes (slice-stack + exposure)."""

from shapely.affinity import scale as shp_scale
from shapely.geometry import box

from exterior_shell.core.envelope import (
    EXTERIOR_ENVELOPE,
    EXTERIOR_EXPOSURE,
    INTERIOR,
    classify_footprints,
)


def _two_storey_feet():
    """Demo-like building: mid-plan level-2 walls standing on the roof slab."""
    return {
        "slab1": (box(0, 0, 10, 10), -0.3, 0.0),
        "slab2": (box(0, 0, 10, 10), 3.55, 3.65),
        "w_s": (box(0, 0, 10, 0.2), 0.0, 3.3),
        "w_n": (box(0, 9.8, 10, 10), 0.0, 3.3),
        "w_w": (box(0, 0, 0.2, 10), 0.0, 3.3),
        "w_e": (box(9.8, 0, 10, 10), 0.0, 3.3),
        "part1": (box(4.9, 0.2, 5.1, 9.8), 0.0, 3.3),
        "w2_edge": (box(0, 9.8, 10, 10), 3.6, 7.2),
        "w2_a": (box(2.0, 4.0, 6.0, 4.2), 3.6, 7.2),
        "w2_b": (box(6.0, 4.2, 6.2, 8.0), 3.6, 7.2),
    }


SOURCES = {"slab1", "slab2", "w_s", "w_n", "w_w", "w_e", "w2_edge", "w2_a", "w2_b"}
WALLS = {"w_s", "w_n", "w_w", "w_e", "w2_edge", "w2_a", "w2_b"}
JUDGED = WALLS | {"part1"}


def test_roof_walls_exposed_via_tier2():
    """Mid-plan level-2 walls on the roof slab are EXTERIOR, partition is not."""
    verdicts = classify_footprints(_two_storey_feet(), JUDGED, SOURCES, WALLS, set())
    assert verdicts["w2_a"] == EXTERIOR_EXPOSURE
    assert verdicts["w2_b"] == EXTERIOR_EXPOSURE
    assert verdicts["w2_edge"] == EXTERIOR_ENVELOPE
    assert verdicts["part1"] == INTERIOR
    assert verdicts["w_s"].startswith("EXTERIOR")
    assert verdicts["w_n"].startswith("EXTERIOR")


def test_skybridge_rides_slice_envelope():
    """A skybridge between two towers rides its own slice envelope."""
    feet = {}
    for i, x0 in enumerate((0.0, 15.0)):
        feet[f"tw_s{i}"] = (box(x0, 0, x0 + 5, 0.2), 0.0, 30.0)
        feet[f"tw_n{i}"] = (box(x0, 4.8, x0 + 5, 5.0), 0.0, 30.0)
        feet[f"tw_w{i}"] = (box(x0, 0, x0 + 0.2, 5.0), 0.0, 30.0)
        feet[f"tw_e{i}"] = (box(x0 + 4.8, 0, x0 + 5, 5.0), 0.0, 30.0)
    feet["bridge"] = (box(5.0, 2.4, 15.0, 2.6), 20.0, 21.0)
    towers = {gid for gid in feet if gid.startswith("tw_")}
    verdicts = classify_footprints(
        feet, towers | {"bridge"}, towers | {"bridge"}, towers | {"bridge"}, set()
    )
    assert verdicts["bridge"] == EXTERIOR_ENVELOPE


def test_opening_seal_keeps_partition_interior():
    """A window cut sealed by its opening keeps the room (and partition) interior."""
    feet = {
        "slab1": (box(0, 0, 10, 10), -0.3, 0.0),
        "w_s": (box(0, 0, 10, 0.2), 0.0, 3.3),
        "w_n1": (box(0, 9.8, 4.5, 10), 0.0, 3.3),
        "w_n2": (box(5.5, 9.8, 10, 10), 0.0, 3.3),
        "w_w": (box(0, 0, 0.2, 10), 0.0, 3.3),
        "w_e": (box(9.8, 0, 10, 10), 0.0, 3.3),
        "part1": (box(4.9, 0.2, 5.1, 9.8), 0.0, 3.3),
        "op": (box(4.5, 9.8, 5.5, 10), 0.9, 2.1),
    }
    sources = {"slab1", "w_s", "w_n1", "w_n2", "w_w", "w_e"}
    walls = {"w_s", "w_n1", "w_n2", "w_w", "w_e"}
    judged = walls | {"part1"}
    sealed = classify_footprints(feet, judged, sources, walls, {"op"})
    assert sealed["part1"] == INTERIOR
    # Without the seal the room leaks to the outdoor region: documented
    # behavior, exposure passes need a closed perimeter.
    leaky = classify_footprints(feet, judged, sources, walls, set())
    assert leaky["part1"] == EXTERIOR_EXPOSURE


def test_roof_plate_does_not_poison_top_slices():
    """A full-height partition under a roof plate stays interior."""
    feet = {
        "slab1": (box(0, 0, 10, 10), -0.3, 0.0),
        "roof": (box(0, 0, 10, 10), 7.2, 7.3),
        "w_s": (box(0, 0, 10, 0.2), 0.0, 7.2),
        "w_n": (box(0, 9.8, 10, 10), 0.0, 7.2),
        "w_w": (box(0, 0, 0.2, 10), 0.0, 7.2),
        "w_e": (box(9.8, 0, 10, 10), 0.0, 7.2),
        "part": (box(4.9, 0.2, 5.1, 9.8), 0.0, 7.2),
    }
    sources = {"slab1", "roof", "w_s", "w_n", "w_w", "w_e"}
    walls = {"w_s", "w_n", "w_w", "w_e"}
    verdicts = classify_footprints(feet, walls | {"part"}, sources, walls, set())
    assert verdicts["part"] == INTERIOR
    assert verdicts["w_s"].startswith("EXTERIOR")


def test_mm_units_are_scaled_to_metres():
    """Millimetre models get scaled before slicing and classify identically."""
    feet = {
        gid: (
            shp_scale(fp, 1000, 1000, origin=(0, 0, 0)),
            zlo * 1000,
            zhi * 1000,
        )
        for gid, (fp, zlo, zhi) in _two_storey_feet().items()
    }
    verdicts = classify_footprints(feet, JUDGED, SOURCES, WALLS, set())
    assert verdicts["part1"] == INTERIOR
    assert verdicts["w2_a"] == EXTERIOR_EXPOSURE
