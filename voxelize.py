#!/usr/bin/env python3
"""
Stanford Bunny → Minecraft Datapack Generator

Downloads the Stanford Bunny PLY model, voxelizes it, and generates
a Minecraft datapack that places the bunny with a single command.
"""

import argparse
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

import numpy as np
import requests
import trimesh
from scipy.ndimage import label

BUNNY_URL = "http://graphics.stanford.edu/pub/3Dscanrep/bunny.tar.gz"
BUNNY_PLY_REL = "bunny/reconstruction/bun_zipper.ply"

PACK_MCMETA = {
    "pack": {
        "pack_format": 48,
        "supported_formats": [15, 71],
        "description": "Stanford Bunny - classic 3D test model in Minecraft",
    }
}


def download_bunny(data_dir: Path) -> Path:
    """Download and extract the Stanford Bunny PLY."""
    ply_path = data_dir / BUNNY_PLY_REL
    if ply_path.exists():
        print(f"Using cached PLY: {ply_path}")
        return ply_path

    tar_path = data_dir / "bunny.tar.gz"
    data_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading Stanford Bunny from {BUNNY_URL} ...")
    resp = requests.get(BUNNY_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with open(tar_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Downloaded {tar_path.stat().st_size / 1024:.0f} KB")

    print("Extracting...")
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=data_dir)
    tar_path.unlink()

    if not ply_path.exists():
        sys.exit(f"Error: expected PLY not found at {ply_path}")
    return ply_path


def voxelize_mesh(ply_path: Path, target_height: int, hollow: bool) -> np.ndarray:
    """Load PLY and voxelize to a 3D boolean array."""
    print(f"Loading mesh: {ply_path}")
    mesh = trimesh.load(str(ply_path))

    # Fill holes in the mesh (Stanford Bunny has holes in the bottom)
    if not mesh.is_watertight:
        print("Mesh has holes, repairing...")
        trimesh.repair.fill_holes(mesh)
        if not mesh.is_watertight:
            print("  Note: mesh still not fully watertight after repair")

    bounds = mesh.bounds  # [[min_x, min_y, min_z], [max_x, max_y, max_z]]
    height = bounds[1][1] - bounds[0][1]  # Y extent
    pitch = height / target_height

    print(f"Mesh bounds: {bounds[0]} → {bounds[1]}")
    print(f"Mesh height: {height:.4f} units, pitch: {pitch:.6f}")
    print(f"Target height: {target_height} blocks")

    print("Voxelizing...")
    voxelized = trimesh.voxel.creation.voxelize(mesh, pitch=pitch)
    matrix = voxelized.matrix.copy()

    if not hollow:
        print("Filling interior...")
        # Seal the bottom temporarily: the Stanford Bunny has holes at the
        # base which would let flood-fill leak into the interior.  Cap it by
        # projecting the XZ footprint onto the lowest Y slice — but only on a
        # temporary copy so the seal blocks don't end up in the final output.
        sealed = matrix.copy()
        footprint = sealed.any(axis=1)  # (X, Z) — True where column has any voxel
        min_y_global = np.where(sealed.any(axis=(0, 2)))[0][0]
        sealed[:, min_y_global, :] |= footprint

        # Flood-fill from exterior to correctly identify interior voxels.
        # Pad with 1 layer of empty space so exterior is fully connected.
        padded = np.pad(sealed, pad_width=1, mode="constant", constant_values=False)
        # Invert: empty space becomes True, shell becomes False
        inverted = ~padded
        # Label connected components of empty space
        labeled, num_features = label(inverted)
        # The exterior is whichever component touches the corner (0,0,0)
        exterior_label = labeled[0, 0, 0]
        # Everything that is NOT exterior and NOT shell = interior
        interior = (labeled != exterior_label) & inverted
        # Remove padding and merge with the ORIGINAL matrix (not sealed)
        interior = interior[1:-1, 1:-1, 1:-1]
        matrix = matrix | interior

    print(f"Voxel grid shape: {matrix.shape}")
    print(f"Filled voxels: {matrix.sum():,}")

    return matrix


def generate_mcfunction(matrix: np.ndarray, block: str):
    """Generate setblock commands from voxel matrix using ^ (caret) coords.

    Uses ``execute rotated ~ 0`` so ^ coordinates are always horizontal,
    regardless of the player's pitch.  The ^ axes are:
        ^left  ^up  ^forward   (relative to the player's horizontal facing)

    trimesh voxel matrix axes: axis 0 = X, axis 1 = Y, axis 2 = Z.
    In the Stanford Bunny PLY the model faces toward +Z in the voxel
    matrix.  Flipping Z maps the bunny's nose to low ^forward values
    (closest to the player), so it faces toward the player.

    The player stands at the left-bottom-near corner of the bounding box;
    all offsets are non-negative.
    """
    commands = []
    commands.append(
        f"# Stanford Bunny ({matrix.shape[0]}x{matrix.shape[1]}x{matrix.shape[2]})"
    )
    commands.append(f"# Total blocks: {matrix.sum():,}")
    commands.append(f"# Generated by voxelize.py")
    commands.append("")

    # Flip Z so the bunny faces toward the player
    matrix = matrix[:, :, ::-1]
    # Flip X so the bunny isn't mirrored (^left positive = player's left,
    # so inverting X places the bunny to the right and restores correct chirality)
    matrix = matrix[::-1, :, :]

    indices = np.argwhere(matrix)
    min_coords = indices.min(axis=0)
    max_coords = indices.max(axis=0)

    # Player at right-bottom-near corner; left values <= 0 (= player's right)
    for x, y, z in indices:
        left = x - max_coords[0]
        up = y - min_coords[1]
        forward = z - min_coords[2]
        commands.append(
            f"setblock ^{left} ^{up} ^{forward} {block} replace"
        )

    return commands


def package_datapack(
    commands: list[str], output_dir: Path, namespace: str = "stanford_bunny"
) -> Path:
    """Write datapack directory and create zip.

    Creates two mcfunction files:
      build.mcfunction  — entry point; locks pitch to 0 then delegates
      _place.mcfunction — actual setblock commands using ^ coordinates
    """
    dp_dir = output_dir / "stanford-bunny-datapack"

    # Clean previous output
    if dp_dir.exists():
        shutil.rmtree(dp_dir)

    # Create directory structure
    func_dir = dp_dir / "data" / namespace / "function"
    func_dir.mkdir(parents=True)

    # Write pack.mcmeta
    mcmeta_path = dp_dir / "pack.mcmeta"
    with open(mcmeta_path, "w") as f:
        json.dump(PACK_MCMETA, f, indent=2)

    # build.mcfunction — wrapper that normalises pitch so ^ coords stay horizontal
    build_path = func_dir / "build.mcfunction"
    with open(build_path, "w") as f:
        f.write(f"# Lock pitch to 0 so caret coordinates are always horizontal\n")
        f.write(f"execute rotated ~ 0 run function {namespace}:_place\n")

    # _place.mcfunction — setblock commands (called with normalised rotation)
    place_path = func_dir / "_place.mcfunction"
    with open(place_path, "w") as f:
        f.write("\n".join(commands))
        f.write("\n")

    print(f"Written {len(commands)} lines to {place_path}")

    # Create zip
    zip_path = output_dir / "stanford-bunny-datapack"
    archive_path = shutil.make_archive(str(zip_path), "zip", root_dir=str(dp_dir))
    print(f"Created datapack: {archive_path}")

    return Path(archive_path)


def preview_voxels(matrix: np.ndarray):
    """Show a 3D matplotlib preview of the voxel model."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib is required for preview. Install with: pip install matplotlib")
        return

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.voxels(matrix, facecolors="white", edgecolors="#cccccc", linewidth=0.1)
    ax.set_xlabel("X")
    ax.set_ylabel("Y")
    ax.set_zlabel("Z")
    ax.set_title("Stanford Bunny - Voxel Preview")

    # Equal aspect ratio
    shape = np.array(matrix.shape)
    max_dim = shape.max()
    for setter, size in zip(
        [ax.set_xlim, ax.set_ylim, ax.set_zlim], shape
    ):
        setter([0, max_dim])

    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Minecraft datapack of the Stanford Bunny"
    )
    parser.add_argument(
        "--height",
        type=int,
        default=30,
        help="Target height in blocks (default: 30)",
    )
    parser.add_argument(
        "--block",
        default="minecraft:white_concrete",
        help="Block type to use (default: minecraft:white_concrete)",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory (default: output)",
    )
    parser.add_argument(
        "--hollow",
        action="store_true",
        help="Generate hollow shell only (skip interior fill)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Show matplotlib 3D preview of the voxel model",
    )

    args = parser.parse_args()

    project_dir = Path(__file__).resolve().parent
    data_dir = project_dir / "data"
    output_dir = project_dir / args.output

    # Step 1: Download
    ply_path = download_bunny(data_dir)

    # Step 2: Voxelize
    matrix = voxelize_mesh(ply_path, args.height, args.hollow)

    # Step 3: Preview (optional)
    if args.preview:
        preview_voxels(matrix)

    # Step 4: Generate mcfunction
    commands = generate_mcfunction(matrix, args.block)
    setblock_count = sum(1 for c in commands if c.startswith("setblock"))
    print(f"\nsetblock commands: {setblock_count:,}")

    if setblock_count > 65536:
        print(
            f"WARNING: {setblock_count:,} commands exceeds default maxCommandChainLength (65,536)."
        )
        print("Consider reducing --height or using --hollow.")

    # Step 5: Package datapack
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = package_datapack(commands, output_dir)

    # Summary
    print("\n" + "=" * 60)
    print("Done!")
    print(f"  Datapack: {zip_path}")
    print(f"  Grid: {matrix.shape[0]} x {matrix.shape[1]} x {matrix.shape[2]}")
    print(f"  Blocks: {setblock_count:,}")
    print()
    print("Usage in Minecraft:")
    print(f"  1. Copy {zip_path.name} to your world's datapacks/ folder")
    print("  2. In-game: /reload")
    print("  3. Stand where you want the bunny and run:")
    print("     /function stanford_bunny:build")
    print("=" * 60)


if __name__ == "__main__":
    main()
