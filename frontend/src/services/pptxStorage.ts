/**
 * Per-session PPTX persistence via the Origin Private File System (OPFS).
 *
 * Why OPFS:
 *   - Backend artifact_store has a 1h TTL; reload after that → 404
 *   - Cross-chat isolation: storing per session id keeps Chat A's history
 *     out of Chat B's UI
 *   - Users often want to download / inspect older versions
 *
 * Layout:
 *   /pptx/<sessionId>/<artifactId>.pptx
 *   /pptx/<sessionId>/index.json   { [artifactId]: {filename, savedAt} }
 *
 * The index file holds metadata that can't be reconstructed from the binary
 * alone (original filename, save timestamp). A best-effort approach: every
 * write updates index.json; a corrupt index.json just causes lost metadata,
 * not lost binaries.
 */

const ROOT_DIR = 'pptx'
const INDEX_FILE = 'index.json'

/** Latest N versions kept per session. Older are evicted on save to bound storage. */
const MAX_VERSIONS_PER_SESSION = 30

export interface StoredArtifactMeta {
  artifactId: string
  filename: string
  sizeBytes: number
  savedAt: number   // ms epoch
}

interface IndexFile {
  [artifactId: string]: { filename: string; savedAt: number }
}

function isOpfsAvailable(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    'storage' in navigator &&
    typeof navigator.storage.getDirectory === 'function'
  )
}

async function getRoot(): Promise<FileSystemDirectoryHandle | null> {
  if (!isOpfsAvailable()) return null
  try {
    return await navigator.storage.getDirectory()
  } catch {
    return null
  }
}

async function getSessionDir(
  sessionId: string,
): Promise<FileSystemDirectoryHandle | null> {
  const root = await getRoot()
  if (!root) return null
  try {
    const pptxDir = await root.getDirectoryHandle(ROOT_DIR, { create: true })
    return await pptxDir.getDirectoryHandle(sessionId, { create: true })
  } catch (e) {
    console.warn('[pptxStorage] getSessionDir failed:', e)
    return null
  }
}

async function readIndex(
  sessionDir: FileSystemDirectoryHandle,
): Promise<IndexFile> {
  try {
    const fh = await sessionDir.getFileHandle(INDEX_FILE)
    const f = await fh.getFile()
    const txt = await f.text()
    if (!txt) return {}
    return JSON.parse(txt) as IndexFile
  } catch {
    return {}
  }
}

async function writeIndex(
  sessionDir: FileSystemDirectoryHandle,
  idx: IndexFile,
): Promise<void> {
  const fh = await sessionDir.getFileHandle(INDEX_FILE, { create: true })
  const w = await fh.createWritable()
  await w.write(JSON.stringify(idx))
  await w.close()
}

async function evictExcess(
  sessionDir: FileSystemDirectoryHandle,
  idx: IndexFile,
): Promise<IndexFile> {
  const entries = Object.entries(idx)
  if (entries.length <= MAX_VERSIONS_PER_SESSION) return idx
  // Drop oldest by savedAt
  entries.sort((a, b) => a[1].savedAt - b[1].savedAt)
  const toRemove = entries.slice(0, entries.length - MAX_VERSIONS_PER_SESSION)
  for (const [aid] of toRemove) {
    try {
      await sessionDir.removeEntry(`${aid}.pptx`)
    } catch {
      /* ignore */
    }
    delete idx[aid]
  }
  return idx
}

/** Save (or overwrite) a PPTX for the given session/artifact. */
export async function savePptx(
  sessionId: string,
  artifactId: string,
  filename: string,
  blob: Blob,
): Promise<void> {
  const dir = await getSessionDir(sessionId)
  if (!dir) return
  try {
    const fh = await dir.getFileHandle(`${artifactId}.pptx`, { create: true })
    const w = await fh.createWritable()
    await w.write(blob)
    await w.close()
    const idx = await readIndex(dir)
    idx[artifactId] = { filename, savedAt: Date.now() }
    const trimmed = await evictExcess(dir, idx)
    await writeIndex(dir, trimmed)
  } catch (e) {
    console.warn(`[pptxStorage] savePptx(${sessionId}/${artifactId}) failed:`, e)
  }
}

/** Read a saved PPTX as a Blob. Returns null when missing or OPFS unavailable. */
export async function getPptx(
  sessionId: string,
  artifactId: string,
): Promise<Blob | null> {
  const dir = await getSessionDir(sessionId)
  if (!dir) return null
  try {
    const fh = await dir.getFileHandle(`${artifactId}.pptx`)
    return await fh.getFile()
  } catch {
    return null
  }
}

/** List all stored artifacts for a session, newest first. */
export async function listSessionArtifacts(
  sessionId: string,
): Promise<StoredArtifactMeta[]> {
  const dir = await getSessionDir(sessionId)
  if (!dir) return []
  try {
    const idx = await readIndex(dir)
    const out: StoredArtifactMeta[] = []
    for (const [artifactId, meta] of Object.entries(idx)) {
      try {
        const fh = await dir.getFileHandle(`${artifactId}.pptx`)
        const f = await fh.getFile()
        out.push({
          artifactId,
          filename: meta.filename,
          sizeBytes: f.size,
          savedAt: meta.savedAt,
        })
      } catch {
        // file vanished — drop from index lazily
      }
    }
    out.sort((a, b) => b.savedAt - a.savedAt)
    return out
  } catch (e) {
    console.warn(`[pptxStorage] listSessionArtifacts(${sessionId}) failed:`, e)
    return []
  }
}

/** Delete a single artifact from a session. */
export async function deleteSessionArtifact(
  sessionId: string,
  artifactId: string,
): Promise<void> {
  const dir = await getSessionDir(sessionId)
  if (!dir) return
  try {
    await dir.removeEntry(`${artifactId}.pptx`)
    const idx = await readIndex(dir)
    delete idx[artifactId]
    await writeIndex(dir, idx)
  } catch (e) {
    console.warn(`[pptxStorage] delete failed:`, e)
  }
}

/** Wipe all artifacts for a session (called when session itself is deleted). */
export async function deleteSession(sessionId: string): Promise<void> {
  const root = await getRoot()
  if (!root) return
  try {
    const pptxDir = await root.getDirectoryHandle(ROOT_DIR, { create: true })
    await pptxDir.removeEntry(sessionId, { recursive: true })
  } catch (e) {
    console.warn(`[pptxStorage] deleteSession(${sessionId}) failed:`, e)
  }
}
