# Revisit Chrome extension

1. Create a Google OAuth client of type **Chrome extension** using the final Chrome Web Store extension ID.
2. Replace the placeholder `oauth2.client_id` in `manifest.json`.
3. Replace the production backend hostname in `manifest.json`, `background.js`, and `options.js` if needed.
4. Load this directory unpacked for staging, then upload a ZIP of its contents to the Chrome Web Store.

The extension requests only identity, local/sync storage, context-menu, active-tab, alarm, and configured Revisit API host access. Page content is sent only after the user clicks **Research** or **Capture**.
