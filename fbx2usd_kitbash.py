#!/usr/bin/env python3

import os
import sys

# Ensure the local FBX SDK can be found in the current script directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import fbx
except ImportError:
    print("Error: Autodesk FBX SDK ('fbx' module) not found.")
    sys.exit(1)

try:
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade
except ImportError:
    print("Error: Pixar USD API ('pxr' module) not found.")
    sys.exit(1)

"""
FBX to USD Kitbash Converter (Modular Multi-Material Edition)
- Modular: One standalone USD per asset + Master Assembly.
- Centered: Each asset centered at (0,0,0) locally.
- Shading: MaterialX Standard Surface matching project template.
- Multi-Material: Correct extraction of per-face materials via GeomSubsets.
- UVs: Full UV extraction to 'st' primvar.
"""


def get_node_bounds(node, bbox_min=None, bbox_max=None):
    if bbox_min is None:
        bbox_min = [float("inf")] * 3
    if bbox_max is None:
        bbox_max = [float("-inf")] * 3

    attr = node.GetNodeAttribute()
    if attr and attr.GetAttributeType() == fbx.FbxNodeAttribute.EType.eMesh:
        mesh = node.GetMesh()
        gt = node.EvaluateGlobalTransform()
        control_points = mesh.GetControlPoints()
        for i in range(mesh.GetControlPointsCount()):
            p = control_points[i]
            p_world = gt.MultT(p)
            for j in range(3):
                bbox_min[j] = min(bbox_min[j], p_world[j])
                bbox_max[j] = max(bbox_max[j], p_world[j])

    for i in range(node.GetChildCount()):
        get_node_bounds(node.GetChild(i), bbox_min, bbox_max)
    return bbox_min, bbox_max


def find_texture(base_dir, mtl_name, suffix):
    """
    Search for textures in KB3D standardized locations relative to the FBX file.
    """
    extensions = [".png", ".jpg", ".tga", ".exr", ".tif"]
    search_patterns = [f"{mtl_name}_{suffix}", f"{mtl_name}{suffix}"]
    subfolders = [".", "KB3DTextures", "KB3DTextures/4k", "Textures", "textures"]

    for sub in subfolders:
        search_dir = os.path.join(base_dir, sub)
        if not os.path.isdir(search_dir):
            continue
        for pattern in search_patterns:
            for ext in extensions:
                path = os.path.join(search_dir, pattern + ext)
                if os.path.exists(path):
                    return path
    return None


