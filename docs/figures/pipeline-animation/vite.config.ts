import {defineConfig} from 'vite';
import mc from '@motion-canvas/vite-plugin';
import ff from '@motion-canvas/ffmpeg';

// CJS packages — default export is nested under .default in ESM context
const motionCanvas = (mc as any).default ?? mc;
const ffmpeg = (ff as any).default ?? ff;

export default defineConfig({
  plugins: [
    motionCanvas(),
    ffmpeg(),
  ],
});
