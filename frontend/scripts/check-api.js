// Drift check: regenerate the client into a temp dir next to the real one (same relative
// depth, so imports match) and diff. Never touches src/api/generated or any other work.
import { execFileSync, spawnSync } from 'node:child_process'
import { rmSync } from 'node:fs'

const TMP = 'src/api/.generated-check'
rmSync(TMP, { recursive: true, force: true })
try {
  execFileSync('bunx', ['openapi-ts', '-f', 'openapi-ts.config.js', '-o', TMP], { stdio: 'ignore' })
  const r = spawnSync('diff', ['-r', 'src/api/generated', TMP], { encoding: 'utf8' })
  if (r.status !== 0) {
    process.stderr.write(
      (r.stdout || '').slice(0, 4000) + '\nGenerated API client is stale: run `make api`.\n',
    )
    process.exitCode = 1
  }
} finally {
  rmSync(TMP, { recursive: true, force: true })
}