def create_mtlx_material(stage, mtl_path, tex_base_dir):
    """
    Creates a MaterialX material matching material_fixed.usd exactly.
    """
    material = UsdShade.Material.Define(stage, mtl_path)
    mtl_name = mtl_path.name
    prim = material.GetPrim()

    # Apply MaterialXConfigAPI metadata manually to match template
    list_op = Sdf.TokenListOp()
    list_op.prependedItems = ["MaterialXConfigAPI"]
    prim.SetMetadata("apiSchemas", list_op)
    prim.CreateAttribute("config:mtlx:version", Sdf.ValueTypeNames.String).Set("1.39")

    # Define Output Terminals
    mtlx_surf_out = material.CreateOutput("mtlx:surface", Sdf.ValueTypeNames.Token)
    mtlx_disp_out = material.CreateOutput("mtlx:displacement", Sdf.ValueTypeNames.Token)
    usd_surf_out = material.CreateOutput("surface", Sdf.ValueTypeNames.Token)

    # 1. MaterialX Standard Surface Shader
    shader = UsdShade.Shader.Define(stage, mtl_path.AppendChild("mtlxstandard_surface"))
    shader.CreateIdAttr("ND_standard_surface_surfaceshader")
    mtlx_surf_out.ConnectToSource(shader.ConnectableAPI(), "out")

    # 2. USD Preview Surface
    preview = UsdShade.Shader.Define(
        stage, mtl_path.AppendChild("mtlxstandard_preview")
    )
    preview.CreateIdAttr("UsdPreviewSurface")
    usd_surf_out.ConnectToSource(preview.ConnectableAPI(), "surface")

    # 3. Displacement Stub
    displace = UsdShade.Shader.Define(stage, mtl_path.AppendChild("mtlxdisplacement"))
    displace.CreateIdAttr("ND_displacement_float")
    mtlx_disp_out.ConnectToSource(displace.ConnectableAPI(), "out")

    # 4. Preview UV Reader
    uv_reader = UsdShade.Shader.Define(
        stage, mtl_path.AppendChild("mtlxstandard_preview_uv")
    )
    uv_reader.CreateIdAttr("UsdPrimvarReader_float2")
    uv_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    uv_out = uv_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    # Shading Network Helper
    def hook_tex(suffix, surf_in, prev_in, node_id, is_color=True):
        tex_path = find_texture(tex_base_dir, mtl_name, suffix)
        if not tex_path:
            return None

        # MaterialX Image node
        img = UsdShade.Shader.Define(stage, mtl_path.AppendChild(f"mtlximage_{suffix}"))
        img.CreateIdAttr(node_id)
        img.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(tex_path)
        out_type = Sdf.ValueTypeNames.Color3f if is_color else Sdf.ValueTypeNames.Float
        img_out = img.CreateOutput("out", out_type)
        shader.CreateInput(surf_in, out_type).ConnectToSource(img_out)

        # Preview Texture node
        if prev_in:
            prev_tex = UsdShade.Shader.Define(
                stage, mtl_path.AppendChild(f"mtlxstandard_preview_texture_{prev_in}")
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
            p_out = prev_tex.CreateOutput(p_out_name, p_out_type)
            preview.CreateInput(prev_in, p_out_type).ConnectToSource(p_out)

        return img_out

    hook_tex("basecolor", "base_color", "diffuseColor", "ND_image_color3")
    hook_tex("roughness", "specular_roughness", "roughness", "ND_image_float", False)
    hook_tex("metallic", "metalness", "metallic", "ND_image_float", False)

    # Normal Map
    normal_path = find_texture(tex_base_dir, mtl_name, "normal")
    if normal_path:
        img_node = UsdShade.Shader.Define(
            stage, mtl_path.AppendChild("mtlximage_normal")
        )
        img_node.CreateIdAttr("ND_image_vector3")
        img_node.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(normal_path)
        img_out = img_node.CreateOutput("out", Sdf.ValueTypeNames.Vector3f)

        norm_map = UsdShade.Shader.Define(stage, mtl_path.AppendChild("mtlxnormalmap"))
        norm_map.CreateIdAttr("ND_normalmap_vector3")
        norm_map.CreateInput("in", Sdf.ValueTypeNames.Vector3f).ConnectToSource(img_out)
        norm_map_out = norm_map.CreateOutput("out", Sdf.ValueTypeNames.Vector3f)

        shader.CreateInput("normal", Sdf.ValueTypeNames.Vector3f).ConnectToSource(
            norm_map_out
        )

    return material


def convert_single_asset(fbx_node, output_path, offset, tex_dir):
    if os.path.exists(output_path):
        os.remove(output_path)
    stage = Usd.Stage.CreateNew(output_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    asset_name = fbx_node.GetName().replace(":", "_").replace(" ", "_")
    asset_root = UsdGeom.Xform.Define(stage, Sdf.Path("/" + asset_name))
    stage.SetDefaultPrim(asset_root.GetPrim())

    geo_scope_path = asset_root.GetPath().AppendPath("geo")
    mtl_scope_path = asset_root.GetPath().AppendPath("mtl")
    UsdGeom.Scope.Define(stage, geo_scope_path)
    UsdGeom.Scope.Define(stage, mtl_scope_path)

    local_material_map = {}

    def get_or_create_material(fbx_mtl):
        m_name = fbx_mtl.GetName().replace(":", "_").replace(" ", "_")
        if m_name not in local_material_map:
            m_path = mtl_scope_path.AppendChild(m_name)
            local_material_map[m_name] = create_mtlx_material(stage, m_path, tex_dir)
        return local_material_map[m_name]

    def process_node(node, usd_parent_path):
        attr = node.GetNodeAttribute()
        current_usd_path = usd_parent_path

        if attr and attr.GetAttributeType() == fbx.FbxNodeAttribute.EType.eMesh:
            mesh_name = node.GetName().replace(":", "_").replace(" ", "_")
            mesh_path = usd_parent_path.AppendChild(mesh_name)
            usd_mesh = UsdGeom.Mesh.Define(stage, mesh_path)
            current_usd_path = mesh_path

            # Apply schemas
            UsdShade.MaterialBindingAPI.Apply(usd_mesh.GetPrim())

            fbx_mesh = node.GetMesh()
            gt = node.EvaluateGlobalTransform()
            control_points = fbx_mesh.GetControlPoints()

            # Vertices
            points = [
                Gf.Vec3f(
                    gt.MultT(p)[0] + offset[0],
                    gt.MultT(p)[1] + offset[1],
                    gt.MultT(p)[2] + offset[2],
                )
                for p in control_points
            ]
            usd_mesh.CreatePointsAttr(points)

            # Topology
            face_counts = [
                fbx_mesh.GetPolygonSize(f) for f in range(fbx_mesh.GetPolygonCount())
            ]
            face_indices = []
            for f in range(fbx_mesh.GetPolygonCount()):
                for v in range(fbx_mesh.GetPolygonSize(f)):
                    face_indices.append(fbx_mesh.GetPolygonVertex(f, v))
            usd_mesh.CreateFaceVertexCountsAttr(face_counts)
            usd_mesh.CreateFaceVertexIndicesAttr(face_indices)

            # UVs (st primvar)
            if fbx_mesh.GetElementUVCount() > 0:
                uv_element = fbx_mesh.GetElementUV(0)
                direct_array = uv_element.GetDirectArray()
                st_values = []
                for f in range(fbx_mesh.GetPolygonCount()):
                    for v in range(fbx_mesh.GetPolygonSize(f)):
                        idx = fbx_mesh.GetTextureUVIndex(f, v)
                        uv = direct_array.GetAt(idx)
                        st_values.append(Gf.Vec2f(uv[0], uv[1]))
                st_primvar = UsdGeom.PrimvarsAPI(usd_mesh).CreatePrimvar(
                    "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
                )
                st_primvar.Set(st_values)

            # Materials & GeomSubsets
            mtl_element = fbx_mesh.GetElementMaterial(0)
            fbx_mtl_count = node.GetMaterialCount()

            if mtl_element and fbx_mtl_count > 1:
                polys_by_mtl = {}
                mapping = mtl_element.GetMappingMode()
                reference = mtl_element.GetReferenceMode()

                for f in range(fbx_mesh.GetPolygonCount()):
                    mtl_idx = -1
                    if mapping == fbx.FbxLayerElement.EMappingMode.eByPolygon:
                        if (
                            reference
                            == fbx.FbxLayerElement.EReferenceMode.eIndexToDirect
                        ):
                            mtl_idx = mtl_element.GetIndexArray().GetAt(f)
                        else:
                            mtl_idx = f
                    elif mapping == fbx.FbxLayerElement.EMappingMode.eAllSame:
                        mtl_idx = mtl_element.GetIndexArray().GetAt(0)

                    if mtl_idx >= 0:
                        if mtl_idx not in polys_by_mtl:
                            polys_by_mtl[mtl_idx] = []
                        polys_by_mtl[mtl_idx].append(f)

                for mtl_idx, polygon_indices in polys_by_mtl.items():
                    if mtl_idx < fbx_mtl_count:
                        fbx_mtl = node.GetMaterial(mtl_idx)
                        usd_mtl = get_or_create_material(fbx_mtl)
                        subset_name = f"mat_{fbx_mtl.GetName().replace(':', '_').replace(' ', '_')}"
                        subset = UsdGeom.Subset.CreateGeomSubset(
                            usd_mesh,
                            subset_name,
                            UsdGeom.Tokens.face,
                            polygon_indices,
                            UsdShade.Tokens.materialBind,
                        )
                        UsdGeom.Subset.SetFamilyType(
                            usd_mesh,
                            UsdShade.Tokens.materialBind,
                            UsdGeom.Tokens.partition,
                        )

                        # Apply MaterialBindingAPI to the subset prim and bind
                        UsdShade.MaterialBindingAPI.Apply(subset.GetPrim())
                        UsdShade.MaterialBindingAPI(subset.GetPrim()).Bind(usd_mtl)
            elif fbx_mtl_count > 0:
                UsdShade.MaterialBindingAPI(usd_mesh.GetPrim()).Bind(
                    get_or_create_material(node.GetMaterial(0))
                )
        else:
            if node != fbx_node:
                node_name = node.GetName().replace(":", "_").replace(" ", "_")
                current_usd_path = usd_parent_path.AppendChild(node_name)
                UsdGeom.Xform.Define(stage, current_usd_path)

        for j in range(node.GetChildCount()):
            process_node(node.GetChild(j), current_usd_path)

    process_node(fbx_node, geo_scope_path)
    stage.GetRootLayer().Save()


def run_conversion(fbx_path, output_dir, target_asset=None):
    print(f"Loading FBX: {fbx_path}")
    tex_dir = os.path.dirname(fbx_path)
    manager = fbx.FbxManager.Create()
    ios = fbx.FbxIOSettings.Create(manager, fbx.IOSROOT)
    importer = fbx.FbxImporter.Create(manager, "")
    importer.Initialize(fbx_path, -1, ios)
    scene = fbx.FbxScene.Create(manager, "")
    importer.Import(scene)
    importer.Destroy()

    fbx.FbxAxisSystem.MayaYUp.ConvertScene(scene)
    fbx.FbxSystemUnit.m.ConvertScene(scene)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    assets_dir = os.path.join(output_dir, "assets")
    if not os.path.exists(assets_dir):
        os.makedirs(assets_dir)

    root_node = scene.GetRootNode()
    master_path = os.path.join(
        output_dir, os.path.splitext(os.path.basename(fbx_path))[0] + "_master.usd"
    )
    master_stage = Usd.Stage.CreateNew(master_path)
    UsdGeom.SetStageUpAxis(master_stage, UsdGeom.Tokens.y)
    master_root = UsdGeom.Xform.Define(master_stage, "/root")
    master_stage.SetDefaultPrim(master_root.GetPrim())

    for i in range(root_node.GetChildCount()):
        asset_node = root_node.GetChild(i)
        asset_name = asset_node.GetName()
        if target_asset and target_asset.lower() not in asset_name.lower():
            continue

        print(f"Processing: {asset_name}")
        b_min, b_max = get_node_bounds(asset_node)
        if b_min[0] == float("inf"):
            continue
        center = Gf.Vec3d(
            (b_min[0] + b_max[0]) * 0.5,
            (b_min[1] + b_max[1]) * 0.5,
            (b_min[2] + b_max[2]) * 0.5,
        )

        asset_usd_filename = f"{asset_name.replace(':', '_').replace(' ', '_')}.usd"
        convert_single_asset(
            asset_node, os.path.join(assets_dir, asset_usd_filename), -center, tex_dir
        )

        ref_path = Sdf.Path("/root").AppendChild(
            asset_name.replace(":", "_").replace(" ", "_")
        )
        ref_prim = master_stage.OverridePrim(ref_path)
        ref_prim.GetReferences().AddReference(
            os.path.join("assets", asset_usd_filename)
        )
        UsdGeom.Xformable(ref_prim).AddTranslateOp().Set(center)

    master_stage.GetRootLayer().Save()
    print(f"Conversion Complete. Master: {master_path}")
    manager.Destroy()


if __name__ == "__main__":
    fbx_in = "/mnt/archive/lib/global/assets/kitbash3d_gaea/kb3d_gaea.fbxobj.native/kb3d_gaea-native.fbx"
    out_dir = os.path.join(os.getcwd(), "..", "out", "gaea_v17")
    if "--" in sys.argv:
        args = sys.argv[sys.argv.index("--") + 1 :]
        if len(args) >= 1:
            fbx_in = args[0]
        if len(args) >= 2:
            out_dir = args[1]
    run_conversion(fbx_in, out_dir)
