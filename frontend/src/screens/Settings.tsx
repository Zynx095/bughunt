import { useEffect, useState } from 'react'

import { get, loadIdentity, saveIdentity, setApiIdentity } from '../lib/api'
import { cx } from '../lib/cx'
import { useTheme, type ThemePreference } from '../lib/theme'
import type { Role } from '../lib/types'
import { live } from '../live/client'
import { Button, Field, KV, Note, Section, inputCls } from '../ui/primitives'

interface Health { status: string; engines: Record<string, { status: string; warning?: string; active_provider?: string }> }

export function Settings() {
  const { preference, setPreference, resolved } = useTheme()
  const [idn, setIdn] = useState(loadIdentity)
  const [saved, setSaved] = useState(false)
  const [detector, setDetector] = useState<Record<string, unknown> | null>(null)
  const [device, setDevice] = useState<string>('')
  const [health, setHealth] = useState<Health | null>(null)

  useEffect(() => {
    const id = window.setTimeout(() => {
      live.status().then((s) => { setDetector(s.detector); setDevice(s.device) }).catch(() => undefined)
      get<Health>('/api/health').then(setHealth).catch(() => undefined)
    }, 0)
    return () => window.clearTimeout(id)
  }, [])

  const themes: { id: ThemePreference; label: string }[] = [{ id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }, { id: 'system', label: 'Match system' }]
  const ai = health?.engines.ai
  return (
    <div className="mx-auto h-full max-w-3xl overflow-y-auto">
      <Section title="Appearance">
        <div className="flex gap-2" role="radiogroup" aria-label="Theme">
          {themes.map((t) => (
            <button key={t.id} type="button" role="radio" aria-checked={preference === t.id} onClick={() => setPreference(t.id)}
              className={cx('h-9 rounded-[5px] border px-4 text-[13px]', preference === t.id ? 'border-accent bg-raised font-medium text-ink' : 'border-line text-ink-2 hover:text-ink')}>
              {t.label}
            </button>
          ))}
        </div>
        <Note>Showing the {resolved} theme. Your choice is kept in this browser.</Note>
      </Section>

      <Section title="Operator">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name shown in incident records"><input className={inputCls} value={idn.actor} onChange={(e) => setIdn({ ...idn, actor: e.target.value })} /></Field>
          <Field label="Role">
            <select className={inputCls} value={idn.role} onChange={(e) => setIdn({ ...idn, role: e.target.value as Role })}>
              <option value="viewer">Viewer (watch only)</option><option value="analyst">Operator</option><option value="reviewer">Safety officer</option><option value="admin">Administrator</option>
            </select>
          </Field>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button variant="primary" onClick={() => { setApiIdentity(idn); saveIdentity(idn); setSaved(true) }}>Save operator</Button>
          {saved && <span className="text-[13px] text-ink-2">Saved. New actions are recorded under this name.</span>}
        </div>
        <Note>This prototype has no sign-in: the name and role are declared by this browser and enforced by the server's permission rules.</Note>
      </Section>

      <Section title="Detection">
        {detector ? (
          <KV rows={[
            ['Person detector', detector.backend === 'yolo' ? 'YOLO (local weights)' : detector.backend === 'hog' ? 'OpenCV HOG (fallback, weaker)' : 'unavailable'],
            ['Model file', String(detector.weights_path ?? detector.model ?? '—')],
            ['Checked at start-up', detector.verified ? 'yes, a test inference ran' : 'no'],
            ['Runs on', device === 'cuda' ? 'GPU (CUDA)' : 'CPU'],
            ['Tracking', 'ByteTrack identities, ground-plane Kalman filter'],
          ]} />
        ) : <Note>Checking the detector…</Note>}
        <Note>Weights are loaded from disk only; nothing is downloaded while the system runs.</Note>
      </Section>

      <Section title="Reading the numbers">
        <ul className="list-disc space-y-1.5 pl-4 text-[13px] text-ink-2">
          <li>Counts and densities are estimates from a camera, not ground truth. People hidden behind others are missed.</li>
          <li>Densities are in people per m² only after a measured calibration; otherwise they are a relative index where 1 means congested.</li>
          <li>Grey hatched floor is not observed: a missing or failed feed is never treated as empty.</li>
          <li>Recordings and the simulation are always labelled as such and never shown as live.</li>
          <li>Routes and alerts are advice. Organisers decide; nothing here can close an emergency exit.</li>
        </ul>
      </Section>

      <Section title="System">
        <KV rows={[
          ['Server', health ? health.status : '—'],
          ['Analysis engines', health ? `${Object.keys(health.engines).length} running` : '—'],
          ['Briefing text', ai?.active_provider === 'local-fallback' ? 'built-in templates (no AI service configured)' : ai?.active_provider ?? '—'],
        ]} />
        <p className="mt-2 text-[12.5px] text-muted">Built on the OMNIFORGE engine framework. Developers can inspect every endpoint at <a className="text-accent hover:underline" href="/docs" target="_blank" rel="noreferrer">/docs</a>.</p>
      </Section>
    </div>
  )
}
