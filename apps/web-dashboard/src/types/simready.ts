/**
 * SimReady types — mirrors NVIDIA omniverse-cad-to-simready v0.2.0
 * workflow inputs/outputs (see .agents/skills/omniverse-cad-to-simready/references/workflow.md).
 *
 * GeoSentinel adaptation: terrain/DEM CAD assets for landslide physics simulation.
 * Default profile is Prop-Robotics-Neutral for generic terrain props.
 */

export type SimReadyProfile = 'Prop-Robotics-Neutral' | 'Robot-Body-Runnable' | 'Custom'
export type PropertyAssignmentIntent = 'run' | 'skip' | 'blocked'
export type WorkflowStatus = 'passed' | 'blocked' | 'failed' | 'needs_rerun'
export type StageStatus = 'pending' | 'running' | 'passed' | 'blocked' | 'failed' | 'needs_rerun' | 'skipped'

export interface SimReadyInputs {
  sourceAsset: File | null
  sourceAssetPath: string
  sourceFormat: string
  outputRoot: string
  simreadyProfile: SimReadyProfile
  profileVersion: string
  propertyAssignmentIntent: PropertyAssignmentIntent
  enablePreview: boolean
  enablePackage: boolean
  packageName: string
  packageVersion: string
}

export interface StageReport {
  stage: string
  title: string
  status: StageStatus
  inputPath?: string
  outputPath?: string
  reportPath?: string
  durationMs?: number
  message?: string
  details?: Record<string, unknown>
}

export interface ValidationGate {
  id: string
  label: string
  requirement: string
  status: StageStatus
  findings: number
  reportPath?: string
}

// Consolidated report JSON per workflow.md Output Report Fields
export interface SimReadyReport {
  source_asset_path: string
  source_format: string
  asset_context_report_path?: string
  asset_identity?: string
  output_root: string
  output_usd_path?: string
  conformed_usd_path?: string
  simready_profile: string
  property_assignment_status: PropertyAssignmentIntent
  materialized_usd_path?: string
  physics_usd_path?: string
  textured_usdz_path?: string
  render_preview_path?: string
  deliverable_root?: string
  assembled_root_usd_path?: string
  assembly_report_path?: string
  package_root?: string
  package_definition_path?: string
  markdown_report_path: string
  passed: boolean
  needs_rerun: boolean
  rerun_reasons: string[]
  steps: StageReport[]
  validation_gates: ValidationGate[]
  generated_at: string
}

export const SUPPORTED_FORMATS: Record<string, { route: string; supported: boolean }> = {
  urdf: { route: 'urdf-usd-converter via convert-to-usd', supported: true },
  xml: { route: 'mujoco-usd-converter via convert-to-usd', supported: true },
  fbx: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  obj: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  gltf: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  glb: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  dae: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  stl: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  ply: { route: 'usd-convert-gsplat via convert-to-usd', supported: true },
  spz: { route: 'usd-convert-gsplat via convert-to-usd', supported: true },
  usd: { route: 'skip — validate directly', supported: true },
  usda: { route: 'skip — validate directly', supported: true },
  usdc: { route: 'skip — validate directly', supported: true },
  usdz: { route: 'skip — validate directly', supported: true },
  // GeoSentinel terrain specifics
  tif: { route: 'DEM GeoTIFF → usd-convert-cad (heightfield)', supported: true },
  tiff: { route: 'DEM GeoTIFF → usd-convert-cad (heightfield)', supported: true },
  step: { route: 'usd-convert-cad via convert-to-usd', supported: true },
  stp: { route: 'usd-convert-cad via convert-to-usd', supported: true },
}

export const DEFAULT_INPUTS: SimReadyInputs = {
  sourceAsset: null,
  sourceAssetPath: '',
  sourceFormat: '',
  outputRoot: '/tmp/geosentinel-simready/terrain-run-01',
  simreadyProfile: 'Prop-Robotics-Neutral',
  profileVersion: '1.0.0',
  propertyAssignmentIntent: 'skip',
  enablePreview: true,
  enablePackage: false,
  packageName: 'geosentinel-terrain',
  packageVersion: '1.0.0',
}
