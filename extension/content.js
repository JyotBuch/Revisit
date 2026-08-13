(() => {
  if (window.top !== window || document.documentElement.dataset.revisitLoaded) return;
  document.documentElement.dataset.revisitLoaded = "true";
  let host = null;
  let selectionText = "";
  let rect = null;
  let busy = false;
  let currentRoot = null;

  const escape = value => String(value || "").slice(0, 20000);
  const meta = selector => document.querySelector(selector)?.content || null;
  const canonicalUrl = () => document.querySelector('link[rel="canonical"]')?.href || location.href;

  function remove() { if (host) host.remove(); host = null; currentRoot = null; busy = false; }
  function selectionAllowed(range) {
    const node = range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentElement : range.commonAncestorContainer;
    return node && !node.closest('input, textarea, [contenteditable="true"], [role="textbox"]');
  }

  function payload(mode, note = "") {
    return {
      source_type: selectionText ? "passage" : "article",
      selected_text: selectionText || null,
      url: canonicalUrl(), title: document.title || null, domain: location.hostname,
      description: meta('meta[name="description"]') || meta('meta[property="og:description"]'),
      author: meta('meta[name="author"]'), user_note: note || null,
      captured_at: new Date().toISOString(), mode, idempotency_key: crypto.randomUUID()
    };
  }

  function renderStatus(root, text, state = "") {
    const status = root.querySelector(".status"); status.textContent = text; status.dataset.state = state;
  }

  function show(x, y, text = "") {
    remove(); selectionText = escape(text || window.getSelection()?.toString().trim());
    host = document.createElement("div");
    host.style.cssText = `all:initial;position:absolute;z-index:2147483647;left:${Math.max(8, x)}px;top:${Math.max(8, y)}px`;
    const root = host.attachShadow({ mode: "closed" });
    currentRoot = root;
    root.innerHTML = `<style>
      .box{font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#111827;color:#fff;border-radius:10px;padding:7px;box-shadow:0 8px 28px #0005;display:flex;gap:5px;align-items:center}
      button{border:0;border-radius:7px;padding:7px 10px;font:600 12px inherit;cursor:pointer}.research{background:#6366f1;color:#fff}.capture{background:#fff;color:#111827}.note{background:transparent;color:#c7d2fe;padding:5px}button:disabled{opacity:.55}.status{padding:0 5px;color:#d1d5db;max-width:170px}.status[data-state="ok"]{color:#86efac}.status[data-state="error"]{color:#fca5a5}input{width:180px;border:0;border-radius:6px;padding:7px;display:none}.with-note input{display:block}.with-note .note{display:none}
    </style><div class="box"><button class="research">Research</button><button class="capture">Capture</button><button class="note" title="Add optional context">+ context</button><input maxlength="1000" placeholder="Optional context"><span class="status"></span></div>`;
    const box = root.querySelector(".box");
    root.querySelector(".note").onclick = () => { box.classList.add("with-note"); root.querySelector("input").focus(); };
    for (const mode of ["research", "capture"]) root.querySelector(`.${mode}`).onclick = async () => {
      if (busy) return; busy = true;
      root.querySelectorAll("button").forEach(button => button.disabled = true);
      renderStatus(root, "Saving…");
      const result = await chrome.runtime.sendMessage({ type: "REVISIT_SAVE", payload: payload(mode, root.querySelector("input").value) });
      if (result?.ok) { renderStatus(root, "Saved", "ok"); setTimeout(remove, 900); }
      else { renderStatus(root, result?.error || "Retry", "error"); busy = false; root.querySelectorAll("button").forEach(button => button.disabled = false); }
    };
    document.documentElement.appendChild(host);
  }

  document.addEventListener("mouseup", event => setTimeout(() => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim()) return;
    const range = selection.getRangeAt(0);
    if (!selectionAllowed(range)) return remove();
    rect = range.getBoundingClientRect();
    show(window.scrollX + Math.min(rect.right, innerWidth - 270), window.scrollY + rect.bottom + 8, selection.toString().trim());
  }, 0), true);
  document.addEventListener("mousedown", event => { if (host && !event.composedPath().includes(host)) remove(); }, true);
  document.addEventListener("keydown", event => { if (event.key === "Escape") remove(); }, true);
  window.addEventListener("pagehide", remove);
  chrome.runtime.onMessage.addListener(message => {
    if (message.type === "REVISIT_FALLBACK") {
      const text = message.selectedText || window.getSelection()?.toString().trim() || "";
      show(window.scrollX + innerWidth / 2 - 120, window.scrollY + 80, text);
      if (message.mode) currentRoot?.querySelector(`.${message.mode}`)?.click();
    }
  });
})();
