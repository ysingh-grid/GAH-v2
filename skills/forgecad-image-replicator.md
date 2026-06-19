---
name: forgecad-image-replicator
description: Build real ForgeCAD geometry from one or more reference images by treating images as evidence, inferring the object, then validating against both reference-matched and canonical views.
forgecad-public: true
---

# ForgeCAD Image Replicator

Use this skill when the user provides one or more images and wants a ForgeCAD model of the object shown.

The reference image is evidence. It is not the deliverable.

The deliverable is a real parametric object that remains believable from front, back, side, top, bottom, and reference camera views. A model that matches one image but falls apart from other angles has failed, even if the comparison board looks close.

If a reference image is cutaway, sectioned, exploded, partly hidden, or transparent, treat that as evidence about the complete object. Do not make the default ForgeCAD result a permanently cutaway or exploded display unless the user explicitly asked for a teaching/display model. Build the closed artifact first, then use ForgeCAD viewer/inspection tools to recreate explanatory views.

## Required Companion Skills

- Use `forgecad` for API docs, model authoring, and renderer behavior.
- Use `forgecad-prepare-prompt` when the image does not fully determine the artifact family, process posture, scale, operating story, or validation boundary.
- Use `forgecad-make-a-model` for file placement, decomposition, parametric modeling, and definition of done.
- Use `forgecad-render-inspect` before final delivery when the object has multiple parts, internal geometry, mechanisms, thin walls, or fit-sensitive features.

## Core Rule

Infer the real object before matching the camera.

Do not begin by chasing pixels, silhouettes, or the prettiest view. First form a 3D object hypothesis: what the artifact is, how it is made, what hidden sides must contain, what scale it likely has, and what geometry must exist for it to be physically coherent.

Reference matching is a validation step after the object exists.

## Workflow

1. Save the references.
   Put all provided images in `/tmp/<slug>-replicate/refs`. Keep the original filenames. If there are multiple views, add clear view names when possible: `front`, `side`, `rear-iso`, `top`, `detail`, and so on.

2. Read the images as evidence.
   For each image, record:
   - visible facts: silhouette, view direction, visible faces, major masses, feature counts, color and material boundaries, seams, holes, fasteners, labels, repeated spacing
   - scale cues: hands, hardware, wheels, ports, boards, screws, wall thickness, known product proportions
   - camera cues: perspective strength, parallel edges, lens distortion, crop, object center, likely elevation and azimuth
   - unknowns: hidden sides, occluded parts, ambiguous thickness, missing rear or underside geometry
   - conflicts: details that disagree across images or appear stylized, distorted, cropped, or shadow-hidden

3. Write a Real Object Brief.
   This is a hard gate before modeling. Include:
   - artifact identity and family
   - likely purpose or operating story
   - assumed scale and units
   - manufacturing/process posture and material cues
   - part and BOM boundary: what is modeled as real geometry, purchased hardware, ghost geometry, or omitted context
   - visible facts from the reference set
   - inferred hidden-side geometry
   - expected canonical front, back, left, right, top, and bottom forms
   - required internal, interface, or fit geometry
   - validation views and inspection evidence

4. Choose the modeling structure.
   Use a multi-file `main.forge.js` project when the object has distinct parts, repeated feature families, internals, purchased hardware, variants, or meaningful manufacturing assumptions. Put renderable/importable parts and sub-assemblies in neighboring `.forge.js` files; keep only pure dimensions, materials, math helpers, and lookup tables in plain `.js` files.

5. Build a coarse 3D blockout.
   Model the object, not the image. Start with the large volumes, axes, symmetry, side depth, rear form, underside, and hidden continuations. Render canonical views before doing reference-camera comparison.

6. Calibrate one camera per usable reference.
   Match camera after the blockout makes sense from canonical views. Use the object center as `target`. Estimate azimuth, elevation, distance, and FOV from visible faces and perspective cues. Use orthographic when parallel edges stay parallel and there is no visible perspective convergence.

7. Render comparison boards.
   Render the model from each calibrated reference camera and place the result next to the original image. Do not compare from memory.

