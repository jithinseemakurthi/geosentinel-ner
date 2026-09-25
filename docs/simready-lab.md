# SimReady Terrain Lab — GeoSentinel-NER

> Implements NVIDIA **omniverse-cad-to-simready v0.2.0** (`Apache-2.0`) — `.agents/skills/omniverse-cad-to-simready/`

Converts NER hillslope CAD / DEM / mesh assets into **SimReady USD** for landslide physics simulation in Omniverse / Isaac Sim.

## Why

High-resolution terrain CAD (ISRO Bhuvan DEM, GSI, state PWD) + designed mitigation CAD (retaining walls, anchors) need to become simulation-ready USD with physics colliders before runout / debris-flow simulation. This lab follows the skill's coordinated workflow instead of a monolithic runner.

## Workflow (18 steps, per `references/workflow.md`)

```
1. Confirm source asset path exists
2. Resolve property_assignment_intent (default: run for end-to-end; skip for conversion-only)
3. Preflight — dependencies & manifest (PHYSICAL_AI_PREFLIGHT_MANIFEST + PHYSICAL_AI_REQUIRE_PREFLIGHT=1)
4. Content Agents readiness gate (deploy if missing — Material, Physics, Texture via OVRTX)
5. identify-asset-context (web-backed terrain classification)
6. convert-to-usd (routes: urdf→urdf-usd-converter, CAD→usd-convert-cad, splat→usd-convert-gsplat, USD→skip)
7. validate-usd-minimum (viability gate — metersPerUnit != 1.0 deferred per Hard Rules)
8. Content Agents · Material
9. Content Agents · Physics (--optimize-usd --enable-deinstance --enable-split when CAD structure detected)
10. simready-conform-profile (applies FET repairs post-assignment)
11. omni-asset-validate
12. omni-asset-validate-geometry
13. omni-asset-validate-physics
14. simready-validate (profile: Prop-Robotics-Neutral for terrain props)
15. ovrtx-render-service (thumbnail — black background, no authored lights)
16. assemble-package-source → deliverable/simready_usd/sm_<asset>_01.usd + .thumbs/256x256/
17. nv-core-package-sample (on deliverable/ only, never pipeline/)
18. Consolidated report — omniverse-cad-to-simready-report.md + JSON
```

**Hard Rules enforced:** preflight before any stage when intent=run; Content Agents readiness before inspection/conversion; `validate-usd-minimum` only gate before service calls (no FET001 before assignment); `simready-conform-profile` only after assignment; preserve every stage's `output_usd_path`.

## Windows vs Linux GPU

| Host | Command | What works |
|------|---------|------------|
| Windows (no GPU, this machine) | `python scripts/simready_preflight.py --skip-content-agents --env-file .simready-env` | Conversion-only: `convert-to-usd` → `validate-usd-minimum` |
| Linux + Docker + NVIDIA GPU | `python .agents/skills/omniverse-cad-to-simready/references/preflight/scripts/preflight.py --env-file $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env` | Full: Material+Physics → conform → validations → OVRTX → package |

See `references/preflight/README.md` for the full prerequisite matrix (Python 3.12, uv, Docker, NVIDIA Container Toolkit, provider keys: `NVIDIA_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_API_KEY`).

## Frontend

- **Route:** `?tab=simready` — `apps/web-dashboard/src/components/SimReadyLab.tsx`
- **Types:** `src/types/simready.ts`, `src/lib/simreadyWorkflow.ts`, `src/services/simready.ts`
- **Map 3D:** Toggle **3D Terrain (SimReady DEM)** in Live Map — uses Terrarium DEM (`raster-dem` + `setTerrain`) mirroring the DEM→USD heightfield route. Link to lab for CAD→USD conversion.

## Running locally (conversion-only, Windows-safe)

```powershell
python scripts/simready_preflight.py --skip-content-agents --env-file .simready-env --report .simready-preflight.json --markdown-report .simready-preflight.md
# then in browser: open SimReady Lab → drop a .obj/.stl/.tif → Run workflow (simulated; real conversion needs usd-convert-cad wheel on Python 3.12 Linux)
```

## Full deploy (Linux GPU)

```bash
python3 .agents/skills/omniverse-cad-to-simready/references/preflight/scripts/preflight.py \
  --env-file $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env \
  --markdown-report $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.md
. $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env

python3 .agents/skills/omniverse-cad-to-simready/references/convert-to-usd/scripts/run.py \
  /path/to/terrain.obj /tmp/geosentinel-simready/conversion --report /tmp/geosentinel-simready/conversion.json

python3 .agents/skills/omniverse-cad-to-simready/references/validate-usd-minimum/scripts/run.py \
  /tmp/geosentinel-simready/conversion/output.usd --report /tmp/geosentinel-simready/minimum-usd.json

# … then content-agents, simready-conform-profile, validations, ovrtx-render, assemble-package-source, nv-core-package-sample
# See references/commands.md for exact portable patterns.
```

## Next work

- Connect the lab's "**Run workflow**" button to a real `simready-service` FastAPI that shells out to the installed reference scripts (when `PHYSICAL_AI_REQUIRE_PREFLIGHT=1`).
- Enable `GSP.001` FET005 repair: OVRTX render → vision-selected grasp line via `simready-foundation-conform-fet-005`.
- Generate Isaac Sim landslide runout from the conformed terrain USD (`physics_usd_path`) — cohesion/friction → `UsdPhysics.RigidBodyAPI` + colliders.

## References

- Skill: `.agents/skills/omniverse-cad-to-simready/SKILL.md`
- Workflow: `references/workflow.md` · Commands: `references/commands.md` · Preflight: `references/preflight/README.md` · Troubleshooting: `references/troubleshooting.md`
- Upstream pins: `upstream-versions.lock.json` (usd-convert-cad v0.2.0, simready-foundation v2026.04.1, content-agents v0.5.2)
