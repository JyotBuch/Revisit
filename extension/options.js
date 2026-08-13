const input = document.querySelector("#backend");
chrome.storage.sync.get({ backendUrl: "https://revisit.onrender.com" }).then(value => input.value = value.backendUrl);
document.querySelector("#save").onclick = async () => {
  const backendUrl = input.value.trim().replace(/\/$/, "");
  if (!/^https:\/\//.test(backendUrl) && !/^http:\/\/127\.0\.0\.1:8000$/.test(backendUrl)) return;
  await chrome.storage.sync.set({ backendUrl });
  document.querySelector("#status").textContent = "Saved";
};
