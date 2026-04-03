/* PlagiarismGuard — Content Script (injected into web pages) */

// Listen for messages from the popup or background script
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "getSelectedText") {
    sendResponse({ text: window.getSelection().toString() });
  }
  if (msg.action === "getPageText") {
    sendResponse({ text: document.body.innerText });
  }
});
