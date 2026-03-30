# minecraft-stanford-bunny

A datapack generator that voxelizes the Stanford Bunny and places it in Minecraft.

Works in vanilla Minecraft — build the Stanford Bunny with a single command.

[日本語ドキュメント](README.ja.md)

## Quick Start

1. Copy `output/stanford-bunny-datapack.zip` into your world's `datapacks/` folder
2. In-game: `/reload`
3. Stand where you want the bunny and run:
   ```
   /function stanford_bunny:build
   ```

## Generate from Source

```bash
pip install -r requirements.txt
python voxelize.py
```

### CLI Options

| Option | Default | Description |
|---|---|---|
| `--height N` | 60 | Target height in blocks |
| `--block ID` | `minecraft:white_concrete` | Block type to use |
| `--output DIR` | `output` | Output directory |
| `--hollow` | - | Generate hollow shell only |
| `--preview` | - | Show 3D preview with matplotlib |

### Examples

```bash
# 40-block tall bunny made of smooth quartz
python voxelize.py --height 40 --block minecraft:smooth_quartz

# Hollow bunny (fewer blocks)
python voxelize.py --hollow

# Preview before generating
python voxelize.py --preview
```

## Placement

The player's feet position becomes the bottom-left-front corner of the bunny.

| Direction | Axis | Extent |
|---|---|---|
| East (+X) | Width | 62 blocks |
| Up (+Y) | Height | 61 blocks |
| South (+Z) | Depth | 48 blocks |

The bunny faces **North (-Z)**. Walk to the north side to see its face.

## Specs

- Supported versions: Minecraft Java Edition 1.20 – 1.21.5
- Default size: 62 x 61 x 48 blocks, ~52,000 blocks total
- Stays within the default `maxCommandChainLength` (65,536)

## Credits

3D model: [The Stanford 3D Scanning Repository](https://graphics.stanford.edu/data/3Dscanrep/) — Stanford Computer Graphics Laboratory
