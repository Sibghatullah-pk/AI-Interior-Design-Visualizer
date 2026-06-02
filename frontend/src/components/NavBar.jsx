import React, { useState } from 'react'
import { Link } from 'react-router-dom'

export default function NavBar() {
  const [open, setOpen] = useState(false)

  return (
    <nav className="navbar appbar-v2">
      <div className="nav-left">
        <Link to="/" className="brand">AI Interior Design Visualizer</Link>
      </div>
      <button className="nav-toggle" onClick={() => setOpen(o => !o)} aria-label="Toggle navigation">{open ? '✕' : '☰'}</button>
      <div className={`nav-right nav-links-v2 ${open ? 'open' : ''}`}>
        <Link to="/" onClick={() => setOpen(false)}>Landing</Link>
        <Link to="/dashboard" onClick={() => setOpen(false)}>Dashboard</Link>
        <Link to="/results" onClick={() => setOpen(false)}>Results</Link>
        <Link to="/legacy" onClick={() => setOpen(false)}>Legacy</Link>
        <Link to="/analytics" onClick={() => setOpen(false)}>Analytics</Link>
        <Link to="/about" onClick={() => setOpen(false)}>About</Link>
      </div>
    </nav>
  )
}

