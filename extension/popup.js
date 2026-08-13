const status = document.querySelector("#status");
document.querySelector("#signin").onclick = async () => {
  status.textContent = "Signing in…";
  const result = await chrome.runtime.sendMessage({ type: "REVISIT_SIGN_IN" });
  status.textContent = result?.ok ? "Signed in. Select text to begin." : result?.error || "Sign-in failed";
};
chrome.storage.local.get(["revisitToken", "pendingCaptures"]).then(data => {
  if (data.revisitToken) status.textContent = `Signed in${data.pendingCaptures?.length ? ` · ${data.pendingCaptures.length} queued` : ""}`;
});
