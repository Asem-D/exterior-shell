"""Geometry-based classification passes (v2.1 architecture).

Two passes run AFTER the type rules and BEFORE the AI fallback:

Tier 1 — slice-stack envelope: the building is sliced into elevation bands;
each band gets an envelope from the walls/slabs/curtain walls/roofs present at
that level (holes filled). An element is EXTERIOR if >= MIN_RIDE_FRAC of its
footprint rides the envelope boundary of any level it spans. Untrusted slices
(envelope < MIN_TRUST_FRAC of the building's max envelope) inherit from the
nearest trusted level, so sparse levels don't self-elect.

Tier 2 — face exposure: for elements Tier 1 rejected. At each slice center
strictly inside the element's z-span, build the "solid" union of wall and
curtain-wall footprints (plus door/window/opening footprints that seal voids
cut into walls) that exist at exactly that height. The outdoor region is the
component of (analysis rectangle minus outdoor-reference) touching the
rectangle corners, where the outdoor-reference is the wall union
supplemented by the inherited (effective) envelope from the nearest trusted
level.  A pure wall-union at untrusted slices is too thin to bound the
building (walls are sub-metre ribbons in XY), so rect.difference gives the
entire analysis rectangle as "outdoor" and every interior wall face ray
reaches it.  The inherited envelope anchors the separator to the actual
building footprint.  An element
is EXTERIOR if a ray cast outward from one of its faces (length EXPOSE_PROBE,
skipping end caps and wall-solid-blocked rays) reaches the outdoor region at
any such slice.  Everything uses strict z-containment and horizontal plates
are excluded from the solid: a thick transfer slab or roof plate that fills
a slice would otherwise declare every spanning element exposed.

Courtyard walls facing fully-enclosed lightwells still classify INTERIOR
(bounded region in plan); a future open-top rule may address that, but it
misfires on structure-only models without roofs, so it is intentionally absent.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from shapely.affinity import scale as shp_scale
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

from .models import Classification, ClassificationSource, Element, ElementType

logger = logging.getLogger(__name__)

# ── Thresholds (metres) ──────────────────────────────────────────────────────
SLICE_HEIGHT = 0.5      # elevation band height
RIDE_BAND = 0.5         # envelope boundary band width for the ride test
MIN_RIDE_FRAC = 0.25    # footprint fraction that must ride the envelope
MIN_TRUST_FRAC = 0.30   # slice envelope must be >= this share of max envelope
EXPOSE_PROBE = 0.6      # face ray length for the exposure test
MIN_FACE_LENGTH = 1.0   # edges shorter than this are end caps, not faces
RECT_MARGIN = 5.0       # analysis rectangle margin beyond the building bounds

# Element types re-judged by geometry (rules and AI become fallbacks for these)
GEOMETRY_JUDGED_TYPES: set[ElementType] = {
    ElementType.WALL,
    ElementType.WALL_STANDARD,
    ElementType.DOOR,
    ElementType.WINDOW,
    ElementType.WINDOW_CASE,
    ElementType.DOOR_CASE,
    ElementType.BUILDING_ELEMENT_PROXY,
    ElementType.COLUMN,
    ElementType.BEAM,
    ElementType.PLATE,
    ElementType.STAIR,
    ElementType.RAILING,
}

# Footprints that form the Tier 1 envelope of a slice.
ENVELOPE_SOURCE_TYPES: set[ElementType] = {
    ElementType.WALL,
    ElementType.WALL_STANDARD,
    ElementType.SLAB,
    ElementType.CURTAIN_WALL,
    ElementType.ROOF,
}

# Footprints unioned into the Tier 2 solid to seal voids cut into walls
# (openings) and leaf positions (doors/windows), so rooms stay bounded and
# cannot leak to the outdoor region through glazing or doorway cuts.
SOLID_FILL_TYPES: set[ElementType] = {
    ElementType.OPENING_ELEMENT,
    ElementType.DOOR,
    ElementType.WINDOW,
    ElementType.WINDOW_CASE,
    ElementType.DOOR_CASE,
}

# Wall-type footprints that form the Tier 2 exposure solid (strict slices).
# Horizontal plates (slabs, roofs) are deliberately excluded: a plate filling a
# slice would declare every spanning element exposed (see module docstring).
SOLID_WALL_TYPES: set[ElementType] = {
    ElementType.WALL,
    ElementType.WALL_STANDARD,
    ElementType.CURTAIN_WALL,
}

EXTERIOR_ENVELOPE = "EXTERIOR_ENVELOPE"
EXTERIOR_EXPOSURE = "EXTERIOR_EXPOSURE"
INTERIOR = "INTERIOR"


def _fill_holes(geom) -> Polygon | MultiPolygon:
    """Fill polygon holes so interior rooms don't create fake envelope edges."""
    polys = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    return unary_union([Polygon(p.exterior) for p in polys])


