/* Modelo de edição puro, também usado pelos testes sem WebView. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EmilyEditorCore = api;
})(typeof window !== 'undefined' ? window : globalThis, function() {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const blank = () => ({version: 1, updated_at: 0, theme: {}, elements: {}, pages: []});
  class History {
    constructor(document, limit = 100) {
      this.limit = limit; this.reset(document);
    }
    reset(document) { this.stack = [clone(document)]; this.index = 0; this.lastKey = ''; this.lastTime = 0; }
    get current() { return clone(this.stack[this.index]); }
    get canUndo() { return this.index > 0; }
    get canRedo() { return this.index < this.stack.length - 1; }
    push(document, key = '', now = Date.now()) {
      const next = clone(document);
      if (JSON.stringify(next) === JSON.stringify(this.stack[this.index])) return false;
      const coalesce = key && key === this.lastKey && now - this.lastTime < 700 && !this.canRedo && this.index > 0;
      this.stack.splice(this.index + 1);
      if (coalesce) this.stack[this.index] = next;
      else { this.stack.push(next); this.index++; }
      if (this.stack.length > this.limit + 1) { this.stack.shift(); this.index--; }
      this.lastKey = key; this.lastTime = now;
      return true;
    }
    undo() { if (this.canUndo) this.index--; this.lastKey = ''; return this.current; }
    redo() { if (this.canRedo) this.index++; this.lastKey = ''; return this.current; }
  }
  const css = styles => {
    const output = {};
    for (const [name, value] of Object.entries(styles || {})) {
      if (name === 'x' || name === 'y') continue;
      output[name] = typeof value === 'number' && !['opacity','order','flexGrow'].includes(name) ? `${value}px` : String(value);
    }
    if ('x' in (styles || {}) || 'y' in (styles || {})) output.translate = `${styles.x || 0}px ${styles.y || 0}px`;
    return output;
  };
  return {clone, blank, History, css};
});
