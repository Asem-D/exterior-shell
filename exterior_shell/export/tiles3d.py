"""3D Tiles 1.1 exporter — pure-Python GLB writer + tileset.json generator.

Converts an assembled exterior ShellGeometry into a CesiumJS-compatible
3D Tiles 1.1 directory with `tileset.json` + `model.glb`.

Coordinate convention:
  - Input geometry (from IFC / interior-shell assembler) is Z-up.
  - glTF 2.0 / 3D Tiles convention is Y-up, right-handed.
  - Transform: (x, y, z) -> (x, z, -y).

Zero new dependencies: only stdlib + numpy (already required).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np

from ..core.models import Face, ShellGeometry


# ── Public API ────────────────────────────────────────────────────────────────


def export_tiles3d(
    shell: ShellGeometry,
    output_dir: Path,
    crs: str = "EPSG:4326",
) -> dict:
    """Export a ShellGeometry to a 3D Tiles 1.1 directory.

    Creates ``<output_dir>/tileset.json`` and ``<output_dir>/model.glb``.

    Args:
        shell: Assembled exterior shell (Z-up).
        output_dir: Destination directory. Created if missing.
        crs: Coordinate reference system hint (stored as metadata).

    Returns:
        Stats dict with file sizes, face count, bounding box, and CRS.
    """
    from .. import __version__

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    glb_bytes, bbox = _build_glb(shell.faces)

    glb_path = output_dir / "model.glb"
    glb_path.write_bytes(glb_bytes)

    tileset = _build_tileset(bbox, content_uri="model.glb")
    tileset_path = output_dir / "tileset.json"
    tileset_path.write_text(
        json.dumps(tileset, indent=2), encoding="utf-8"
    )

    return {
        "directory": str(output_dir),
        "tileset_path": str(tileset_path),
        "glb_path": str(glb_path),
        "tileset_size": tileset_path.stat().st_size,
        "glb_size": glb_path.stat().st_size,
        "face_count": len(shell.faces),
        "bounding_box": bbox,
        "crs": crs,
        "generator": f"exterior-shell v{__version__}",
    }


# ── GLB writer ────────────────────────────────────────────────────────────────


def _transform_vertex(x: float, y: float, z: float) -> tuple[float, float, float]:
    """IFC Z-up -> glTF Y-up: (x, y, z) -> (x, z, -y)."""
    return x, z, -y


def _compute_bounding_box(
    positions: np.ndarray,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return (min, max) of an (N, 3) float64 array."""
    if positions.shape[0] == 0:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    mn = positions.min(axis=0)
    mx = positions.max(axis=0)
    return (float(mn[0]), float(mn[1]), float(mn[2])), (
        float(mx[0]),
        float(mx[1]),
        float(mx[2]),
    )


