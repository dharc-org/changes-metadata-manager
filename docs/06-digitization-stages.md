<!--
SPDX-FileCopyrightText: 2025-2026 Arcangelo Massari <arcangelo.massari@unibo.it>

SPDX-License-Identifier: CC-BY-4.0
-->

# Digitization stages

Every digitized object goes through a pipeline of four stages. Each stage builds on the previous ones, and the metadata is cumulative: a `dcho` folder contains triples from `raw`, `rawp`, and `dcho` steps.

## Stages

### raw

The original acquisition output. For photogrammetry-based objects, this means the photographs (PNG, JPG, TIF, NEF, RAW, ARW, CR2, RW2). For scanner-based objects, this is either `.scan` files or an Artec project (`.a3d` file with its `data/` directory).

**Processing step**: 00

### rawp

The processed raw model. This is the first 3D output after the initial processing of raw data: an OBJ or FBX file, sometimes accompanied by a diffuse texture (PNG/JPG).

Export components:
- OBJ: `.obj` + `.mtl` (material definitions)
- FBX: standalone

**Processing steps**: 00, 01

### dcho

The Digital Cultural Heritage Object. This is the refined 3D model after geometry corrections, with a full set of PBR textures:

- Diffuse map (`map_Kd` in MTL files)
- Normal map (`map_Bump`)
- Roughness map (`map_Ns`)
- Metalness map (`map_Pm`)

Models can be multi-texture, meaning they may include multiple diffuse maps and additional PBR maps.

**Processing steps**: 00, 01, 02

### dchoo

The optimized version for web-based real-time rendering. Exported as glTF (`.gltf` + `.bin`) with associated textures. The glTF file links textures through a three-level indirection: `images[]` (file references), `textures[]` (image bindings), and `materials[]` (role assignment: `baseColorTexture`, `normalTexture`, `metallicRoughnessTexture`).

This is the version served to online 3D viewers.

**Processing steps**: 00, 01, 02, 03, 04, 05, 06

## Stage dependencies

```
raw  (step 00)
 |
 v
rawp (steps 00-01)
 |
 v
dcho (steps 00-02)
 |
 v
dchoo (steps 00-06)
```

Because metadata is cumulative, the author list grows at each stage. The people who created the `dchoo` include everyone from `raw`, `rawp`, and `dcho` as well.
