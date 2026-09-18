"""Regression test: single-rear-wall misclassification bug.

The bug: at slices above the ground floor where only a rear wall exists
(and no other exterior walls), the Tier 2 outdoor reference falls back to
solid.buffer(0.15).  Because the rear wall alone is a thin ribbon, the
buffered union doesn't bound the building footprint, so the outdoor region
swallows almost the entire analysis rectangle.  Interior partitions at those
slices then get their face rays reaching "outdoor" and are falsely classified
as EXTERIOR_EXPOSURE.

The fix: at untrusted slices where the effective envelope was inherited from
a trusted neighbour, use that inherited envelope as the outdoor-reference
separator (combined with local wall solids) instead of the thin wall buffer.
"""

from shapely.geometry import box

from exterior_shell.core.envelope import (
    EXTERIOR_ENVELOPE,
    EXTERIOR_EXPOSURE,
    INTERIOR,
    classify_footprints,
)


def test_partition_stays_interior_above_rear_wall():
    """Building: full perimeter on ground floor, only rear wall above.

    Ground floor (z=0..3): 4 walls (N,S,E,W) + slab
    Upper floor  (z=3..6): only rear wall (N)
    Partition spans upper floor only (z=3..6), in the middle of the plan.

    The partition must be INTERIOR: it sits inside the building envelope
    inherited from the trusted ground-floor slices.
    """
    feet = {
        "slab":   (box(0, 0, 10, 10),  -0.3, 0.0),
        "w_n":    (box(0, 9.8, 10, 10), 0.0, 3.0),
        "w_s":    (box(0, 0, 10, 0.2),   0.0, 3.0),
        "w_e":    (box(9.8, 0, 10, 10),  0.0, 3.0),
        "w_w":    (box(0, 0, 0.2, 10),   0.0, 3.0),
        # Rear wall: only exterior wall on upper floor
        "w_rear": (box(0, 9.8, 10, 10), 3.0, 6.0),
        # Interior partition: middle of plan, upper floor only
        "part":   (box(4.9, 0.2, 5.1, 9.8), 3.0, 6.0),
    }
    sources = {"slab", "w_n", "w_s", "w_e", "w_w", "w_rear"}
    walls = {"w_n", "w_s", "w_e", "w_w", "w_rear"}
    judged = walls | {"part"}
    verdicts = classify_footprints(feet, judged, sources, walls, set())

    # Rear wall rides the inherited envelope boundary -> exterior
    assert verdicts["w_rear"] == EXTERIOR_ENVELOPE
    # Partition is inside the building envelope -> interior
    assert verdicts["part"] == INTERIOR


def test_partition_stays_interior_no_upper_walls():
    """Building: full perimeter on ground floor, no walls above.

    Ground floor (z=0..3): 4 walls + slab
    Upper floor  (z=3..6): no walls at all, only an interior partition

    The partition must be INTERIOR.
    """
    feet = {
        "slab": (box(0, 0, 10, 10), -0.3, 0.0),
        "w_n":  (box(0, 9.8, 10, 10), 0.0, 3.0),
        "w_s":  (box(0, 0, 10, 0.2),  0.0, 3.0),
        "w_e":  (box(9.8, 0, 10, 10), 0.0, 3.0),
        "w_w":  (box(0, 0, 0.2, 10),  0.0, 3.0),
        # Partition on upper floor, middle of plan
        "part": (box(4.9, 0.2, 5.1, 9.8), 3.0, 6.0),
    }
    sources = {"slab", "w_n", "w_s", "w_e", "w_w"}
    walls = {"w_n", "w_s", "w_e", "w_w"}
    judged = walls | {"part"}
    verdicts = classify_footprints(feet, judged, sources, walls, set())

    assert verdicts["part"] == INTERIOR
