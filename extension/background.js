const DEFAULT_BACKEND = "https://revisit.onrender.com";

async function settings() {
  return chrome.storage.sync.get({ backendUrl: DEFAULT_BACKEND });
}

async function authenticate(interactive = true) {
  const result = await chrome.identity.getAuthToken({ interactive });
  const googleToken = typeof result === "string" ? result : result.token;
  if (!googleToken) throw new Error("Google sign-in was cancelled");
  const { backendUrl } = await settings();
  const response = await fetch(`${backendUrl}/api/v1/auth/extension/google`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ access_token: googleToken })
  });
  if (!response.ok) {
    await chrome.identity.removeCachedAuthToken({ token: googleToken });
    throw new Error("Revisit sign-in failed");
  }
  const credential = await response.json();
  await chrome.storage.local.set({ revisitToken: credential.token, tokenExpiresAt: credential.expires_at });
  return credential.token;
}

async function token(interactive = true) {
  const stored = await chrome.storage.local.get(["revisitToken", "tokenExpiresAt"]);
  if (stored.revisitToken && stored.tokenExpiresAt > Date.now() / 1000 + 60) return stored.revisitToken;
  return authenticate(interactive);
}

async function saveCapture(payload, interactive = true) {
  const { backendUrl } = await settings();
  let bearer = await token(interactive);
  let response;
  try {
    response = await fetch(`${backendUrl}/api/v1/captures`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${bearer}`, "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    await queue(payload);
    throw new Error("Offline — queued for retry");
  }
  if (response.status === 401 && interactive) {
    await chrome.storage.local.remove(["revisitToken", "tokenExpiresAt"]);
    bearer = await authenticate(true);
    return saveCapture(payload, false);
  }
  if (!response.ok) throw new Error(response.status === 401 ? "Sign in again" : "Could not save selection");
  return response.json();
}

async function queue(payload) {
  const { pendingCaptures = [] } = await chrome.storage.local.get("pendingCaptures");
  if (!pendingCaptures.some(item => item.idempotency_key === payload.idempotency_key)) pendingCaptures.push(payload);
  await chrome.storage.local.set({ pendingCaptures });
  await chrome.alarms.create("retry-captures", { delayInMinutes: 1, periodInMinutes: 5 });
}

async function retryPending() {
  const { pendingCaptures = [] } = await chrome.storage.local.get("pendingCaptures");
  const remaining = [];
  for (const payload of pendingCaptures) {
    try { await saveCapture(payload, false); } catch (_) { remaining.push(payload); }
  }
  await chrome.storage.local.set({ pendingCaptures: remaining });
  if (!remaining.length) await chrome.alarms.clear("retry-captures");
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "revisit-capture", title: "Capture in Revisit", contexts: ["selection", "page"] });
  chrome.contextMenus.create({ id: "revisit-research", title: "Research with Revisit", contexts: ["selection", "page"] });
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  chrome.tabs.sendMessage(tab.id, { type: "REVISIT_FALLBACK", mode: info.menuItemId.endsWith("research") ? "research" : "capture", selectedText: info.selectionText || "" });
});
chrome.commands.onCommand.addListener((_command, tab) => chrome.tabs.sendMessage(tab.id, { type: "REVISIT_FALLBACK", mode: "capture" }));
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === "retry-captures") retryPending(); });
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "REVISIT_SAVE") {
    saveCapture(message.payload).then(data => sendResponse({ ok: true, data })).catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === "REVISIT_SIGN_IN") {
    authenticate(true).then(() => sendResponse({ ok: true })).catch(error => sendResponse({ ok: false, error: error.message }));
    return true;
  }
});
