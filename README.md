# fbx2usdmatx

A Python utility designed to convert FBX scenes into modular, production-ready USD assets with high-fidelity MaterialX shading.

## Key Features

- **Modular Output**: Automatically splits large FBX scenes into individual standalone USD files for each top-level branch.
- **MaterialX Shading**: Implements full MaterialX shading networks using the `ND_standard_surface_surfaceshader` closure, matching standard production templates (e.g., Houdini/Solaris).
- **Multi-Material Support**: Detects and extracts per-polygon material assignments from FBX, generating valid `UsdGeomSubset` partitions with localized bindings.
- **Automatic Texture Discovery**: Scans for common texture suffixes (`basecolor`, `roughness`, `metallic`, `normal`) in standardized directory structures.
- **Viewport Ready**: Includes a `UsdPreviewSurface` network connected via `UsdUVTexture` nodes for high-quality real-time viewport feedback.
- **Full UV Extraction**: Maps the first UV set to the standard `st` primvar on every mesh.
- **Master Assembly**: Generates a master assembly USD file that references all modular assets at their original coordinates.

## Prerequisites

The easiest way to run this tool is using **Blender 4.0+** as it comes bundled with the FBX SDK and Pixar USD API.

Alternatively, you can run it via a standalone Python 3 environment if you have the following modules installed:
- `fbx` (Autodesk FBX Python SDK)
- `pxr` (Pixar USD API)

## Usage

### Using Blender (Recommended)

Run the script in background mode using Blender's internal Python interpreter:

```bash
blender --background --python fbx2usdmatx.py -- <input_fbx_path> <output_directory>
```

### Using Standard Python

```bash
python3 fbx2usdmatx.py <input_fbx_path> <output_directory>
```

### Optional Arguments

- `--textures <path>`: Manually specify the root directory where textures are located if they are not stored relative to the FBX file.

## Output Structure

The tool generates an encapsulated structure ready for referencing in any USD pipeline:

```text
output_directory/
├── <input_name>_master.usd    # Master assembly referencing all assets
└── assets/
    ├── asset_01.usd           # Standalone asset with local /geo and /mtl
    ├── asset_02.usd
    └── ...
```

Each asset USD contains:
- `/<AssetName>/geo`: Geometry hierarchy with `st` UVs and correctly assigned GeomSubsets.
- `/<AssetName>/mtl`: MaterialX shading networks with image loaders and Preview Surface support.

## License

MIT