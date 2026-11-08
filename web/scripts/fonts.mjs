// The open fonts the site ships itself (docs/frame.md §1.3). Each font of fonts.json is taken from its npm
// package (a devDependency) into dist/fonts/: <id>.css — its @font-face rules, the woff2 sources only, the
// family named as fonts.json declares it — and <id>/, the files those rules name and the package's licence.
// The pages app publishes dist at /apps/site/, so a page links /apps/site/fonts/<id>.css (the address is
// [look] fonts of the site file) when, and only when, the person chose a look that names the font. A font's
// unicode-range slices stay as its package cut them: a browser fetches only the slices its text uses.
// Run by `npm run build` after vite (which empties dist), or alone: node scripts/fonts.mjs.

import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = join(web, 'dist', 'fonts');
const catalog = JSON.parse(readFileSync(join(web, 'fonts.json'), 'utf8'));
const FACE = /@font-face\s*\{([^}]*)\}/g;
const SOURCE = /url\(\s*['"]?([^'")]+)['"]?\s*\)\s*(?:format\(\s*['"]?([\w-]+)['"]?\s*\))?/g;
const LICENCE = /^(?:licen[cs]e|ofl)(?:\.(?:md|txt))?$/i;

/** The declarations of one @font-face block, in order, as [name, value]. */
function declarations(block) {
  return block.split(';').map(d => d.trim()).filter(Boolean).map(d => {
    const i = d.indexOf(':');
    return [d.slice(0, i).trim().toLowerCase(), d.slice(i + 1).trim()];
  });
}

/** One font into dist/fonts: its stylesheet and its files; what it took, for the report. */
function build(font) {
  const root = join(web, 'node_modules', font.package);
  const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const dir = join(out, font.id);
  mkdirSync(dir, { recursive: true });
  const taken = new Map();  // file name in dist → its source path (two sources may not share a name)
  const faces = [];
  let skipped = 0;
  for (const rel of font.css) {
    const sheet = join(root, rel);
    if (!existsSync(sheet)) throw new Error(`${font.id}: ${font.package} has no ${rel}`);
    for (const [, block] of readFileSync(sheet, 'utf8').matchAll(FACE)) {
      const decls = declarations(block);
      const src = decls.find(([k]) => k === 'src')?.[1] ?? '';
      const woff2 = [...src.matchAll(SOURCE)].find(([, url, format]) => format?.startsWith('woff2') || /\.woff2(?:[?#].*)?$/.test(url));
      if (!woff2) { skipped += 1; continue; }
      const from = resolve(dirname(sheet), woff2[1].replace(/[?#].*$/, ''));
      const name = basename(from);
      if (taken.has(name) && taken.get(name) !== from) throw new Error(`${font.id}: two files named ${name}`);
      if (!taken.has(name)) { copyFileSync(from, join(dir, name)); taken.set(name, from); }
      const keep = decls.filter(([k]) => k !== 'src' && k !== 'font-family' && k !== 'font-display');
      faces.push(['@font-face {', `  font-family: "${font.family}";`, '  font-display: swap;',
                  ...keep.map(([k, v]) => `  ${k}: ${v};`), `  src: url("${font.id}/${name}?v=${pkg.version}") format("${woff2[2]?.startsWith('woff2') ? woff2[2] : 'woff2'}");`, '}'].join('\n'));
    }
  }
  if (!faces.length) throw new Error(`${font.id}: no woff2 face in ${font.css.join(', ')}`);
  // the licence travels with the files: the one fonts.json names (licence_file), else the package's own at its root
  const licence = font.licence_file ?? readdirSync(root).find(f => LICENCE.test(f));
  if (!licence || !existsSync(join(root, licence))) throw new Error(`${font.id}: ${font.package} carries no licence file (name it: licence_file)`);
  copyFileSync(join(root, licence), join(dir, basename(licence)));
  writeFileSync(join(out, `${font.id}.css`),
    `/* ${font.family} — ${font.package}@${pkg.version}, ${font.licence} (${font.id}/${basename(licence)}). Built by web/scripts/fonts.mjs. */\n${faces.join('\n')}\n`);
  return { faces: faces.length, files: taken.size, skipped };
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
const seen = new Set();
for (const font of catalog.fonts) {
  if (seen.has(font.id)) throw new Error(`${font.id} is declared twice`);
  seen.add(font.id);
  const r = build(font);
  console.log(`fonts: ${font.id} (${font.family}) — ${r.faces} faces, ${r.files} files${r.skipped ? `, ${r.skipped} without woff2 left out` : ''}`);
}
