/**
 * SimReady API stubs — mirrors the portable command patterns in
 * .agents/skills/omniverse-cad-to-simready/references/commands.md
 *
 * In production these proxy to a Python service (gis-service or simready-service)
 * that runs the stage reference scripts directly (per Hard Rules: use stage-specific
 * installed reference scripts, no monolithic runner).
 * For the browser demo we simulate the workflow so the UX can be reviewed without
 * GPU / Docker / Content Agents.
 */

import type { SimReadyInputs, SimReadyReport, StageReport, ValidationGate } from '@/types/simready'
import { SUPPORTED_FORMATS } from '@/types/simready'
import { WORKFLOW_STEPS, buildMockReport, extFromPath } from '@/lib/simreadyWorkflow'

export function validateInputs(inputs: SimReadyInputs): string | null {
  if (!inputs.sourceAssetPath) return 'Source asset path is required (workflow § Inputs).'
  const ext = extFromPath(inputs.sourceAssetPath).toLowerCase()
  if (ext && !(ext in SUPPORTED_FORMATS)) return `Unsupported source format .${ext} — check Source Routing table (workflow.md).`
  if (!inputs.outputRoot) return 'output_root is required.'
  return null
}

export async function simulateWorkflow(
  inputs: SimReadyInputs,
  onStage: (stage: StageReport, idx: number) => void,
): Promise<SimReadyReport> {
  const stages: StageReport[] = WORKFLOW_STEPS.map((s) => ({
    stage: s.id,
    title: s.label,
    status: 'pending',
  }))

  const gates: ValidationGate[] = [
    { id: 'UN.007', label: 'metersPerUnit == 1.0', requirement: 'UN.007', status: 'pending', findings: 0 },
    { id: 'GSP.001', label: 'Grasp / FET005', requirement: 'GSP.001', status: 'pending', findings: 0 },
    { id: 'RB.MB.001', label: 'Multi-body physics · FET004', requirement: 'RB.MB.001', status: 'pending', findings: 0 },
  ]

  const isSkip = inputs.propertyAssignmentIntent === 'skip'

  for (let i = 0; i < stages.length; i++) {
    const sid = stages[i].stage
    // Skip logic per skill Hard Rules
    if ((sid === 'material' || sid === 'physics' || sid === 'content-agents-gate') && isSkip) {
      stages[i] = { ...stages[i], status: 'skipped', message: 'property_assignment_intent=skip — conversion-only (workflow § Minimum Viable Scope)' }
      onStage(stages[i], i)
      continue
    }
    if ((sid === 'assemble' || sid === 'package') && !inputs.enablePackage) {
      stages[i] = { ...stages[i], status: 'skipped', message: 'Packaging not requested' }
      onStage(stages[i], i)
      continue
    }
    if (sid === 'render' && !inputs.enablePreview) {
      stages[i] = { ...stages[i], status: 'skipped', message: 'Preview disabled' }
      onStage(stages[i], i)
      continue
    }

    stages[i] = { ...stages[i], status: 'running' }
    onStage(stages[i], i)

    // Simulate work: stagger timings to feel real, longer for heavy stages
    const delay =
      sid === 'convert' ? 1100 :
      sid === 'validate-minimum' ? 450 :
      sid === 'preflight' ? 700 :
      sid === 'conform' ? 600 :
      sid.startsWith('validate') ? 400 :
      300
    await new Promise((r) => setTimeout(r, delay))

    // Inject a realistic non-blocking finding for demo (UN.007 fixed in conform, GSP.001 needs rerun)
    if (sid === 'validate-minimum') {
      stages[i] = { ...stages[i], status: 'passed', message: 'USD viability OK — metersPerUnit 1.0, profile issues deferred per Hard Rules', outputPath: `${inputs.outputRoot}/conversion/output.usd` }
    } else if (sid === 'conform') {
      stages[i] = { ...stages[i], status: 'passed', message: 'SimReady conform applied — FET001 (UN.007) checked', outputPath: `${inputs.outputRoot}/pipeline/conform/conformed.usd` }
    } else if (sid === 'validate-profile') {
      stages[i] = { ...stages[i], status: 'needs_rerun', message: 'GSP.001 single finding — route to FET005 when vision available', outputPath: `${inputs.outputRoot}/pipeline/simready-profile.json` }
      gates[1].findings = 1
      gates[1].status = 'needs_rerun'
    } else if (sid.startsWith('validate')) {
      const ok = sid !== 'validate-profile'
      stages[i] = { ...stages[i], status: ok ? 'passed' : 'needs_rerun', message: ok ? 'No blocking findings' : 'See rerun_reasons' }
      if (ok && sid === 'validate-asset') gates[0].status = 'passed'
    } else if (sid === 'render') {
      stages[i] = { ...stages[i], status: 'passed', message: 'OVRTX render OK (black background, no authored lights)', outputPath: `${inputs.outputRoot}/pipeline/06_render/thumbnail.png` }
    } else {
      stages[i] = { ...stages[i], status: 'passed', message: 'OK', outputPath: `${inputs.outputRoot}/pipeline/${sid}/output` }
    }
    onStage(stages[i], i)
  }

  // Finalize gates that were not touched
  for (const g of gates) if (g.status === 'pending') { g.status = 'passed'; g.findings = 0 }

  return buildMockReport(inputs, stages, gates)
}
