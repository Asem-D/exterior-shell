"""3D model renderer for AI classification.

Renders IFC models from multiple viewpoints to produce images
that can be analyzed by vision models for exterior/interior classification.

Two rendering strategies:
1. Full 3D render via ifcopenshell + trimesh (when geometry tessellates)
2. Bounding box fallback via matplotlib (when tessellation fails)
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Classification colors for bounding box fallback
_COLORS = {
    "exterior": "#2196F3",   # blue
    "interior": "#9E9E9E",   # gray
    "ambiguous": "#FF9800",  # orange
    "default": "#FF9800",
}


def _try_ifc_to_trimesh(ifc_path: str | Path) -> Optional[object]:
    """Try to convert IFC to trimesh scene via ifcopenshell geometry.

    Returns trimesh.Scene or None if tessellation fails.
    """
    try:
        import trimesh
        import ifcopenshell
        import ifcopenshell.geom

        model = ifcopenshell.open(str(ifc_path))
        settings = ifcopenshell.geom.settings()
        it = ifcopenshell.geom.iterator(settings, model, num_threads=1)

        if not it.initialize():
            logger.debug("Iterator failed to initialize, cannot tessellate geometry")
            return None

        meshes = []
        while True:
            shape = it.next()
            if shape is None:
                break
            verts = np.array(shape.geometry.verts).reshape(-1, 3)
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            if len(verts) > 0 and len(faces) > 0:
                meshes.append(trimesh.Trimesh(vertices=verts, faces=faces))

        if not meshes:
            return None

        return trimesh.Scene(meshes) if len(meshes) > 1 else trimesh.Scene(meshes[0])

    except Exception as e:
        logger.debug(f"trimesh conversion failed: {e}")
        return None


def _try_trimesh_render(
    scene: object,
    output_path: Path,
    camera_pos: np.ndarray,
    target: np.ndarray,
    resolution: tuple[int, int] = (1024, 768),
) -> bool:
    """Try to render a trimesh scene from a viewpoint.

    Returns True if render succeeded.
    """
    try:
        bounds = scene.bounds
        if bounds is None:
            return False

        center = (bounds[0] + bounds[1]) / 2.0
        size = np.linalg.norm(bounds[1] - bounds[0])

        direction = camera_pos - target
        dist = np.linalg.norm(direction)
        if dist < 1e-6:
            direction = np.array([0, 0, 1])
            dist = 1.0

        new_pos = center + (direction / dist) * size * 1.5
        scene.camera_transform = np.eye(4)
        scene.camera_transform[:3, 3] = new_pos

        png_data = scene.save_image(resolution=resolution)
        output_path.write_bytes(png_data)
        return True

    except Exception as e:
        logger.debug(f"trimesh render failed: {e}")
        return False


def _render_bbox_fallback(
    ifc_path: str | Path,
    output_path: Path,
    camera_elev: float = 30,
    camera_azim: float = -60,
    resolution: tuple[int, int] = (1024, 768),
    classification_map: dict[str, str] | None = None,
) -> bool:
    """Render bounding boxes from element metadata using matplotlib.

    Args:
        ifc_path: Path to IFC file.
        output_path: Where to save the PNG.
        camera_elev: Camera elevation angle in degrees.
        camera_azim: Camera azimuth angle in degrees.
        resolution: Image size (width, height).
        classification_map: Dict mapping global_id -> classification string.

    Returns:
        True if render succeeded.
    """
    try:
        import ifcopenshell
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        model = ifcopenshell.open(str(ifc_path))

        # Extract bounding boxes from IfcProduct elements
        products = model.by_type("IfcProduct")
        if not products:
            return False

        fig = plt.figure(figsize=(resolution[0] / 100, resolution[1] / 100), dpi=100)
        ax = fig.add_subplot(111, projection="3d")

        all_mins = []
        all_maxs = []
        element_count = 0

        for product in products:
            # Get Placement coordinates as a proxy for position
            placement = product.ObjectPlacement
            if placement is None:
                continue

            # Extract translation from placement
            loc = _extract_placement_origin(placement)
            if loc is None:
                continue

            # Estimate element size from type
            size = _estimate_element_size(product)
            if size is None:
                continue

            bbox_min = loc - size / 2
            bbox_max = loc + size / 2
            all_mins.append(bbox_min)
            all_maxs.append(bbox_max)

            # Get classification color
            gid = product.GlobalId
            cls = "default"
            if classification_map and gid in classification_map:
                cls = classification_map[gid]
            elif product.is_a("IfcWindow") or product.is_a("IfcDoor"):
                cls = "exterior"
            elif product.is_a("IfcFurnishingElement"):
                cls = "interior"

            color = _COLORS.get(cls, _COLORS["default"])
            alpha = 0.6 if cls == "exterior" else 0.3 if cls == "interior" else 0.5

            # Draw bounding box
            _draw_bbox(ax, bbox_min, bbox_max, color, alpha)
            element_count += 1

        if not all_mins:
            plt.close(fig)
            return False

        # Set axis limits
        all_mins = np.array(all_mins)
        all_maxs = np.array(all_maxs)
        global_min = all_mins.min(axis=0)
        global_max = all_maxs.max(axis=0)
        center = (global_min + global_max) / 2
        span = (global_max - global_min).max() / 2 * 1.3

        ax.set_xlim(center[0] - span, center[0] + span)
        ax.set_ylim(center[1] - span, center[1] + span)
        ax.set_zlim(center[2] - span, center[2] + span)

        ax.view_init(elev=camera_elev, azim=camera_azim)
        ax.set_axis_off()
        ax.set_title(f"{element_count} elements (bounding box view)", fontsize=12, pad=10)

        fig.tight_layout()
        fig.savefig(str(output_path), dpi=100, bbox_inches="tight", pad_inches=0.1)
        plt.close(fig)
        return True

    except Exception as e:
        logger.error(f"Bounding box render failed: {e}")
        return False


def _extract_placement_origin(placement) -> Optional[np.ndarray]:
    """Extract the origin point from an IfcLocalPlacement chain.

    Walks up the placement hierarchy to get the absolute position.
    """
    import ifcopenshell

    try:
        total = np.array([0.0, 0.0, 0.0])
        current = placement

        while current is not None:
            ax2 = current.RelativePlacement
            if ax2 and ax2.Location:
                loc = ax2.Location.Coordinates
                total += np.array([loc[0], loc[1], loc[2]])

            # Walk to parent placement
            if hasattr(current, "PlacementRelTo") and current.PlacementRelTo:
                current = current.PlacementRelTo
            else:
                break

        return total
    except Exception:
        return None


def _estimate_element_size(product) -> Optional[np.ndarray]:
    """Estimate element size based on IFC type.

    Returns approximate (x, y, z) dimensions.
    """
    ifc_type = product.is_a()
    sizes = {
        "IfcWall": np.array([6.0, 0.3, 3.0]),
        "IfcWallStandardCase": np.array([6.0, 0.3, 3.0]),
        "IfcColumn": np.array([0.4, 0.4, 3.0]),
        "IfcBeam": np.array([6.0, 0.3, 0.5]),
        "IfcSlab": np.array([10.0, 10.0, 0.3]),
        "IfcRoof": np.array([12.0, 12.0, 0.3]),
        "IfcWindow": np.array([1.2, 0.1, 1.5]),
        "IfcDoor": np.array([1.0, 0.1, 2.1]),
        "IfcFurnishingElement": np.array([1.0, 0.8, 0.8]),
        "IfcStair": np.array([3.0, 3.0, 3.0]),
        "IfcCurtainWall": np.array([6.0, 0.15, 3.0]),
    }
    return sizes.get(ifc_type)


def _draw_bbox(ax, bbox_min, bbox_max, color, alpha):
    """Draw a 3D bounding box on a matplotlib axes."""
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    x0, y0, z0 = bbox_min
    x1, y1, z1 = bbox_max

    # 8 vertices of the box
    verts = [
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ]

    # 6 faces
    faces = [
        [verts[0], verts[1], verts[5], verts[4]],
        [verts[2], verts[3], verts[7], verts[6]],
        [verts[0], verts[3], verts[7], verts[4]],
        [verts[1], verts[2], verts[6], verts[5]],
        [verts[0], verts[1], verts[2], verts[3]],
        [verts[4], verts[5], verts[6], verts[7]],
    ]

    poly = Poly3DCollection(faces, alpha=alpha, facecolor=color, edgecolor=color, linewidth=0.3)
    ax.add_collection3d(poly)


# ── Viewpoint definitions ────────────────────────────────────────────────────

VIEWPOINTS = {
    "front":     {"elev": 10, "azim": -90},
    "back":      {"elev": 10, "azim": 90},
    "left":      {"elev": 10, "azim": 180},
    "right":     {"elev": 10, "azim": 0},
    "top":       {"elev": 90, "azim": -90},
    "iso_front": {"elev": 25, "azim": -45},
    "iso_back":  {"elev": 25, "azim": 135},
    "iso_right": {"elev": 25, "azim": 45},
}


def render_views(
    ifc_path: str | Path,
    output_dir: str | Path,
    views: list[str] | None = None,
    resolution: tuple[int, int] = (1024, 768),
    classification_map: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Render IFC model from multiple viewpoints.

    Tries full 3D rendering first; falls back to bounding box visualization.

    Args:
        ifc_path: Path to IFC file.
        output_dir: Directory to save rendered images.
        views: List of view names (default: all viewpoints).
        resolution: Image resolution (width, height).
        classification_map: Optional dict mapping global_id -> classification.

    Returns:
        Dict mapping view names to saved image paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if views is None:
        views = list(VIEWPOINTS.keys())

    # Try full 3D rendering first
    scene = _try_ifc_to_trimesh(ifc_path)
    use_trimesh = scene is not None

    if use_trimesh:
        logger.info("Using trimesh full 3D rendering")
    else:
        logger.info("Trimesh rendering unavailable, using bounding box fallback")

    rendered_views = {}

    for view_name in views:
        if view_name not in VIEWPOINTS:
            logger.warning(f"Unknown view: {view_name}")
            continue

        vp = VIEWPOINTS[view_name]
        output_path = output_dir / f"view_{view_name}.png"

        success = False
        if use_trimesh:
            # Build camera position from elev/azim
            elev_rad = np.radians(vp["elev"])
            azim_rad = np.radians(vp["azim"])
            dist = 50.0
            cam_x = dist * np.cos(elev_rad) * np.cos(azim_rad)
            cam_y = dist * np.cos(elev_rad) * np.sin(azim_rad)
            cam_z = dist * np.sin(elev_rad)
            camera_pos = np.array([cam_x, cam_y, cam_z])
            target = np.zeros(3)

            success = _try_trimesh_render(scene, output_path, camera_pos, target, resolution)

        if not success:
            success = _render_bbox_fallback(
                ifc_path, output_path,
                camera_elev=vp["elev"],
                camera_azim=vp["azim"],
                resolution=resolution,
                classification_map=classification_map,
            )

        if success:
            rendered_views[view_name] = output_path
            logger.debug(f"Rendered {view_name}: {output_path}")
        else:
            logger.error(f"Failed to render {view_name}")

    logger.info(f"Rendered {len(rendered_views)}/{len(views)} views")
    return rendered_views
