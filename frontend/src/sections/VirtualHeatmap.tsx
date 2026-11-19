import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertOctagon,
  AlertTriangle,
  ArrowRight,
  Camera,
  CheckCircle2,
  ChevronRight,
  Columns2,
  Compass,
  Cpu,
  Download,
  Eye,
  Flame,
  Grid,
  Info,
  Layers,
  MapPin,
  Maximize2,
  MoveRight,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  Sliders,
  StepForward,
  Tv,
  Upload,
  Users,
  Video,
  Zap,
} from 'lucide-react'

import { Badge, Button, Card, ErrorBox, Spinner, Stat, StatusBadge } from '../components/ui'
import { get, send } from '../lib/api'
import { cx } from '../lib/cx'

type ViewTab = 'camera' | 'birdseye' | 'heatmap' | 'movement' | 'digitaltwin'

interface CalibrationPoint {
  x: number
  y: number
}

interface CalibrationQuad {
  top_left: CalibrationPoint
  top_right: CalibrationPoint
  bottom_right: CalibrationPoint
  bottom_left: CalibrationPoint
}

interface ZoneMetric {
  zone_id: string
  zone_name: string
  population: number
  capacity: number
  occupancy_pct: number
  area_sq_meters: number
  density_per_sq_meter: number
  avg_speed_mps: number
  risk_level: 'low' | 'moderate' | 'high' | 'critical'
  status_message: string
}

interface CongestionAlert {
  id: string
  timestamp_s: number
  alert_type: string
  severity: 'low' | 'moderate' | 'high' | 'critical'
  zone_id?: string
  message: string
  location_birdseye: [number, number]
  metrics: Record<string, unknown>
  recommendation: string
}

interface FrameTelemetry {
  frame_idx: number
  timestamp_s: number
  total_detected: number
  active_tracks_count: number
  peak_density_per_sq_meter: number
  mean_density_per_sq_meter: number
  high_density_area_sq_meters: number
  zone_metrics: ZoneMetric[]
  alerts: CongestionAlert[]
  processing_latency_ms: number
  is_fallback_detection: boolean
  is_synthetic: boolean
}

