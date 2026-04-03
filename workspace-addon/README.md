# PlagiarismGuard — Google Workspace Add-on

A Google Workspace add-on that brings PlagiarismGuard's plagiarism detection, AI text detection, and text humanization directly into **Google Docs** and **Google Slides**.

## Features

- **Scan Selected Text** — Highlight text and check for plagiarism
- **Scan Full Document** — Analyze the entire document in one click
- **AI Detection** — Detect ChatGPT, Claude, Gemini, Copilot-generated text with model identification
- **Text Humanizer** — Rewrite AI-generated text to sound natural, directly in your document
- **Google Slides Support** — Works with presentations too
- **Sidebar + Card UI** — Full sidebar for detailed results, card-based quick actions

## How to Deploy

### 1. Create a Google Apps Script Project

1. Go to [script.google.com](https://script.google.com)
2. Click **New project**
3. Delete the default `Code.gs` content
4. Copy the contents of each file from this folder:
   - `Code.gs` → Main script file
   - `Sidebar.html` → Sidebar UI
   - `Settings.html` → Settings UI  
   - `appsscript.json` → Click **Project Settings** → Check **Show "appsscript.json" manifest file**, then paste the contents

### 2. Test as Editor Add-on

1. In the Apps Script editor, click **Deploy** → **Test deployments**
2. Select **Editor Add-on** → **Google Docs** (or Slides)
3. Click **Execute** — this opens a test Google Doc with the add-on installed
4. Go to **Extensions** → **PlagiarismGuard** → **Open Sidebar**
5. Enter your server URL and API key in Settings

### 3. Publish to Google Workspace Marketplace

1. In Apps Script, click **Deploy** → **New deployment**
2. Select type: **Add-on**
3. Fill in description, then click **Deploy**
4. Go to [Google Cloud Console](https://console.cloud.google.com)
5. Create a project (or use existing) and link it to your Apps Script
6. Enable the **Google Workspace Marketplace SDK** API
7. Go to **Google Workspace Marketplace SDK** → **App Configuration**:
   - **App name**: PlagiarismGuard
   - **Description**: Check plagiarism and AI-generated text in Google Docs and Slides
   - **App type**: Editor Add-on
   - **Works with**: Google Docs, Google Slides
   - **Pricing**: Free with paid features
   - Upload icons (128x128 and 32x32)
   - Add screenshots (1280x800 recommended)
   - Set the privacy policy URL, terms of service URL
8. Submit for review

### Requirements for Marketplace Listing

- [x] Privacy policy page (you have `/privacy.html`)
- [x] Terms of service page (you have `/terms.html`)  
- [ ] Google Cloud project with OAuth consent screen configured
- [ ] App verification (required for sensitive scopes)
- [ ] Screenshots (at least 1, max 5, 1280x800px)
- [ ] Icon (128x128 PNG)

## Architecture

```
User (Google Docs/Slides)
    ↓
Google Apps Script (Code.gs)
    ↓ HTTPS API calls
PlagiarismGuard Server (FastAPI)
    ↓
Azure OpenAI + Search Engines
```

The add-on runs entirely in Google's infrastructure. It calls your PlagiarismGuard API server via `UrlFetchApp.fetch()`. User credentials (server URL + API key) are stored in `PropertiesService.getUserProperties()` — private to each user's Google account.

## Files

| File | Purpose |
|------|---------|
| `appsscript.json` | Manifest — scopes, triggers, add-on config |
| `Code.gs` | Server-side Apps Script — API calls, text extraction, card/sidebar builders |
| `Sidebar.html` | Main sidebar UI — scan buttons, results display, AI detection, humanizer |
| `Settings.html` | Settings sidebar — server URL and API key configuration |