def _footprint(faces) -> Polygon | None:
    """Dissolve the XY projection of an element's triangles into a footprint."""
    tris = []
    for face in faces:
        p = Polygon(face.vertices[:, :2])
        if not p.is_valid:
            p = p.buffer(0)
        if p.area > 1e-9:
            tris.append(p)
    if not tris:
        return None
    union = unary_union(tris)
    if union.is_empty:
        return None
    union = union.simplify(0.01, preserve_topology=True)
    if not union.is_valid:
        union = union.buffer(0)
    return union


def _extract_feet(elements: list[Element]) -> dict[str, tuple[Polygon, float, float]]:
    """Map GlobalId -> (footprint, zlo, zhi) for every element with geometry."""
    feet: dict[str, tuple[Polygon, float, float]] = {}
    for e in elements:
        if not e.global_id or not e.faces or e.bbox_min is None or e.bbox_max is None:
            continue
        fp = _footprint(e.faces)
        if fp is None or fp.area <= 1e-6:
            continue
        feet[e.global_id] = (fp, float(e.bbox_min[2]), float(e.bbox_max[2]))

    # Unit guard: mm models are scaled to metres. A real building is < 1e6 m²
    # while the same building in mm² exceeds 1e8, so 1e6 splits them safely.
    if feet:
        total_area = unary_union([fp for fp, _, _ in feet.values()]).area
        if total_area > 1e6:
            feet = {
                gid: (
                    shp_scale(fp, 0.001, 0.001, origin=(0, 0, 0)),
                    zlo * 0.001,
                    zhi * 0.001,
                )
                for gid, (fp, zlo, zhi) in feet.items()
            }
            logger.info("Geometry pass: scaled mm coordinates to metres")
    return feet


def _spans_window(zlo: float, zhi: float, zc: float) -> bool:
    """Element overlaps the slice band [zc - h/2, zc + h/2]."""
    return zlo < zc + SLICE_HEIGHT / 2 and zhi > zc - SLICE_HEIGHT / 2


def _spans_strict(zlo: float, zhi: float, zc: float) -> bool:
    """Slice center lies inside the element's z-span (used for plates)."""
    return zlo <= zc <= zhi


def _face_rays(footprint: Polygon, probe: float) -> list[tuple[Point, LineString]]:
    """Rays cast outward from the footprint's long edges (its faces).

    Short edges (end caps) are skipped: a partition ending at a facade wall
    must not probe around the facade into the outdoor region. Each ray is a
    straight segment of length `probe` starting just off the edge; the caller
    discards rays whose segment is blocked by solid geometry.
    """
    coords: list[tuple[float, float]] = []
    parts = list(footprint.geoms) if isinstance(footprint, MultiPolygon) else [footprint]
    for part in parts:
        coords.extend(part.exterior.coords)
    rays: list[tuple[Point, LineString]] = []
    for (x0, y0), (x1, y1) in zip(coords[:-1], coords[1:]):
        if (x0, y0) == (x1, y1):  # junction between disjoint parts
            continue
        length = math.hypot(x1 - x0, y1 - y0)
        if length < MIN_FACE_LENGTH:
            continue
        nx, ny = -(y1 - y0) / length, (x1 - x0) / length
        for t in (0.25, 0.5, 0.75):
            mx, my = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            for sign in (1.0, -1.0):
                px, py = mx + sign * nx * probe, my + sign * ny * probe
                point = Point(px, py)
                if footprint.contains(point):
                    continue
                start = (mx + sign * nx * 0.02, my + sign * ny * 0.02)
                rays.append((point, LineString([start, (px, py)])))
    return rays


