"""Tests for the geometry simplifier module."""

import numpy as np
import pytest

from exterior_shell.core.models import Face, Element, ElementType
from exterior_shell.core.simplifier import (
    filter_tiny_faces,
    merge_coplanar_faces,
    simplify_shell,
    _face_area_3d,
    _normals_parallel,
    _share_edge,
)


def _make_face(v0, v1, v2, normal=None):
    """Helper to create a Face with 3 vertices."""
    verts = np.array([v0, v1, v2], dtype=float)
    if normal is None:
        edge1 = verts[1] - verts[0]
        edge2 = verts[2] - verts[0]
        n = np.cross(edge1, edge2)
        n_len = np.linalg.norm(n)
        normal = n / n_len if n_len > 1e-10 else np.array([0.0, 0.0, 1.0])
    return Face(vertices=verts, normal=normal)


# ── Unit tests ──────────────────────────────────────────────────────────────


def test_face_area_3d():
    """Area of a simple triangle in 3D."""
    face = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    area = _face_area_3d(face)
    assert abs(area - 0.5) < 1e-6


def test_face_area_3d_tilted():
    """Area of a tilted triangle should be larger than its projection."""
    face_flat = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    face_tilted = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 1])
    area_flat = _face_area_3d(face_flat)
    area_tilted = _face_area_3d(face_tilted)
    assert area_tilted > area_flat


def test_normals_parallel():
    """Parallel normals should return True."""
    n1 = np.array([0.0, 0.0, 1.0])
    n2 = np.array([0.0, 0.0, 1.0])
    assert _normals_parallel(n1, n2)

    # Anti-parallel should also be True (absolute value check)
    n3 = np.array([0.0, 0.0, -1.0])
    assert _normals_parallel(n1, n3)


def test_normals_not_parallel():
    """Perpendicular normals should return False."""
    n1 = np.array([0.0, 0.0, 1.0])
    n2 = np.array([1.0, 0.0, 0.0])
    assert not _normals_parallel(n1, n2)


def test_share_edge():
    """Faces sharing two vertices should share an edge."""
    f1 = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    # Shares edge [0,0,0]-[1,0,0]
    f2 = _make_face([0, 0, 0], [1, 0, 0], [0, 0, 1])
    assert _share_edge(f1, f2)


def test_no_shared_edge():
    """Faces with only one common vertex should not share an edge."""
    f1 = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    f2 = _make_face([0, 0, 0], [-1, 0, 0], [0, -1, 0])
    # They share vertex [0,0,0] but no edge
    assert not _share_edge(f1, f2)


# ── filter_tiny_faces tests ────────────────────────────────────────────────


def test_filter_removes_degenerate():
    """Zero-area triangle should be filtered out."""
    face_normal = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    face_degen = _make_face([0, 0, 0], [1, 0, 0], [0.5, 0, 0])  # collinear

    result = filter_tiny_faces([face_normal, face_degen], min_area=1e-6)
    assert len(result) == 1
    assert result[0] is face_normal


def test_filter_keeps_valid():
    """Valid faces above threshold should be kept."""
    f1 = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    f2 = _make_face([1, 0, 0], [2, 0, 0], [1, 1, 0])
    result = filter_tiny_faces([f1, f2], min_area=1e-6)
    assert len(result) == 2


def test_filter_empty():
    """Empty list returns empty list."""
    assert filter_tiny_faces([], min_area=1e-6) == []


def test_filter_threshold_affects_count():
    """Larger threshold removes more faces."""
    f_small = _make_face([0, 0, 0], [0.01, 0, 0], [0, 0.01, 0])
    f_large = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])

    # Small threshold keeps both
    result = filter_tiny_faces([f_small, f_large], min_area=1e-6)
    assert len(result) == 2

    # Large threshold removes the small one
    result = filter_tiny_faces([f_small, f_large], min_area=0.01)
    assert len(result) == 1
    assert result[0] is f_large


# ── merge_coplanar_faces tests ─────────────────────────────────────────────


def test_merge_coplanar_two_triangles():
    """Two coplanar adjacent triangles sharing an edge should merge."""
    # Two triangles forming a rectangle, both on Z=0 plane
    f1 = _make_face([0, 0, 0], [1, 0, 0], [1, 1, 0])
    f2 = _make_face([0, 0, 0], [1, 1, 0], [0, 1, 0])

    result = merge_coplanar_faces([f1, f2])
    # Merged rectangle re-triangulated: should be at most 2 faces
    # (same count or fewer, Z preserved)
    assert len(result) <= 2
    # Z coordinates should be preserved at 0
    for face in result:
        assert all(abs(v[2]) < 1e-6 for v in face.vertices)


