---
name: forgecad-render-inspect
description: Run and interpret ForgeCAD inspection bundles for model verification. Use when asked to inspect a ForgeCAD model, analyze an inspection bundle, validate collisions, wall thickness, connectivity, floating bodies, sections, masks, depth, normals, or Zebra stripes.
forgecad-public: true
---

# ForgeCAD Render Inspect

Use `forgecad inspect <evidence>` when a shaded viewport render is too ambiguous and you need structured evidence about a ForgeCAD model. The command writes a deterministic directory bundle containing evidence PNGs plus a root `manifest.json`.

This skill owns the inspection workflow: choosing evidence, generating the bundle, reading the manifest, visually inspecting the relevant PNGs, and turning the findings into model fixes or a verification report.

Inspection is not a substitute artifact. Use sections, object masks, transparency, focus, and hide controls to look inside a real model; do not edit the model into a cutaway or exploded default just to make the inspection easier.

## Trigger Boundary

Use this skill for:

- inspecting an existing `.forge.js` model
- analyzing a previously generated inspection bundle
- validating collisions, wall thickness, section cuts, connectivity, floating bodies, distance, object masks, depth, normals, or Zebra stripes
- deciding which inspection evidence to run
- producing evidence before calling a model complete

Routing:

| Need | Skill |
|------|-------|
| Learn or use ForgeCAD APIs while authoring geometry | `forgecad` |
| Create a new model in the personal model repo | `forgecad-make-a-model` |
| Run and interpret inspection bundles | `forgecad-render-inspect` |
| Debug the inspection command implementation itself | `forgecad` plus this skill's source map |

## Workflow

1. Identify the inspection question.
   Decide what would make the model wrong: unexpected overlap, too-thin walls, missing parts, hidden cavity failure, disconnected bodies, unintentionally fused bodies, orientation artifacts, or object identity confusion.

2. Choose a scratch output directory.
   Use `/tmp/<model-name>-inspect` by default so generated PNGs do not dirty the repo. Use a project output directory only when the user wants a persistent artifact.

3. Pick the evidence.
   Prefer one targeted evidence command at a time. Use `forgecad inspect evidence`
   to list the available commands.

4. Run the command.
   In the ForgeCAD repo, prefer the built CLI when you want the current checkout:

   ```bash
   node dist-cli/forgecad.js inspect collisions model.forge.js /tmp/model-collisions-inspect --camera iso --force --size 700
   ```

   Outside the ForgeCAD repo, use the installed CLI:

   ```bash
   forgecad inspect collisions model.forge.js /tmp/model-collisions-inspect --camera iso --force --size 700
   ```

   If the model may not execute, run `forgecad run model.forge.js` first. If imports are suspect, add `--debug-imports` to the run command.

5. Summarize the manifest.
   Run the bundled helper:

   ```bash
   python skills/forgecad-render-inspect/summarize_manifest.py /tmp/model-inspect
   ```

   Use `jq` for targeted follow-up when needed:

   ```bash
   jq '.evidence.collisions | {collisionCount, collisions, warnings}' /tmp/model-inspect/manifest.json
   jq '.evidence.thickness.objects[] | {name, minThickness, p05Thickness, criticalAreaPercent, warningAreaPercent, unresolvedAreaPercent}' /tmp/model-inspect/manifest.json
   jq '.evidence.connectivity | {componentCount, edges, warnings}' /tmp/model-inspect/manifest.json
   jq '.evidence.floating | {floatingBodyCount, floatingObjectCount, warnings}' /tmp/model-inspect/manifest.json
   ```

6. Inspect the PNGs, not only the JSON.
   Always look at the view PNGs that match the risk. Use the manifest paths instead of assuming layout when writing automation; custom cameras may not use canonical filenames.

7. Decide whether findings are bugs.
   Treat unexpected collision findings, critical thin regions, high unresolved thickness, missing sections, wrong object names, wrong component count, or surprising distance gaps as model bugs. If an overlap is intentional, isolate the check with `--focus` or `--hide` so the remaining report is meaningful.

8. Report evidence.
   Include the exact command, bundle path, evidence emitted, manifest highlights, PNG views inspected, and any residual limits. Do not say the geometry is verified if you only ran `forgecad run`.

## Evidence Selection