def classify_footprints(
    feet: dict[str, tuple[Polygon, float, float]],
    judged_ids: set[str],
    source_ids: set[str],
    wall_ids: set[str],
    fill_ids: set[str],
) -> dict[str, str]:
    """Classify judged elements from their footprints alone.

    Args:
        feet: GlobalId -> (footprint polygon, z_bottom, z_top) for all
            elements that participate in geometry classification (sources,
            fill and judged).
        judged_ids: GlobalIds to classify (candidates).
        source_ids: GlobalIds whose footprints form slice envelopes (Tier 1).
        wall_ids: Wall/curtain-wall GlobalIds forming the Tier 2 solid.
        fill_ids: Openings/doors/windows sealing wall projection holes (their
            cuts punch through the XY projection at every slice, so the fill
            footprints are unioned into overlapping walls up front).

    Returns:
        GlobalId -> verdict, one of EXTERIOR_ENVELOPE (Tier 1: rides the
        envelope), EXTERIOR_EXPOSURE (Tier 2: a face reaches outdoor space)
        or INTERIOR.
    """
    if not feet or not judged_ids:
        return {}

    zmin = min(zlo for _, zlo, _ in feet.values())
    zmax = max(zhi for _, _, zhi in feet.values())
    slices = [round(float(z), 3) for z in np.arange(zmin + SLICE_HEIGHT / 2, zmax, SLICE_HEIGHT)]
    bounds = unary_union([fp for fp, _, _ in feet.values()]).bounds
    rect = Polygon(
        [
            (bounds[0] - RECT_MARGIN, bounds[1] - RECT_MARGIN),
            (bounds[2] + RECT_MARGIN, bounds[1] - RECT_MARGIN),
            (bounds[2] + RECT_MARGIN, bounds[3] + RECT_MARGIN),
            (bounds[0] - RECT_MARGIN, bounds[3] + RECT_MARGIN),
        ]
    )
    corners = [Point(x, y) for x, y in rect.exterior.coords[:4]]

    # Seal wall projection holes: openings, doors and windows cut wall solid
    # geometry, so the XY projection keeps those holes at every slice even
    # where the wall is physically solid (above a window head, for example).
    # Union the fill footprints into overlapping walls once, up front; slight
    # over-sealing at the cut slices is harmless for exposure verdicts.
    if fill_ids:
        sealed = dict(feet)
        for fid in fill_ids:
            fill = feet.get(fid)
            if fill is None:
                continue
            for wid in wall_ids:
                wall = sealed.get(wid)
                if wall is None or not fill[0].intersects(wall[0]):
                    continue
                sealed[wid] = (
                    unary_union([wall[0], fill[0]]),
                    wall[1],
                    wall[2],
                )
        feet = sealed

    def window_sources_at(zc: float, ids: set[str]) -> list[Polygon]:
        """Sources overlapping the slice band (Tier 1 envelope)."""
        return [
            feet[gid][0]
            for gid in ids
            if gid in feet and _spans_window(feet[gid][1], feet[gid][2], zc)
        ]

    def strict_sources_at(zc: float, ids: set[str]) -> list[Polygon]:
        """Sources whose z-span contains the slice center (Tier 2 solid)."""
        return [
            feet[gid][0]
            for gid in ids
            if gid in feet and _spans_strict(feet[gid][1], feet[gid][2], zc)
        ]

    # ── Tier 1: slice envelopes with trust inheritance ───────────────────
    raw: dict[float, tuple[object, float]] = {}
    for zc in slices:
        src = window_sources_at(zc, source_ids)
        if src:
            env = _fill_holes(unary_union(src))
            raw[zc] = (env, env.area)
        else:
            raw[zc] = (None, 0.0)
    max_area = max((area for _, area in raw.values()), default=0.0)
    if max_area <= 0:
        return {}

    trusted = {
        zc: (env if env is not None and area >= MIN_TRUST_FRAC * max_area else None)
        for zc, (env, area) in raw.items()
    }
    effective: dict[float, object] = {}
    for zc in slices:
        if trusted[zc] is not None:
            effective[zc] = trusted[zc]
            continue
        env = None
        for d in np.arange(SLICE_HEIGHT, zmax - zmin + SLICE_HEIGHT, SLICE_HEIGHT):
            for cand in (round(zc - float(d), 3), round(zc + float(d), 3)):
                if cand in trusted and trusted[cand] is not None:
                    env = trusted[cand]
                    break
            if env is not None:
                break
        effective[zc] = env

    verdicts: dict[str, str] = {}
    pending: list[str] = []
    for gid in judged_ids:
        entry = feet.get(gid)
        if entry is None:
            continue
        fp, zlo, zhi = entry
        best = 0.0
        for zc in slices:
            if not _spans_window(zlo, zhi, zc):
                continue
            env = effective.get(zc)
            if env is None:
                continue
            frac = fp.intersection(env.boundary.buffer(RIDE_BAND)).area / fp.area
            best = max(best, frac)
        if best >= MIN_RIDE_FRAC:
            verdicts[gid] = EXTERIOR_ENVELOPE
        else:
            verdicts[gid] = INTERIOR
            pending.append(gid)

    if not pending:
        return verdicts

    # ── Tier 2: face exposure against the outdoor region ─────────────────
    solid_cache: dict[float, tuple[object, object]] = {}

    def solid_and_outdoor(zc: float):
        if zc in solid_cache:
            return solid_cache[zc]
        parts = strict_sources_at(zc, wall_ids)
        if not parts:
            solid_cache[zc] = (None, None)
            return solid_cache[zc]
        # Wall-only solid for ray blocking: keeps the original behaviour
        # where a wall face ray must clear neighbouring wall geometry.
        solid = unary_union(parts)
        # Outdoor region separator: at trusted slices the local envelope
        # provides a clean indoor/outdoor boundary.  At untrusted slices
        # (no slab or curtain wall at this elevation), the raw wall-union
        # alone is too thin (sub-metre ribbons in XY) to partition the
        # plane: rect.difference gives the entire rectangle as "outdoor"
        # and every interior wall face ray reaches it.  Buffering by a
        # small margin closes gaps between wall segments that form a
        # perimeter, producing a filled ring whose interior is "indoor".
        # Where walls don't form a closed perimeter (e.g. a few walls on
        # a roof slab), the buffered union stays open and the outdoor
        # region correctly includes the unenclosed space.
        env = trusted.get(zc)
        if env is not None:
            outdoor_ref = unary_union(parts + [env])
        else:
            # At untrusted slices the wall ribbon is too thin to
            # bound the building; check if the solid's convex hull
            # covers a meaningful fraction of the inherited envelope.
            # If not (sparse walls, e.g. a single rear wall), the
            # buffer approach inflates the outdoor region across the
            # entire rectangle, falsely exposing interior elements.
            # Use the inherited envelope to anchor the indoor side.
            eff = effective.get(zc)
            if eff is not None and solid.area > 0:
                hull_ratio = solid.convex_hull.area / eff.area
                if hull_ratio < 0.25:
                    outdoor_ref = unary_union(parts + [eff])
                else:
                    outdoor_ref = solid.buffer(0.15)
            else:
                outdoor_ref = solid.buffer(0.15)
        comp = rect.difference(outdoor_ref)
        comps = list(comp.geoms) if isinstance(comp, MultiPolygon) else [comp]
        outdoor = unary_union(
            [p for p in comps if any(p.intersects(c) for c in corners)]
        )
        solid_cache[zc] = (solid, outdoor)
        return solid_cache[zc]

    for gid in pending:
        fp, zlo, zhi = feet[gid]
        rays = _face_rays(fp, EXPOSE_PROBE)
        if not rays:
            continue
        for zc in slices:
            if not _spans_strict(zlo, zhi, zc):
                continue
            solid, outdoor = solid_and_outdoor(zc)
            if solid is None or outdoor is None or outdoor.is_empty:
                continue
            for point, ray in rays:
                if solid.intersects(ray):
                    continue  # face blocked by neighbouring solid geometry
                if outdoor.contains(point):
                    verdicts[gid] = EXTERIOR_EXPOSURE
                    break
            else:
                continue
            break

    exposed = sum(1 for v in verdicts.values() if v == EXTERIOR_EXPOSURE)
    logger.info(
        "Geometry pass: %d envelope-exterior, %d exposure-exterior, %d interior",
        sum(1 for v in verdicts.values() if v == EXTERIOR_ENVELOPE),
        exposed,
        sum(1 for v in verdicts.values() if v == INTERIOR),
    )
    return verdicts


