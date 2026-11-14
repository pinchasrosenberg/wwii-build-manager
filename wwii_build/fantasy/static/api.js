const token = document.querySelector('meta[name="fantasy-token"]').content;

const request = (method, url, body) =>
  fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-Fantasy-Token': token },
    body: body === undefined ? undefined : JSON.stringify(body),
    keepalive: method === 'POST',
  }).then((res) => res.json().then((data) => (res.ok ? data : Promise.reject(new Error(data.error || res.statusText)))));

export const api = {
  setClock: (id, clock) => request('POST', `/api/worlds/${id}/clock`, clock),
  worlds: () => request('GET', '/api/worlds'),
  createWorld: (name, description, useLlm, extra = {}) => request('POST', '/api/worlds', { name, description, use_llm: useLlm, ...extra }),
  models: () => request('GET', '/api/models'),
  startModels: () => request('POST', '/api/models/start', {}),
  proposePlan: (id, text, image, useLlm) => request('POST', `/api/worlds/${id}/plan/propose`, { text, image, use_llm: useLlm }),
  resolvePlan: (pid, action) => request('POST', `/api/plan_proposals/${pid}/resolve`, { action }),
  worldVersions: (id) => request('GET', `/api/worlds/${id}/versions`),
  revertWorld: (id, version) => request('POST', `/api/worlds/${id}/revert`, { version }),
  world: (id) => request('GET', `/api/worlds/${id}`),
  savePlayer: (id, state) => request('POST', `/api/worlds/${id}/player`, state),
  propose: (id, room, text, useLlm) => request('POST', `/api/worlds/${id}/rooms/${room}/propose`, { text, use_llm: useLlm }),
  preview: (pid, selected) => request('POST', `/api/proposals/${pid}/preview`, { selected }),
  resolve: (pid, action, selected, scopes) => request('POST', `/api/proposals/${pid}/resolve`, { action, selected, scopes }),
  history: (id, room) => request('GET', `/api/worlds/${id}/rooms/${room}/history`),
  revert: (id, room, version) => request('POST', `/api/worlds/${id}/rooms/${room}/revert`, { version }),
  assets: () => request('GET', '/api/assets'),
  proposeObject: (id, target, text, useLlm) => request('POST', `/api/worlds/${id}/objects/propose`, { target, text, use_llm: useLlm }),
  resolveObject: (pid, action) => request('POST', `/api/object_proposals/${pid}/resolve`, { action }),
  useLibrary: (id, body) => request('POST', `/api/worlds/${id}/library/use`, body),
  house: (id, hid) => request('GET', `/api/worlds/${id}/houses/${hid}`),
};