| Question | Evidence command |
|----------|------------------|
| Quick visual sanity | `inspect image` |
| Object naming and identity | `inspect objects` |
| Hidden internals, cavities, pockets, screw paths, captured components | `inspect sections` |
| Multi-part interference, fit checks, ghost parts, moving clearances | `inspect collisions` |
| Printability, shell walls, ribs, bosses, snaps, slots | `inspect thickness` plus `inspect sections` when internals matter |
| Parts without a mesh-contact path to the ground | `inspect floating` |
| Accidental fusion, connected solids | `inspect connectivity` |
| Air gaps between physical components | `inspect distance` |
| Surface orientation, occlusion, faceting, strange protrusions | `inspect depth` or `inspect normals` |
| Loft, fillet, skin, and sweep surface continuity | `inspect zebra` or `inspect normals` |
| Reference-vs-candidate reconstruction comparison | `inspect comparison --with reference.3mf` |

## Command Patterns

Explicit fast bundle:

```bash
forgecad inspect objects model.forge.js /tmp/model-objects-inspect --camera iso --force --size 700
forgecad inspect sections model.forge.js /tmp/model-sections-inspect --force --size 700
```

Reference-vs-candidate comparison bundle:

```bash
forgecad inspect comparison candidate.forge.js /tmp/candidate-compare --with reference.3mf --compare-samples 3000 --force --size 700
```

Final fit/interference check:

```bash
forgecad inspect collisions model.forge.js /tmp/model-collisions-inspect --camera iso --force --size 700
```

Collision-focused isolation:

```bash
forgecad inspect collisions model.forge.js /tmp/model-fit --focus "Bracket,Screw Ghost" --camera iso --force
```

Thickness check with process-aware thresholds:

```bash
forgecad inspect thickness model.forge.js /tmp/model-thickness --min 1.6 --warn 2.4 --camera iso --force
```

Hide known clutter or mock geometry:

```bash
forgecad inspect collisions model.forge.js /tmp/model-collisions-inspect --hide "Fixture Ghost,Debug Envelope" --camera iso --force
```

Use bare `--focus` to hide mock objects while keeping real scene objects:

```bash
forgecad inspect collisions model.forge.js /tmp/model-real-collisions --focus --camera iso --force
```

## Reading Results

Manifest fields to check first:

- `bundle.evidenceRequested` / `bundle.evidenceEmitted`: confirm you inspected what you intended.
- `bundle.filters`: confirm focus/hide did not accidentally exclude relevant geometry.
- `scene.bbox` and `scene.volume`: catch absurd scale, missing geometry, or bad units.
- `scene.objects`: confirm expected part names and mock flags.
- `evidence.objects.objects`: map object colors to names; do not rely on object order alone.
- `evidence.collisions.collisionCount`: investigate every unexpected positive-volume overlap.
- `evidence.thickness.objects`: inspect `minThickness`, `p05Thickness`, critical/warning percentages, and unresolved area.
- `evidence.connectivity.componentCount`: compare to the expected number of physical components.
- `evidence.floating.floatingBodyCount`: investigate every body without a mesh-contact path to the ground plane, especially body entries from one unioned object.
- `evidence.distance.maxRootDistance` and per-object `nearestGap`: check suspicious isolation or spacing.
- `evidence.sections.planes`: look for missing slices, wrong path counts, or empty internal cuts. These are inspection views, not instructions to section the returned production geometry.

PNG review order:

1. Image evidence for human shape sanity when needed.
2. Object evidence and one orthogonal object view for identity when needed.
3. The risk evidence's chosen view.
4. Orthogonal cameras (`front`, `right`, `top`) when the iso view hides the issue.
5. Section slices around the suspected feature when internals matter.

## Interpretation Rules

- Collision findings are positive-volume boolean overlaps. Face-touching is not a collision.
- Connectivity uses bbox as a broadphase, then shared physical-contact detection for component grouping: mesh surfaces within contact tolerance count as connected, exact positive-volume overlap is used when needed, and bbox-only contact does not merge separate scene objects by default. Use collisions evidence for positive-volume overlap defects.
- Floating uses the same shared physical-contact detection plus scene-ground reachability. Mesh gaps within contact tolerance count as connected, bbox overlap or bbox face contact alone does not, and every component without a contact path to ground is reported. Disconnected mesh islands inside one object are inspected separately.
- Distance is a bbox-gap metric between physical components, not exact closest surface distance.
- Thickness is a contact-aware mesh/raycast approximation. It uses the same physical-contact edges as connectivity/floating, so rays jump over direct-neighbor contact seams within contact tolerance before measuring the next surface. Gray or high unresolved area means the visual heatmap is incomplete, not that the model is safe.
- Depth is a visual heatmap, not raw floating-point depth data.
- Normals are camera-view normals, not world-space normals.
- Zebra is a reflective stripe shader for visual continuity inspection, not an exact curvature-continuity proof.
- Mask colors are stable within a bundle and resolved through the manifest.

## Source Map

Read these only when needed:

