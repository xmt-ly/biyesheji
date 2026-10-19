export function errorMessage(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(x => `${(x.loc || []).filter(y => y !== 'body').join('.')}: ${x.msg || '输入无效'}`).join('；')
  if (detail?.violations) return detail.violations.map(x => x.message || x.code).join('；') || '规划校验未通过'
  return detail?.message || '请求失败，请稍后重试'
}

export function createApiClient({ getToken = () => '', fetchImpl = globalThis.fetch, onUnauthorized = () => {} } = {}) {
  async function request(path, { method = 'GET', data, signal, blob = false } = {}) {
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('://')) throw new Error('请求地址无效')
    const headers = {}
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
    const init = { method, headers, signal }
    if (data !== undefined) {
      if (typeof FormData !== 'undefined' && data instanceof FormData) init.body = data
      else { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(data) }
    }
    let response
    try { response = await fetchImpl(path.startsWith('/api/') ? path : `/api${path}`, init) }
    catch (cause) {
      if (cause.name === 'AbortError') throw cause
      throw new Error('网络连接失败，请检查后端服务或重试', { cause })
    }
    if (!response.ok) {
      let payload
      try { payload = await response.json() } catch { payload = {} }
      if (response.status === 401 && token && getToken() === token && !['/auth/login','/api/auth/login'].includes(path)) onUnauthorized()
      const error = new Error(errorMessage(payload.detail) || `请求失败（${response.status}）`)
      error.status = response.status
      error.detail = payload.detail
      throw error
    }
    if (blob) return response.blob()
    if (response.status === 204) return null
    return response.json()
  }
  return { request }
}
