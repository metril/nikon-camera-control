import { client } from './generated/client.gen'

// Plain URLs for <img>/<a> when no API key is needed. The patterns must match generated
// operations; urls.test.js verifies that against sdk.gen.ts so a rename fails the tests.
export const URL_PATTERNS = {
  thumbnail: '/api/v1/thumbnails/{path}',
  file: '/api/v1/files/{path}',
  video: '/api/v1/videos/{session_id}/{name}',
  cameraFile: '/api/v1/camera/files/{folder}/{name}',
}

export const thumbnailUrl = (path, size) =>
  client.buildUrl({ url: URL_PATTERNS.thumbnail, path: { path }, query: size ? { size } : {} })
export const fileUrl = (path) => client.buildUrl({ url: URL_PATTERNS.file, path: { path } })
export const videoUrl = (sessionId, name) =>
  client.buildUrl({ url: URL_PATTERNS.video, path: { session_id: sessionId, name } })
export const cameraFileUrl = (folder, name) =>
  client.buildUrl({ url: URL_PATTERNS.cameraFile, path: { folder, name } })