8. Iterate in the right order.
   Change one class of thing at a time:
   - object hypothesis: identity, scale, symmetry, hidden-side assumptions, process logic
   - major proportions: width, depth, height, taper, curvature, radius families
   - canonical geometry: rear, underside, side depth, internal clearances, part interfaces
   - camera: azimuth, elevation, target, distance, FOV, orthographic zoom
   - details: holes, seams, fasteners, labels, vents, edge treatments, small hardware
   - presentation: colors, materials, lighting, background, edge style

   If improving one reference view makes another view or canonical render worse, the object hypothesis is probably wrong. Fix the model, not the camera illusion.

9. Use every image as a constraint.
   When multiple images are attached, do not choose one as the target and ignore the rest. Assign each image a camera, evidence list, and confidence level. Optimize one shared geometry against the whole set. If an image is decorative, distorted, or contradictory, state how it was weighted.

10. Inspect the final object.
   Run `forgecad run`, render the reference comparison boards, render canonical views, and use targeted `forgecad inspect <evidence>` commands. For multi-part, mechanical, internal, or fit-sensitive models, include `inspect collisions` and `inspect sections`, but keep the delivered model as the complete closed artifact.

## Renderer Camera Support

ForgeCAD `render 3d` supports explicit camera control:

```bash
forgecad render 3d model.forge.js /tmp/render.png \
  --camera "proj=perspective;pos=200,-160,120;target=0,0,20;up=0,0,1;fov=38" \
  --size 1000
```

Supported camera forms:

- `--camera front`, `top`, `side`, `right`, `iso`
- `--camera 45:25` for azimuth/elevation in degrees
- `--camera 45:25:260` for azimuth/elevation/distance
- `--camera "proj=perspective;pos=x,y,z;target=x,y,z;up=0,0,1;fov=42"`
- `--camera "proj=orthographic;pos=x,y,z;target=x,y,z;up=0,0,1;zoom=4"`

If exact full camera specs do not render in the current checkout, fix the renderer before continuing. Do not work around missing camera control by guessing from default `iso` renders.

## Rendering And Comparison

Prefer the built CLI from the repo checkout when available:

```bash
node dist-cli/forgecad.js render 3d path/to/model.forge.js /tmp/<slug>-replicate/render-front.png \
  --camera "proj=perspective;pos=200,-160,120;target=0,0,20;up=0,0,1;fov=38" \
  --size 1000 --edges thin
```

Build side-by-side boards with the bundled helper:

```bash
node skills/forgecad-image-replicator/scripts/compare_images.mjs \
  /tmp/<slug>-replicate/refs/front.png \
  /tmp/<slug>-replicate/render-front.png \
  /tmp/<slug>-replicate/compare-front.png \
  --height 900 --labels "Reference,ForgeCAD"
```

Common helper options:

```bash
node skills/forgecad-image-replicator/scripts/compare_images.mjs ref.png render.png compare.png
node skills/forgecad-image-replicator/scripts/compare_images.mjs ref.jpg render.png compare.png --height 1200 --fit contain
node skills/forgecad-image-replicator/scripts/compare_images.mjs ref.png render.png compare.png --fit cover --labels "Target,Current"
node skills/forgecad-image-replicator/scripts/compare_images.mjs ref.png render.png compare.png --no-labels
```

Use `--fit contain` by default. Use `--fit cover` only when both images already share the same crop and aspect.

## Acceptance Standard

A successful result:

- has a written Real Object Brief
- has parametric ForgeCAD geometry, not a billboard, facade, pasted texture, or one-view shell
- makes sense from canonical views before reference matching
- matches each usable reference image as closely as the evidence allows
- includes honest hidden-side assumptions where the images are silent
- includes internal, interface, purchased, or hardware geometry when the artifact calls for it
- passes `forgecad run`
- includes final reference comparison boards and canonical renders
- includes inspection results for the risk evidence that matters

A result fails if it only works from the original camera.

## Output Contract

When finished, report:

- model file path
- reference images used
- Real Object Brief summary
- hidden-side and scale assumptions
- final camera spec for each reference image
- comparison board path for each usable reference image
- canonical render paths
- inspection bundle path, when used
- validation commands run
- remaining mismatches, unknowns, or downgraded confidence

For non-trivial references, expect several render, compare, canonical-view, and inspect iterations. One render is not enough.

---

## File: `agents/openai.yaml`

```yaml
interface:
  display_name: "ForgeCAD Image Replicator"
  short_description: "Build real CAD objects from images"
  default_prompt: "Use $forgecad-image-replicator to infer the real object from these reference images and build a ForgeCAD model that holds up from all views."
```

