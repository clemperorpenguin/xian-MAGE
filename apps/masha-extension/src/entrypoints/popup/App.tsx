/*
 * Masha — Browser extension selection translator.
 * Copyright (C) 2026  Clementine Pendragon <clem@pendragon.systems>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 *
 * Contact: clem@pendragon.systems (Clementine Pendragon, c/o Xian Project Development)
 */

import { useState, useEffect, CSSProperties } from 'react';
import { shouldWarnHttpToNonLoopback } from '../../utils/lemonadeUrl';
import { getConfig, setConfig } from '../../utils/config';
import { BridgeHealth, DEFAULT_CONFIG, MashaConfig } from '../../platform/bridge';

const SOURCE_LANGS = ['Auto', 'Chinese', 'Japanese', 'Korean', 'English', 'Spanish', 'French', 'German', 'Russian', 'Arabic', 'Hindi', 'Vietnamese'];
const TARGET_LANGS = SOURCE_LANGS.filter((l) => l !== 'Auto');

const HOVER_MODES: Array<[MashaConfig['hoverMode'], string]> = [
  ['off', 'Off'],
  ['hover', 'On hover'],
  ['shift', 'Hold Shift'],
  ['alt', 'Hold Alt'],
  ['ctrl', 'Hold Ctrl'],
];

/** Send a command to the tab the user is looking at. */
async function tellActiveTab(message: object): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) await chrome.tabs.sendMessage(tab.id, message);
}

