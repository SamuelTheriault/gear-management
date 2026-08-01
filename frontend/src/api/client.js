/**
 * Client API minimal pour le backend Django REST Framework.
 *
 * Auth : session Django (cookie), pas de token — voir architecture.md
 * section 3. Tant que le flux Google OAuth n'est pas branché côté Vue, se
 * connecter via /api-auth/login/ ou /admin/login/ dans le même navigateur
 * suffit pour que ces appels passent (credentials: 'include').
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

function buildUrl(path, params) {
  const url = new URL(`${BASE_URL}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, value)
      }
    })
  }
  return url.toString()
}

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`))
  return match ? decodeURIComponent(match[2]) : null
}

async function request(method, path, { params, body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (method !== 'GET') {
    const csrfToken = getCookie('csrftoken')
    if (csrfToken) headers['X-CSRFToken'] = csrfToken
  }

  const res = await fetch(buildUrl(path, params), {
    method,
    headers,
    credentials: 'include',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const error = new Error(`Erreur API ${res.status} sur ${method} ${path}`)
    error.status = res.status
    error.data = data
    throw error
  }

  return data
}

export const api = {
  get: (path, params) => request('GET', path, { params }),
  post: (path, body) => request('POST', path, { body }),
  patch: (path, body) => request('PATCH', path, { body }),
  put: (path, body) => request('PUT', path, { body }),
  delete: (path) => request('DELETE', path),
}
