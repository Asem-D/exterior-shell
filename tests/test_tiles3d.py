"""Tests for the 3D Tiles 1.1 exporter."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from exterior_shell.core.models import Face, ShellGeometry
from exterior_shell.export.tiles3d import (
    _build_glb,
    _build_tileset,
    _compute_bounding_box,
    _transform_vertex,
    export_tiles3d,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def make_face(
    verts: list[tuple[float, float, float]],
    normal: tuple[float, float, float],
) -> Face:
    """Helper: create a Face with float64 vertices."""
    return Face(
        vertices=np.array(verts, dtype=np.float64),
        normal=np.array(normal, dtype=np.float64),
    )


def make_simple_shell() -> ShellGeometry:
    """Build a small shell with 2 triangles on the Z=10 plane (Z-up)."""
    # Triangle 1: a flat triangle in the XY plane (Z=10), normal pointing up +Z
    t1 = make_face(
        [(0.0, 0.0, 10.0), (5.0, 0.0, 10.0), (0.0, 5.0, 10.0)],
        (0.0, 0.0, 1.0),
    )
    # Triangle 2: adjacent flat triangle, same plane and normal
    t2 = make_face(
        [(5.0, 0.0, 10.0), (5.0, 5.0, 10.0), (0.0, 5.0, 10.0)],
        (0.0, 0.0, 1.0),
    )
    return ShellGeometry(faces=[t1, t2], element_count=1, total_face_count=2)


# ── Coordinate transform ──────────────────────────────────────────────────────


class TestCoordinateTransform:
    """IFC Z-up -> glTF Y-up transform."""

    def test_z_up_point(self):
        # A point at height Z=10 in IFC should become Y=10 in glTF.
        gx, gy, gz = _transform_vertex(1.0, 2.0, 10.0)
        assert gx == 1.0
        assert gy == 10.0  # Z becomes Y
        assert gz == -2.0  # -Y becomes Z

    def test_origin_unchanged(self):
        assert _transform_vertex(0.0, 0.0, 0.0) == (0.0, 0.0, 0.0)

    def test_normal_transform(self):
        # A normal pointing up in IFC (0,0,1) should point up in glTF (0,1,0).
        nx, ny, nz = _transform_vertex(0.0, 0.0, 1.0)
        assert (nx, ny, nz) == (0.0, 1.0, 0.0)


# ── GLB binary structure ─────────────────────────────────────────────────────


class TestBuildGlb:
    """Low-level GLB binary format checks."""

    def test_glb_magic_bytes(self):
        """First 4 bytes must be ASCII 'glTF' (0x46546C67 little-endian)."""
        glb_bytes, _ = _build_glb([])
        assert glb_bytes[:4] == b"glTF"
        # As little-endian uint32, 'g'=0x67, 'l'=0x6C, 'T'=0x54, 'F'=0x46
        # so the uint32 LE is 0x46546C67.
        magic_int = struct.unpack("<I", glb_bytes[:4])[0]
        assert magic_int == 0x46546C67

    def test_glb_version_is_2(self):
        glb_bytes, _ = _build_glb([])
        version = struct.unpack("<I", glb_bytes[4:8])[0]
        assert version == 2

    def test_empty_shell_glb_header(self):
        """Even with zero faces, a valid GLB with empty JSON/BIN should be produced."""
        glb_bytes, bbox = _build_glb([])
        assert len(glb_bytes) >= 12  # at least header
        # Both chunks can be zero-length but the binary structure must still parse.
        total = struct.unpack("<I", glb_bytes[8:12])[0]
        assert total == len(glb_bytes)
        # bbox is (min, max) but with zero points it returns zeros from empty array
        assert bbox == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    def test_glb_json_and_bin_chunks(self):
        """Verify JSON + BIN chunk headers and contents."""
        faces = make_simple_shell().faces
        glb_bytes, _ = _build_glb(faces)

        # JSON chunk
        json_chunk_len = struct.unpack("<I", glb_bytes[12:16])[0]
        json_chunk_type = struct.unpack("<I", glb_bytes[16:20])[0]
        assert json_chunk_type == 0x4E4F534A  # "JSON"

        json_bytes = glb_bytes[20 : 20 + json_chunk_len]
        gltf = json.loads(json_bytes.decode("utf-8").rstrip(" "))
        assert gltf["asset"]["version"] == "2.0"
        assert gltf["scene"] == 0
        assert gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"] == 0
        assert gltf["meshes"][0]["primitives"][0]["attributes"]["NORMAL"] == 1
        assert gltf["meshes"][0]["primitives"][0]["indices"] == 2
        assert gltf["meshes"][0]["primitives"][0]["material"] == 0
        assert gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"] == [
            0.85, 0.85, 0.85, 1.0
        ]
        # 5126 = FLOAT, 5125 = UNSIGNED_INT
        assert gltf["accessors"][0]["componentType"] == 5126
        assert gltf["accessors"][2]["componentType"] == 5125
        # 34962 = ARRAY_BUFFER, 34963 = ELEMENT_ARRAY_BUFFER
        assert gltf["bufferViews"][0]["target"] == 34962
        assert gltf["bufferViews"][2]["target"] == 34963
        # Counts: 2 faces * 3 verts, 2 faces * 3 indices
        assert gltf["accessors"][0]["count"] == 6
        assert gltf["accessors"][1]["count"] == 6
        assert gltf["accessors"][2]["count"] == 6

        # BIN chunk immediately follows the JSON chunk
        bin_offset = 20 + json_chunk_len
        bin_chunk_len = struct.unpack("<I", glb_bytes[bin_offset : bin_offset + 4])[0]
        bin_chunk_type = struct.unpack(
            "<I", glb_bytes[bin_offset + 4 : bin_offset + 8]
        )[0]
        assert bin_chunk_type == 0x004E4942  # "BIN\0"

        bin_bytes = glb_bytes[bin_offset + 8 : bin_offset + 8 + bin_chunk_len]
        # 6 verts * (12 pos + 12 norm) + 6 indices * 4 bytes = 168 bytes
        expected = 6 * 12 + 6 * 12 + 6 * 4
        assert len(bin_bytes) == expected

    def test_glb_alignment_padding(self):
        """JSON padded to 4 bytes with spaces; BIN padded with zeros."""
        glb_bytes, _ = _build_glb(make_simple_shell().faces)

        json_chunk_len = struct.unpack("<I", glb_bytes[12:16])[0]
        json_bytes = glb_bytes[20 : 20 + json_chunk_len]
        assert json_chunk_len % 4 == 0
        # Trailing padding must be spaces (0x20), not garbage.
        stripped = json_bytes.rstrip(b" ")
        assert json_bytes[len(stripped):] == b" " * (json_chunk_len - len(stripped))

        bin_offset = 20 + json_chunk_len
        bin_chunk_len = struct.unpack("<I", glb_bytes[bin_offset : bin_offset + 4])[0]
        assert bin_chunk_len % 4 == 0

    def test_flat_shading_per_triangle_vertices(self):
        """Each face gets 3 unique vertices with the same normal across all 3."""
        glb_bytes, _ = _build_glb(make_simple_shell().faces)

        json_chunk_len = struct.unpack("<I", glb_bytes[12:16])[0]
        bin_offset = 20 + json_chunk_len + 8
        # Skip positions (6*12 = 72), read normals
        norm_offset = bin_offset + 72
        normals = np.frombuffer(
            glb_bytes[norm_offset : norm_offset + 6 * 12], dtype=np.float32
        ).reshape(6, 3)
        # For both triangles, the original normal was (0,0,1) in IFC Z-up.
        # After transform it becomes (0, 1, 0) in glTF.
        expected = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        np.testing.assert_allclose(normals, np.tile(expected, (6, 1)), atol=1e-6)

    def test_bounding_box_after_transform(self):
        """BBox is computed in glTF coords after Y-up transform."""
        # Triangle in Z=10 plane -> vertices end up at Y=10 in glTF.
        glb_bytes, (mn, mx) = _build_glb(make_simple_shell().faces)
        assert pytest.approx(mn[1], abs=1e-5) == 10.0
        assert pytest.approx(mx[1], abs=1e-5) == 10.0
        assert mn[0] == 0.0
        assert pytest.approx(mx[0], abs=1e-5) == 5.0
        assert pytest.approx(mn[2], abs=1e-5) == -5.0
        assert mx[2] == 0.0


# ── tileset.json generator ────────────────────────────────────────────────────


class TestBuildTileset:
    """3D Tiles 1.1 tileset.json structure."""

    def test_tileset_basic_structure(self):
        bbox = ((-1.0, -2.0, -3.0), (1.0, 2.0, 3.0))
        ts = _build_tileset(bbox)

        assert ts["asset"]["version"] == "1.1"
        assert ts["geometricError"] == 500.0
        assert ts["root"]["geometricError"] == 0.0
        assert ts["root"]["refine"] == "ADD"
        assert ts["root"]["content"]["uri"] == "model.glb"

    def test_tileset_bounding_box_center_and_halfs(self):
        bbox = ((0.0, 0.0, 0.0), (10.0, 4.0, 6.0))
        ts = _build_tileset(bbox)
        box = ts["root"]["boundingVolume"]["box"]
        assert len(box) == 12
        # Center
        assert box[0] == 5.0
        assert box[1] == 2.0
        assert box[2] == 3.0
        # Half-extents on the diagonal of the 3x3 matrix
        assert box[3] == 5.0  # hx
        assert box[7] == 2.0  # hy
        assert box[11] == 3.0  # hz
        # Off-diagonal entries of the 3x3 rotation/scale matrix are zero.
        # Indices 4-6 (hy*row), 8-10 (hz*row) should be 0.
        for i in (4, 5, 6, 8, 9, 10):
            assert box[i] == 0.0

    def test_tileset_default_content_uri(self):
        ts = _build_tileset(((0, 0, 0), (1, 1, 1)))
        assert ts["root"]["content"]["uri"] == "model.glb"

    def test_tileset_custom_uri(self):
        ts = _build_tileset(((0, 0, 0), (1, 1, 1)), content_uri="building.glb")
        assert ts["root"]["content"]["uri"] == "building.glb"

    def test_tileset_is_json_serializable(self):
        ts = _build_tileset(((-1, -1, -1), (1, 1, 1)))
        # Must round-trip through JSON without errors.
        text = json.dumps(ts)
        reloaded = json.loads(text)
        assert reloaded == ts


# ── Bounding box helper ───────────────────────────────────────────────────────


class TestBoundingBox:
    def test_bbox_single_point(self):
        pts = np.array([[1.0, 2.0, 3.0]])
        mn, mx = _compute_bounding_box(pts)
        assert mn == (1.0, 2.0, 3.0)
        assert mx == (1.0, 2.0, 3.0)

    def test_bbox_corners(self):
        pts = np.array(
            [[0, 0, 0], [1, 0, 0], [0, 2, 0], [0, 0, 3]], dtype=np.float64
        )
        mn, mx = _compute_bounding_box(pts)
        assert mn == (0.0, 0.0, 0.0)
        assert mx == (1.0, 2.0, 3.0)


# ── End-to-end export ─────────────────────────────────────────────────────────


class TestExportTiles3d:
    def test_creates_directory_and_files(self, tmp_path: Path):
        shell = make_simple_shell()
        out = tmp_path / "3dtiles_out"
        stats = export_tiles3d(shell, out)

        assert (out / "tileset.json").exists()
        assert (out / "model.glb").exists()
        assert stats["face_count"] == 2
        assert stats["glb_size"] > 0
        assert stats["tileset_size"] > 0

    def test_export_creates_missing_dirs(self, tmp_path: Path):
        out = tmp_path / "deep" / "nested" / "tiles"
        shell = make_simple_shell()
        stats = export_tiles3d(shell, out)
        assert Path(stats["directory"]).is_dir()
        assert (out / "model.glb").exists()

    def test_export_writes_valid_glb(self, tmp_path: Path):
        out = tmp_path / "tiles"
        export_tiles3d(make_simple_shell(), out)
        glb_bytes = (out / "model.glb").read_bytes()
        assert glb_bytes[:4] == b"glTF"
        assert struct.unpack("<I", glb_bytes[4:8])[0] == 2

    def test_export_writes_valid_tileset(self, tmp_path: Path):
        out = tmp_path / "tiles"
        export_tiles3d(make_simple_shell(), out)
        ts = json.loads((out / "tileset.json").read_text(encoding="utf-8"))
        assert ts["asset"]["version"] == "1.1"
        assert ts["root"]["content"]["uri"] == "model.glb"
        assert len(ts["root"]["boundingVolume"]["box"]) == 12

    def test_export_empty_shell(self, tmp_path: Path):
        """Empty shell produces valid (minimal) outputs, not an error."""
        empty = ShellGeometry(faces=[], element_count=0, total_face_count=0)
        out = tmp_path / "empty_tiles"
        stats = export_tiles3d(empty, out)
        assert (out / "tileset.json").exists()
        assert (out / "model.glb").exists()
        assert stats["face_count"] == 0

    def test_export_single_face(self, tmp_path: Path):
        face = make_face(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            (0.0, 0.0, 1.0),
        )
        shell = ShellGeometry(faces=[face], element_count=1, total_face_count=1)
        out = tmp_path / "one_face"
        stats = export_tiles3d(shell, out)

        assert stats["face_count"] == 1
        # Verify GLB contains exactly one triangle worth of data
        glb_bytes = (out / "model.glb").read_bytes()
        json_chunk_len = struct.unpack("<I", glb_bytes[12:16])[0]
        bin_offset = 20 + json_chunk_len
        bin_chunk_len = struct.unpack(
            "<I", glb_bytes[bin_offset : bin_offset + 4]
        )[0]
        # 3 verts * (12 + 12) + 3 indices * 4 = 84 bytes
        assert bin_chunk_len == 84

    def test_stats_include_crs(self, tmp_path: Path):
        out = tmp_path / "tiles"
        stats = export_tiles3d(make_simple_shell(), out, crs="EPSG:3857")
        assert stats["crs"] == "EPSG:3857"

    def test_generator_includes_version(self, tmp_path: Path):
        out = tmp_path / "tiles"
        stats = export_tiles3d(make_simple_shell(), out)
        assert stats["generator"].startswith("exterior-shell v")