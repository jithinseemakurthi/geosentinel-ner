/**
 * SimReady workflow helpers — implements the 18-step CAD-to-SimReady pipeline
 * from .agents/skills/omniverse-cad-to-simready/references/workflow.md
 * and preflight contract in references/preflight/README.md.
 *
 * On Windows without GPU, the workflow runs in conversion-only mode
 * (property_assignment_intent=skip) via `preflight --skip-content-agents`.
 */

import type { SimReadyInputs, StageReport, SimReadyReport, ValidationGate } from '@/types/simready'

export const WORKFLOW_STEPS = [
  { id: 'source', label: '1. Confirm source asset', ref: 'workflow §1', cmd: '—' },
  { id: 'intent', label: '2. Resolve property_assignment_intent', ref: 'workflow §2', cmd: '—' },
  { id: 'preflight', label: '3. Preflight — deps & manifest', ref: 'preflight/scripts/preflight.py', cmd: 'preflight --skip-content-agents' },
  { id: 'content-agents-gate', label: '4. Content Agents readiness gate', ref: 'deploy-content-agents', cmd: '— (skip when intent=skip)' },
  { id: 'context', label: '5. identify-asset-context', ref: 'identify-asset-context', cmd: 'identify-asset-context' },
  { id: 'convert', label: '6. convert-to-usd', ref: 'convert-to-usd/scripts/run.py', cmd: 'convert-to-usd' },
  { id: 'validate-minimum', label: '7. validate-usd-minimum', ref: 'validate-usd-minimum', cmd: 'validate-usd-minimum' },
  { id: 'material', label: '8. Content Agents · Material', ref: 'content-agents --call material', cmd: 'content-agents --call material' },
  { id: 'physics', label: '9. Content Agents · Physics', ref: 'content-agents --call physics', cmd: 'content-agents --call physics' },
  { id: 'conform', label: '10. simready-conform-profile', ref: 'simready-conform-profile', cmd: 'simready-conform-profile' },
  { id: 'validate-asset', label: '11. omni-asset-validate', ref: 'omni-asset-validate', cmd: 'omni-asset-validate' },
  { id: 'validate-geo', label: '12. omni-asset-validate-geometry', ref: 'omni-asset-validate-geometry', cmd: 'omni-asset-validate-geometry' },
  { id: 'validate-phys', label: '13. omni-asset-validate-physics', ref: 'omni-asset-validate-physics', cmd: 'omni-asset-validate-physics' },
  { id: 'validate-profile', label: '14. simready-validate (profile)', ref: 'simready-validate', cmd: 'simready-validate' },
  { id: 'render', label: '15. ovrtx-render-service (preview)', ref: 'ovrtx-render-service', cmd: 'ovrtx-render-service' },
  { id: 'assemble', label: '16. assemble-package-source', ref: 'assemble-package-source', cmd: 'assemble-package-source' },
  { id: 'package', label: '17. nv-core-package-sample', ref: 'nv-core-package-sample', cmd: 'nv-core-package-sample' },
  { id: 'report', label: '18. Consolidated report', ref: 'workflow §18', cmd: 'omniverse-cad-to-simready-report.md' },
] as const

export function extFromPath(p: string): string {
  const m = p.split('.').pop()?.toLowerCase() ?? ''
  return m.split('?')[0].split('#')[0]
}

export function mockStageReports(inputs: SimReadyInputs): { stages: StageReport[]; gates: ValidationGate[] } {
  const isSkip = inputs.propertyAssignmentIntent === 'skip'
  const now = Date.now()
  const stages: StageReport[] = WORKFLOW_STEPS.map((s) => {
    if ((s.id === 'material' || s.id === 'physics' || s.id === 'content-agents-gate') && isSkip) {
      return { stage: s.id, title: s.label, status: 'skipped', message: 'property_assignment_intent=skip — conversion-only mode', reportPath: undefined }
    }
    if ((s.id === 'assemble' || s.id === 'package') && !inputs.enablePackage) {
      return { stage: s.id, title: s.label, status: 'skipped', message: 'Packaging not requested', reportPath: undefined }
    }
    if (s.id === 'render' && !inputs.enablePreview) {
      return { stage: s.id, title: s.label, status: 'skipped', message: 'Preview not requested', reportPath: undefined }
    }
    return { stage: s.id, title: s.label, status: 'pending', reportPath: `${inputs.outputRoot}/pipeline/${s.id}.json` }
  })
  const gates: ValidationGate[] = [
    { id: 'UN.007', label: 'metersPerUnit == 1.0', requirement: 'UN.007', status: 'pending', findings: 0 },
    { id: 'GSP.001', label: 'Grasp simulation (prop)', requirement: 'GSP.001', status: 'pending', findings: 0 },
    { id: 'RB.MB.001', label: 'Multi-body physics', requirement: 'RB.MB.001', status: 'pending', findings: 0 },
  ]
  void now
  return { stages, gates }
}

export function buildMockReport(inputs: SimReadyInputs, stages: StageReport[], gates: ValidationGate[]): SimReadyReport {
  const passed = stages.every((s) => s.status === 'passed' || s.status === 'skipped')
  const needsRerun = gates.some((g) => g.status === 'needs_rerun' || g.findings > 0)
  const base = inputs.sourceAssetPath || 'terrain-sample.obj'
  return {
    source_asset_path: base,
    source_format: inputs.sourceFormat || 'obj',
    asset_context_report_path: `${inputs.outputRoot}/pipeline/context.json`,
    asset_identity: 'Himalayan terrain — shale/soil composite (terrain prop, high confidence)',
    output_root: inputs.outputRoot,
    output_usd_path: `${inputs.outputRoot}/conversion/output.usd`,
    conformed_usd_path: `${inputs.outputRoot}/pipeline/conform/conformed.usd`,
    simready_profile: inputs.simreadyProfile,
    property_assignment_status: inputs.propertyAssignmentIntent,
    render_preview_path: inputs.enablePreview ? `${inputs.outputRoot}/pipeline/06_render/thumbnail.png` : undefined,
    deliverable_root: inputs.enablePackage ? `${inputs.outputRoot}/deliverable` : undefined,
    assembled_root_usd_path: inputs.enablePackage ? `deliverable/simready_usd/sm_${inputs.packageName}_01.usd` : undefined,
    markdown_report_path: `${inputs.outputRoot}/omniverse-cad-to-simready-report.md`,
    passed,
    needs_rerun: needsRerun,
    rerun_reasons: needsRerun ? gates.filter((g) => g.findings > 0).map((g) => `${g.id}: ${g.findings} finding(s)`) : [],
    steps: stages,
    validation_gates: gates,
    generated_at: new Date().toISOString(),
  }
}

export function preflightCommandPreview(intent: string): string {
  if (intent === 'skip') {
    return [
      'python3 .agents/skills/omniverse-cad-to-simready/references/preflight/scripts/preflight.py \\',
      '  --skip-content-agents \\',
      '  --env-file $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env \\',
      '  --report $OUTPUT_ROOT/cad-to-simready-preflight.json',
      '',
      '. $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env',
    ].join('\n')
  }
  return [
    'python3 .agents/skills/omniverse-cad-to-simready/references/preflight/scripts/preflight.py \\',
    '  --env-file $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env',
    '',
    '. $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env',
  ].join('\n')
}
