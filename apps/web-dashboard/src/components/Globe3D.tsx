/**
 * GeoSentinel cinematic 3D Earth — login hero (premium pass).
 *
 * Realistic day → night via custom shader blending
 * earth_atmos + earth_lights across a soft solar terminator,
 * ocean sun-glint, layered atmosphere, lens flare, starfield,
 * NER monitoring stations with light-columns, network arcs with
 * traveling data pulses, and an inclined satellite on orbit.
 *
 * Drag to rotate · wheel/pinch to zoom · inertia + idle auto-spin.
 */
import { useEffect, useRef } from 'react'
import * as THREE from 'three'

// ── Data ──────────────────────────────────────────────────────────
const NER_MARKERS: Array<{ name: string; lat: number; lon: number; color: number }> = [
  { name: 'Aizawl', lat: 23.7271, lon: 92.7176, color: 0x38bdf8 },
  { name: 'Imphal', lat: 24.817, lon: 93.9368, color: 0x34d399 },
  { name: 'Shillong', lat: 25.5788, lon: 91.8933, color: 0xa78bfa },
  { name: 'Gangtok', lat: 27.3389, lon: 88.6065, color: 0xf59e0b },
  { name: 'Kohima', lat: 25.6751, lon: 94.1086, color: 0xf59e0b },
]

// Connect as a network ring + one cross-link
const ARC_LINKS: Array<[number, number]> = [
  [0, 1],
  [1, 4],
  [4, 3],
  [3, 2],
  [2, 0],
  [0, 4],
]

// ── Helpers ───────────────────────────────────────────────────────
function latLonToVec3(lat: number, lon: number, radius: number): THREE.Vector3 {
  const phi = THREE.MathUtils.degToRad(90 - lat)
  const theta = THREE.MathUtils.degToRad(lon + 180)
  return new THREE.Vector3(
    -radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

function makeFallbackTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 1024
  canvas.height = 512
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#052c4f'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  for (let i = 0; i < 6000; i++) {
    const x = Math.random() * canvas.width
    const y = Math.random() * canvas.height
    const r = 2 + Math.random() * 8
    ctx.fillStyle = Math.random() > 0.28 ? 'rgba(22,106,78,0.28)' : 'rgba(56,189,248,0.12)'
    ctx.beginPath()
    ctx.arc(x, y, r, 0, Math.PI * 2)
    ctx.fill()
  }
  const t = new THREE.CanvasTexture(canvas)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

function makeRadialTexture(stops: Array<[number, string]>, size = 256): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = c.height = size
  const ctx = c.getContext('2d')!
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  stops.forEach(([o, col]) => g.addColorStop(o, col))
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const t = new THREE.CanvasTexture(c)
  t.colorSpace = THREE.SRGBColorSpace
  return t
}

function makeBeamTexture(): THREE.CanvasTexture {
  const c = document.createElement('canvas')
  c.width = 32
  c.height = 128
  const ctx = c.getContext('2d')!
  const g = ctx.createLinearGradient(0, 0, 0, 128)
  // bottom (near surface) opaque → top fades out
  g.addColorStop(0, 'rgba(255,255,255,1)')
  g.addColorStop(0.32, 'rgba(255,255,255,0.55)')
  g.addColorStop(0.7, 'rgba(255,255,255,0.12)')
  g.addColorStop(1, 'rgba(255,255,255,0)')
  ctx.fillStyle = g
  ctx.fillRect(0, 0, 32, 128)
  const t = new THREE.CanvasTexture(c)
  // alphaMap uses luminance — keep linear
  return t
}

