import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, markRaw, nextTick, reactive } from 'vue'

async function componentUrl(path, shell = false) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  let code = compileScript(descriptor, { id: path, inlineTemplate: true }).content
  code = code.replace(/from (['"])vue\1/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
  if (shell) {
    code = code.replace(/import \{ createWorkspace \} from ['"]\.\/workspace\.js['"]/, 'const createWorkspace = () => globalThis.shellWorkspace')
    code = code.replace(/import (\w+) from ['"]\.\/views\/[^'"]+['"]/g, 'const $1 = { render: () => null }')
  }
  const imports = [...code.matchAll(/from (['"])(\.\/[^'"]+\.vue)\1/g)]
  for (const match of imports) {
    const url = await componentUrl(new URL(match[2], new URL(path, import.meta.url)).href)
    code = code.replace(match[0], `from ${JSON.stringify(url)}`)
  }
  return `data:text/javascript,${encodeURIComponent(code)}`
}

function surface() {
  const listeners = new Map()
  const doc = { activeElement: null, body: { style: { overflow: '' } }, addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: name => listeners.delete(name) }
  function node(tag, text = '') {
    const value = {
      tag, text, children: [], props: {}, parent: null, isConnected: true,
      focus() { if (!value.closest('[inert]')) doc.activeElement = value },
      contains(item) { return item === value || value.children.some(child => child.contains(item)) },
      getClientRects() { return value.props.hidden ? [] : [{}] },
      closest() { return value.props.hidden || value.props.inert ? value : value.parent?.closest() },
      querySelectorAll() { return descendants(value).filter(item => ['button', 'input', 'select', 'textarea'].includes(item.tag) && !item.props.disabled || item.tag === 'a' && item.props.href) },
    }
    return markRaw(value)
  }
  const renderer = createRenderer({
    createElement: tag => node(tag), createText: text => node('#text', text), createComment: text => node('#comment', text),
    setText: (item, text) => { item.text = text }, setElementText: (item, text) => { item.text = text },
    patchProp: (item, key, before, after) => { item.props[key] = after },
    insert(item, parent, anchor = null) { item.parent = parent; const index = parent.children.indexOf(anchor); if (index < 0) parent.children.push(item); else parent.children.splice(index, 0, item) },
    remove(item) { item.isConnected = false; item.parent.children.splice(item.parent.children.indexOf(item), 1) },
    parentNode: item => item.parent, nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] || null,
  })
  const root = node('root')
  globalThis.document = doc
  return { doc, root, listeners, renderer, node, find: predicate => descendants(root).find(predicate) }
}

function descendants(root) { return root.children.flatMap(item => [item, ...descendants(item)]) }
function keyEvent(key, shiftKey = false) { return { key, shiftKey, prevented: false, preventDefault() { this.prevented = true }, stopPropagation() {} } }

test('任务抽屉保留对话框语义、Escape关闭和入口焦点恢复', async () => {
  const Modal = (await import(await componentUrl('../src/components/Modal.vue'))).default
  const ui = surface(), trigger = ui.node('button')
  trigger.focus()
  let closed = 0
  const app = ui.renderer.createApp({ render: () => h(Modal, { title: '任务详情', variant: 'drawer', onClose: () => closed++ }, () => h('input')) })
  try {
    app.mount(ui.root)
    const dialog = ui.find(item => item.props.role === 'dialog')
    assert.ok(dialog.props.class.includes('modal-drawer'), '任务详情必须使用抽屉')
    assert.equal(dialog.props['aria-modal'], 'true')
    assert.equal(dialog.props['aria-label'], '任务详情')
    ui.listeners.get('keydown')(keyEvent('Escape'))
    assert.equal(closed, 1)
    app.unmount()
    assert.ok(ui.doc.activeElement === trigger, '关闭后焦点回到原入口')
  } finally { if (ui.root._vnode) app.unmount(); delete globalThis.document }
})

test('对话框从初始容器焦点进入并环绕可用控件', async () => {
  const Modal = (await import(await componentUrl('../src/components/Modal.vue'))).default
  const ui = surface()
  const app = ui.renderer.createApp({ render: () => h(Modal, { title: '核对计划' }, () => [h('input', { disabled: true }), h('input', { hidden: true }), h('input', { id: 'last-input' })]) })
  try {
    app.mount(ui.root)
    const dialog = ui.find(item => item.props.role === 'dialog'), last = ui.find(item => item.props.id === 'last-input')
    dialog.focus()
    const reverse = keyEvent('Tab', true)
    ui.listeners.get('keydown')(reverse)
    assert.equal(reverse.prevented, true)
    assert.ok(ui.doc.activeElement === last, '从初始焦点反向进入最后一个可用控件')
    const forward = keyEvent('Tab')
    ui.listeners.get('keydown')(forward)
    assert.equal(forward.prevented, true)
    assert.equal(ui.doc.activeElement.props['aria-label'], '关闭对话框')
  } finally { app.unmount(); delete globalThis.document }
})

test('手机菜单导航与Escape关闭后恢复入口和滚动，演示标签取自配置', async () => {
  const App = (await import(await componentUrl('../src/App.vue', true))).default
  const ui = surface()
  const mediaListeners = new Map()
  globalThis.window = { matchMedia: () => ({ matches: true, addEventListener: (name, fn) => mediaListeners.set(name, fn), removeEventListener: name => mediaListeners.delete(name) }) }
  const s = reactive({ booting: false, user: { name: '一组成员甲', identity: 'student' }, tab: 'home', projects: [], selectedId: 1, config: { demo_data: true, ai_ready: false }, resourceErrors: {}, data: { project: { name: '项目', role: 'member' }, cards: [] } })
  globalThis.shellWorkspace = { s, init() {}, dispose() {}, selectProject() {}, loadRequirements() {}, refreshProject() {}, logout() {} }
  const app = ui.renderer.createApp(App)
  try {
    app.mount(ui.root)
    await nextTick()
    const trigger = ui.find(item => item.props['aria-controls'] === 'project-navigation')
    assert.ok(trigger, '手机必须有明确菜单入口')
    trigger.focus()
    trigger.props.onClick()
    await nextTick()
    assert.equal(trigger.props['aria-expanded'], true)
    assert.equal(ui.doc.body.style.overflow, 'hidden')
    const sidebar = ui.find(item => item.props.id === 'project-navigation')
    const reverse = keyEvent('Tab', true)
    sidebar.props.onKeydown(reverse)
    assert.equal(reverse.prevented, true)
    assert.equal(ui.doc.activeElement.props['aria-label'], '退出登录')
    const forward = keyEvent('Tab')
    sidebar.props.onKeydown(forward)
    assert.equal(forward.prevented, true)
    assert.equal(ui.doc.activeElement.props['aria-label'], '关闭导航菜单')
    sidebar.props.onKeydown(keyEvent('Escape'))
    await nextTick()
    assert.equal(trigger.props['aria-expanded'], false)
    assert.ok(ui.doc.activeElement === trigger, '手机菜单关闭后焦点回到入口')
    assert.equal(ui.doc.body.style.overflow, '')
    trigger.props.onClick()
    await nextTick()
    const tasks = ui.find(item => item.tag === 'button' && descendants(item).some(child => child.text === '任务看板'))
    tasks.props.onClick()
    await nextTick()
    assert.equal(s.tab, 'tasks')
    assert.equal(trigger.props['aria-expanded'], false)
    assert.ok(ui.find(item => item.text === '演示数据'))
    s.config.demo_data = false
    await nextTick()
    assert.equal(ui.find(item => item.text === '演示数据'), undefined)
    trigger.props.onClick()
    await nextTick()
    const mask = ui.find(item => item.props.class === 'sidebar-mask')
    mask.props.onClick()
    await nextTick()
    assert.equal(trigger.props['aria-expanded'], false)
    trigger.props.onClick()
    await nextTick()
    mediaListeners.get('change')({ matches: false })
    await nextTick()
    assert.equal(trigger.props['aria-expanded'], false)
    assert.equal(ui.doc.body.style.overflow, '')
  } finally { app.unmount(); delete globalThis.document; delete globalThis.window; delete globalThis.shellWorkspace }
})
