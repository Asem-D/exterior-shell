"""Geometry simplifier — merge coplanar faces and filter tiny triangles."""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from .models import Face

logger = logging.getLogger(__name__)


def _face_area_3d(face: Face) -> float:
    """Area of a triangular face in 3D."""
    edge1 = face.vertices[1] - face.vertices[0]
    edge2 = face.vertices[2] - face.vertices[0]
    return 0.5 * float(np.linalg.norm(np.cross(edge1, edge2)))


def _normals_parallel(n1: np.ndarray, n2: np.ndarray, threshold: float = 0.01) -> bool:
    """Check if two unit normals are approximately parallel (or anti-parallel)."""
    return abs(float(np.dot(n1, n2))) > (1.0 - threshold)


def _share_edge(f1: Face, f2: Face, tol: float = 1e-6) -> bool:
    """Check if two faces share at least one edge (two common vertices)."""
    shared = 0
    for v1 in f1.vertices:
        for v2 in f2.vertices:
            if np.linalg.norm(v1 - v2) < tol:
                shared += 1
                if shared >= 2:
                    return True
    return False


def filter_tiny_faces(faces: list[Face], min_area: float = 1e-6) -> list[Face]:
    """Remove degenerate or tiny faces below an area threshold.

    Args:
        faces: Input faces.
        min_area: Minimum face area to keep (in model units squared).

    Returns:
        Filtered list of faces.
    """
    if not faces or min_area <= 0:
        return faces

    original = len(faces)
    result = [f for f in faces if _face_area_3d(f) >= min_area]
    removed = original - len(result)
    if removed:
        logger.info(f"Filtered {removed} tiny faces (area < {min_area})")
    return result


