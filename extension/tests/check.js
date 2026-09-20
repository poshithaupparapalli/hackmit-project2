import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
const root = resolve(import.meta.dirname, '..');
const manifest = JSON.parse(readFileSync(`${root}/manifest.json`));
if (manifest.manifest_version !== 3 || manifest.incognito !== 'not_allowed') throw new Error('Manifest privacy configuration invalid');
for (const file of [manifest.background.service_worker, manifest.side_panel.default_path, ...manifest.content_scripts.flatMap(script => script.js)]) if (!existsSync(`${root}/${file}`)) throw new Error(`Missing ${file}`);
for (const directory of ['', '/lib', '/tests']) for (const file of readdirSync(root + directory).filter(file => /\.m?js$/.test(file))) execFileSync(process.execPath, ['--check', root + directory + '/' + file]);
console.log('Manifest references and all JavaScript syntax checks passed.');