// ── Component ─────────────────────────────────────────────────────
export default function Globe3D() {
  const hostRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    // Scene
    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(0x020617, 0.032)

    const camera = new THREE.PerspectiveCamera(42, host.clientWidth / host.clientHeight, 0.1, 100)
    camera.position.set(0.15, 0.05, 3.35)

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(host.clientWidth, host.clientHeight)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.12
    renderer.domElement.className = 'h-full w-full cursor-grab active:cursor-grabbing touch-none select-none'
    renderer.domElement.setAttribute('aria-label', 'Interactive Earth globe — drag to rotate, wheel to zoom')
    host.appendChild(renderer.domElement)

    // Groups
    const globeGroup = new THREE.Group()
    globeGroup.position.x = 0.18
    globeGroup.rotation.z = THREE.MathUtils.degToRad(-8)
    scene.add(globeGroup)

    const sunDirWorld = new THREE.Vector3(-3.5, 2.2, 4).normalize()
    const globeCenter = new THREE.Vector3(0.18, 0, 0)

    // Textures
    const loader = new THREE.TextureLoader()
    loader.setCrossOrigin('anonymous')
    const url = (f: string) => `https://unpkg.com/three@0.160.0/examples/textures/planets/${f}`

    const fallbackDay = makeFallbackTexture()
    const fallbackNight = (() => {
      const c = document.createElement('canvas')
      c.width = 1024
      c.height = 512
      const ctx = c.getContext('2d')!
      ctx.fillStyle = '#040b18'
      ctx.fillRect(0, 0, 1024, 512)
      for (let i = 0; i < 2500; i++) {
        const x = Math.random() * 1024
        const y = Math.random() * 512
        ctx.fillStyle = `rgba(253,224,120,${0.35 + Math.random() * 0.5})`
        ctx.fillRect(x, y, 1.2, 1.2)
      }
      const t = new THREE.CanvasTexture(c)
      t.colorSpace = THREE.SRGBColorSpace
      return t
    })()

    const dayTexture = loader.load(url('earth_atmos_2048.jpg'), undefined, undefined, () => {
      // fallback handled via uniform swap in onError — but material already has fallback
      earthMat.uniforms.uDay.value = fallbackDay
    })
    dayTexture.colorSpace = THREE.SRGBColorSpace
    dayTexture.anisotropy = renderer.capabilities.getMaxAnisotropy()

    const nightTexture = loader.load(url('earth_lights_2048.png'), undefined, undefined, () => {
      earthMat.uniforms.uNight.value = fallbackNight
    })
    nightTexture.colorSpace = THREE.SRGBColorSpace
    nightTexture.anisotropy = renderer.capabilities.getMaxAnisotropy()

    const specTexture = loader.load(url('earth_specular_2048.jpg'))
    const cloudsTexture = loader.load(url('earth_clouds_1024.png'))

    // ── Earth — custom day/night shader ──────────────────────────
    const earthMat = new THREE.ShaderMaterial({
      uniforms: {
        uDay: { value: dayTexture },
        uNight: { value: nightTexture },
        uSpec: { value: specTexture },
        uSunDir: { value: sunDirWorld.clone() },
      },
      vertexShader: `
        varying vec2 vUv;
        varying vec3 vWorldNormal;
        varying vec3 vWorldPos;
        void main() {
          vUv = uv;
          vec4 worldPos = modelMatrix * vec4(position, 1.0);
          vWorldPos = worldPos.xyz;
          vWorldNormal = normalize(mat3(modelMatrix) * normal);
          gl_Position = projectionMatrix * viewMatrix * worldPos;
        }
      `,
      fragmentShader: `
        uniform sampler2D uDay;
        uniform sampler2D uNight;
        uniform sampler2D uSpec;
        uniform vec3 uSunDir;
        varying vec2 vUv;
        varying vec3 vWorldNormal;
        varying vec3 vWorldPos;
        void main() {
          vec3 n = normalize(vWorldNormal);
          vec3 s = normalize(uSunDir);
          float sunDot = dot(n, s);

          float dayW   = smoothstep(-0.08, 0.25, sunDot);
          float nightW = 1.0 - smoothstep(-0.22, 0.08, sunDot);

          vec3 dayTex   = texture2D(uDay,   vUv).rgb;
          vec3 nightTex = texture2D(uNight, vUv).rgb;

          // Day: warm diffuse + tiny ambient so terminator isn't black
          vec3 dayCol = dayTex * (0.14 + 1.12 * max(sunDot, 0.0));

          // Night: dim earth + city lights (warm-boosted, stronger)
          vec3 nightCol = dayTex * 0.03 + nightTex * vec3(1.42, 1.06, 0.62) * 2.2;

          vec3 col = mix(nightCol, dayCol, dayW);

          // Sunset / sunrise warm band along the terminator
          float term = 1.0 - smoothstep(0.0, 0.30, abs(sunDot + 0.03));
          col += vec3(1.0, 0.44, 0.12) * term * 0.24 * (0.22 + 0.78 * dayW);

          // Ocean sun glint — Blinn-Phong, day side only, modulated by specular map
          vec3 v = normalize(cameraPosition - vWorldPos);
          vec3 h = normalize(s + v);
          float specMask = texture2D(uSpec, vUv).r;
          float spec = pow(max(dot(n, h), 0.0), 44.0) * specMask * dayW;
          col += vec3(0.58, 0.78, 1.0) * spec * 0.62;

          gl_FragColor = vec4(col, 1.0);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }
      `,
    })
    const earth = new THREE.Mesh(new THREE.SphereGeometry(1, 128, 128), earthMat)
    ;(earth.material as THREE.ShaderMaterial).toneMapped = true
    globeGroup.add(earth)

    // Clouds — Lambert so they shade with the directional sun
    const cloudMat = new THREE.MeshLambertMaterial({
      map: cloudsTexture,
      transparent: true,
      opacity: 0.26,
      depthWrite: false,
    })
    // clouds shouldn't be fogged
    ;(cloudMat as unknown as { fog: boolean }).fog = false
    const clouds = new THREE.Mesh(new THREE.SphereGeometry(1.012, 96, 96), cloudMat)
    globeGroup.add(clouds)

    // ── Atmosphere — dual layer ──────────────────────────────────
    const atmosMat = new THREE.ShaderMaterial({
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      uniforms: {
        uColor: { value: new THREE.Color(0x38bdf8) },
        uSunDir: { value: sunDirWorld.clone() },
      },
      vertexShader: `
        varying vec3 vNormal;
        varying vec3 vViewDir;
        varying vec3 vWorldNormal;
        void main() {
          vNormal = normalize(normalMatrix * normal);
          vWorldNormal = normalize(mat3(modelMatrix) * normal);
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vViewDir = normalize(-mv.xyz);
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform vec3 uColor;
        uniform vec3 uSunDir;
        varying vec3 vNormal;
        varying vec3 vViewDir;
        varying vec3 vWorldNormal;
        void main() {
          float rim = pow(max(0.72 - dot(normalize(vNormal), normalize(vViewDir)), 0.0), 3.5);
          float sunSide = clamp(dot(normalize(vWorldNormal), normalize(uSunDir)) * 0.5 + 0.58, 0.15, 1.0);
          gl_FragColor = vec4(uColor, rim * sunSide * 1.05);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }
      `,
    })
    ;(atmosMat as unknown as { fog: boolean }).fog = false
    const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(1.068, 96, 96), atmosMat)
    globeGroup.add(atmosphere)

    // Soft outer halo (sprite billboarding at globe center — cheap & gorgeous)
    const haloTex = makeRadialTexture(
      [
        [0, 'rgba(56,189,248,0.95)'],
        [0.18, 'rgba(56,189,248,0.42)'],
        [0.42, 'rgba(56,189,248,0.16)'],
        [0.72, 'rgba(56,189,248,0.04)'],
        [1, 'rgba(56,189,248,0)'],
      ],
      256,
    )
    const haloMat = new THREE.SpriteMaterial({
      map: haloTex,
      transparent: true,
      opacity: 0.72,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    ;(haloMat as unknown as { fog: boolean }).fog = false
    const halo = new THREE.Sprite(haloMat)
    halo.position.copy(globeCenter)
    halo.scale.set(3.18, 3.18, 1)
    scene.add(halo)

    // ── Lens / sun glow ──────────────────────────────────────────
    const sunGlowTex = makeRadialTexture(
      [
        [0, 'rgba(255,250,235,1)'],
        [0.16, 'rgba(255,220,130,0.95)'],
        [0.32, 'rgba(255,170,70,0.50)'],
        [0.6, 'rgba(255,120,40,0.14)'],
        [1, 'rgba(0,0,0,0)'],
      ],
      256,
    )
    const sunGlowMat = new THREE.SpriteMaterial({
      map: sunGlowTex,
      transparent: true,
      opacity: 0.0, // faded in after load to avoid flash
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    ;(sunGlowMat as unknown as { fog: boolean }).fog = false
    const sunGlow = new THREE.Sprite(sunGlowMat)
    sunGlow.position.copy(globeCenter).add(sunDirWorld.clone().multiplyScalar(6.2))
    sunGlow.scale.set(4.8, 4.8, 1)
    scene.add(sunGlow)
    // fade in
    setTimeout(() => (sunGlowMat.opacity = 0.95), 60)

    const flareRingTex = makeRadialTexture(
      [
        [0.45, 'rgba(125,211,252,0)'],
        [0.52, 'rgba(125,211,252,0.55)'],
        [0.56, 'rgba(125,211,252,0.22)'],
        [0.72, 'rgba(125,211,252,0)'],
      ],
      256,
    )
    const flareRingMat = new THREE.SpriteMaterial({
      map: flareRingTex,
      transparent: true,
      opacity: 0.42,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    ;(flareRingMat as unknown as { fog: boolean }).fog = false
    const flareRing = new THREE.Sprite(flareRingMat)
    flareRing.position.copy(globeCenter).add(sunDirWorld.clone().multiplyScalar(2.55))
    flareRing.scale.set(1.55, 1.55, 1)
    scene.add(flareRing)

    // ── Nebula backdrop (3 huge soft sprites, very far) ─────────
    const nebulaSprites: THREE.Sprite[] = []
    const nebulaDefs: Array<{ pos: THREE.Vector3; scale: number; colorStops: Array<[number, string]>; opacity: number }> = [
      {
        pos: new THREE.Vector3(-9, 4.5, -16),
        scale: 18,
        colorStops: [
          [0, 'rgba(99,102,241,0.36)'],
          [0.35, 'rgba(79,70,229,0.18)'],
          [1, 'rgba(0,0,0,0)'],
        ],
        opacity: 0.55,
      },
      {
        pos: new THREE.Vector3(10, -3.5, -14),
        scale: 15,
        colorStops: [
          [0, 'rgba(6,182,212,0.32)'],
          [0.4, 'rgba(6,182,212,0.12)'],
          [1, 'rgba(0,0,0,0)'],
        ],
        opacity: 0.5,
      },
      {
        pos: new THREE.Vector3(2, 7, -18),
        scale: 20,
        colorStops: [
          [0, 'rgba(168,85,247,0.22)'],
          [0.5, 'rgba(168,85,247,0.09)'],
          [1, 'rgba(0,0,0,0)'],
        ],
        opacity: 0.42,
      },
    ]
    for (const d of nebulaDefs) {
      const tex = makeRadialTexture(d.colorStops, 256)
      const mat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        opacity: d.opacity,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      ;(mat as unknown as { fog: boolean }).fog = false
      const s = new THREE.Sprite(mat)
      s.position.copy(d.pos)
      s.scale.set(d.scale, d.scale, 1)
      scene.add(s)
      nebulaSprites.push(s)
    }

    // ── Markers + beams + pulse rings ────────────────────────────
    const beamTex = makeBeamTexture()
    const beamGeo = new THREE.CylinderGeometry(0.004, 0.014, 0.16, 10, 1, true)
    // shift so bottom sits at y=0 (base at marker surface)
    beamGeo.translate(0, 0.08, 0)

    type MarkerEntry = {
      core: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>
      ring: THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>
      beam: THREE.Mesh<THREE.CylinderGeometry, THREE.MeshBasicMaterial>
      phase: number
    }
    const markers: MarkerEntry[] = []
    for (const m of NER_MARKERS) {
      const p = latLonToVec3(m.lat, m.lon, 1.018)
      const normal = p.clone().normalize()

      const core = new THREE.Mesh(
        new THREE.SphereGeometry(0.013, 16, 16),
        new THREE.MeshBasicMaterial({ color: m.color }),
      )
      ;(core.material as unknown as { fog: boolean }).fog = false
      core.position.copy(p)
      globeGroup.add(core)

      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.018, 0.031, 36),
        new THREE.MeshBasicMaterial({
          color: m.color,
          transparent: true,
          opacity: 0.78,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      )
      ;(ring.material as unknown as { fog: boolean }).fog = false
      ring.position.copy(p)
      ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal)
      globeGroup.add(ring)

      const beamMat = new THREE.MeshBasicMaterial({
        color: m.color,
        transparent: true,
        opacity: 0.42,
        alphaMap: beamTex,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      ;(beamMat as unknown as { fog: boolean }).fog = false
      const beam = new THREE.Mesh(beamGeo, beamMat)
      beam.position.copy(p)
      beam.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal)
      globeGroup.add(beam)

      markers.push({ core, ring, beam, phase: Math.random() * Math.PI * 2 })
    }

    // ── Network arcs + traveling pulses ──────────────────────────
    type ArcInfo = {
      curve: THREE.QuadraticBezierCurve3
      geo: THREE.BufferGeometry
      line: THREE.Line
      pulse: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial>
      pulse2: THREE.Mesh<THREE.SphereGeometry, THREE.MeshBasicMaterial> | null
      offset: number
    }
    const arcInfos: ArcInfo[] = []
    for (let k = 0; k < ARC_LINKS.length; k++) {
      const [ai, bi] = ARC_LINKS[k]
      const a = latLonToVec3(NER_MARKERS[ai].lat, NER_MARKERS[ai].lon, 1.018)
      const b = latLonToVec3(NER_MARKERS[bi].lat, NER_MARKERS[bi].lon, 1.018)
      const mid = a.clone().add(b).multiplyScalar(0.5)
      const dist = a.distanceTo(b)
      mid.normalize().multiplyScalar(1 + dist * 0.44 + 0.06)
      const curve = new THREE.QuadraticBezierCurve3(a.clone(), mid, b.clone())
      const pts = curve.getPoints(84)
      const geo = new THREE.BufferGeometry().setFromPoints(pts)
      geo.setDrawRange(0, 0)
      const mat = new THREE.LineBasicMaterial({
        color: 0x7dd3fc,
        transparent: true,
        opacity: 0,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
      ;(mat as unknown as { fog: boolean }).fog = false
      const line = new THREE.Line(geo, mat)
      line.frustumCulled = false
      globeGroup.add(line)

      const pulseMat = new THREE.MeshBasicMaterial({
        color: 0xe0f2fe,
        transparent: true,
        opacity: 0.95,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      ;(pulseMat as unknown as { fog: boolean }).fog = false
      const pulse = new THREE.Mesh(new THREE.SphereGeometry(0.0075, 12, 12), pulseMat)
      pulse.visible = false
      globeGroup.add(pulse)

      // second pulse on longer arcs for a busier network feel
      let pulse2: ArcInfo['pulse2'] = null
      if (dist > 0.22) {
        const m2 = new THREE.Mesh(
          new THREE.SphereGeometry(0.006, 10, 10),
          new THREE.MeshBasicMaterial({
            color: 0xbae6fd,
            transparent: true,
            opacity: 0.9,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
          }),
        )
        ;(m2.material as unknown as { fog: boolean }).fog = false
        m2.visible = false
        globeGroup.add(m2)
        pulse2 = m2
      }

      arcInfos.push({ curve, geo, line, pulse, pulse2, offset: Math.random() })
    }

    // ── Satellite + inclined orbit ───────────────────────────────
    const satOrbitGroup = new THREE.Group()
    satOrbitGroup.position.copy(globeCenter)
    satOrbitGroup.rotation.x = THREE.MathUtils.degToRad(24)
    satOrbitGroup.rotation.z = THREE.MathUtils.degToRad(11)
    scene.add(satOrbitGroup)

    const orbitRadius = 1.42
    const orbitPts: THREE.Vector3[] = []
    for (let a = 0; a <= 360; a += 2) {
      const t = THREE.MathUtils.degToRad(a)
      orbitPts.push(new THREE.Vector3(Math.cos(t) * orbitRadius, 0, Math.sin(t) * orbitRadius))
    }
    const orbitGeo = new THREE.BufferGeometry().setFromPoints(orbitPts)
    const orbitMat = new THREE.LineBasicMaterial({
      color: 0x67e8f9,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    ;(orbitMat as unknown as { fog: boolean }).fog = false
    const orbitLine = new THREE.LineLoop(orbitGeo, orbitMat)
    satOrbitGroup.add(orbitLine)

    // subtle second orbit (polar-ish) — adds depth without clutter
    const orbit2Mat = new THREE.LineBasicMaterial({
      color: 0xa78bfa,
      transparent: true,
      opacity: 0.08,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
    ;(orbit2Mat as unknown as { fog: boolean }).fog = false
    const orbit2Pts: THREE.Vector3[] = []
    for (let a = 0; a <= 360; a += 3) {
      const t = THREE.MathUtils.degToRad(a)
      orbit2Pts.push(new THREE.Vector3(Math.cos(t) * 1.56, Math.sin(t) * 0.62, Math.sin(t) * 1.24))
    }
    const orbit2 = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(orbit2Pts), orbit2Mat)
    globeGroup.add(orbit2)

    const sat = new THREE.Group()

    const bodyMat = new THREE.MeshPhongMaterial({ color: 0xcbd5e1, shininess: 70, specular: 0x6b7280 })
    ;(bodyMat as unknown as { fog: boolean }).fog = false
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.02, 0.02), bodyMat)
    sat.add(body)

    const panelMat = new THREE.MeshPhongMaterial({ color: 0x1e3a5f, shininess: 60, specular: 0x60a5fa })
    ;(panelMat as unknown as { fog: boolean }).fog = false
    const panelGeo = new THREE.BoxGeometry(0.058, 0.0016, 0.022)
    const panelL = new THREE.Mesh(panelGeo, panelMat)
    panelL.position.set(-0.044, 0, 0)
    sat.add(panelL)
    const panelR = new THREE.Mesh(panelGeo, panelMat.clone())
    panelR.position.set(0.044, 0, 0)
    sat.add(panelR)

    const beaconMat = new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.95 })
    ;(beaconMat as unknown as { fog: boolean }).fog = false
    const beacon = new THREE.Mesh(new THREE.SphereGeometry(0.0045, 10, 10), beaconMat)
    beacon.position.set(0, 0.014, 0)
    sat.add(beacon)

    satOrbitGroup.add(sat)

    // ── Starfield — two layers + dust ────────────────────────────
    function makeStarLayer(count: number, rMin: number, rMax: number, size: number, opacity: number) {
      const geo = new THREE.BufferGeometry()
      const pos = new Float32Array(count * 3)
      const col = new Float32Array(count * 3)
      const palettes = [
        new THREE.Color(0xffffff),
        new THREE.Color(0xc7d2fe),
        new THREE.Color(0xbae6fd),
        new THREE.Color(0xfde68a),
      ]
      for (let i = 0; i < count; i++) {
        const r = rMin + Math.random() * (rMax - rMin)
        const theta = Math.random() * Math.PI * 2
        const phi = Math.acos(2 * Math.random() - 1)
        pos[i * 3] = r * Math.sin(phi) * Math.cos(theta)
        pos[i * 3 + 1] = r * Math.cos(phi)
        pos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
        const c = palettes[Math.floor(Math.random() * palettes.length)].clone()
        // slight jitter
        c.offsetHSL((Math.random() - 0.5) * 0.04, 0, (Math.random() - 0.5) * 0.12)
        col[i * 3] = c.r
        col[i * 3 + 1] = c.g
        col[i * 3 + 2] = c.b
      }
      geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
      geo.setAttribute('color', new THREE.BufferAttribute(col, 3))
      const mat = new THREE.PointsMaterial({
        size,
        vertexColors: true,
        transparent: true,
        opacity,
        depthWrite: false,
        sizeAttenuation: true,
      })
      ;(mat as unknown as { fog: boolean }).fog = false
      return new THREE.Points(geo, mat)
    }

    const starsA = makeStarLayer(2600, 11, 34, 0.022, 0.86)
    scene.add(starsA)
    const starsB = makeStarLayer(900, 9, 18, 0.032, 0.72)
    scene.add(starsB)

    // Dust — faint slow drift near the globe, adds parallax
    const dustCount = 340
    const dustGeo = new THREE.BufferGeometry()
    const dustPos = new Float32Array(dustCount * 3)
    for (let i = 0; i < dustCount; i++) {
      const r = 1.45 + Math.random() * 3.2
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      dustPos[i * 3] = r * Math.sin(phi) * Math.cos(theta) + globeCenter.x
      dustPos[i * 3 + 1] = r * Math.cos(phi) * 0.9
      dustPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta)
    }
    dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3))
    const dustMat = new THREE.PointsMaterial({
      color: 0x93c5fd,
      size: 0.011,
      transparent: true,
      opacity: 0.24,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      sizeAttenuation: true,
    })
    ;(dustMat as unknown as { fog: boolean }).fog = false
    const dust = new THREE.Points(dustGeo, dustMat)
    scene.add(dust)

    // ── Lighting ─────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0x3a4a6a, 1.35))
    const sun = new THREE.DirectionalLight(0xffffff, 3.05)
    sun.position.set(-3.5, 2.2, 4)
    scene.add(sun)
    const fill = new THREE.PointLight(0x38bdf8, 6.2, 12)
    fill.position.set(3.8, -1.8, 2.8)
    scene.add(fill)
    const rimLight = new THREE.PointLight(0xa78bfa, 2.2, 10)
    rimLight.position.set(-2.2, 2.8, -3.2)
    scene.add(rimLight)

    // ── Interaction ──────────────────────────────────────────────
    let pointerDown = false
    let lastX = 0
    let lastY = 0
    let velocityX = 0.004
    let velocityY = 0
    let cameraDistance = 3.35
    let targetDistance = 3.35

    const onPointerDown = (e: PointerEvent) => {
      pointerDown = true
      lastX = e.clientX
      lastY = e.clientY
      renderer.domElement.setPointerCapture(e.pointerId)
    }
    const onPointerMove = (e: PointerEvent) => {
      if (!pointerDown) return
      const dx = e.clientX - lastX
      const dy = e.clientY - lastY
      lastX = e.clientX
      lastY = e.clientY
      velocityX = -dx * 0.0035
      velocityY = -dy * 0.0028
      globeGroup.rotation.y += velocityX * 2.2
      globeGroup.rotation.x += velocityY * 2.2
    }
    const onPointerUp = () => {
      pointerDown = false
    }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      targetDistance = THREE.MathUtils.clamp(targetDistance + e.deltaY * 0.0015, 2.15, 4.7)
    }
    renderer.domElement.addEventListener('pointerdown', onPointerDown)
    renderer.domElement.addEventListener('pointermove', onPointerMove)
    renderer.domElement.addEventListener('pointerup', onPointerUp)
    renderer.domElement.addEventListener('pointercancel', onPointerUp)
    renderer.domElement.addEventListener('wheel', onWheel, { passive: false })

    // ── Animate ──────────────────────────────────────────────────
    const clock = new THREE.Clock()
    let frame = 0
    const animate = () => {
      const elapsed = clock.getElapsedTime()

      // Auto-spin when not dragging (+ slight wobble)
      if (!pointerDown) {
        velocityX += (0.0036 - velocityX) * 0.018
        velocityY *= 0.95
        globeGroup.rotation.y += velocityX
        globeGroup.rotation.x += velocityY * 0.7
        // gentle breathing on tilt
        globeGroup.rotation.z = THREE.MathUtils.degToRad(-8 + Math.sin(elapsed * 0.11) * 1.2)
      }

      cameraDistance += (targetDistance - cameraDistance) * 0.09
      camera.position.z = cameraDistance

      // Clouds drift eastward slightly faster than earth
      clouds.rotation.y += 0.0016

      // Halo breathes with the globe
      const haloPulse = 1 + Math.sin(elapsed * 0.9) * 0.035
      halo.scale.set(3.18 * haloPulse, 3.18 * haloPulse, 1)
      halo.material.opacity = 0.62 + Math.sin(elapsed * 0.9) * 0.08

      // Sun glow subtle pulse
      sunGlow.scale.setScalar(4.8 + Math.sin(elapsed * 0.7) * 0.18)
      flareRing.material.opacity = 0.32 + Math.sin(elapsed * 1.1) * 0.1

      // Stars / dust — ultra-slow parallax
      starsA.rotation.y += 0.00022
      starsA.rotation.x += 0.00005
      starsB.rotation.y += 0.00014
      dust.rotation.y += 0.00038
      dust.rotation.x += 0.00008
      orbit2.rotation.y -= 0.0009

      // Markers — pulse ring + core + beam
      markers.forEach((m) => {
        const pulse = (Math.sin(elapsed * 2.7 + m.phase) + 1) * 0.5
        m.ring.scale.setScalar(0.85 + pulse * 1.65)
        m.ring.material.opacity = 0.80 - pulse * 0.50
        m.core.scale.setScalar(1 + pulse * 0.20)
        // beam opacity rides the same pulse, slightly muted
        m.beam.material.opacity = 0.22 + pulse * 0.38
      })

      // Network arcs — staggered draw-in over first ~3.5s, then steady pulses
      arcInfos.forEach((info, idx) => {
        const stagger = idx * 0.22
        const localT = elapsed - stagger
        if (elapsed < 3.8) {
          const frac = THREE.MathUtils.clamp(localT / 2.4, 0, 1)
          const eased = 1 - Math.pow(1 - frac, 2.4)
          const totalPts = 85
          const visible = Math.floor(eased * totalPts)
          info.geo.setDrawRange(0, Math.max(0, visible))
          ;(info.line.material as THREE.LineBasicMaterial).opacity = eased * 0.42
        } else {
          info.geo.setDrawRange(0, 85)
          ;(info.line.material as THREE.LineBasicMaterial).opacity =
            0.28 + Math.sin(elapsed * 0.9 + idx) * 0.07
        }

        // traveling pulse
        const drawCount = (info.geo.drawRange.count as number) ?? 0
        if (drawCount > 18) {
          const t1 = (elapsed * 0.20 + info.offset) % 1
          // keep away from endpoints for cleaner look
          const ct1 = 0.06 + t1 * 0.88
          info.pulse.position.copy(info.curve.getPoint(ct1))
          info.pulse.visible = t1 < 0.985
          const s1 = 0.88 + Math.sin(elapsed * 6 + idx * 1.3) * 0.18
          info.pulse.scale.setScalar(s1)
          ;(info.pulse.material as THREE.MeshBasicMaterial).opacity =
            0.62 + Math.sin(elapsed * 5 + idx) * 0.22

          if (info.pulse2) {
            const t2 = (t1 + 0.5) % 1
            const ct2 = 0.06 + t2 * 0.88
            info.pulse2.position.copy(info.curve.getPoint(ct2))
            info.pulse2.visible = t2 < 0.985
            info.pulse2.scale.setScalar(0.9 + Math.sin(elapsed * 5.5 + idx) * 0.15)
            ;(info.pulse2.material as THREE.MeshBasicMaterial).opacity =
              0.52 + Math.sin(elapsed * 4.5 + idx * 0.9) * 0.20
          }
        } else {
          info.pulse.visible = false
          if (info.pulse2) info.pulse2.visible = false
        }
      })

      // Satellite orbit
      const satAngle = elapsed * 0.38
      sat.position.set(Math.cos(satAngle) * orbitRadius, 0, Math.sin(satAngle) * orbitRadius)
      sat.rotation.y = -satAngle
      sat.rotation.z = Math.sin(satAngle * 2) * 0.08
      // beacon blink
      beaconMat.opacity = 0.35 + (Math.sin(elapsed * 7.2) > 0 ? 0.6 : 0)
      beacon.scale.setScalar(1 + (beaconMat.opacity > 0.7 ? 0.35 : 0))
      orbitLine.material.opacity = 0.18 + Math.sin(elapsed * 0.8) * 0.05

      renderer.render(scene, camera)
      frame = requestAnimationFrame(animate)
    }
    animate()

    // Resize
    const resizeObserver = new ResizeObserver(() => {
      const w = host.clientWidth
      const h = host.clientHeight
      if (w === 0 || h === 0) return
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    })
    resizeObserver.observe(host)

    // Cleanup
    return () => {
      cancelAnimationFrame(frame)
      resizeObserver.disconnect()
      renderer.domElement.removeEventListener('pointerdown', onPointerDown)
      renderer.domElement.removeEventListener('pointermove', onPointerMove)
      renderer.domElement.removeEventListener('pointerup', onPointerUp)
      renderer.domElement.removeEventListener('pointercancel', onPointerUp)
      renderer.domElement.removeEventListener('wheel', onWheel)
      if (renderer.domElement.parentElement === host) host.removeChild(renderer.domElement)

      // Dispose everything
      const toDisposeTex = [haloTex, sunGlowTex, flareRingTex, beamTex, fallbackDay, fallbackNight]
      // nebula textures are owned by sprite mats → disposed via traverse (mat.map)
      scene.traverse((obj) => {
        const anyObj = obj as unknown as {
          geometry?: THREE.BufferGeometry
          material?: THREE.Material | THREE.Material[]
        }
        if (
          obj instanceof THREE.Mesh ||
          obj instanceof THREE.Points ||
          obj instanceof THREE.Line ||
          obj instanceof THREE.Sprite
        ) {
          if (anyObj.geometry) anyObj.geometry.dispose()
          const mats = Array.isArray(anyObj.material) ? anyObj.material : anyObj.material ? [anyObj.material] : []
          for (const m of mats) {
            const mm = m as unknown as { map?: THREE.Texture; alphaMap?: THREE.Texture }
            // sprite/beam maps are canvas textures — disposing here covers them
            // (halo/sun/nebula maps are also sprite maps, but we also keep refs)
            if (mm.map && !toDisposeTex.includes(mm.map as THREE.CanvasTexture)) {
              // will be disposed via mat.dispose path if not in keep-list? keep uniform textures separate
            }
            m.dispose()
          }
        }
      })
      // Uniform textures (not owned by a disposed mat.map in traverse if shader mat was disposed without map)
      dayTexture.dispose()
      nightTexture.dispose()
      specTexture.dispose()
      cloudsTexture.dispose()
      for (const t of toDisposeTex) t.dispose()
      // nebula sprite maps were disposed via traverse's mat.dispose loop's map — but traverse disposes mat before map;
      // ensure maps are disposed (traverse above disposes mats, not maps). Do it explicitly for sprites we created:
      for (const s of nebulaSprites) (s.material as THREE.SpriteMaterial).map?.dispose()
      for (const s of [halo, sunGlow, flareRing]) (s.material as THREE.SpriteMaterial).map?.dispose()
      // arc/satellite/dust geometries already disposed via traverse

      renderer.dispose()
    }
  }, [])

  return (
    <div className="absolute inset-0 -z-10 overflow-hidden bg-[#020617]" aria-hidden="true">
      <div ref={hostRef} className="h-full w-full" />
      {/* Cinematic contrast — keeps the form readable without hiding the globe */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_88%_72%_at_52%_44%,rgba(2,6,23,0.08),rgba(2,6,23,0.55)_58%,rgba(2,6,23,0.92)_78%,rgba(2,6,23,0.98))]" />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-slate-950/90 via-slate-950/10 to-slate-950/45" />
      {/* Subtle vignette + top light spill from the sun */}
      <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_140px_rgba(0,0,0,0.82)]" />
      <div className="pointer-events-none absolute -right-10 -top-10 h-[42%] w-[58%] bg-[radial-gradient(ellipse_at_center,rgba(125,211,252,0.10),transparent_68%)] blur-[1px]" />
    </div>
  )
}
