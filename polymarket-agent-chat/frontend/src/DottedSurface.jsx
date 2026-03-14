import { useEffect, useRef } from 'react'
import * as THREE from 'three'

export default function DottedSurface({ visible = true }) {
  const containerRef = useRef(null)
  const sceneRef = useRef(null)
  const wrapperRef = useRef(null)

  // Handle visibility transitions
  useEffect(() => {
    const el = wrapperRef.current
    if (!el) return
    if (visible) {
      // Animate in from bottom
      el.style.transition = 'none'
      el.style.transform = 'translateY(30%)'
      el.style.opacity = '0'
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          el.style.transition = 'transform 1.8s cubic-bezier(0.22, 1, 0.36, 1), opacity 1.5s ease'
          el.style.transform = 'translateY(0)'
          el.style.opacity = '1'
        })
      })
    } else {
      // Animate out downward
      el.style.transition = 'transform 1.2s cubic-bezier(0.55, 0, 1, 0.45), opacity 0.8s ease'
      el.style.transform = 'translateY(40%)'
      el.style.opacity = '0'
    }
  }, [visible])

  useEffect(() => {
    if (!containerRef.current) return

    const SEPARATION = 140
    const AMOUNTX = 45
    const AMOUNTY = 55

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 1, 10000)
    camera.position.set(0, 380, 1300)

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(window.innerWidth, window.innerHeight)
    renderer.setClearColor(0x000000, 0)

    containerRef.current.appendChild(renderer.domElement)

    // Particle geometry
    const positions = []
    const colors = []
    for (let ix = 0; ix < AMOUNTX; ix++) {
      for (let iy = 0; iy < AMOUNTY; iy++) {
        const x = ix * SEPARATION - (AMOUNTX * SEPARATION) / 2
        const z = iy * SEPARATION - (AMOUNTY * SEPARATION) / 2
        positions.push(x, 0, z)
        // Subtle blue-tinted dots matching our accent
        colors.push(0.18, 0.36, 1.0) // accent-blue tint
      }
    }

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))

    const material = new THREE.PointsMaterial({
      size: 6,
      vertexColors: true,
      transparent: true,
      opacity: 0.35,
      sizeAttenuation: true,
    })

    const points = new THREE.Points(geometry, material)
    scene.add(points)

    let count = 0
    let animationId

    const animate = () => {
      animationId = requestAnimationFrame(animate)
      const posArr = geometry.attributes.position.array

      let i = 0
      for (let ix = 0; ix < AMOUNTX; ix++) {
        for (let iy = 0; iy < AMOUNTY; iy++) {
          // Slower, gentler wave
          posArr[i * 3 + 1] =
            Math.sin((ix + count) * 0.25) * 35 +
            Math.sin((iy + count) * 0.4) * 35
          i++
        }
      }
      geometry.attributes.position.needsUpdate = true
      renderer.render(scene, camera)
      count += 0.035 // Much slower
    }

    const handleResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight
      camera.updateProjectionMatrix()
      renderer.setSize(window.innerWidth, window.innerHeight)
    }
    window.addEventListener('resize', handleResize)
    animate()

    sceneRef.current = { scene, renderer, animationId }

    return () => {
      window.removeEventListener('resize', handleResize)
      cancelAnimationFrame(animationId)
      scene.traverse(obj => {
        if (obj instanceof THREE.Points) {
          obj.geometry.dispose()
          if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())
          else obj.material.dispose()
        }
      })
      renderer.dispose()
      if (containerRef.current && renderer.domElement.parentNode === containerRef.current) {
        containerRef.current.removeChild(renderer.domElement)
      }
    }
  }, [])

  return (
    <div
      ref={wrapperRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        opacity: 0,
        transform: 'translateY(30%)',
      }}
    >
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}