---

## File: `scripts/compare_images.mjs`

```js
#!/usr/bin/env node

import { existsSync } from 'node:fs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, extname, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import puppeteer from 'puppeteer-core';

const CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
];

const MIME_BY_EXT = new Map([
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.webp', 'image/webp'],
  ['.gif', 'image/gif'],
  ['.bmp', 'image/bmp'],
  ['.svg', 'image/svg+xml'],
]);

function usage() {
  return `Usage:
  compare_images.mjs <reference-image> <forgecad-render> <output.png> [options]

Options:
  --height <px>             Panel height in pixels (default: 900)
  --panel-width <px>        Panel width in pixels (default: max input aspect at --height)
  --gap <px>                Gap between panels (default: 16)
  --padding <px>            Outer padding (default: 16)
  --background <color>      Canvas background (default: #111111)
  --fit <contain|cover>     Fit mode inside equal panels (default: contain)
  --labels <left,right>     Labels (default: Reference,ForgeCAD)
  --no-labels               Disable label band
  --chrome-path <path>      Chrome or Chromium executable
  -h, --help                Show help`;
}

function readValue(argv, index, flag) {
  const value = argv[index + 1];
  if (!value || value.startsWith('--')) {
    throw new Error(`Missing value for ${flag}`);
  }
  return value;
}

function parsePositiveInt(raw, label) {
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label} must be a positive integer.`);
  }
  return value;
}

function parseArgs(argv) {
  if (argv.includes('-h') || argv.includes('--help')) {
    console.log(usage());
    process.exit(0);
  }

  const positionals = [];
  const options = {
    height: 900,
    panelWidth: null,
    gap: 16,
    padding: 16,
    background: '#111111',
    fit: 'contain',
    labels: ['Reference', 'ForgeCAD'],
    chromePath: process.env.CHROME_PATH || null,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--height') {
      options.height = parsePositiveInt(readValue(argv, i, arg), '--height');
      i += 1;
    } else if (arg === '--panel-width') {
      options.panelWidth = parsePositiveInt(readValue(argv, i, arg), '--panel-width');
      i += 1;
    } else if (arg === '--gap') {
      options.gap = parsePositiveInt(readValue(argv, i, arg), '--gap');
      i += 1;
    } else if (arg === '--padding') {
      options.padding = parsePositiveInt(readValue(argv, i, arg), '--padding');
      i += 1;
    } else if (arg === '--background') {
      options.background = readValue(argv, i, arg);
      i += 1;
    } else if (arg === '--fit') {
      const fit = readValue(argv, i, arg);
      if (fit !== 'contain' && fit !== 'cover') {
        throw new Error('--fit must be contain or cover.');
      }
      options.fit = fit;
      i += 1;
    } else if (arg === '--labels') {
      const labels = readValue(argv, i, arg)
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean);
      if (labels.length !== 2) {
        throw new Error('--labels must contain two comma-separated labels.');
      }
      options.labels = labels;
      i += 1;
    } else if (arg === '--no-labels') {
      options.labels = null;
    } else if (arg === '--chrome-path') {
      options.chromePath = readValue(argv, i, arg);
      i += 1;
    } else if (arg.startsWith('--')) {
      throw new Error(`Unknown option: ${arg}`);
    } else {
      positionals.push(arg);
    }
  }

  if (positionals.length !== 3) {
    throw new Error(`Expected reference, render, and output paths.\n\n${usage()}`);
  }

  return {
    referencePath: resolve(positionals[0]),
    renderPath: resolve(positionals[1]),
    outputPath: resolve(positionals[2]),
    ...options,
  };
}