def merge_coplanar_faces(
    faces: list[Face],
    angle_threshold: float = 0.01,
) -> list[Face]:
    """Merge adjacent coplanar triangles into larger polygon faces.

    Groups faces by approximate normal direction and adjacency, then merges
    each group into a single polygon. Returns triangulated faces from the
    merged polygon boundary.

    Args:
        faces: Input triangulated faces.
        angle_threshold: Max angle deviation (dot product) for coplanarity.

    Returns:
        Simplified list of faces (re-triangulated from merged polygons).
    """
    if len(faces) <= 1:
        return faces

    # Build adjacency groups via union-find on coplanar + adjacent pairs
    parent = list(range(len(faces)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Group faces that are coplanar and share an edge
    for i in range(len(faces)):
        for j in range(i + 1, len(faces)):
            if find(i) != find(j):
                if (
                    _normals_parallel(faces[i].normal, faces[j].normal, angle_threshold)
                    and _share_edge(faces[i], faces[j])
                ):
                    union(i, j)

    # Collect groups
    groups: dict[int, list[int]] = {}
    for i in range(len(faces)):
        root = find(i)
        groups.setdefault(root, []).append(i)

    # If no merging happened, return original
    if all(len(g) == 1 for g in groups.values()):
        logger.info("No coplanar groups found to merge")
        return faces

    # Merge each group into a single polygon
    merged_faces: list[Face] = []
    total_merged = 0

    for root, indices in groups.items():
        group_faces = [faces[i] for i in indices]

        if len(group_faces) == 1:
            merged_faces.append(group_faces[0])
            continue

        # Project coplanar triangles to 2D, merge, then reconstruct 3D
        polygons_2d, transform_info = _project_to_2d(group_faces)
        if polygons_2d is None:
            merged_faces.extend(group_faces)
            continue

        try:
            merged_2d = unary_union(polygons_2d)
            new_faces = _unproject_to_3d(merged_2d, transform_info)
            # Only use the merged result if it's smaller or equal
            if len(new_faces) <= len(group_faces):
                merged_faces.extend(new_faces)
                total_merged += len(group_faces) - len(new_faces)
            else:
                # Fan triangulation produced more faces; keep originals
                merged_faces.extend(group_faces)
        except Exception:
            merged_faces.extend(group_faces)

    if total_merged > 0:
        logger.info(
            f"Merged coplanar faces: {len(faces)} -> {len(merged_faces)} "
            f"({total_merged} triangles absorbed)"
        )

    return merged_faces


def _project_to_2d(faces: list[Face]):
    """Project coplanar faces to a 2D plane for merging.

    Uses the face normal to define a projection plane. Stores the
    origin point on the plane so we can reverse the projection exactly.
    """
    avg_normal = faces[0].normal.copy()
    avg_normal = avg_normal / np.linalg.norm(avg_normal)

    # Build an orthonormal basis on the plane
    if abs(avg_normal[0]) < 0.9:
        arbitrary = np.array([1.0, 0.0, 0.0])
    else:
        arbitrary = np.array([0.0, 1.0, 0.0])

    u = np.cross(avg_normal, arbitrary)
    u = u / np.linalg.norm(u)
    v = np.cross(avg_normal, u)
    v = v / np.linalg.norm(v)

    # Compute the plane origin: project the centroid of all vertices
    # onto the plane along the normal direction.
    all_verts = np.vstack([f.vertices for f in faces])
    centroid_3d = all_verts.mean(axis=0)
    # The origin is the closest point on the plane to the centroid
    # d = dot(centroid, normal) -- plane constant
    d = float(np.dot(centroid_3d, avg_normal))
    origin_3d = d * avg_normal  # Point on plane closest to origin

    # Project all face vertices to 2D
    polygons_2d = []
    for face in faces:
        pts_2d = []
        for vert in face.vertices:
            # Subtract origin to get vector from plane origin, then project
            relative = vert - origin_3d
            x = float(np.dot(relative, u))
            y = float(np.dot(relative, v))
            pts_2d.append((x, y))
        # Close ring
        if pts_2d[0] != pts_2d[-1]:
            pts_2d.append(pts_2d[0])
        try:
            poly = Polygon(pts_2d)
            if poly.is_valid and not poly.is_empty:
                polygons_2d.append(poly)
        except Exception:
            continue

    if not polygons_2d:
        return None, None

    transform_info = {"u": u, "v": v, "normal": avg_normal, "origin_3d": origin_3d}
    return polygons_2d, transform_info


def _unproject_to_3d(
    merged_2d,
    transform_info: dict,
) -> list[Face]:
    """Convert merged 2D polygon(s) back to 3D triangular faces."""
    u = transform_info["u"]
    v = transform_info["v"]
    n = transform_info["normal"]
    origin_3d = transform_info["origin_3d"]

    result_faces = []

    geom_type = merged_2d.geom_type
    if geom_type == "Polygon":
        polygons = [merged_2d]
    elif geom_type == "MultiPolygon":
        polygons = list(merged_2d.geoms)
    else:
        return []

    for poly in polygons:
        coords = list(poly.exterior.coords[:-1])  # Remove closure
        if len(coords) < 3:
            continue

        # Reconstruct 3D points: 3d = origin_3d + x * u + y * v
        pts_3d = []
        for cx, cy in coords:
            pt_3d = origin_3d + cx * u + cy * v
            pts_3d.append(pt_3d)

        # Fan triangulation from vertex 0
        for i in range(1, len(pts_3d) - 1):
            triangle = np.array([pts_3d[0], pts_3d[i], pts_3d[i + 1]])
            edge1 = triangle[1] - triangle[0]
            edge2 = triangle[2] - triangle[0]
            tri_normal = np.cross(edge1, edge2)
            norm_len = np.linalg.norm(tri_normal)
            if norm_len > 1e-10:
                tri_normal = tri_normal / norm_len
            else:
                tri_normal = n.copy()

            result_faces.append(Face(vertices=triangle, normal=tri_normal))

    return result_faces


def simplify_shell(
    faces: list[Face],
    min_area: float = 1e-6,
    angle_threshold: float = 0.01,
    merge: bool = True,
) -> list[Face]:
    """Full simplification pipeline: filter then merge.

    Args:
        faces: Input triangulated faces.
        min_area: Minimum face area to keep.
        angle_threshold: Coplanarity threshold for merging.
        merge: Whether to merge coplanar faces.

    Returns:
        Simplified face list.
    """
    if not faces:
        return faces

    result = filter_tiny_faces(faces, min_area)

    if merge and len(result) > 1:
        result = merge_coplanar_faces(result, angle_threshold)

    return result
