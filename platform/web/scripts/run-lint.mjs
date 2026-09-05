import { readdirSync } from 'node:fs';
import { extname, join } from 'node:path';
import { spawnSync } from 'node:child_process';

const roots = ['app', join('components', 'workspace'), 'lib'];
const extensions = new Set(['.js', '.jsx', '.ts', '.tsx']);

function collect(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return collect(path);
    return extensions.has(extname(entry.name)) ? [path] : [];
  });
}

const files = [...roots.flatMap(collect), join('hooks', 'use-vegetation-webmcp.ts')];
const cli = join(process.cwd(), 'node_modules', 'oxlint', 'bin', 'oxlint');
const result = spawnSync(process.execPath, [cli, '--no-ignore', ...files], {
  cwd: process.cwd(),
  encoding: 'utf8',
  stdio: 'inherit',
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
