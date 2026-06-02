import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:5000'

const STYLE_THEME_MAP = {
    modern: 'modern_luxe',
    wood: 'scandinavian',
    minimal: 'japandi',
    velvet: 'industrial',
}

export default function LegacyDesign({ beforeImage, setBeforeImage }) {
    const [file, setFile] = useState(null)
    const [imageUrl, setImageUrl] = useState('')
    const [masks, setMasks] = useState([])
    const [selectedMasks, setSelectedMasks] = useState([])
    const [wallColor, setWallColor] = useState('#D6CCC2')
    const [style, setStyle] = useState('modern')
    const [palettes, setPalettes] = useState(null)
    const [status, setStatus] = useState('Upload a room image to start.')
    const [shareUrl, setShareUrl] = useState('')
    const [afterImage, setAfterImage] = useState('')
    const fabricCanvas = useRef(null)
    const fabricLibRef = useRef(null)

    useEffect(() => {
        let canvas = null
        let mounted = true

        async function initCanvas() {
            if (!fabricLibRef.current) {
                const mod = await import('fabric')
                fabricLibRef.current = mod.fabric || mod.default || mod
            }
            const fabric = fabricLibRef.current
            if (!mounted || !fabric) return

            canvas = new fabric.Canvas('designCanvas', {
                width: 620,
                height: 430,
                backgroundColor: '#eeeeee',
                preserveObjectStacking: true,
            })
            fabricCanvas.current = canvas

            function dropHandler(ev) {
                ev.preventDefault()
                const kind = ev.dataTransfer.getData('kind')
                const rect = canvas.upperCanvasEl.getBoundingClientRect()
                const x = ev.clientX - rect.left
                const y = ev.clientY - rect.top
                addFurniture(kind, x, y)
            }

            function dragOverHandler(ev) {
                ev.preventDefault()
            }

            canvas.upperCanvasEl.addEventListener('dragover', dragOverHandler)
            canvas.upperCanvasEl.addEventListener('drop', dropHandler)

            return () => {
                mounted = false
                if (canvas) {
                    canvas.upperCanvasEl.removeEventListener('dragover', dragOverHandler)
                    canvas.upperCanvasEl.removeEventListener('drop', dropHandler)
                    canvas.dispose()
                }
            }
        }

        const cleanupPromise = initCanvas()

        return () => {
            mounted = false
            cleanupPromise.then((cleanup) => {
                if (typeof cleanup === 'function') {
                    cleanup()
                }
            }).catch(() => { })
        }
    }, [])

    function getCanvas() {
        return fabricCanvas.current
    }

    function updateAfterImage() {
        const canvas = getCanvas()
        if (!canvas) return
        try {
            setAfterImage(canvas.toDataURL({ format: 'png', quality: 0.8 }))
        } catch (err) {
            console.warn('After image update failed:', err)
        }
    }

    async function setCanvasBackground(url) {
        const canvas = getCanvas()
        if (!canvas) {
            setStatus('Canvas is not ready.')
            return
        }

        const oldFurniture = canvas.getObjects().filter((obj) => obj.customType === 'furniture')
        canvas.clear()
        canvas.backgroundColor = '#eeeeee'

        if (!url) {
            canvas.renderAll()
            updateAfterImage()
            return
        }

        const fullUrl = url.startsWith('http') || url.startsWith('data:') || url.startsWith('blob:')
            ? url
            : `${API_BASE}${url}`
        const fabric = fabricLibRef.current
        if (!fabric) {
            setStatus('Fabric loading failed. Please refresh.')
            return
        }

        console.log('Loading image from:', fullUrl)
        try {
            // Fabric.js v7 uses promise-based API
            const img = await fabric.Image.fromURL(fullUrl, {
                crossOrigin: 'anonymous',
            })
            console.log('Image loaded successfully:', img.width, 'x', img.height)

            // Scale image to fit canvas while maintaining aspect ratio
            const maxWidth = canvas.width
            const maxHeight = canvas.height
            let scale = 1

            if (img.width > maxWidth || img.height > maxHeight) {
                const scaleX = maxWidth / img.width
                const scaleY = maxHeight / img.height
                scale = Math.min(scaleX, scaleY)
            }

            img.set({
                left: canvas.width / 2,
                top: canvas.height / 2,
                scaleX: scale,
                scaleY: scale,
                originX: 'center',
                originY: 'center',
                selectable: false,
                evented: false,
                customType: 'background',
            })
            canvas.add(img)
            canvas.sendToBack(img)
            oldFurniture.forEach((obj) => canvas.add(obj))
            canvas.renderAll()
            updateAfterImage()
            setStatus('Editable canvas image loaded. Now add or reposition furniture.')
        } catch (e) {
            console.error('Image loading failed:', e)
            setStatus(`Image loading failed: ${e.message}`)
        }
    }

    async function uploadImage() {
        if (!file) {
            setStatus('Please select an image first.')
            return
        }

        setStatus('Uploading image and segmenting room...')
        const formData = new FormData()
        formData.append('image', file)

        try {
            const res = await fetch(`${API_BASE}/api/segment`, {
                method: 'POST',
                body: formData,
            })
            const data = await res.json()
            if (!res.ok) {
                setStatus(data.error || 'Upload failed.')
                return
            }

            const url = data.imageSource?.url || data.image_url || ''
            const absUrl = url.startsWith('http') ? url : `${API_BASE}${url}`
            setImageUrl(absUrl)
            setSelectedMasks([])
            setMasks(data.masks || [])
            setShareUrl('')
            setBeforeImage && setBeforeImage(absUrl)
            await setCanvasBackground(absUrl)
            loadPalettes(url)
            setStatus('Image segmented. Select a region to recolor or apply style.')
        } catch (err) {
            console.error(err)
            setStatus('Upload or segmentation request failed.')
        }
    }

    async function loadPalettes(imageUrlValue) {
        if (!imageUrlValue) return
        const payload = imageUrlValue.startsWith('data:image')
            ? { imageData: imageUrlValue }
            : { imageUrl: imageUrlValue }
        try {
            const res = await fetch(`${API_BASE}/api/palette`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            const data = await res.json()
            if (res.ok) {
                setPalettes(data)
            }
        } catch (err) {
            console.warn(err)
        }
    }

    async function segmentSharedImage(sharedSource) {
        if (!sharedSource) return
        setStatus('Segmenting shared image...')
        try {
            const payload = sharedSource.startsWith('data:image')
                ? { imageData: sharedSource }
                : { imageUrl: sharedSource }
            const res = await fetch(`${API_BASE}/api/segment`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            })
            const data = await res.json()
            if (!res.ok) {
                setStatus(data.error || 'Segmentation failed.')
                return
            }
            const url = data.imageSource?.url || data.image_url || ''
            const absUrl = url.startsWith('http') ? url : `${API_BASE}${url}`
            setImageUrl(absUrl)
            setMasks(data.masks || [])
            setSelectedMasks([])
            setShareUrl('')
            await setCanvasBackground(absUrl)
            loadPalettes(url)
            setStatus('Shared image segmented. Select a region to recolor or apply style.')
        } catch (err) {
            console.error(err)
            setStatus('Shared image segmentation failed.')
        }
    }

    useEffect(() => {
        if (!beforeImage || imageUrl) return
        segmentSharedImage(beforeImage)
    }, [beforeImage, imageUrl])

    function normalizeMaskType(mask) {
        if (!mask) return null
        const rawType = String(mask.type || '').toLowerCase().trim()
        if (!rawType) return null
        if (rawType === 'object/furniture') {
            const name = String(mask.name || '').toLowerCase().trim()
            if (['sofa', 'table', 'lamp', 'furniture'].includes(name)) return name
            return 'furniture'
        }
        if (rawType.startsWith('object/')) return rawType.split('/')[1]
        return rawType
    }

    function toggleMask(maskId) {
        if (selectedMasks.includes(maskId)) {
            setSelectedMasks(selectedMasks.filter((id) => id !== maskId))
        } else {
            setSelectedMasks([...selectedMasks, maskId])
        }
    }

    function selectOnly(mask) {
        const regionType = normalizeMaskType(mask)
        if (!regionType) return
        setSelectedMasks(masks.filter((item) => normalizeMaskType(item) === regionType).map((item) => item.id))
    }

    function chosenRegion() {
        const selected = masks.filter((mask) => selectedMasks.includes(mask.id))
        if (selected.length === 0) return null
        const types = [...new Set(selected.map(normalizeMaskType).filter(Boolean))]
        if (types.includes('wall')) return 'wall'
        if (types.includes('floor')) return 'floor'
        return types[0] || null
    }

    async function applyWallColor() {
        const region = chosenRegion()
        if (!imageUrl || !region) {
            setStatus('Select a wall or floor region first.')
            return
        }

        setStatus('Applying color...')
        try {
            const res = await fetch(`${API_BASE}/api/recolor`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ imageUrl, region, targetColor: wallColor }),
            })
            const data = await res.json()
            if (!res.ok) {
                setStatus(data.error || 'Color apply failed.')
                return
            }
            setCanvasBackground(data.previewUrl || imageUrl)
            setStatus('Color applied. Canvas updated.')
        } catch (err) {
            console.error(err)
            setStatus('Color request failed.')
        }
    }

    async function applyStyle() {
        if (!imageUrl) {
            setStatus('Upload an image first.')
            return
        }

        setStatus('Applying style theme...')
        const styleTheme = STYLE_THEME_MAP[style] || style

        try {
            const res = await fetch(`${API_BASE}/api/redesign`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ imageUrl, styleTheme, wallColor, roomType: 'Living Room' }),
            })
            const data = await res.json()
            if (!res.ok) {
                setStatus(data.error || 'Style apply failed.')
                return
            }
            setCanvasBackground(data.previewUrl || imageUrl)
            setStatus('Style applied. Canvas updated.')
        } catch (err) {
            console.error(err)
            setStatus('Style request failed.')
        }
    }

    function addFurniture(kind, x, y) {
        const canvas = getCanvas()
        const fabric = fabricLibRef.current
        if (!canvas || !fabric) return
        if (x == null) x = 250
        if (y == null) y = 200

        let object = null
        if (kind === 'sofa') {
            const rect = new fabric.Rect({ width: 140, height: 60, rx: 16, ry: 16, fill: '#8B7355', originX: 'center', originY: 'center' })
            const text = new fabric.Text('Sofa', { fontSize: 18, fill: 'white', originX: 'center', originY: 'center' })
            object = new fabric.Group([rect, text], { left: x, top: y })
        }
        if (kind === 'table') {
            const circle = new fabric.Circle({ radius: 42, fill: '#A47148', originX: 'center', originY: 'center' })
            const text = new fabric.Text('Table', { fontSize: 15, fill: 'white', originX: 'center', originY: 'center' })
            object = new fabric.Group([circle, text], { left: x, top: y })
        }
        if (kind === 'lamp') {
            const triangle = new fabric.Triangle({ width: 70, height: 90, fill: '#DDB892', originX: 'center', originY: 'center' })
            const text = new fabric.Text('Lamp', { fontSize: 14, fill: '#222', originX: 'center', originY: 'center' })
            object = new fabric.Group([triangle, text], { left: x, top: y })
        }
        if (kind === 'plant') {
            const leaf = new fabric.Circle({ radius: 35, fill: '#6B8E23', originX: 'center', originY: 'center', top: -18 })
            const pot = new fabric.Rect({ width: 55, height: 35, fill: '#A47148', originX: 'center', originY: 'center', top: 35 })
            const text = new fabric.Text('Plant', { fontSize: 12, fill: 'white', originX: 'center', originY: 'center', top: -18 })
            object = new fabric.Group([leaf, pot, text], { left: x, top: y })
        }
        if (kind === 'rug') {
            const rug = new fabric.Rect({ width: 160, height: 75, rx: 25, ry: 25, fill: '#C9A66B', originX: 'center', originY: 'center' })
            const text = new fabric.Text('Rug', { fontSize: 16, fill: '#222', originX: 'center', originY: 'center' })
            object = new fabric.Group([rug, text], { left: x, top: y })
        }
        if (object) {
            object.set({ customType: 'furniture', cornerStyle: 'circle', transparentCorners: false })
            canvas.add(object)
            canvas.setActiveObject(object)
            canvas.renderAll()
            updateAfterImage()
            setStatus(`${kind} added. You can move or resize it.`)
        }
    }

    function deleteSelectedObject() {
        const canvas = getCanvas()
        const active = canvas?.getActiveObject()
        if (active && active.customType === 'furniture') {
            canvas.remove(active)
            canvas.renderAll()
            updateAfterImage()
            setStatus('Selected furniture deleted.')
        } else {
            setStatus('Please select a furniture item first.')
        }
    }

    function clearFurniture() {
        const canvas = getCanvas()
        canvas.getObjects().forEach((obj) => {
            if (obj.customType === 'furniture') {
                canvas.remove(obj)
            }
        })
        canvas.renderAll()
        updateAfterImage()
        setStatus('Furniture items cleared.')
    }

    async function saveDesign() {
        const canvas = getCanvas()
        const dataUrl = canvas.toDataURL({ format: 'png', quality: 1 })

        try {
            const res = await fetch(`${API_BASE}/api/designs/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ data_url: dataUrl }),
            })
            const data = await res.json()
            if (!res.ok) {
                setStatus(data.error || 'Save failed.')
                return
            }
            const path = data.shareUrl || data.share_url || ''
            setShareUrl(path.startsWith('http') ? path : `${API_BASE}${path}`)
            setStatus('Design saved successfully.')
        } catch (err) {
            console.error(err)
            setStatus('Save request failed.')
        }
    }

    return (
        <div className="page page-v2">
            <section className="section-card-v2">
                <div className="section-head-v2">
                    <div>
                        <h2>Legacy Design Editor</h2>
                        <p>Upload a room photo, view region masks, recolor walls or floors, and add furniture in the canvas.</p>
                    </div>
                    <Link to="/dashboard" className="btn-v2">Back to Dashboard</Link>
                </div>

                <div className="canvas-wrap" style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '18px', marginTop: '18px' }}>
                    <div style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '18px' }}>
                        <div className="panel">
                            <h3>Before</h3>
                            {(beforeImage || imageUrl) ? (
                                <img src={beforeImage || imageUrl} alt="Before" style={{ width: '100%', borderRadius: '12px' }} />
                            ) : (
                                <div className="img-empty-v2" style={{ minHeight: '260px' }}>Upload a room photo to preview the before image.</div>
                            )}
                        </div>
                        <div className="panel">
                            <h3>After</h3>
                            {afterImage ? (
                                <img src={afterImage} alt="After" style={{ width: '100%', borderRadius: '12px' }} />
                            ) : (
                                <div className="img-empty-v2" style={{ minHeight: '260px' }}>Canvas updates will appear here.</div>
                            )}
                        </div>
                    </div>
                    <div className="panel" style={{ minHeight: '700px' }}>
                        <h3>Controls</h3>
                        <label>Upload Room Image</label>
                        <input type="file" accept="image/*" onChange={(ev) => setFile(ev.target.files?.[0] ?? null)} />
                        <button className="btn-v2 primary" style={{ width: '100%', marginTop: '8px' }} onClick={uploadImage}>Upload + Segment</button>
                        <p className="palette-hint-v2">Use a room photo with visible walls and floor for best results.</p>

                        <h3 style={{ marginTop: '18px' }}>Select Regions</h3>
                        <div style={{ color: '#94a3b8', fontSize: '13px', marginBottom: '8px' }}>Selected region: {chosenRegion() || 'None'}</div>
                        <div style={{ maxHeight: '220px', overflowY: 'auto', border: '1px solid rgba(255,255,255,0.08)', padding: '10px', borderRadius: '10px', background: 'rgba(255,255,255,0.02)' }}>
                            {masks.length === 0 ? (
                                <p style={{ margin: 0, color: '#94a3b8' }}>No masks available yet.</p>
                            ) : masks.map((mask) => (
                                <div key={mask.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                                    <label style={{ fontSize: '13px', color: '#e2e8f0' }}>
                                        <input type="checkbox" checked={selectedMasks.includes(mask.id)} onChange={() => toggleMask(mask.id)} style={{ marginRight: '8px' }} />
                                        {mask.name} · {mask.type}
                                    </label>
                                    <button type="button" style={{ background: '#1f2937', color: '#fff', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px', padding: '6px 9px', fontSize: '12px' }} onClick={() => selectOnly(mask)}>Only</button>
                                </div>
                            ))}
                        </div>

                        <h3 style={{ marginTop: '18px' }}>Wall / Floor Color</h3>
                        <input type="color" value={wallColor} onChange={(ev) => setWallColor(ev.target.value)} style={{ width: '100%', height: '45px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.12)' }} />
                        <button className="btn-v2 primary" style={{ width: '100%', marginTop: '10px' }} onClick={applyWallColor}>Apply Color</button>

                        {palettes && (
                            <div style={{ marginTop: '18px' }}>
                                <h3>AI Suggested Palettes</h3>
                                {palettes.recommendations?.map((paletteItem) => (
                                    <div key={paletteItem.name} style={{ marginBottom: '12px' }}>
                                        <strong style={{ color: '#fff' }}>{paletteItem.name}</strong>
                                        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
                                            {paletteItem.colors?.map((color) => (
                                                <button key={color} type="button" title={color} onClick={() => setWallColor(color)} style={{ width: '32px', height: '32px', borderRadius: '50%', border: '1px solid rgba(255,255,255,0.1)', background: color, cursor: 'pointer' }} />
                                            ))}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        <h3 style={{ marginTop: '18px' }}>Furniture Style</h3>
                        <select value={style} onChange={(ev) => setStyle(ev.target.value)} style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.12)', background: '#0b1220', color: '#fff' }}>
                            <option value="modern">Modern</option>
                            <option value="wood">Wood</option>
                            <option value="minimal">Minimal</option>
                            <option value="velvet">Velvet</option>
                        </select>
                        <button className="btn-v2 primary" style={{ width: '100%', marginTop: '10px' }} onClick={applyStyle}>Apply Style</button>

                        <h3 style={{ marginTop: '18px' }}>Furniture Catalog</h3>
                        <p style={{ color: '#94a3b8', marginTop: 0 }}>Drag items to the canvas or tap to add them.</p>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                            {['sofa', 'table', 'lamp', 'plant', 'rug'].map((item) => (
                                <button
                                    key={item}
                                    type="button"
                                    draggable
                                    onDragStart={(ev) => ev.dataTransfer.setData('kind', item)}
                                    onClick={() => addFurniture(item)}
                                    style={{ background: '#111827', color: '#f8fafc', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', padding: '10px', cursor: 'pointer' }}
                                >
                                    {item.charAt(0).toUpperCase() + item.slice(1)}
                                </button>
                            ))}
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '14px' }}>
                            <button type="button" onClick={deleteSelectedObject} style={{ background: '#1f2937', color: '#fff', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', padding: '10px' }}>Delete Item</button>
                            <button type="button" onClick={clearFurniture} style={{ background: '#1f2937', color: '#fff', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)', padding: '10px' }}>Clear Furniture</button>
                        </div>

                        <button className="btn-v2 primary" style={{ width: '100%', marginTop: '14px' }} onClick={saveDesign}>Save & Share</button>
                        {shareUrl && <a href={shareUrl} target="_blank" rel="noreferrer" style={{ display: 'block', marginTop: '10px', color: '#60a5fa', wordBreak: 'break-all' }}>{shareUrl}</a>}
                        <div style={{ marginTop: '16px', padding: '12px', borderRadius: '12px', background: 'rgba(255,255,255,0.04)', color: '#cbd5e1', fontSize: '13px' }}>{status}</div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr', gap: '18px' }}>
                        <div className="panel" style={{ minHeight: '300px' }}>
                            <h3>Before + Selected Regions</h3>
                            <div style={{ position: 'relative', borderRadius: '12px', overflow: 'hidden', minHeight: '320px', background: '#0f172a', border: '1px solid rgba(255,255,255,0.06)' }}>
                                {imageUrl ? (
                                    <img src={imageUrl} alt="Before" style={{ width: '100%', display: 'block' }} />
                                ) : (
                                    <div style={{ padding: '24px', color: '#94a3b8' }}>Before image will appear here.</div>
                                )}
                                {masks.filter((mask) => selectedMasks.includes(mask.id)).map((mask) => mask.mask_png ? (
                                    <img key={mask.id} src={mask.mask_png} alt={mask.name} style={{ position: 'absolute', top: 0, left: 0, width: '100%', pointerEvents: 'none' }} />
                                ) : null)}
                            </div>
                        </div>

                        <div className="panel" style={{ minHeight: '300px' }}>
                            <h3>After / Editable Canvas</h3>
                            <div style={{ width: '100%', overflow: 'auto', minHeight: '430px', background: '#0f172a', borderRadius: '12px', padding: '10px' }}>
                                <canvas id="designCanvas" width="620" height="430" style={{ width: '100%', minHeight: '430px' }} />
                            </div>
                            <p style={{ marginTop: '10px', color: '#94a3b8' }}>Drag catalog items into the canvas or use Add buttons.</p>
                        </div>
                    </div>
                </div>
            </section>
        </div>
    )
}
