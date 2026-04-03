/* PlagiarismGuard Chrome Extension — Popup Logic */

const $ = (id) => document.getElementById(id);

// Elements
const serverUrlInput = $("serverUrl");
const apiKeyInput = $("apiKey");
const saveBtn = $("saveBtn");
const scanBtn = $("scanBtn");
const scanPageBtn = $("scanPageBtn");
const statusEl = $("status");
const spinnerEl = $("spinner");
const resultsEl = $("results");
const wordInfoEl = $("wordInfo");

// Load saved settings
chrome.storage.sync.get(["pgServerUrl", "pgApiKey"], (data) => {
  if (data.pgServerUrl) serverUrlInput.value = data.pgServerUrl;
  if (data.pgApiKey) apiKeyInput.value = data.pgApiKey;
  updateButtonState();
});

function updateButtonState() {
  const hasSettings = serverUrlInput.value.trim() && apiKeyInput.value.trim();
  scanBtn.disabled = !hasSettings;
  scanPageBtn.disabled = !hasSettings;
}

// Save settings
saveBtn.addEventListener("click", () => {
  const url = serverUrlInput.value.trim().replace(/\/+$/, "");
  const key = apiKeyInput.value.trim();
  if (!url || !key) {
    showStatus("Please enter both Server URL and API Key.", "error");
    return;
  }
  chrome.storage.sync.set({ pgServerUrl: url, pgApiKey: key }, () => {
    showStatus("Settings saved!", "success");
    updateButtonState();
  });
});

serverUrlInput.addEventListener("input", updateButtonState);
apiKeyInput.addEventListener("input", updateButtonState);

// Scan selected text
scanBtn.addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window.getSelection().toString(),
    });
    const text = (result || "").trim();
    if (!text) {
      showStatus("No text selected. Highlight text on the page first.", "error");
      return;
    }
    if (text.length < 50) {
      showStatus("Please select at least 50 characters for accurate results.", "error");
      return;
    }
    await runScan(text);
  } catch (err) {
    showStatus("Cannot access this page. Try a different tab.", "error");
  }
});

// Quick scan full page
scanPageBtn.addEventListener("click", async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => document.body.innerText,
    });
    const text = (result || "").trim();
    if (!text || text.length < 50) {
      showStatus("Page has insufficient text to scan.", "error");
      return;
    }
    // Limit to first 10,000 chars for quick scan
    await runScan(text.substring(0, 10000));
  } catch (err) {
    showStatus("Cannot access this page. Try a different tab.", "error");
  }
});

async function runScan(text) {
  const serverUrl = serverUrlInput.value.trim().replace(/\/+$/, "");
  const apiKey = apiKeyInput.value.trim();

  const wordCount = text.split(/\s+/).filter(Boolean).length;
  wordInfoEl.textContent = `Scanning ${wordCount.toLocaleString()} words…`;

  resultsEl.classList.remove("visible");
  spinnerEl.classList.add("active");
  statusEl.className = "status";
  scanBtn.disabled = true;
  scanPageBtn.disabled = true;

  try {
    const resp = await fetch(`${serverUrl}/api/v1/analyze/quick`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${apiKey}`,
      },
      body: JSON.stringify({ text }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `Server returned ${resp.status}`);
    }

    const data = await resp.json();
    displayResults(data);
    showStatus("Scan complete!", "success");
  } catch (err) {
    showStatus(err.message || "Scan failed. Check your settings.", "error");
  } finally {
    spinnerEl.classList.remove("active");
    updateButtonState();
    wordInfoEl.textContent = "";
  }
}

function displayResults(data) {
  const plagScore = data.plagiarism_score ?? data.score ?? 0;
  const aiScore = data.ai_score ?? 0;
  const risk = data.risk_level || "LOW";
  const conf = data.confidence_score ?? data.confidence ?? 0;

  $("plagScore").textContent = `${plagScore.toFixed(1)}%`;
  $("plagScore").className = `score-value ${scoreClass(plagScore)}`;

  $("aiScore").textContent = `${aiScore.toFixed(1)}%`;
  $("aiScore").className = `score-value ${scoreClass(aiScore)}`;

  $("riskLevel").textContent = risk;
  $("riskLevel").className = `score-value ${risk === "HIGH" ? "score-high" : risk === "MEDIUM" ? "score-medium" : "score-low"}`;

  $("confidence").textContent = `${(conf * 100).toFixed(0)}%`;

  // Model attribution
  const modelAttr = data.model_attribution || {};
  const modelDiv = $("modelAttribution");
  const tagsDiv = $("modelTags");
  if (Object.keys(modelAttr).length > 0) {
    tagsDiv.innerHTML = "";
    for (const [model, count] of Object.entries(modelAttr)) {
      const tag = document.createElement("span");
      tag.className = "model-tag";
      tag.textContent = `${model} (${count})`;
      tagsDiv.appendChild(tag);
    }
    modelDiv.style.display = "block";
  } else {
    modelDiv.style.display = "none";
  }

  resultsEl.classList.add("visible");
}

function scoreClass(score) {
  if (score >= 60) return "score-high";
  if (score >= 30) return "score-medium";
  return "score-low";
}

function showStatus(msg, type) {
  statusEl.textContent = msg;
  statusEl.className = `status ${type}`;
}
