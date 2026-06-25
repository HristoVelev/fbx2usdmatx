<<<<<<< HEAD
# fbx2usdmatx
FBX to USD/MaterialX convertor. Python script, uses Blender
=======
# FBX to USD Kitbash Converter

A specialized Python utility designed to convert complex FBX kitbash libraries into modular, production-ready USD assets with high-fidelity MaterialX shading.

## Key Features

- **Modular Output**: Automatically splits large FBX scenes into individual standalone USD files per asset branch.
- **Centered at Origin**: Recursively calculates the world-space bounding box of each component and applies a local offset to ensure every asset is perfectly centered at `(0,0,0)`.
- **Master Assembly**: Generates a master assembly USD file that references all modular assets at their original world coordinates.
- **Template-Driven Shading**: Implements a full MaterialX shading network using the `ND_standard_surface_surfaceshader` closure, matching standard production templates (e.g., Houdini/Solaris).
- **Multi-Material Support**: Detects and extracts per-polygon material assignments from FBX, generating valid `UsdGeomSubset` partitions with localized bindings.
- **Automatic Texture Discovery**: Optimized search logic for Kitbash3D style directory structures (scans for `4k`, `Textures`, etc.) and automatically maps `basecolor`, `roughness`, `metallic`, and `normal` maps.
- **Viewport Ready**: Includes a `UsdPreviewSurface` network connected to the same textures for real-time viewport feedback.
- **Full UV Extraction**: Maps the first UV set to the standard `st` primvar on every mesh.

## Prerequisites

The easiest way to run this tool is using **Blender 4.0+** as it comes bundled with the FBX SDK and Pixar USD API.

Alternatively, you can run it via a standalone Python 3 environment if you have the following modules installed:
- `fbx` (Autodesk FBX Python SDK)
- `pxr` (Pixar USD API)

## Usage

### Using Blender (Recommended)

Run the script in background mode using Blender's internal Python interpreter:

```bash
blender --background --python fbx2usd_kitbash.py -- <input_fbx_path> <output_directory>
```

### Using Standard Python

```bash
python3 fbx2usd_kitbash.py <input_fbx_path> <output_directory>
```

### Optional Arguments

- `--textures <path>`: Manually specify the root directory where textures are located if they are not relative to the FBX file.

## Output Structure

The tool generates a clean, encapsulated structure:

```text
output_directory/
├── kitbash_master.usd         # Master assembly referencing all assets
└── assets/
    ├── asset_01.usd           # Standalone, centered asset with local /geo and /mtl
    ├── asset_02.usd
    └── ...
```

Each asset USD contains:
- `/AssetName/geo`: Geometry hierarchy with `st` UVs.
- `/AssetName/mtl`: MaterialX shading networks with image loaders.

## License

MIT
>>>>>>> 085e98f (Initial release of FBX to USD Kitbash Converter)
