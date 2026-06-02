import React from 'react'
import { Link } from 'react-router-dom'

export default function Landing() {
  return (
    <div className="page page-v2">
      <section className="hero-v2">
        <div className="hero-copy-v2">
          <p className="tagline-v2">Redecorate your room before buying a single thing</p>
          <h1>Redesign your room before buying a single thing.</h1>
          <p>
            Upload a room photo, segment walls, floor, and furniture in the browser, then test wall colors,
            furniture styles, and full-room redesigns side-by-side.
          </p>
          <div className="hero-cta-v2">
            <Link to="/dashboard" className="btn-v2 primary">Start Designing</Link>
            <Link to="/results" className="btn-v2">View Results</Link>
            <Link to="/legacy" className="btn-v2">Open Legacy Page</Link>
          </div>
        </div>
        <div className="hero-visual-v2">
          <svg width="420" height="300" viewBox="0 0 420 300" fill="none" xmlns="http://www.w3.org/2000/svg" className="hero-svg">
            <rect x="0" y="0" width="420" height="300" rx="12" fill="url(#g)" />
            <defs>
              <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#e6f7ff" />
                <stop offset="1" stopColor="#f0f9f4" />
              </linearGradient>
            </defs>
            <g transform="translate(28,22)">
              <rect x="0" y="60" width="280" height="160" rx="8" fill="#fff" opacity="0.8" />
              <rect x="16" y="40" width="120" height="60" rx="8" fill="#0f62fe" opacity="0.95" />
              <rect x="172" y="64" width="80" height="40" rx="6" fill="#00b894" opacity="0.95" />
            </g>
          </svg>
        </div>
      </section>

      <section className="feature-grid-v2">
        <article className="feature-card-v2">
          <h3>Semantic Segmentation</h3>
          <p>Use DeepLab or SAM-style masks to isolate walls, floors, and furniture for precise edits.</p>
        </article>
        <article className="feature-card-v2">
          <h3>AI Palette Engine</h3>
          <p>Recommend palette combinations that match the room and make color choices easier.</p>
        </article>
        <article className="feature-card-v2">
          <h3>Furniture Swap UX</h3>
          <p>Furniture replacement is a roadmap item. The current build focuses on room upload, segmentation, and color exploration.</p>
        </article>
        <article className="feature-card-v2">
          <h3>Save & Share</h3>
          <p>Keep your redesign state, export previews, and share the final concept with others.</p>
        </article>
      </section>

      <section className="journey-v2">
        <h2>How it works</h2>
        <div className="steps-v2">
          <div><strong>1</strong><span>Upload a room photo</span></div>
          <div><strong>2</strong><span>Segment walls, floor, and furniture</span></div>
          <div><strong>3</strong><span>Swap furniture and tune colors</span></div>
          <div><strong>4</strong><span>Save and share the redesign</span></div>
        </div>
      </section>
    </div>
  )
}