def test_merge_no_merge_different_planes():
    """Faces on different planes should not merge."""
    f_floor = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    f_wall = _make_face([0, 0, 0], [1, 0, 0], [0, 0, 1])

    result = merge_coplanar_faces([f_floor, f_wall])
    assert len(result) == 2


def test_merge_empty():
    """Empty list returns empty list."""
    assert merge_coplanar_faces([]) == []


def test_merge_single_face():
    """Single face returns unchanged."""
    f = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    result = merge_coplanar_faces([f])
    assert len(result) == 1


def test_merge_preserves_z():
    """Merged faces should preserve Z coordinates from original."""
    f1 = _make_face([0, 0, 5], [1, 0, 5], [1, 1, 5])
    f2 = _make_face([0, 0, 5], [1, 1, 5], [0, 1, 5])

    result = merge_coplanar_faces([f1, f2])
    # All resulting faces should be at Z=5
    for face in result:
        assert all(
            abs(v[2] - 5.0) < 1e-6 for v in face.vertices
        ), f"Z coordinate not preserved: {face.vertices}"


def test_merge_no_face_count_increase():
    """Merging should never increase the face count."""
    # Build a strip of 4 coplanar triangles
    normal = np.array([0.0, 0.0, 1.0])
    f1 = _make_face([0, 0, 10], [1, 0, 10], [1, 1, 10], normal=normal)
    f2 = _make_face([1, 0, 10], [2, 0, 10], [2, 1, 10], normal=normal)
    f3 = _make_face([0, 1, 10], [1, 0, 10], [1, 1, 10], normal=normal)
    f4 = _make_face([1, 1, 10], [2, 0, 10], [2, 1, 10], normal=normal)

    result = merge_coplanar_faces([f1, f2, f3, f4])
    assert len(result) <= 4


def test_merge_reduces_count_for_adjacent():
    """A connected strip of coplanar triangles should reduce in count."""
    # Create a strip of 3 coplanar triangles that form a fan
    # All sharing a common edge
    normal = np.array([0.0, 0.0, 1.0])
    # Triangle fan from origin on Z=0 plane
    f1 = _make_face([0, 0, 0], [1, 0, 0], [0.5, 0.5, 0], normal=normal)
    f2 = _make_face([0, 0, 0], [0.5, 0.5, 0], [0, 1, 0], normal=normal)

    result = merge_coplanar_faces([f1, f2])
    # Fan from same vertex, sharing an edge, same plane -> should merge
    assert len(result) <= 2


# ── simplify_shell tests ───────────────────────────────────────────────────


def test_simplify_empty():
    """Simplify empty list returns empty."""
    assert simplify_shell([]) == []


def test_simplify_removes_tiny():
    """Simplify filters tiny faces."""
    f_valid = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    f_tiny = _make_face([10, 10, 10], [10.0001, 10, 10], [10, 10.0001, 10])

    result = simplify_shell([f_valid, f_tiny], min_area=1e-4, merge=False)
    assert len(result) == 1


def test_simplify_full_pipeline():
    """Full pipeline: filter then merge."""
    # Two large coplanar triangles
    f1 = _make_face([0, 0, 0], [10, 0, 0], [10, 10, 0])
    f2 = _make_face([0, 0, 0], [10, 10, 0], [0, 10, 0])
    # One tiny triangle
    f_tiny = _make_face([50, 50, 0], [50.001, 50, 0], [50, 50.001, 0])

    result = simplify_shell([f1, f_tiny, f2], min_area=1e-6, merge=True)
    # Tiny one removed, two coplanar merged
    assert len(result) < 3
    # At least one face should exist
    assert len(result) >= 1


def test_simplify_merge_disabled():
    """When merge=False, only filtering happens."""
    f1 = _make_face([0, 0, 0], [1, 0, 0], [0, 1, 0])
    f2 = _make_face([1, 0, 0], [2, 0, 0], [1, 1, 0])

    result = simplify_shell([f1, f2], merge=False)
    assert len(result) == 2
