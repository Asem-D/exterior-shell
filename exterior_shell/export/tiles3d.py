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

    Flat shading: each triangle owns its 3 vertices with a duplicated face
    normal — no vertex sharing across triangles.

    Returns:
        (glb_bytes, (bbox_min, bbox_max)) in glTF (Y-up) coordinates.
    """
    n_faces = len(faces)

    # Build interleaved binary buffers: positions + normals, then indices.
    pos_bytes = bytearray()
    norm_bytes = bytearray()

    positions_yup = np.zeros((n_faces * 3, 3), dtype=np.float32)

    for face_idx, face in enumerate(faces):
        verts = face.vertices  # (3, 3) float64 in IFC Z-up
        n = face.normal        # (3,) float64 in IFC Z-up

        for v_idx in range(3):
            x, y, z = float(verts[v_idx, 0]), float(verts[v_idx, 1]), float(verts[v_idx, 2])
            gx, gy, gz = _transform_vertex(x, y, z)
            nx, ny, nz = _transform_vertex(float(n[0]), float(n[1]), float(n[2]))
            # Write position
            pos_bytes += struct.pack("<fff", gx, gy, gz)
            positions_yup[face_idx * 3 + v_idx] = (gx, gy, gz)
            # Normal (duplicated for every vertex of the triangle)
            norm_bytes += struct.pack("<fff", nx, ny, nz)

    n_verts = n_faces * 3
    n_indices = n_faces * 3

    pos_byte_length = n_verts * 12
    norm_byte_length = n_verts * 12
    idx_byte_offset = pos_byte_length + norm_byte_length

    # Indices are just 0..n_indices-1 because vertices are not shared.
    idx_array = np.arange(n_indices, dtype=np.uint32)
    idx_bytes = idx_array.tobytes()
    idx_byte_length = len(idx_bytes)

    bin_data = bytes(pos_bytes) + bytes(norm_bytes) + idx_bytes
    bin_byte_length = len(bin_data)

    # Pad binary chunk to 4-byte alignment with zero bytes.
    bin_pad = (4 - (bin_byte_length % 4)) % 4
    bin_data_padded = bin_data + (b"\x00" * bin_pad)

    # Bounding box in glTF (Y-up) coordinates.
    bbox_min, bbox_max = _compute_bounding_box(positions_yup)

    gltf_json: dict[str, Any] = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                        "mode": 4,
                    }
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.85, 0.85, 0.85, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.9,
                }
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,  # FLOAT
                "count": n_verts,
                "type": "VEC3",
                "min": list(bbox_min),
                "max": list(bbox_max),
            },
            {
                "bufferView": 1,
                "componentType": 5126,
                "count": n_verts,
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": 5125,  # UNSIGNED_INT
                "count": n_indices,
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": pos_byte_length,
                "target": 34962,  # ARRAY_BUFFER
            },
            {
                "buffer": 0,
                "byteOffset": pos_byte_length,
                "byteLength": norm_byte_length,
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": idx_byte_offset,
                "byteLength": idx_byte_length,
                "target": 34963,  # ELEMENT_ARRAY_BUFFER
            },
        ],
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