| Need | Source |
|------|--------|
| Bundle contract and evidence semantics | `docs/permanent/guides/inspection-bundles.md` |
| CLI reference and options | `docs/permanent/CLI.md` |
| CLI parser, bundle writer, manifest generation | `cli/forge-render.mjs` |
| Browser-side evidence rendering | `cli/render.ts` |
| Collision semantics | `cli/collision-inspection.ts` |
| Thickness semantics | `cli/thickness-inspection.ts` |
| Connectivity, floating, and distance semantics | `cli/physical-connectivity.ts`, `cli/floating-inspection.ts`, and `cli/distance-inspection.ts` |

---

## File: `summarize_manifest.py`

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

"""Summarize a ForgeCAD inspection manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_manifest(path_arg: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_arg).expanduser()
    if path.is_dir():
        path = path / "manifest.json"
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return path, json.load(handle)


def fmt_num(value: Any, digits: int = 2) -> str:
    if isinstance(value, (int, float)) and value == value and value not in (float("inf"), float("-inf")):
        return f"{value:.{digits}f}"
    if value is None:
        return "null"
    return str(value)


def dimensions(scene: dict[str, Any]) -> str:
    bbox = scene.get("bbox") or {}
    mn = bbox.get("min")
    mx = bbox.get("max")
    if not (isinstance(mn, list) and isinstance(mx, list) and len(mn) >= 3 and len(mx) >= 3):
        return "unknown"
    size = [mx[i] - mn[i] for i in range(3)]
    return " x ".join(fmt_num(v, 1) for v in size)


def evidence_keys(manifest: dict[str, Any]) -> list[str]:
    bundle = manifest.get("bundle") or {}
    emitted = bundle.get("evidenceEmitted")
    if isinstance(emitted, list) and emitted:
        return [str(item) for item in emitted]
    evidence = manifest.get("evidence") or {}
    return sorted(evidence.keys())


def object_names(manifest: dict[str, Any]) -> list[str]:
    scene = manifest.get("scene") or {}
    objects = scene.get("objects") or []
    names: list[str] = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("id")
        if name:
            names.append(str(name))
    return names


def print_header(manifest_path: Path, manifest: dict[str, Any]) -> None:
    source = manifest.get("source") or {}
    bundle = manifest.get("bundle") or {}
    scene = manifest.get("scene") or {}
    generator = manifest.get("generator") or {}
    print(f"Manifest: {manifest_path}")
    print(f"Command:  {generator.get('command', 'unknown')}")
    if generator.get("forgecadVersion"):
        print(f"Version:  {generator['forgecadVersion']}")
    print(f"Source:   {source.get('entryFile', 'unknown')}")
    requested = bundle.get("evidenceRequested") or evidence_keys(manifest)
    print(f"Evidence: requested={requested} emitted={evidence_keys(manifest)}")
    print(f"Filters:  {bundle.get('filters', {})}")
    print(f"Scene:    objects={len(scene.get('objects') or [])} size={dimensions(scene)} volume={fmt_num(scene.get('volume'), 1)}")
    names = object_names(manifest)
    if names:
        preview = ", ".join(names[:12])
        suffix = "" if len(names) <= 12 else f", ... (+{len(names) - 12})"
        print(f"Objects:  {preview}{suffix}")


def print_collisions(evidence: dict[str, Any]) -> None:
    collisions = evidence.get("collisions")
    if not isinstance(collisions, dict):
        return
    findings = collisions.get("collisions") or []
    print("")
    print(f"Collisions: count={collisions.get('collisionCount', len(findings))}")
    for finding in findings[:12]:
        print(
            "  - "
            f"{finding.get('sourceName', finding.get('sourceId'))} vs "
            f"{finding.get('targetName', finding.get('targetId'))}: "
            f"overlapVolume={fmt_num(finding.get('overlapVolume'), 3)}"
        )
    if len(findings) > 12:
        print(f"  ... +{len(findings) - 12} more")
    warnings = collisions.get("warnings") or []
    for warning in warnings:
        print(f"  warning: {warning}")


def print_thickness(evidence: dict[str, Any]) -> None:
    thickness = evidence.get("thickness")
    if not isinstance(thickness, dict):
        return
    objects = thickness.get("objects") or []
    ranked = sorted(
        [obj for obj in objects if isinstance(obj, dict)],
        key=lambda obj: (
            -(obj.get("criticalAreaPercent") or 0),
            -(obj.get("warningAreaPercent") or 0),
            -(obj.get("unresolvedAreaPercent") or 0),
            obj.get("minThickness") if obj.get("minThickness") is not None else float("inf"),
        ),
    )
    print("")
    print(
        "Thickness: "
        f"objects={thickness.get('objectCount', len(objects))} "
        f"thresholds={thickness.get('options', {})}"
    )
    for obj in ranked[:12]:
        print(
            "  - "
            f"{obj.get('name', obj.get('id'))}: "
            f"min={fmt_num(obj.get('minThickness'))} "
            f"p05={fmt_num(obj.get('p05Thickness'))} "
            f"critical={fmt_num(obj.get('criticalAreaPercent'))}% "
            f"warning={fmt_num(obj.get('warningAreaPercent'))}% "
            f"unresolved={fmt_num(obj.get('unresolvedAreaPercent'))}%"
        )
    if len(ranked) > 12:
        print(f"  ... +{len(ranked) - 12} more")
    for warning in thickness.get("warnings") or []:
        print(f"  warning: {warning}")


def print_connectivity(evidence: dict[str, Any]) -> None:
    connectivity = evidence.get("connectivity")
    if not isinstance(connectivity, dict):
        return
    components = connectivity.get("components") or []
    print("")
    print(
        "Connectivity: "
        f"objects={connectivity.get('objectCount', 0)} "
        f"components={connectivity.get('componentCount', len(components))} "
        f"edges={len(connectivity.get('edges') or [])}"
    )
    for component in components[:12]:
        names = component.get("objectNames") or []
        print(f"  - component {component.get('index')}: bodies={component.get('bodyCount')} objects={names}")
    if len(components) > 12:
        print(f"  ... +{len(components) - 12} more")
    for warning in connectivity.get("warnings") or []:
        print(f"  warning: {warning}")


def print_distance(evidence: dict[str, Any]) -> None:
    distance = evidence.get("distance")
    if not isinstance(distance, dict):
        return
    objects = [obj for obj in distance.get("objects") or [] if isinstance(obj, dict)]
    ranked = sorted(objects, key=lambda obj: obj.get("rootDistance") or 0, reverse=True)
    print("")
    print(
        "Distance: "
        f"components={distance.get('componentCount', 0)} "
        f"root={distance.get('rootComponentIndex')} "
        f"maxRootDistance={fmt_num(distance.get('maxRootDistance'))}"
    )
    for obj in ranked[:12]:
        print(
            "  - "
            f"{obj.get('name', obj.get('id'))}: "
            f"component={obj.get('componentIndex')} "
            f"rootDistance={fmt_num(obj.get('rootDistance'))} "
            f"nearestGap={fmt_num(obj.get('nearestGap'))}"
        )
    if len(ranked) > 12:
        print(f"  ... +{len(ranked) - 12} more")
    for warning in distance.get("warnings") or []:
        print(f"  warning: {warning}")


def print_sections(evidence: dict[str, Any]) -> None:
    sections = evidence.get("sections")
    if not isinstance(sections, dict):
        return
    planes = sections.get("planes") or {}
    print("")
    print("Sections:")
    for plane_name in ("xy", "xz", "yz"):
        plane = planes.get(plane_name)
        if not isinstance(plane, dict):
            continue
        slices = plane.get("slices") or []
        path_counts = [s.get("pathCount") for s in slices if isinstance(s, dict)]
        areas = [s.get("area") for s in slices if isinstance(s, dict)]
        print(
            f"  - {plane_name}: slices={len(slices)} "
            f"pathCounts={path_counts} "
            f"areas={[fmt_num(area, 1) for area in areas]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_or_bundle", help="Path to manifest.json or its containing inspect bundle directory")
    parser.add_argument("--json", action="store_true", help="Print a compact JSON summary instead of text")
    args = parser.parse_args()

    manifest_path, manifest = load_manifest(args.manifest_or_bundle)
    evidence = manifest.get("evidence") or {}

    if args.json:
        scene = manifest.get("scene") or {}
        summary = {
            "manifest": str(manifest_path),
            "source": (manifest.get("source") or {}).get("entryFile"),
            "evidence": evidence_keys(manifest),
            "objectCount": len(scene.get("objects") or []),
            "dimensions": dimensions(scene),
            "volume": scene.get("volume"),
            "collisionCount": (evidence.get("collisions") or {}).get("collisionCount"),
            "connectivityComponents": (evidence.get("connectivity") or {}).get("componentCount"),
            "distanceMaxRootDistance": (evidence.get("distance") or {}).get("maxRootDistance"),
        }
        print(json.dumps(summary, indent=2))
        return

    print_header(manifest_path, manifest)
    print_collisions(evidence)
    print_thickness(evidence)
    print_connectivity(evidence)
    print_distance(evidence)
    print_sections(evidence)


if __name__ == "__main__":
    main()
```