/** Base64 for a picked file — `sendMessage` is JSON, so bytes cannot go raw. */
async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function App() {
  const [config, setLocalConfig] = useState<MashaConfig>(DEFAULT_CONFIG);
  const [styles, setStyles] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [health, setHealth] = useState<BridgeHealth | null>(null);
  const [pageBusy, setPageBusy] = useState(false);
  const [glossary, setGlossary] = useState<Record<string, string>>({});
  const [term, setTerm] = useState({ source: '', target: '' });
  const [job, setJob] = useState<{ id: string; status: string; progress: number } | null>(null);

  /** Update one setting locally; `Save` is what persists the form. */
  function patch(update: Partial<MashaConfig>): void {
    setLocalConfig((current) => ({ ...current, ...update }));
  }

  /** Toggles take effect immediately — a switch that needs saving is a bug. */
  async function toggle(update: Partial<MashaConfig>): Promise<void> {
    patch(update);
    await setConfig(update);
  }

  useEffect(() => {
    getConfig().then((cfg) => {
      setLocalConfig(cfg);
      setStyles(cfg.styles.join(', '));
    });
    chrome.runtime.sendMessage({ type: 'MASHA_BRIDGE_HEALTH' }).then((response) => {
      if (response?.success) setHealth(response.health);
    }).catch(() => setHealth({ reachable: false, ocr: false, documents: false }));
    chrome.runtime.sendMessage({ type: 'MASHA_GLOSSARY_GET' }).then((response) => {
      if (response?.success) setGlossary(response.terms || {});
    }).catch(() => {});
  }, []);

  // Poll a running document job until it stops running.
  useEffect(() => {
    if (!job || job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') return;
    const timer = setInterval(async () => {
      const response = await chrome.runtime.sendMessage({ type: 'MASHA_DOCUMENT_POLL', jobId: job.id });
      if (response?.success) {
        setJob({ id: job.id, status: response.status, progress: response.progress ?? 0 });
      }
    }, 1000);
    return () => clearInterval(timer);
  }, [job]);

  const handleSave = async () => {
    setStatus('saving');
    if (shouldWarnHttpToNonLoopback(config.serverUrl)) {
      const ok = window.confirm(
        'Warning: You are saving an HTTP Lemonade URL that is not localhost. Traffic on untrusted networks can be intercepted.\n\nClick OK to save or Cancel to edit.',
      );
      if (!ok) {
        setStatus('idle');
        return;
      }
    }
    await setConfig({
      ...config,
      styles: styles.split(',').map((s) => s.trim()).filter(Boolean),
    });
    setLocalConfig(await getConfig());
    setStatus('saved');
    setTimeout(() => setStatus('idle'), 2000);
  };

  const handlePage = async (type: 'MASHA_PAGE_TRANSLATE' | 'MASHA_PAGE_UNDO') => {
    setPageBusy(true);
    try {
      await tellActiveTab({ type });
    } catch {
      // A page MASHA cannot be injected into (the store, a PDF viewer).
    }
    setPageBusy(false);
  };

  const handleAddTerm = async () => {
    if (!term.source.trim() || !term.target.trim()) return;
    await chrome.runtime.sendMessage({
      type: 'MASHA_GLOSSARY_SET',
      source: term.source.trim(),
      target: term.target.trim(),
    });
    setGlossary({ ...glossary, [term.source.trim()]: term.target.trim() });
    setTerm({ source: '', target: '' });
  };

  const handleDocument = async (file: File | undefined) => {
    if (!file) return;
    const response = await chrome.runtime.sendMessage({
      type: 'MASHA_DOCUMENT_JOB',
      filename: file.name,
      data: await fileToBase64(file),
      sourceLang: config.sourceLang,
      targetLang: config.targetLang,
    });
    if (response?.success) setJob({ id: response.jobId, status: 'queued', progress: 0 });
  };

  const label: CSSProperties = { fontSize: '12px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' };
  const field: CSSProperties = {
    width: '100%', padding: '10px 12px', backgroundColor: '#1e293b', border: '1px solid #334155',
    borderRadius: '8px', color: '#f8fafc', fontSize: '13px', boxSizing: 'border-box', outline: 'none',
  };
  const section: CSSProperties = { marginTop: '18px', paddingTop: '14px', borderTop: '1px solid #1e293b' };
  const row: CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', fontSize: '13px', color: '#cbd5e1', padding: '3px 0' };
  const action: CSSProperties = {
    flex: 1, padding: '9px', border: '1px solid #334155', borderRadius: '8px',
    background: '#1e293b', color: '#e2e8f0', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
  };

  /** A labelled switch, saved the moment it moves. */
  const Switch = ({ on, onChange, children }: { on: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) => (
    <label style={{ ...row, cursor: 'pointer' }}>
      <span>{children}</span>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} style={{ accentColor: '#a855f7', width: '16px', height: '16px' }} />
    </label>
  );

  return (
    <div style={{ width: '340px', padding: '22px', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', backgroundColor: '#0f172a', color: '#f8fafc', boxSizing: 'border-box' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
        <div style={{ width: '36px', height: '36px', borderRadius: '10px', background: 'linear-gradient(135deg, #6366f1, #a855f7)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', boxShadow: '0 0 15px rgba(99, 102, 241, 0.5)' }}>✨</div>
        <div>
          <h1 style={{ fontSize: '18px', fontWeight: 800, margin: 0, letterSpacing: '-0.025em', background: 'linear-gradient(to right, #818cf8, #c084fc)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>MASHA</h1>
          <p style={{ fontSize: '11px', color: '#94a3b8', margin: 0 }}>Context-Aware Translator</p>
        </div>
      </div>

      {/* This page */}
      <div style={{ display: 'flex', gap: '8px' }}>
        <button style={action} disabled={pageBusy} onClick={() => handlePage('MASHA_PAGE_TRANSLATE')}>
          Translate this page
        </button>
        <button style={action} disabled={pageBusy} onClick={() => handlePage('MASHA_PAGE_UNDO')}>
          Undo
        </button>
      </div>
      <p style={{ fontSize: '11px', lineHeight: 1.5, color: '#64748b', margin: '8px 0 0' }}>
        Or select text, right-click, and choose <strong>Translate with MASHA</strong>.
      </p>

      {/* Languages and model */}
      <div style={{ ...section, display: 'flex', flexDirection: 'column', gap: '14px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={label}>Lemonade Node URL</label>
          <input type="text" value={config.serverUrl} onChange={(e) => patch({ serverUrl: e.target.value })} placeholder="http://localhost:13305/v1" style={field} />
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={label}>From</label>
            <select value={config.sourceLang} onChange={(e) => patch({ sourceLang: e.target.value })} style={field}>
              {SOURCE_LANGS.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={label}>To</label>
            <select value={config.targetLang} onChange={(e) => patch({ targetLang: e.target.value })} style={field}>
              {TARGET_LANGS.map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={label}>Style terms (optional)</label>
          <input type="text" value={styles} onChange={(e) => setStyles(e.target.value)} placeholder="e.g. formal, gaming" style={field} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <label style={label}>Domain expertise (optional)</label>
          <input type="text" value={config.expertise} onChange={(e) => patch({ expertise: e.target.value })} placeholder="e.g. medicine, law" style={field} />
        </div>
      </div>

      <button
        onClick={handleSave}
        disabled={status === 'saving'}
        style={{ marginTop: '14px', width: '100%', padding: '11px', background: status === 'saved' ? '#10b981' : 'linear-gradient(135deg, #6366f1, #a855f7)', color: '#ffffff', border: 'none', borderRadius: '8px', fontWeight: 600, fontSize: '13px', cursor: 'pointer', transition: 'all 0.2s ease' }}
      >
        {status === 'saving' ? 'Saving...' : status === 'saved' ? 'Saved!' : 'Save Settings'}
      </button>

      {/* While you read */}
      <div style={section}>
        <label style={{ ...label, display: 'block', marginBottom: '8px' }}>While you read</label>
        <div style={row}>
          <span>Hover to translate</span>
          <select value={config.hoverMode} onChange={(e) => toggle({ hoverMode: e.target.value as MashaConfig['hoverMode'] })} style={{ ...field, width: 'auto', padding: '5px 8px', fontSize: '12px' }}>
            {HOVER_MODES.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </div>
        <Switch on={config.composeEnabled} onChange={(v) => toggle({ composeEnabled: v })}>
          Triple-space to translate what you type
        </Switch>
        <Switch on={config.subtitlesEnabled} onChange={(v) => toggle({ subtitlesEnabled: v })}>
          Translate video subtitles
        </Switch>
        {config.subtitlesEnabled && (
          <Switch on={config.audioSubtitlesEnabled} onChange={(v) => toggle({ audioSubtitlesEnabled: v })}>
            …and transcribe audio when there is no track
          </Switch>
        )}
        {config.subtitlesEnabled && config.audioSubtitlesEnabled && (
          <div style={row}>
            <span style={{ fontSize: '12px' }}>Transcription model</span>
            <input
              type="text"
              value={config.asrModel}
              onChange={(e) => patch({ asrModel: e.target.value })}
              onBlur={() => setConfig({ asrModel: config.asrModel })}
              style={{ ...field, width: '140px', padding: '5px 8px', fontSize: '12px' }}
            />
          </div>
        )}
        <Switch on={config.imagesEnabled} onChange={(v) => toggle({ imagesEnabled: v })}>
          Right-click an image to translate it
        </Switch>
        <Switch on={config.comicsEnabled} onChange={(v) => toggle({ comicsEnabled: v })}>
          Translate comic panels while scrolling
        </Switch>
        {config.comicsEnabled && (
          <Switch on={config.comicRtl} onChange={(v) => toggle({ comicRtl: v })}>
            …right-to-left panel order (manga)
          </Switch>
        )}
        {(config.imagesEnabled || config.comicsEnabled) && health && !health.ocr && (
          <p style={{ fontSize: '11px', color: '#f59e0b', margin: '6px 0 0' }}>
            The bridge has no OCR engine, so images cannot be read yet.
          </p>
        )}
      </div>

      {/* Bridge-backed features */}
      <div style={section}>
        <label style={{ ...label, display: 'block', marginBottom: '8px' }}>
          Bridge {health === null ? '· checking…' : health.reachable ? `· v${health.version ?? '?'}` : '· not running'}
        </label>

        {!health?.reachable && (
          <p style={{ fontSize: '11px', color: '#64748b', margin: 0, lineHeight: 1.5 }}>
            Documents, images and the shared glossary need the local bridge:
            <code style={{ color: '#a5b4fc' }}> uv run -m xian_bridge</code>
          </p>
        )}

        {health?.documents && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={{ fontSize: '12px', color: '#cbd5e1' }}>Translate a document</span>
            <input
              type="file"
              accept=".txt,.srt,.ass,.vtt,.html,.htm,.epub"
              onChange={(e) => handleDocument(e.target.files?.[0])}
              style={{ ...field, padding: '7px' }}
            />
            {job && (
              <span style={{ fontSize: '11px', color: job.status === 'failed' ? '#ef4444' : '#94a3b8' }}>
                {job.status} · {Math.round((job.progress ?? 0) * 100)}%
              </span>
            )}
          </div>
        )}

        {health?.reachable && (
          <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <span style={{ fontSize: '12px', color: '#cbd5e1' }}>
              Glossary · {Object.keys(glossary).length} terms
            </span>
            <div style={{ display: 'flex', gap: '6px' }}>
              <input type="text" value={term.source} onChange={(e) => setTerm({ ...term, source: e.target.value })} placeholder="term" style={{ ...field, padding: '7px 9px' }} />
              <input type="text" value={term.target} onChange={(e) => setTerm({ ...term, target: e.target.value })} placeholder="translation" style={{ ...field, padding: '7px 9px' }} />
              <button onClick={handleAddTerm} style={{ ...action, flex: '0 0 auto', padding: '7px 12px' }}>Add</button>
            </div>
          </div>
        )}
      </div>

      <div style={{ marginTop: '16px', paddingTop: '12px', borderTop: '1px solid #1e293b', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '11px', color: '#475569' }}>v1.0.0</span>
        <span style={{ fontSize: '11px', color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981', display: 'inline-block' }}></span> Active
        </span>
      </div>
    </div>
  );
}

export default App;
