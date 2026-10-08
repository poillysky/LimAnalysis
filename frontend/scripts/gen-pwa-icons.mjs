/**
 * 用 logo-app.svg 生成 PWA / favicon PNG（需 sharp）。
 *   node scripts/gen-pwa-icons.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
const svg = readFileSync(join(pub, "logo-app.svg"));

async function writePng(name, size) {
  const buf = await sharp(svg).resize(size, size).png().toBuffer();
  writeFileSync(join(pub, name), buf);
  console.log(`wrote ${name} (${size}x${size})`);
}

await writePng("pwa-512.png", 512);
await writePng("pwa-192.png", 192);
await writePng("favicon-32.png", 32);
console.log("done");
