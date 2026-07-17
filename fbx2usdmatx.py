#!/usr/bin/env python3

import argparse
import os
import sys

# Ensure local directory and src directory are searched for the FBX SDK
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

try:
    import fbx
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
except ImportError as e:
    print(f"Error: Missing dependencies. {e}")
    print("This tool requires the Autodesk FBX SDK and Pixar USD API.")
    print("Recommended environment: Blender 4.0+ (comes with both pre-installed).")
    print("Usage: blender --background --python fbx2usdmatx.py -- [args]")
    sys.exit(1)

"""
fbx2usdmatx
A specialized utility to convert FBX scenes into modular USD assets
with full MaterialX Standard Surface shading and USD Preview support.
"""


class FBXToUSDMatX:
    def __init__(self, input_fbx, output_dir, tex_dir=None):
        self.input_fbx = input_fbx
        self.output_dir = output_dir
        self.assets_dir = os.path.join(output_dir, "assets")
        self.tex_dir = tex_dir or os.path.dirname(input_fbx)

        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir)

    def find_texture(self, mtl_name, suffix, fbx_mtl=None):
        """Searches for textures using MaterialX naming conventions OR actual FBX texture links."""
        # 1. Try to find actual texture from FBX Material properties
        if fbx_mtl:
            # Map suffix to FBX property names
            prop_map = {
                "basecolor": [
                    "DiffuseColor",
                    "Diffuse",
                    "base_color_map",
                    "diffuse_map",
                ],
                "roughness": ["ReflectionFactor", "Shininess", "roughness_map"],
                "normal": ["NormalMap", "Bump", "normal_map"],
                "metallic": ["Reflection", "metalness_map"],
            }

            for prop_key in prop_map.get(suffix, []):
                prop = fbx_mtl.FindProperty(prop_key)
                if not prop.IsValid():
                    # Fallback: scan all properties for texture connections if primary keys fail
                    p = fbx_mtl.GetFirstProperty()
                    while p.IsValid():
                        if (
                            p.GetSrcObjectCount(
                                fbx.FbxCriteria.ObjectType(fbx.FbxFileTexture.ClassId)
                            )
                            > 0
                        ):
                            print(f"    Scanning prop: {p.GetName()} for {suffix}")
                            # Check if the property name contains the suffix (e.g. 'Diffuse')
                            if suffix == "basecolor" and any(
                                x in p.GetName() for x in ["Diffuse", "Color"]
                            ):
                                prop = p
                                break
                            if suffix == "normal" and any(
                                x in p.GetName() for x in ["Normal", "Bump"]
                            ):
                                prop = p
                                break
                        p = fbx_mtl.GetNextProperty(p)

                if not prop or not prop.IsValid():
                    continue

                # Check for texture connected to property
                tex_count = prop.GetSrcObjectCount(
                    fbx.FbxCriteria.ObjectType(fbx.FbxFileTexture.ClassId)
                )
                if tex_count > 0:
                    print(f"    FOUND {tex_count} textures on {prop.GetName()}")
                    tex = prop.GetSrcObject(
                        fbx.FbxCriteria.ObjectType(fbx.FbxFileTexture.ClassId), 0
                    )
                    fbx_path = tex.GetFileName()
                    if fbx_path:
                        # Handle Windows paths in FBX on Linux
                        filename = fbx_path.replace("\\", "/").split("/")[-1]
                        print(
                            f"    Checking filename: '{filename}' from {prop.GetName()} (dir: {self.tex_dir})"
                        )
                        # Search for this specific filename in texture directories
                        subfolders = [
                            ".",
                            "KB3DTextures",
                            "KB3DTextures/4k",
                            "Textures",
                            "textures",
                            "photo",
                        ]
                        for sub in subfolders:
                            d = os.path.join(self.tex_dir, sub)
                            if not os.path.isdir(d):
                                continue
                            path = os.path.join(d, filename)
                            # CASE-INSENSITIVE CHECK
                            if not os.path.exists(path):
                                for f in os.listdir(d):
                                    if f.lower() == filename.lower():
                                        path = os.path.join(d, f)
                                        break

                            if os.path.exists(path):
                                # Convert to absolute path for USD
                                abs_path = os.path.abspath(path)
                                print(f"  [Found Texture] {suffix}: {abs_path}")
                                return abs_path
            print(f"  [Missing Texture] {suffix} (checked {prop_map.get(suffix)})")

        # 2. Fallback to name-based pattern matching
        extensions = [".png", ".jpg", ".tga", ".exr", ".tif"]
        search_patterns = [f"{mtl_name}_{suffix}", f"{mtl_name}{suffix}"]
        subfolders = [
            ".",
            "KB3DTextures",
            "KB3DTextures/4k",
            "Textures",
            "textures",
            "photo",
        ]

        for sub in subfolders:
            d = os.path.join(self.tex_dir, sub)
            if not os.path.isdir(d):
                continue
            for pattern in search_patterns:
                for ext in extensions:
                    path = os.path.join(d, pattern + ext)
                    if os.path.exists(path):
                        return path
        return None

    def create_mtlx_material(self, stage, mtl_path, fbx_mtl=None):
        """Creates a MaterialX Standard Surface + USD Preview shading network."""
        material = UsdShade.Material.Define(stage, mtl_path)
        mtl_name = mtl_path.name
        prim = material.GetPrim()

        # Apply MaterialX configuration metadata
        list_op = Sdf.TokenListOp()
        list_op.prependedItems = ["MaterialXConfigAPI"]
        prim.SetMetadata("apiSchemas", list_op)
        prim.CreateAttribute("config:mtlx:version", Sdf.ValueTypeNames.String).Set(
            "1.39"
        )

        # Define terminals
        mtlx_surf = material.CreateOutput("mtlx:surface", Sdf.ValueTypeNames.Token)
        mtlx_disp = material.CreateOutput("mtlx:displacement", Sdf.ValueTypeNames.Token)
        usd_surf = material.CreateOutput("surface", Sdf.ValueTypeNames.Token)

        # 1. Main MaterialX Shader
        shader = UsdShade.Shader.Define(
            stage, mtl_path.AppendChild("mtlxstandard_surface")
        )
        shader.CreateIdAttr("ND_standard_surface_surfaceshader")
        mtlx_surf.ConnectToSource(shader.ConnectableAPI(), "out")

        # 2. USD Preview Shader (Viewport)
        preview = UsdShade.Shader.Define(
            stage, mtl_path.AppendChild("mtlxstandard_preview")
        )
        preview.CreateIdAttr("UsdPreviewSurface")
        usd_surf.ConnectToSource(preview.ConnectableAPI(), "surface")

        # 3. Displacement stub
        displace = UsdShade.Shader.Define(
            stage, mtl_path.AppendChild("mtlxdisplacement")
        )
        displace.CreateIdAttr("ND_displacement_float")
        mtlx_disp.ConnectToSource(displace.ConnectableAPI(), "out")

        # 4. Preview UV Primvar Reader
        uv_reader = UsdShade.Shader.Define(
            stage, mtl_path.AppendChild("mtlxstandard_preview_uv")
        )
        uv_reader.CreateIdAttr("UsdPrimvarReader_float2")
        uv_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        uv_out = uv_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

        def hook_tex(suffix, surf_in, prev_in, node_id, is_color=True):
            tex_path = self.find_texture(mtl_name, suffix, fbx_mtl)
            if not tex_path:
                return None

            img = UsdShade.Shader.Define(
                stage, mtl_path.AppendChild(f"mtlximage_{suffix}")
            )
            img.CreateIdAttr(node_id)
            img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(tex_path)

            out_type = (
                Sdf.ValueTypeNames.Color3f if is_color else Sdf.ValueTypeNames.Float
            )
            img_out = img.CreateOutput("out", out_type)

            # Connect to MaterialX
            shader.CreateInput(surf_in, out_type).ConnectToSource(img_out)

            # Connect to Preview
            if prev_in:
                prev_tex = UsdShade.Shader.Define(
                    stage,
                    mtl_path.AppendChild(f"mtlxstandard_preview_texture_{prev_in}"),
                )
                prev_tex.CreateIdAttr("UsdUVTexture")
                prev_tex.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(tex_path)
                prev_tex.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(
                    uv_out
                )

                p_out_name = "rgb" if is_color else "r"
                p_out_type = (
                    Sdf.ValueTypeNames.Color3f if is_color else Sdf.ValueTypeNames.Float
                )
                preview.CreateInput(prev_in, p_out_type).ConnectToSource(
                    prev_tex.CreateOutput(p_out_name, p_out_type)
                )
            return img_out

        hook_tex("basecolor", "base_color", "diffuseColor", "ND_image_color3")
        hook_tex(
            "roughness", "specular_roughness", "roughness", "ND_image_float", False
        )
        hook_tex("metallic", "metalness", "metallic", "ND_image_float", False)

        normal_path = self.find_texture(mtl_name, "normal", fbx_mtl)
        if normal_path:
            img = UsdShade.Shader.Define(
                stage, mtl_path.AppendChild("mtlximage_normal")
            )
            img.CreateIdAttr("ND_image_vector3")
            img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(normal_path)

            nmap = UsdShade.Shader.Define(stage, mtl_path.AppendChild("mtlxnormalmap"))
            nmap.CreateIdAttr("ND_normalmap_vector3")
            nmap.CreateInput("in", Sdf.ValueTypeNames.Vector3f).ConnectToSource(
                img.CreateOutput("out", Sdf.ValueTypeNames.Vector3f)
            )
            shader.CreateInput("normal", Sdf.ValueTypeNames.Vector3f).ConnectToSource(
                nmap.ConnectableAPI(), "out"
            )

        return material

    def convert_asset(self, fbx_node):
        """Converts a specific FBX node branch into a standalone USD file."""
        asset_name = fbx_node.GetName().replace(":", "_").replace(" ", "_")
        output_path = os.path.join(self.assets_dir, f"{asset_name}.usd")

        stage = Usd.Stage.CreateNew(output_path)
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        root = UsdGeom.Xform.Define(stage, Sdf.Path("/" + asset_name))
        stage.SetDefaultPrim(root.GetPrim())

        geo_scope = UsdGeom.Scope.Define(stage, root.GetPath().AppendPath("geo"))
        mtl_scope = UsdGeom.Scope.Define(stage, root.GetPath().AppendPath("mtl"))
        local_materials = {}

        def get_mtl(fbx_mtl):
            m_name = (
                fbx_mtl.GetName().replace(":", "_").replace(" ", "_").replace("#", "_")
            )
            if m_name not in local_materials:
                local_materials[m_name] = self.create_mtlx_material(
                    stage, mtl_scope.GetPath().AppendChild(m_name), fbx_mtl
                )
            return local_materials[m_name]

        def process_node(node, parent_path):
            attr = node.GetNodeAttribute()
            cur_path = parent_path

            if attr and attr.GetAttributeType() == fbx.FbxNodeAttribute.EType.eMesh:
                mesh_name = node.GetName().replace(":", "_").replace(" ", "_")
                mesh_path = parent_path.AppendChild(mesh_name)
                usd_mesh = UsdGeom.Mesh.Define(stage, mesh_path)
                UsdShade.MaterialBindingAPI.Apply(usd_mesh.GetPrim())

                fbx_mesh = node.GetMesh()
                gt = node.EvaluateGlobalTransform()

                # Geometry Data
                pts = [
                    Gf.Vec3f(gt.MultT(p)[0], gt.MultT(p)[1], gt.MultT(p)[2])
                    for p in fbx_mesh.GetControlPoints()
                ]
                usd_mesh.CreatePointsAttr(pts)
                usd_mesh.CreateFaceVertexCountsAttr(
                    [
                        fbx_mesh.GetPolygonSize(f)
                        for f in range(fbx_mesh.GetPolygonCount())
                    ]
                )
                usd_mesh.CreateFaceVertexIndicesAttr(
                    [
                        fbx_mesh.GetPolygonVertex(f, v)
                        for f in range(fbx_mesh.GetPolygonCount())
                        for v in range(fbx_mesh.GetPolygonSize(f))
                    ]
                )

                # UV Data (st)
                if fbx_mesh.GetElementUVCount() > 0:
                    uvs = fbx_mesh.GetElementUV(0).GetDirectArray()
                    st = [
                        Gf.Vec2f(
                            uvs.GetAt(fbx_mesh.GetTextureUVIndex(f, v))[0],
                            uvs.GetAt(fbx_mesh.GetTextureUVIndex(f, v))[1],
                        )
                        for f in range(fbx_mesh.GetPolygonCount())
                        for v in range(fbx_mesh.GetPolygonSize(f))
                    ]
                    UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                        "st",
                        Sdf.ValueTypeNames.TexCoord2fArray,
                        UsdGeom.Tokens.faceVarying,
                    ).Set(st)

                # Material Binding (Subset Support)
                mtl_el = fbx_mesh.GetElementMaterial(0)
                mtl_count = node.GetMaterialCount()

                if mtl_el and mtl_count > 1:
                    polys_by_mtl = {}
                    indices = mtl_el.GetIndexArray()
                    for f in range(fbx_mesh.GetPolygonCount()):
                        idx = indices.GetAt(f)
                        if idx not in polys_by_mtl:
                            polys_by_mtl[idx] = []
                        polys_by_mtl[idx].append(f)

                    for idx, faces in polys_by_mtl.items():
                        if idx < mtl_count:
                            fbx_mtl = node.GetMaterial(idx)
                            subset_name = f"mat_{fbx_mtl.GetName().replace(':', '_').replace(' ', '_').replace('#', '_')}"
                            subset = UsdGeom.Subset.CreateGeomSubset(
                                usd_mesh,
                                subset_name,
                                UsdGeom.Tokens.face,
                                faces,
                                UsdShade.Tokens.materialBind,
                            )
                            UsdGeom.Subset.SetFamilyType(
                                usd_mesh,
                                UsdShade.Tokens.materialBind,
                                UsdGeom.Tokens.partition,
                            )
                            UsdShade.MaterialBindingAPI.Apply(subset.GetPrim()).Bind(
                                get_mtl(fbx_mtl)
                            )
                elif mtl_count > 0:
                    UsdShade.MaterialBindingAPI(usd_mesh.GetPrim()).Bind(
                        get_mtl(node.GetMaterial(0))
                    )

            elif node != fbx_node:
                cur_path = parent_path.AppendChild(
                    node.GetName().replace(":", "_").replace(" ", "_")
                )
                UsdGeom.Xform.Define(stage, cur_path)

            for i in range(node.GetChildCount()):
                process_node(node.GetChild(i), cur_path)

        process_node(fbx_node, geo_scope.GetPath())
        stage.GetRootLayer().Save()
        return output_path

    def run(self):
        """Main execution loop for FBX Scene to Modular USD Assembly."""
        manager = fbx.FbxManager.Create()
        ios = fbx.FbxIOSettings.Create(manager, fbx.IOSROOT)
        importer = fbx.FbxImporter.Create(manager, "")
        if not importer.Initialize(self.input_fbx, -1, ios):
            print("Error: FBX Importer failed to initialize.")
            return

        scene = fbx.FbxScene.Create(manager, "ImportScene")
        importer.Import(scene)

        # Standardize scene environment
        fbx.FbxAxisSystem.MayaYUp.ConvertScene(scene)
        fbx.FbxSystemUnit.m.ConvertScene(scene)

        master_path = os.path.join(
            self.output_dir,
            os.path.splitext(os.path.basename(self.input_fbx))[0] + "_master.usd",
        )
        master_stage = Usd.Stage.CreateNew(master_path)
        UsdGeom.SetStageUpAxis(master_stage, UsdGeom.Tokens.y)
        root = UsdGeom.Xform.Define(master_stage, "/root")
        master_stage.SetDefaultPrim(root.GetPrim())

        fbx_root = scene.GetRootNode()
        for i in range(fbx_root.GetChildCount()):
            node = fbx_root.GetChild(i)
            asset_name = node.GetName().replace(":", "_").replace(" ", "_")
            print(f"Processing Asset: {asset_name}")

            asset_usd = self.convert_asset(node)

            # Reference in assembly
            ref_path = root.GetPath().AppendChild(asset_name)
            ref_prim = master_stage.OverridePrim(ref_path)
            ref_prim.GetReferences().AddReference(
                os.path.relpath(asset_usd, self.output_dir)
            )

        master_stage.GetRootLayer().Save()
        print(f"\nSuccessfully converted FBX to MatX-enabled USD.")
        print(f"Master Assembly: {master_path}")
        manager.Destroy()


if __name__ == "__main__":
    if "OCIO" in os.environ:
        del os.environ["OCIO"]

    parser = argparse.ArgumentParser(description="FBX to USD + MaterialX Converter")
    parser.add_argument("input", help="Path to input FBX file")
    parser.add_argument("output", help="Output directory")
    parser.add_argument(
        "--textures", help="Optional override for texture search directory"
    )

    if "--" in sys.argv:
        cli_args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    else:
        cli_args = parser.parse_args()

    FBXToUSDMatX(cli_args.input, cli_args.output, cli_args.textures).run()
