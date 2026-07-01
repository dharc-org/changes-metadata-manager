<!--
SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>

SPDX-License-Identifier: CC-BY-4.0
-->

# Naming convention

This page documents the directory layout and file naming rules used across the Aldrovandi collection.

## Directory structure

```
aldrovandi/
  sala{1-6}/
    {nr_oggetto}/
      raw/
      rawp/
      dcho/
      dchoo/
```

Each sala (room) corresponds to a section of the exhibition. Inside each sala, folders are named after the object they represent, typically following the pattern `S{sala}-{nr}-{institution}_{objectname}`.

## Path pattern

The full path to a specific file is:

```
/<aldrovandi>/<salax>/<nr_oggetto>/<stage>/<nr>_<stage>_<type>.<extension>
```

## File types by stage

| Stage | Capture method | Extensions | 3D type |
|-------|---------------|------------|---------|
| raw | Photogrammetry | png, jpg, tif, nef, raw, crw, arw, cr2, rw2 | photo |
| raw | Scanner | scan, a3d + data/ | scan / project |
| rawp | - | obj + mtl / fbx, png, jpg, jpeg | 3dmodel, texture |
| dcho | - | obj + mtl / fbx, png, jpg, jpeg | 3dmodel, texture |
| dchoo | - | gltf + bin, png, jpg, jpeg | 3dmodel, texture |

## Export components

3D model formats produce multiple files:

- **OBJ** (rawp, dcho): `.obj` geometry + `.mtl` material definitions. Texture types are identified inside the MTL file:
  - `map_Kd` = diffuse map
  - `map_Bump` = normal map
  - `map_Ns` = roughness map
  - `map_Pm` = metalness map

- **glTF** (dchoo): `.gltf` scene description + `.bin` binary data. Texture roles are assigned in the materials section of the glTF JSON, through `baseColorTexture`, `normalTexture`, and `metallicRoughnessTexture` properties.

## Special cases

- **Materials folder**: some objects have a `materials/` folder with supplementary files outside the standard taxonomy. These are not processed.
- **Grouped objects**: objects like 98a, 98b, 98c are physically distinct but catalogued under the same base number. Each variant has its own subfolder within the stage directories. For Zenodo uploads, grouped objects are merged into a single archive.
- **Scanner projects**: Artec `.a3d` files reference a `data/` subdirectory by its original name. Neither the project file nor its data folder should be renamed.
