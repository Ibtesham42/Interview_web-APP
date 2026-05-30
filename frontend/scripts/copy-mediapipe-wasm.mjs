/**
 * Self-host the MediaPipe Tasks-Vision WASM runtime.
 *
 * Phase C face monitoring (`hooks/useFaceMonitor.ts`) loads the BlazeFace
 * detector's WASM runtime at first use. Historically that came from
 * jsdelivr; if the CDN was blocked/down the face checks silently disabled
 * themselves — a silent-degradation failure mode. We now serve the runtime
 * from our own origin (Vercel `dist/`).
 *
 * The runtime is a build artifact of the already-pinned
 * `@mediapipe/tasks-vision` dependency, so we copy it out of `node_modules`
 * at build time rather than committing ~22 MB of binaries to git. The
 * companion BlazeFace model (`public/mediapipe/blaze_face_short_range.tflite`,
 * ~224 KB) IS committed — it isn't shipped in the npm package, and keeping
 * it in the repo makes the build fully offline / air-gap friendly.
 *
 * Wired as `predev` + `prebuild` so both `vite dev` and `vite build` have
 * the files in `public/mediapipe/wasm/` before they serve / copy `public/`.
 */
import { existsSync, mkdirSync, copyFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, '..');

const SRC_DIR = join(root, 'node_modules', '@mediapipe', 'tasks-vision', 'wasm');
const DEST_DIR = join(root, 'public', 'mediapipe', 'wasm');

// Only the files `FilesetResolver.forVisionTasks` actually fetches: the
// SIMD build and the nosimd fallback (js loader + wasm binary for each).
// The `vision_wasm_module_internal` ES-module variant is not used by this
// loader path, so we skip it to keep the deploy lean.
const FILES = [
  'vision_wasm_internal.js',
  'vision_wasm_internal.wasm',
  'vision_wasm_nosimd_internal.js',
  'vision_wasm_nosimd_internal.wasm',
];

if (!existsSync(SRC_DIR)) {
  console.error(
    `[copy-mediapipe-wasm] source not found: ${SRC_DIR}\n` +
      'Is @mediapipe/tasks-vision installed? Run `npm install` first.',
  );
  process.exit(1);
}

mkdirSync(DEST_DIR, { recursive: true });

let copied = 0;
for (const file of FILES) {
  const src = join(SRC_DIR, file);
  if (!existsSync(src)) {
    console.error(
      `[copy-mediapipe-wasm] expected runtime file missing: ${src}\n` +
        'The @mediapipe/tasks-vision version may have changed its asset names.',
    );
    process.exit(1);
  }
  copyFileSync(src, join(DEST_DIR, file));
  copied += statSync(src).size;
}

console.log(
  `[copy-mediapipe-wasm] copied ${FILES.length} files ` +
    `(${(copied / 1024 / 1024).toFixed(1)} MB) → public/mediapipe/wasm/`,
);