function commandPath(name) {
  try {
    const found = execFileSync(process.platform === 'win32' ? 'where' : 'which', [name], {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim()
      .split(/\r?\n/)[0];
    return found || null;
  } catch {
    return null;
  }
}

function resolveChromePath(explicitPath) {
  if (explicitPath && existsSync(explicitPath)) return explicitPath;
  for (const candidate of CHROME_PATHS) {
    if (existsSync(candidate)) return candidate;
  }
  for (const candidate of ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'brave-browser', 'microsoft-edge', 'chrome']) {
    const found = commandPath(candidate);
    if (found && existsSync(found)) return found;
  }
  return null;
}

async function imageDataUrl(path) {
  if (!existsSync(path)) {
    throw new Error(`Image not found: ${path}`);
  }
  const ext = extname(path).toLowerCase();
  const mime = MIME_BY_EXT.get(ext);
  if (!mime) {
    throw new Error(`Unsupported image extension "${ext}" for ${path}`);
  }
  const bytes = await readFile(path);
  return `data:${mime};base64,${bytes.toString('base64')}`;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  const chromePath = resolveChromePath(options.chromePath);
  if (!chromePath) {
    throw new Error('Chrome or Chromium was not found. Pass --chrome-path or set CHROME_PATH.');
  }

  const [referenceUrl, renderUrl] = await Promise.all([imageDataUrl(options.referencePath), imageDataUrl(options.renderPath)]);
  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: true,
    args: ['--no-sandbox', '--disable-gpu-sandbox'],
  });

  try {
    const page = await browser.newPage();
    const result = await page.evaluate(
      async (payload) => {
        const loadImage = (src) =>
          new Promise((resolveImage, rejectImage) => {
            const img = new Image();
            img.onload = () => resolveImage(img);
            img.onerror = () => rejectImage(new Error('Failed to decode image'));
            img.src = src;
          });

        const [reference, render] = await Promise.all([loadImage(payload.referenceUrl), loadImage(payload.renderUrl)]);
        const panelHeight = payload.height;
        const maxAspect = Math.max(reference.naturalWidth / reference.naturalHeight, render.naturalWidth / render.naturalHeight);
        const panelWidth = payload.panelWidth ?? Math.ceil(panelHeight * maxAspect);
        const labelHeight = payload.labels ? 34 : 0;
        const canvasWidth = payload.padding * 2 + panelWidth * 2 + payload.gap;
        const canvasHeight = payload.padding * 2 + labelHeight + panelHeight;
        const canvas = document.createElement('canvas');
        canvas.width = canvasWidth;
        canvas.height = canvasHeight;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = payload.background;
        ctx.fillRect(0, 0, canvasWidth, canvasHeight);

        const drawLabel = (text, x) => {
          ctx.fillStyle = 'rgba(255,255,255,0.9)';
          ctx.font = '600 18px system-ui, -apple-system, BlinkMacSystemFont, sans-serif';
          ctx.textBaseline = 'top';
          ctx.fillText(text, x, payload.padding + 4);
        };

        const drawPanel = (img, x, y) => {
          const scale =
            payload.fit === 'cover'
              ? Math.max(panelWidth / img.naturalWidth, panelHeight / img.naturalHeight)
              : Math.min(panelWidth / img.naturalWidth, panelHeight / img.naturalHeight);
          const width = img.naturalWidth * scale;
          const height = img.naturalHeight * scale;
          const dx = x + (panelWidth - width) * 0.5;
          const dy = y + (panelHeight - height) * 0.5;

          ctx.save();
          ctx.beginPath();
          ctx.rect(x, y, panelWidth, panelHeight);
          ctx.clip();
          ctx.drawImage(img, dx, dy, width, height);
          ctx.restore();

          ctx.strokeStyle = 'rgba(255,255,255,0.25)';
          ctx.lineWidth = 1;
          ctx.strokeRect(x + 0.5, y + 0.5, panelWidth - 1, panelHeight - 1);
        };

        const leftX = payload.padding;
        const rightX = payload.padding + panelWidth + payload.gap;
        const panelY = payload.padding + labelHeight;
        if (payload.labels) {
          drawLabel(payload.labels[0], leftX);
          drawLabel(payload.labels[1], rightX);
        }
        drawPanel(reference, leftX, panelY);
        drawPanel(render, rightX, panelY);

        return {
          png: canvas.toDataURL('image/png'),
          width: canvasWidth,
          height: canvasHeight,
        };
      },
      {
        referenceUrl,
        renderUrl,
        height: options.height,
        panelWidth: options.panelWidth,
        gap: options.gap,
        padding: options.padding,
        background: options.background,
        fit: options.fit,
        labels: options.labels,
      },
    );

    const png = Buffer.from(result.png.replace(/^data:image\/png;base64,/, ''), 'base64');
    await mkdir(dirname(options.outputPath), { recursive: true });
    await writeFile(options.outputPath, png);
    console.log(`Wrote ${options.outputPath} (${result.width}x${result.height})`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
```
