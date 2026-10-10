/* Presentation queue: no delay in generation, persistence or tool execution. */
(function(root) {
  function step(left) { return Math.max(3, Math.ceil(left / 40)); }
  function create(render, schedule = fn => setTimeout(fn, 16), cancel = clearTimeout) {
    let target = '', shown = '', timer = null, stopped = false;
    function tick() {
      timer = null;
      if (stopped) return;
      if (!target.startsWith(shown)) shown = '';
      let end = Math.min(target.length, shown.length + step(target.length - shown.length));
      if (end < target.length && /[\uD800-\uDBFF]/.test(target[end-1] || '')) end++;
      shown = target.slice(0,end);
      render(shown);
      if (shown !== target) timer = schedule(tick);
    }
    return {
      set(text) { target = String(text || ''); if (!stopped && timer === null && target !== shown) timer = schedule(tick); },
      stop() { stopped = true; if(timer !== null) cancel(timer); timer = null; },
      current() { return shown; }
    };
  }
  root.EmilyProgressiveReply = {create,step};
  if(typeof module !== 'undefined') module.exports = root.EmilyProgressiveReply;
})(typeof globalThis !== 'undefined' ? globalThis : this);
