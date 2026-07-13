"""Geometry assembler — combines exterior elements into a multipatch shell."""

from __future__ import annotations

import logging

import numpy as np

from .models import Classification, Element, Face, ShellGeometry

logger = logging.getLogger(__name__)


def _face_area(face: Face) -> float:
    """Calculate area of a triangular face."""
    edge1 = face.vertices[1] - face.vertices[0]
    edge2 = face.vertices[2] - face.vertices[0]
    return 0.5 * float(np.linalg.norm(np.cross(edge1, edge2)))


def _are_faces_coplanar(f1: Face, f2: Face, angle_threshold: float = 0.01) -> bool:
    """Check if two faces are roughly coplanar and adjacent."""
    # Check if normals are approximately parallel
    dot = abs(float(np.dot(f1.normal, f2.normal)))
    if dot < (1.0 - angle_threshold):
        return False

    # Check if they share an edge (vertices within tolerance)
    tol = 1e-6
    for v1 in f1.vertices:
        for v2 in f2.vertices:
            if np.linalg.norm(v1 - v2) < tol:
                return True
    return False


def _face_is_backward(f: Face, shell_centroid: np.ndarray) -> bool:
    """Check if a face is pointing inward (toward the shell centroid).

    A face pointing toward the centroid is likely an interior face that
    should be removed.
    """
    # Face center
    face_center = f.vertices.mean(axis=0)
    # Vector from face center toward centroid
    to_centroid = shell_centroid - face_center
    # If the face normal points toward centroid, it's inward-facing
    return float(np.dot(f.normal, to_centroid)) > 0


def assemble_shell(
    exterior_elements: list[Element],
    remove_interior_faces: bool = True,
) -> ShellGeometry:
    """Assemble exterior elements into a single shell geometry.

    Takes all classified-exterior elements and combines their faces into
    a unified shell. Optionally removes interior-facing faces.

    Args:
        exterior_elements: Elements classified as exterior.
        remove_interior_faces: If True, remove faces that point inward.

    Returns:
        Assembled ShellGeometry.
    """
    shell = ShellGeometry(
        element_count=len(exterior_elements),
        source_elements=exterior_elements,
    )

    # Collect all exterior faces
    all_faces: list[Face] = []
    for element in exterior_elements:
        all_faces.extend(element.faces)

    if not all_faces:
        logger.warning("No faces to assemble — empty shell")
        return shell

    logger.info(f"Assembling {len(all_faces)} faces from {len(exterior_elements)} elements")

    # Compute rough centroid for interior face detection
    all_verts = np.vstack([f.vertices for f in all_faces])
    centroid = all_verts.mean(axis=0)

    # Optionally remove interior-facing faces
    if remove_interior_faces:
        original_count = len(all_faces)
        all_faces = [f for f in all_faces if not _face_is_backward(f, centroid)]
        removed = original_count - len(all_faces)
        if removed > 0:
            logger.info(f"Removed {removed} interior-facing faces")

    shell.faces = all_faces
    shell.total_face_count = len(all_faces)

    logger.info(
        f"Shell assembled: {shell.element_count} elements, "
        f"{shell.total_face_count} faces"
    )

    return shell


def get_shell_stats(shell: ShellGeometry) -> dict:
    """Get statistics about the assembled shell.

    Returns:
        Dictionary with shell statistics.
    """
    if not shell.faces:
        return {
            "face_count": 0,
            "element_count": 0,
            "bbox": None,
            "total_area": 0.0,
        }

    total_area = sum(_face_area(f) for f in shell.faces)
    bbox_min = shell.bbox_min
    bbox_max = shell.bbox_max

    bbox = None
    if bbox_min is not None and bbox_max is not None:
        bbox = {
            "min": bbox_min.tolist(),
            "max": bbox_max.tolist(),
            "size": (bbox_max - bbox_min).tolist(),
        }

    return {
        "face_count": shell.total_face_count,
        "element_count": shell.element_count,
        "bbox": bbox,
        "total_area": total_area,
    }