def apply_geometry_classification(elements: list[Element]) -> dict[str, int]:
    """Run both geometry passes and mutate candidate elements in place.

    Elements without a geometry verdict keep their existing classification
    (rule-based, later AI) so the passes stay pure overrides, not replacements.
    """
    judged = [
        e for e in elements
        if e.element_type in GEOMETRY_JUDGED_TYPES and e.faces and e.global_id
    ]
    stats = {
        "judged": len(judged),
        "envelope_exterior": 0,
        "exposure_exterior": 0,
        "geometry_interior": 0,
    }
    if not judged:
        return stats

    feet = _extract_feet(elements)
    source_ids = {
        e.global_id for e in elements if e.element_type in ENVELOPE_SOURCE_TYPES
    }
    wall_ids = {
        e.global_id for e in elements if e.element_type in SOLID_WALL_TYPES
    }
    fill_ids = {
        e.global_id for e in elements if e.element_type in SOLID_FILL_TYPES
    }
    verdicts = classify_footprints(
        feet, {e.global_id for e in judged}, source_ids, wall_ids, fill_ids
    )

    by_gid = {e.global_id: e for e in judged}
    for gid, verdict in verdicts.items():
        element = by_gid.get(gid)
        if element is None:
            continue
        if verdict == INTERIOR:
            element.classification = Classification.INTERIOR
            element.classification_source = ClassificationSource.RULE_BASED
            element.confidence = 0.9
            stats["geometry_interior"] += 1
        else:
            element.classification = Classification.EXTERIOR
            element.classification_source = ClassificationSource.RULE_BASED
            element.confidence = 0.9
            if verdict == EXTERIOR_ENVELOPE:
                stats["envelope_exterior"] += 1
            else:
                stats["exposure_exterior"] += 1
    return stats
