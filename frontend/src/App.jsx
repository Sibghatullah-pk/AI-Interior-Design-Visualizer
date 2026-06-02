import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { io } from 'socket.io-client'
import NavBar from './components/NavBar'
import Landing from './pages/Landing'
import Dashboard from './pages/Dashboard'
import Results from './pages/Results'
import About from './pages/About'
import Analytics from './pages/Analytics'
import LegacyDesign from './pages/LegacyDesign'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'

function makeClientId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `client-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

export default function App() {
  const [clientId] = useState(makeClientId)
  const [socket, setSocket] = useState(null)
  const [uiConfig, setUiConfig] = useState(null)
  const [beforeImage, setBeforeImage] = useState(null)
  const [palette, setPalette] = useState([])
  const [targetColor, setTargetColor] = useState('')
  const [designOptions, setDesignOptions] = useState({
    designTheme: '',
    roomType: '',
    generatedAt: null
  })

  useEffect(() => {
    let alive = true
    async function loadConfig() {
      try {
        const res = await fetch(`${API_BASE}/api/ui-config`)
        if (!res.ok) return
        const data = await res.json()
        if (!alive) return
        setUiConfig(data)
        setTargetColor((prev) => prev || data.defaultTargetColor || '')
        setDesignOptions((prev) => ({
          ...prev,
          designTheme: prev.designTheme || data.defaultTheme || '',
          roomType: prev.roomType || data.roomTypes?.[0] || ''
        }))
      } catch (err) {
        console.warn(err)
      }
    }
    loadConfig()
    return () => { alive = false }
  }, [])

  useEffect(() => {
    const s = io(API_BASE, { transports: ['websocket', 'polling'] })
    s.on('connect', () => {
      s.emit('join', { clientId })
    })
    setSocket(s)
    return () => {
      s.disconnect()
    }
  }, [clientId])

  useEffect(() => {
    if (!uiConfig) return
    setDesignOptions((prev) => ({
      ...prev,
      designTheme: prev.designTheme || uiConfig.defaultTheme || '',
      roomType: prev.roomType || uiConfig.roomTypes?.[0] || ''
    }))
    setTargetColor((prev) => prev || uiConfig.defaultTargetColor || '')
  }, [uiConfig])

  return (
    <BrowserRouter>
      <div className="app">
        <NavBar />
        <main className="page-container">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/dashboard" element={<Dashboard uiConfig={uiConfig} beforeImage={beforeImage} setBeforeImage={setBeforeImage} palette={palette} setPalette={setPalette} targetColor={targetColor} setTargetColor={setTargetColor} designOptions={designOptions} setDesignOptions={setDesignOptions} />} />
            <Route path="/results" element={<Results uiConfig={uiConfig} socket={socket} clientId={clientId} beforeImage={beforeImage} palette={palette} targetColor={targetColor} setTargetColor={setTargetColor} designOptions={designOptions} />} />
            <Route path="/legacy" element={<LegacyDesign />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