export function VirtualHeatmapPage() {
  // Navigation & View State
  const [activeTab, setActiveTab] = useState<ViewTab>('heatmap')
  const [sideBySide, setSideBySide] = useState<boolean>(true)
  const [isPlaying, setIsPlaying] = useState<boolean>(true)
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1)

  // Simulation & Pipeline Configuration
  const [scenario, setScenario] = useState<string>('plaza_normal')
  const [heatmapMode, setHeatmapMode] = useState<'gaussian' | 'point' | 'zone' | 'movement'>('gaussian')
  const [bandwidthSigma, setBandwidthSigma] = useState<number>(28)
  const [detectionConfidence, setDetectionConfidence] = useState<number>(0.35)
  const [frameStride, setFrameStride] = useState<number>(2)

  // Ground Plane Calibration State
  const [calibQuad, setCalibQuad] = useState<CalibrationQuad>({
    top_left: { x: 430, y: 280 },
    top_right: { x: 850, y: 280 },
    bottom_right: { x: 1150, y: 680 },
    bottom_left: { x: 130, y: 680 },
  })
  const [groundWidthMeters, setGroundWidthMeters] = useState<number>(24.0)
  const [groundHeightMeters, setGroundHeightMeters] = useState<number>(18.0)
  const [isCalibrating, setIsCalibrating] = useState<boolean>(false)
  const [calibPointStep, setCalibPointStep] = useState<number>(0)
  const [calibrationSaved, setCalibrationSaved] = useState<boolean>(true)

  // Telemetry & Metrics
  const [telemetry, setTelemetry] = useState<FrameTelemetry | null>(null)
  const [loading, setLoading] = useState<boolean>(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [selectedZone, setSelectedZone] = useState<ZoneMetric | null>(null)

  // Video Upload State
  const [uploading, setUploading] = useState<boolean>(false)
  const [uploadedVideoInfo, setUploadedVideoInfo] = useState<{ filename: string; fps: number; frames: number } | null>(null)

  // Image cache-busting timestamp
  const [imgTimestamp, setImgTimestamp] = useState<number>(Date.now())

  // Stepping function
  const stepFrame = useCallback(async () => {
    try {
      const q = new URLSearchParams({
        scenario,
        mode: heatmapMode,
        sigma: bandwidthSigma.toString(),
      })
      const res = await send<FrameTelemetry>('POST', `/api/crowdguard/simulation/step?${q.toString()}`)
      setTelemetry(res)
      setImgTimestamp(Date.now())
      setErrorMessage(null)
    } catch (e) {
      setErrorMessage((e as Error).message)
    }
  }, [scenario, heatmapMode, bandwidthSigma])

  // Playback timer loop
  useEffect(() => {
    if (!isPlaying) return
    const intervalMs = Math.max(80, Math.round(200 / playbackSpeed))
    const timer = setInterval(() => {
      void stepFrame()
    }, intervalMs)
    return () => clearInterval(timer)
  }, [isPlaying, playbackSpeed, stepFrame])

  // Initial load
  useEffect(() => {
    void stepFrame()
  }, [])

  // Calibration save
  const handleApplyCalibration = async () => {
    try {
      setLoading(true)
      await send('POST', '/api/crowdguard/calibration', {
        source_points: calibQuad,
        target_width_px: 800,
        target_height_px: 600,
        ground_width_meters: groundWidthMeters,
        ground_height_meters: groundHeightMeters,
      })
      setCalibrationSaved(true)
      setIsCalibrating(false)
      await stepFrame()
    } catch (e) {
      setErrorMessage((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // Video Upload handler
  const handleVideoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      setUploading(true)
      const resp = await fetch('/api/crowdguard/video/upload', {
        method: 'POST',
        body: formData,
      })
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || 'Upload failed')
      }
      const data = await resp.json()
      setUploadedVideoInfo({
        filename: data.filename,
        fps: data.video_metadata.fps,
        frames: data.video_metadata.frame_count,
      })
      // Start background analysis
      const jobForm = new FormData()
      jobForm.append('video_path', data.saved_path)
      jobForm.append('frame_stride', frameStride.toString())
      jobForm.append('detection_confidence', detectionConfidence.toString())
      jobForm.append('heatmap_mode', heatmapMode)
      await fetch('/api/crowdguard/analysis/start', {
        method: 'POST',
        body: jobForm,
      })
      setIsPlaying(true)
    } catch (err) {
      setErrorMessage((err as Error).message)
    } finally {
      setUploading(false)
    }
  }

  // Reset simulation
  const handleResetSimulation = async () => {
    try {
      setLoading(true)
      await send('POST', `/api/crowdguard/simulation/reset?scenario=${scenario}`)
      await stepFrame()
    } catch (e) {
      setErrorMessage((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // Interactive canvas click for calibration quad
  const handleCanvasClick = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!isCalibrating) return
    const rect = e.currentTarget.getBoundingClientRect()
    // Native dimensions are 1280x720
    const scaleX = 1280.0 / rect.width
    const scaleY = 720.0 / rect.height
    const clickX = Math.round((e.clientX - rect.left) * scaleX)
    const clickY = Math.round((e.clientY - rect.top) * scaleY)

    const pointsOrder = ['top_left', 'top_right', 'bottom_right', 'bottom_left'] as const
    const currentKey = pointsOrder[calibPointStep]

    setCalibQuad((prev) => ({
      ...prev,
      [currentKey]: { x: clickX, y: clickY },
    }))

    if (calibPointStep < 3) {
      setCalibPointStep((p) => p + 1)
    } else {
      setCalibPointStep(0)
      setIsCalibrating(false)
    }
  }

  // Resolves image URL based on current view tab
  const getStreamUrl = (tab: ViewTab) => {
    switch (tab) {
      case 'camera':
        return `/api/crowdguard/analysis/live/frame?t=${imgTimestamp}`
      case 'birdseye':
        return `/api/crowdguard/analysis/live/birdseye?t=${imgTimestamp}`
      case 'heatmap':
        return `/api/crowdguard/analysis/live/heatmap?t=${imgTimestamp}`
      case 'movement':
        return `/api/crowdguard/analysis/live/movement?t=${imgTimestamp}`
      case 'digitaltwin':
        return `/api/crowdguard/analysis/live/digitaltwin?t=${imgTimestamp}`
    }
  }

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex size-2 rounded-full bg-cyan-400 animate-pulse" />
            <span className="text-[10px] font-bold uppercase tracking-widest text-muted">
              Spatial Computer Vision & Crowd Intelligence
            </span>
            <Badge tone="good">VCIE Online</Badge>
            {telemetry?.is_synthetic && <Badge tone="warn">Deterministic Simulation</Badge>}
            {telemetry?.is_fallback_detection && <Badge tone="neutral">Classical CV Fallback</Badge>}
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl mt-1">
            Virtual Bird's-Eye Crowd Intelligence
          </h1>
          <p className="mt-1 text-sm text-ink-2 max-w-3xl">
            Transforms conventional camera perspectives into a top-down metric ground plane with continuous Gaussian KDE density, persistent trajectory tracking, and real-time egress risk alerts.
          </p>
        </div>

        {/* Global Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant={sideBySide ? 'primary' : 'secondary'} onClick={() => setSideBySide(!sideBySide)}>
            <Columns2 className="size-3.5" />
            <span>{sideBySide ? 'Single View' : 'Side-by-Side Comparison'}</span>
          </Button>
          <Button size="sm" variant="secondary" onClick={handleResetSimulation} busy={loading}>
            <RotateCcw className="size-3.5" /> Reset
          </Button>
          <Button
            size="sm"
            variant={isPlaying ? 'secondary' : 'primary'}
            onClick={() => setIsPlaying(!isPlaying)}
          >
            {isPlaying ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
            <span>{isPlaying ? 'Pause' : 'Live Stream'}</span>
          </Button>
          <Button size="sm" variant="ghost" onClick={() => void stepFrame()}>
            <StepForward className="size-3.5" /> Step
          </Button>
        </div>
      </div>

      {errorMessage && <ErrorBox>{errorMessage}</ErrorBox>}

      {/* Main 3-Panel Layout */}
      <div className="grid gap-6 lg:grid-cols-12">
        {/* ======================================================== */}
        {/* LEFT PANEL: Ingestion, Calibration & Configuration (3 cols) */}
        {/* ======================================================== */}
        <div className="space-y-4 lg:col-span-3">
          {/* Feed Ingestion & Scenarios */}
          <Card title="Input Ingestion & Mode" subtitle="Select live feed, upload CCTV footage, or choose synthetic scenarios.">
            <div className="space-y-3 text-xs">
              <div>
                <label className="block font-medium text-ink mb-1">Scenario Demonstration</label>
                <select
                  value={scenario}
                  onChange={(e) => {
                    setScenario(e.target.value)
                    void send('POST', `/api/crowdguard/simulation/reset?scenario=${e.target.value}`)
                  }}
                  className="w-full rounded-lg border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-ink outline-none focus:border-[var(--accent)]"
                >
                  <option value="plaza_normal">Plaza Normal Flow (35 pers)</option>
                  <option value="bottleneck">Exit Corridor Bottleneck (45 pers)</option>
                  <option value="counterflow">Bidirectional Opposing Streams (40 pers)</option>
                  <option value="surge_gate">Ingress Gate Surge (60 pers - Critical)</option>
                </select>
              </div>

              {/* Video Upload Dropzone */}
              <div className="border border-dashed border-line rounded-lg p-3 text-center bg-surface-2/40 hover:bg-surface-2 transition">
                <input
                  type="file"
                  id="video-upload"
                  accept=".mp4,.mov,.avi,.webm"
                  onChange={(e) => void handleVideoUpload(e)}
                  className="hidden"
                />
                <label htmlFor="video-upload" className="cursor-pointer block">
                  <Upload className="size-5 mx-auto text-muted mb-1" />
                  <span className="font-semibold text-ink block">Upload CCTV Video</span>
                  <span className="text-[10px] text-muted block">MP4, AVI, MOV up to 4K</span>
                </label>
                {uploading && <Spinner label="Uploading & decoding stream..." />}
                {uploadedVideoInfo && (
                  <p className="mt-1 text-[10px] text-good-ink">
                    ✓ {uploadedVideoInfo.filename} ({uploadedVideoInfo.frames} frames @ {uploadedVideoInfo.fps.toFixed(0)} FPS)
                  </p>
                )}
              </div>
            </div>
          </Card>

          {/* Perspective Calibration Controls */}
          <Card
            title="Perspective Calibration"
            subtitle="4-point ground-plane planar homography mapping."
            actions={
              <Button
                size="sm"
                variant={isCalibrating ? 'primary' : 'ghost'}
                onClick={() => {
                  setIsCalibrating(!isCalibrating)
                  setCalibPointStep(0)
                }}
              >
                <CrosshairIcon className="size-3.5" />
                <span>{isCalibrating ? `Click P${calibPointStep + 1}` : 'Pick on Feed'}</span>
              </Button>
            }
          >
            <div className="space-y-3 text-xs">
              {isCalibrating && (
                <div className="rounded-lg bg-cyan-500/10 border border-cyan-500/30 p-2 text-cyan-300 text-[11px]">
                  Click on the camera frame to place corner #{calibPointStep + 1}:{' '}
                  <b>{['Top-Left', 'Top-Right', 'Bottom-Right', 'Bottom-Left'][calibPointStep]}</b>
                </div>
              )}

              {/* 4 Corner Coordinates */}
              <div className="grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded border border-line p-1.5 bg-surface-2">
                  <span className="text-muted block">TL (x, y)</span>
                  <span className="font-mono">{calibQuad.top_left.x}, {calibQuad.top_left.y}</span>
                </div>
                <div className="rounded border border-line p-1.5 bg-surface-2">
                  <span className="text-muted block">TR (x, y)</span>
                  <span className="font-mono">{calibQuad.top_right.x}, {calibQuad.top_right.y}</span>
                </div>
                <div className="rounded border border-line p-1.5 bg-surface-2">
                  <span className="text-muted block">BR (x, y)</span>
                  <span className="font-mono">{calibQuad.bottom_right.x}, {calibQuad.bottom_right.y}</span>
                </div>
                <div className="rounded border border-line p-1.5 bg-surface-2">
                  <span className="text-muted block">BL (x, y)</span>
                  <span className="font-mono">{calibQuad.bottom_left.x}, {calibQuad.bottom_left.y}</span>
                </div>
              </div>

              {/* Real World Physical Dimensions */}
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-muted text-[10px]">Ground Width (m)</label>
                  <input
                    type="number"
                    value={groundWidthMeters}
                    onChange={(e) => setGroundWidthMeters(parseFloat(e.target.value) || 20.0)}
                    className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-xs text-ink"
                  />
                </div>
                <div>
                  <label className="block text-muted text-[10px]">Ground Height (m)</label>
                  <input
                    type="number"
                    value={groundHeightMeters}
                    onChange={(e) => setGroundHeightMeters(parseFloat(e.target.value) || 15.0)}
                    className="w-full rounded border border-line bg-surface-2 px-2 py-1 text-xs text-ink"
                  />
                </div>
              </div>

              <div className="pt-1">
                <Button size="sm" variant="primary" onClick={handleApplyCalibration} busy={loading}>
                  <CheckCircle2 className="size-3.5" /> Recalculate Homography Matrix
                </Button>
              </div>
            </div>
          </Card>

          {/* Processing Settings & Heatmap Controls */}
          <Card title="Processing & Density" subtitle="Detection confidence, frame stride, and KDE kernel.">
            <div className="space-y-3 text-xs">
              <div>
                <label className="block font-medium text-ink mb-1">Heatmap Rendering Mode</label>
                <div className="grid grid-cols-2 gap-1.5">
                  {(['gaussian', 'point', 'zone', 'movement'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setHeatmapMode(m)}
                      className={cx(
                        'rounded border px-2 py-1.5 text-center text-xs font-medium capitalize transition',
                        heatmapMode === m
                          ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-white'
                          : 'border-line bg-surface-2 text-ink-2 hover:bg-surface-2/80'
                      )}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-1">
                  <span>KDE Bandwidth (σ)</span>
                  <span className="font-mono">{bandwidthSigma}px</span>
                </div>
                <input
                  type="range"
                  min="10"
                  max="55"
                  step="1"
                  value={bandwidthSigma}
                  onChange={(e) => setBandwidthSigma(parseInt(e.target.value))}
                  className="w-full accent-[var(--accent)] cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-1">
                  <span>Detection Confidence</span>
                  <span className="font-mono">{(detectionConfidence * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range"
                  min="0.15"
                  max="0.85"
                  step="0.05"
                  value={detectionConfidence}
                  onChange={(e) => setDetectionConfidence(parseFloat(e.target.value))}
                  className="w-full accent-[var(--accent)] cursor-pointer"
                />
              </div>

              <div>
                <div className="flex justify-between text-muted text-[11px] mb-1">
                  <span>Frame Sampling Stride</span>
                  <span className="font-mono">1 / {frameStride} frames</span>
                </div>
                <input
                  type="range"
                  min="1"
                  max="5"
                  step="1"
                  value={frameStride}
                  onChange={(e) => setFrameStride(parseInt(e.target.value))}
                  className="w-full accent-[var(--accent)] cursor-pointer"
                />
              </div>
            </div>
          </Card>
        </div>

        {/* ======================================================== */}
        {/* CENTRAL PANEL: Visual Canvas & View Toggles (6 cols)     */}
        {/* ======================================================== */}
        <div className="space-y-4 lg:col-span-6">
          {/* View Toggles & Comparison Mode */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-2 text-xs">
            <div className="flex flex-wrap items-center gap-1">
              {[
                { id: 'camera', label: 'Original Camera', icon: Camera },
                { id: 'birdseye', label: "Bird's-Eye View", icon: Grid },
                { id: 'heatmap', label: 'Crowd Heatmap', icon: Flame },
                { id: 'movement', label: 'Movement Vectors', icon: MoveRight },
                { id: 'digitaltwin', label: 'Venue Digital Twin', icon: Layers },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as ViewTab)}
                  className={cx(
                    'flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition',
                    activeTab === tab.id
                      ? 'bg-sidebar-2 text-white border border-[var(--accent)]/40 shadow-sm'
                      : 'text-muted hover:bg-surface-2 hover:text-ink'
                  )}
                >
                  <tab.icon className="size-3.5" />
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-muted">
                {telemetry ? `${telemetry.processing_latency_ms}ms · ${telemetry.total_detected} detected` : 'connecting...'}
              </span>
            </div>
          </div>

          {/* Central Visual Display */}
          <div className="rounded-xl border border-line bg-surface overflow-hidden shadow-lg">
            {sideBySide ? (
              /* Side-by-side mode */
              <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-line">
                {/* Left: Original Camera Feed */}
                <div className="relative bg-black flex flex-col">
                  <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 bg-black/70 backdrop-blur px-2 py-1 rounded text-[10px] text-white border border-white/10">
                    <Camera className="size-3 text-cyan-400" />
                    <span>Original CCTV Stream (Oblique)</span>
                  </div>
                  <img
                    src={`/api/crowdguard/analysis/live/frame?t=${imgTimestamp}`}
                    alt="Original Camera"
                    onClick={handleCanvasClick}
                    className={cx(
                      'w-full h-auto aspect-video object-contain',
                      isCalibrating && 'cursor-crosshair border-2 border-cyan-400'
                    )}
                  />
                  <div className="p-2 text-[10px] text-muted border-t border-line/60 bg-surface">
                    Ground-contact foot points extracted from bounding box bottom-centers [(x1+x2)/2, y2].
                  </div>
                </div>

                {/* Right: Bird's-Eye Heatmap / Active Tab */}
                <div className="relative bg-black flex flex-col">
                  <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 bg-black/70 backdrop-blur px-2 py-1 rounded text-[10px] text-white border border-white/10">
                    <Flame className="size-3 text-amber-400" />
                    <span>Virtual Top-Down Perspective ({activeTab.toUpperCase()})</span>
                  </div>
                  <img
                    src={getStreamUrl(activeTab)}
                    alt="Virtual Bird's-Eye"
                    className="w-full h-auto aspect-video object-contain"
                  />
                  <div className="p-2 text-[10px] text-muted border-t border-line/60 bg-surface flex justify-between items-center">
                    <span>Planar Homography Projective Mapping</span>
                    <span className="font-mono text-cyan-400">{groundWidthMeters}m × {groundHeightMeters}m</span>
                  </div>
                </div>
              </div>
            ) : (
              /* Single View Mode */
              <div className="relative bg-black">
                <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-black/80 backdrop-blur px-2.5 py-1.5 rounded-lg text-xs text-white border border-white/10">
                  <Eye className="size-3.5 text-cyan-400" />
                  <span className="font-semibold uppercase">{activeTab} View</span>
                  <span className="text-muted">·</span>
                  <span className="text-[11px] text-muted">Virtual Top-Down Space</span>
                </div>
                <img
                  src={getStreamUrl(activeTab)}
                  alt={activeTab}
                  onClick={activeTab === 'camera' ? handleCanvasClick : undefined}
                  className="w-full h-auto max-h-[640px] aspect-video object-contain mx-auto"
                />
              </div>
            )}

            {/* Playback & Scrub Bar */}
            <div className="p-3 border-t border-line bg-surface-2/40 flex flex-wrap items-center justify-between gap-3 text-xs">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setIsPlaying(!isPlaying)}
                  className="size-7 rounded-lg bg-[var(--accent)] text-white flex items-center justify-center hover:brightness-110"
                >
                  {isPlaying ? <Pause className="size-4" /> : <Play className="size-4" />}
                </button>
                <div className="text-[11px] text-muted">
                  Frame <b className="text-ink font-mono">{telemetry?.frame_idx ?? 0}</b> · Time <b className="text-ink font-mono">{(telemetry?.timestamp_s ?? 0).toFixed(1)}s</b>
                </div>
              </div>

              {/* Speed toggle */}
              <div className="flex items-center gap-1">
                {[1, 2, 4].map((spd) => (
                  <button
                    key={spd}
                    onClick={() => setPlaybackSpeed(spd)}
                    className={cx(
                      'px-2 py-0.5 rounded text-[11px] font-mono',
                      playbackSpeed === spd
                        ? 'bg-sidebar-2 font-bold text-white'
                        : 'text-muted hover:text-ink'
                    )}
                  >
                    {spd}x
                  </button>
                ))}
              </div>

              {/* Disclaimer Notice */}
              <div className="text-[10px] text-muted italic">
                Notice: Projective 2D representation; occluded objects are not reconstructed. Advisory indicators for human review.
              </div>
            </div>
          </div>
        </div>

        {/* ======================================================== */}
        {/* RIGHT PANEL: Live Telemetry, Zones & Alerts (3 cols)     */}
        {/* ======================================================== */}
        <div className="space-y-4 lg:col-span-3">
          {/* Key Metric Stats */}
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label="Monitored Population"
              value={telemetry?.active_tracks_count ?? 0}
              hint="Persistent track IDs"
            />
            <Stat
              label="Peak Density"
              value={telemetry ? `${telemetry.peak_density_per_sq_meter.toFixed(2)}` : '0.00'}
              hint="Persons / m²"
              tone={
                (telemetry?.peak_density_per_sq_meter ?? 0) >= 3.0
                  ? 'bad'
                  : (telemetry?.peak_density_per_sq_meter ?? 0) >= 1.5
                  ? 'warn'
                  : 'good'
              }
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Stat
              label="Mean Venue Density"
              value={telemetry ? `${telemetry.mean_density_per_sq_meter.toFixed(2)}` : '0.00'}
              hint="Persons / m²"
            />
            <Stat
              label="High Density Footprint"
              value={telemetry ? `${telemetry.high_density_area_sq_meters.toFixed(0)}m²` : '0m²'}
              hint="Area > 1.5 p/m²"
              tone={(telemetry?.high_density_area_sq_meters ?? 0) > 20 ? 'warn' : 'neutral'}
            />
          </div>

          {/* Zone Occupancy Table */}
          <Card title="Zone Population & Capacity" subtitle="Real-time point-in-polygon spatial metrics.">
            <div className="space-y-2 text-xs">
              {(telemetry?.zone_metrics ?? []).map((z) => (
                <div
                  key={z.zone_id}
                  onClick={() => setSelectedZone(z)}
                  className={cx(
                    'rounded-lg border p-2 cursor-pointer transition',
                    selectedZone?.zone_id === z.zone_id
                      ? 'border-cyan-400 bg-cyan-500/10'
                      : 'border-line/70 bg-surface-2/40 hover:bg-surface-2'
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">{z.zone_name}</span>
                    <Badge
                      tone={
                        z.risk_level === 'critical'
                          ? 'bad'
                          : z.risk_level === 'high'
                          ? 'warn'
                          : 'good'
                      }
                    >
                      {z.risk_level.toUpperCase()}
                    </Badge>
                  </div>
                  <div className="mt-1 flex justify-between text-[11px] text-muted">
                    <span>
                      Occupancy: <b className="text-ink">{z.population}</b> / {z.capacity} ({z.occupancy_pct.toFixed(0)}%)
                    </span>
                    <span className="font-mono text-ink-2">{z.density_per_sq_meter.toFixed(1)} p/m²</span>
                  </div>
                  {/* Capacity progress bar */}
                  <div className="mt-1.5 h-1.5 w-full rounded-full bg-line overflow-hidden">
                    <div
                      className={cx(
                        'h-full rounded-full transition-all duration-300',
                        z.occupancy_pct >= 90
                          ? 'bg-rose-500'
                          : z.occupancy_pct >= 70
                          ? 'bg-amber-500'
                          : 'bg-emerald-500'
                      )}
                      style={{ width: `${Math.min(100, z.occupancy_pct)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Congestion & Safety Alerts */}
          <Card
            title="Congestion & Safety Alerts"
            subtitle="Bottlenecks, opposing counterflow, and crush risk."
          >
            <div className="space-y-2 max-h-56 overflow-y-auto pr-1 text-xs">
              {(telemetry?.alerts ?? []).length === 0 ? (
                <div className="py-4 text-center text-muted text-xs">
                  <CheckCircle2 className="size-6 text-good-ink mx-auto mb-1 opacity-70" />
                  <span>No active safety alerts. Flow is normal.</span>
                </div>
              ) : (
                telemetry?.alerts.map((alert) => (
                  <div
                    key={alert.id}
                    className={cx(
                      'rounded-lg border p-2.5 text-xs',
                      alert.severity === 'critical'
                        ? 'border-rose-500/40 bg-rose-500/10 text-rose-200'
                        : alert.severity === 'high'
                        ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                        : 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
                    )}
                  >
                    <div className="flex items-center gap-1.5 font-semibold">
                      {alert.severity === 'critical' ? (
                        <AlertOctagon className="size-3.5 text-rose-400" />
                      ) : (
                        <AlertTriangle className="size-3.5 text-amber-400" />
                      )}
                      <span className="uppercase tracking-wider text-[10px]">
                        {alert.alert_type.replace('_', ' ')}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-snug">{alert.message}</p>
                    <p className="mt-1.5 text-[10px] text-muted border-t border-white/10 pt-1">
                      Action: {alert.recommendation}
                    </p>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

function CrosshairIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="3" x2="12" y2="7" />
      <line x1="12" y1="17" x2="12" y2="21" />
      <line x1="3" y1="12" x2="7" y2="12" />
      <line x1="17" y1="12" x2="21" y2="12" />
    </svg>
  )
}