def _build_glb(faces: list[Face]) -> tuple[bytes, tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """Build a glTF 2.0 GLB binary from a list of faces.

    Supports per-face colors: faces with the same color are grouped into
    separate primitives with distinct materials. Faces without a color use
    a default light-gray material.

    Flat shading: each triangle owns its 3 vertices with a duplicated face
    normal — no vertex sharing across triangles.

    Returns:
        (glb_bytes, (bbox_min, bbox_max)) in glTF (Y-up) coordinates.
    """
    # Group faces by color
    color_groups: dict[tuple[float, float, float] | None, list[int]] = {}
    for i, face in enumerate(faces):
        key = face.color
        color_groups.setdefault(key, []).append(i)

    if not color_groups:
        # Empty shell: emit a valid but empty GLB.
        empty_json = json.dumps({"asset": {"version": "2.0"}}).encode("utf-8")
        json_pad = (4 - (len(empty_json) % 4)) % 4
        empty_json += b" " * json_pad
        out = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(empty_json))
        out += struct.pack("<II", len(empty_json), 0x4E4F534A)
        out += empty_json
        zeros = (0.0, 0.0, 0.0)
        return bytes(out), (zeros, zeros)

    # Build materials list
    default_color = (0.85, 0.85, 0.85)
    materials = []
    material_map = {}  # color -> material index
    for color_key in color_groups:
        if color_key is None:
            color_key = default_color
        if color_key not in material_map:
            material_map[color_key] = len(materials)
            materials.append({
                "pbrMetallicRoughness": {
                    "baseColorFactor": [color_key[0], color_key[1], color_key[2], 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.9,
                }
            })

    # Build per-group interleaved binary buffer: each color group appends
    # [positions | normals | indices] contiguously, matching the bufferView
    # offsets computed below (pos @ offset, norm @ offset+pos_len, idx @
    # offset+pos_len+norm_len).
    all_buffer_views = []
    all_primitives = []
    all_accessors = []

    bin_data = bytearray()

    positions_yup_all = []
    current_offset = 0
    current_idx_offset = 0

    for color_key, face_indices in color_groups.items():
        mat_color = color_key if color_key else default_color
        mat_idx = material_map[mat_color]

        group_pos = bytearray()
        group_norm = bytearray()
        group_positions = np.zeros((len(face_indices) * 3, 3), dtype=np.float32)

        for local_idx, face_idx in enumerate(face_indices):
            face = faces[face_idx]
            verts = face.vertices
            n = face.normal

            for v_idx in range(3):
                x, y, z = float(verts[v_idx, 0]), float(verts[v_idx, 1]), float(verts[v_idx, 2])
                gx, gy, gz = _transform_vertex(x, y, z)
                nx, ny, nz = _transform_vertex(float(n[0]), float(n[1]), float(n[2]))
                group_pos += struct.pack("<fff", gx, gy, gz)
                group_norm += struct.pack("<fff", nx, ny, nz)
                group_positions[local_idx * 3 + v_idx] = (gx, gy, gz)

        positions_yup_all.append(group_positions)

        n_group_verts = len(face_indices) * 3
        n_group_indices = len(face_indices) * 3

        pos_byte_length = len(group_pos)
        norm_byte_length = len(group_norm)
        idx_byte_length = n_group_indices * 4  # uint32

        # Buffer views for this group
        pos_bv_idx = len(all_buffer_views)
        all_buffer_views.append({
            "buffer": 0,
            "byteOffset": current_offset,
            "byteLength": pos_byte_length,
            "target": 34962,  # ARRAY_BUFFER
        })

        norm_bv_idx = len(all_buffer_views)
        all_buffer_views.append({
            "buffer": 0,
            "byteOffset": current_offset + pos_byte_length,
            "byteLength": norm_byte_length,
            "target": 34962,
        })

        idx_bv_idx = len(all_buffer_views)
        all_buffer_views.append({
            "buffer": 0,
            "byteOffset": current_offset + pos_byte_length + norm_byte_length,
            "byteLength": idx_byte_length,
            "target": 34963,  # ELEMENT_ARRAY_BUFFER
        })

        # Accessors for this group
        pos_acc_idx = len(all_accessors)
        all_accessors.append({
            "bufferView": pos_bv_idx,
            "componentType": 5126,  # FLOAT
            "count": n_group_verts,
            "type": "VEC3",
        })

        norm_acc_idx = len(all_accessors)
        all_accessors.append({
            "bufferView": norm_bv_idx,
            "componentType": 5126,
            "count": n_group_verts,
            "type": "VEC3",
        })

        idx_acc_idx = len(all_accessors)
        all_accessors.append({
            "bufferView": idx_bv_idx,
            "componentType": 5125,  # UNSIGNED_INT
            "count": n_group_indices,
            "type": "SCALAR",
        })

        # Primitive for this group
        prim_idx = len(all_primitives)
        all_primitives.append({
            "attributes": {"POSITION": pos_acc_idx, "NORMAL": norm_acc_idx},
            "indices": idx_acc_idx,
            "material": mat_idx,
            "mode": 4,
        })

        # Append this group's [pos | norm | idx] block to the binary buffer.
        bin_data += group_pos
        bin_data += group_norm
        # glTF indices are LOCAL to each primitive's own vertex buffer,
        # so every group restarts at 0.
        group_idx = np.arange(n_group_indices, dtype=np.uint32)
        bin_data += group_idx.tobytes()

        current_offset += pos_byte_length + norm_byte_length + idx_byte_length

    # Compute global bounding box
    all_positions = np.vstack(positions_yup_all)
    bbox_min, bbox_max = _compute_bounding_box(all_positions)

    # Pad alignment
    bin_byte_length = len(bin_data)
    bin_pad = (4 - (bin_byte_length % 4)) % 4
    bin_data_padded = bin_data + (b"\x00" * bin_pad)

    gltf_json: dict[str, Any] = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": all_primitives,
            }
        ],
        "materials": materials,
        "accessors": all_accessors,
        "bufferViews": all_buffer_views,
        "buffers": [{"byteLength": bin_byte_length}],
    }

    # Serialize JSON. Round-trip floats to make them compact and predictable.
    json_text = json.dumps(gltf_json, separators=(",", ":"))
    json_bytes = json_text.encode("utf-8")

    # Pad JSON chunk to 4-byte alignment with space characters (0x20).
    json_pad = (4 - (len(json_bytes) % 4)) % 4
    json_bytes_padded = json_bytes + (b" " * json_pad)

    json_chunk_length = len(json_bytes_padded)
    bin_chunk_length = len(bin_data_padded)
    total_length = 12 + 8 + json_chunk_length + 8 + bin_chunk_length

    # GLB header
    out = bytearray()
    out += struct.pack("<4sII", b"glTF", 2, total_length)
    # JSON chunk
    out += struct.pack("<II", json_chunk_length, 0x4E4F534A)  # "JSON"
    out += json_bytes_padded
    # BIN chunk
    out += struct.pack("<II", bin_chunk_length, 0x004E4942)  # "BIN\0"
    out += bin_data_padded

    return bytes(out), (bbox_min, bbox_max)


# ── tileset.json generator ────────────────────────────────────────────────────


def _build_tileset(
    bounding_box: tuple[
        tuple[float, float, float], tuple[float, float, float]
    ],
    content_uri: str = "model.glb",
) -> dict:
    """Build a minimal 3D Tiles 1.1 tileset.json with an axis-aligned box.

    The 12-element ``box`` array is:
        [cx, cy, cz, hx, 0, 0, 0, hy, 0, 0, 0, hz]
    representing center + 3 half-axes as column vectors.
    """
    from .. import __version__

    (min_x, min_y, min_z), (max_x, max_y, max_z) = bounding_box
    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    cz = (min_z + max_z) / 2.0
    hx = (max_x - min_x) / 2.0
    hy = (max_y - min_y) / 2.0
    hz = (max_z - min_z) / 2.0

    return {
        "asset": {
            "version": "1.1",
            "generator": f"exterior-shell v{__version__}",
        },
        "geometricError": 500.0,
        "root": {
            "boundingVolume": {
                "box": [
                    cx, cy, cz,
                    hx, 0.0, 0.0,
                    0.0, hy, 0.0,
                    0.0, 0.0, hz,
                ]
            },
            "geometricError": 0.0,
            "refine": "ADD",
            "content": {"uri": content_uri},
        },
    }
