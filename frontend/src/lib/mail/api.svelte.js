// @ts-nocheck: plain JavaScript (ported from Manifest); covered by its unit tests, not by svelte-check.
// Mail's fetch wrapper: /api/mail/..., Kern's X-Kern write header, JSON in/out.
// A 401 hands over to Kern's session handling; a 403 "needs two-factor"
// (mail/api/guard.py on the server) flips `gate` so the mail app can explain.

import { hooks } from '#lib/api.ts';

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export const gate = $state({ code: '', detail: '' });

async function request(method, path, body) {
  const opts = { method, headers: { 'X-Kern': '1' }, credentials: 'same-origin', cache: 'no-store' };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch('/api/mail' + path, opts);
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection.', 0, null);
  }
  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  const data = isJson ? await res.json() : null;
  if (res.status === 401) hooks.onSignedOut?.();
  if (res.status === 403 && data && String(data.code || '').startsWith('needs_2fa')) {
    gate.code = data.code;
    gate.detail = data.detail;
  }
  if (!res.ok) {
    throw new ApiError((data && (data.detail || data.error)) || res.statusText || 'Request failed', res.status, data);
  }
  return data;
}

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') p.set(k, v);
  }
  const s = p.toString();
  return s ? '?' + s : '';
}

export const api = {
  get: (path, params) => request('GET', path + qs(params)),
  post: (path, body) => request('POST', path, body ?? {}),
  patch: (path, body) => request('PATCH', path, body ?? {}),
  put: (path, body) => request('PUT', path, body ?? {}),
  del: (path) => request('DELETE', path),
  upload: (path, files) => {
    const fd = new FormData();
    for (const f of files) fd.append('file', f);
    return request('POST', path, fd);
  },
};
