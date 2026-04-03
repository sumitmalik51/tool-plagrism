/* PlagiarismGuard — Background Service Worker */

// Context menu for right-click scanning
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "pg-scan-selection",
    title: "Scan with PlagiarismGuard",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "pg-scan-selection") return;

  const text = (info.selectionText || "").trim();
  if (!text || text.length < 50) {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: "PlagiarismGuard",
      message: "Please select at least 50 characters to scan.",
    });
    return;
  }

  const { pgServerUrl, pgApiKey } = await chrome.storage.sync.get([
    "pgServerUrl",
    "pgApiKey",
  ]);

  if (!pgServerUrl || !pgApiKey) {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: "PlagiarismGuard",
      message: "Please configure your server URL and API key in the extension popup.",
    });
    return;
  }

  try {
    const resp = await fetch(
      `${pgServerUrl.replace(/\/+$/, "")}/api/v1/analyze/quick`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${pgApiKey}`,
        },
        body: JSON.stringify({ text: text.substring(0, 10000) }),
      }
    );

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    const plagScore = (data.plagiarism_score ?? data.score ?? 0).toFixed(1);
    const aiScore = (data.ai_score ?? 0).toFixed(1);
    const risk = data.risk_level || "LOW";

    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: `PlagiarismGuard — ${risk} Risk`,
      message: `Plagiarism: ${plagScore}% | AI: ${aiScore}% | Risk: ${risk}`,
    });
  } catch (err) {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: "PlagiarismGuard",
      message: `Scan failed: ${err.message}`,
    });
  }
});
