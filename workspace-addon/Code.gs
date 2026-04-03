/**
 * PlagiarismGuard — Google Workspace Add-on
 *
 * Works with Google Docs and Google Slides.
 * Calls the PlagiarismGuard API for plagiarism detection,
 * AI text detection, and text humanization.
 */

// ═══════════════════════════════════════════════════════════════════════════
// Configuration — users set these via the Settings card
// ═══════════════════════════════════════════════════════════════════════════

var PROPERTY_SERVER_URL = "PG_SERVER_URL";
var PROPERTY_API_KEY = "PG_API_KEY";

function getServerUrl() {
  return PropertiesService.getUserProperties().getProperty(PROPERTY_SERVER_URL) || "";
}

function getApiKey() {
  return PropertiesService.getUserProperties().getProperty(PROPERTY_API_KEY) || "";
}

function saveSettings(serverUrl, apiKey) {
  var props = PropertiesService.getUserProperties();
  props.setProperty(PROPERTY_SERVER_URL, serverUrl.replace(/\/+$/, ""));
  props.setProperty(PROPERTY_API_KEY, apiKey);
  return { success: true };
}

// ═══════════════════════════════════════════════════════════════════════════
// Add-on Entry Points (Card-based UI for Workspace add-ons)
// ═══════════════════════════════════════════════════════════════════════════

function onDocsHomepage(e) {
  return buildHomeCard("docs");
}

function onSlidesHomepage(e) {
  return buildHomeCard("slides");
}

/**
 * Legacy menu-based trigger for editor add-ons.
 */
function onOpen(e) {
  var ui;
  try {
    ui = DocumentApp.getUi();
  } catch (_) {
    try {
      ui = SlidesApp.getUi();
    } catch (_) {
      return;
    }
  }
  ui.createAddonMenu()
    .addItem("Open Sidebar", "showSidebar")
    .addItem("Scan Selected Text", "scanSelectedFromMenu")
    .addItem("Settings", "showSettings")
    .addToUi();
}

function onInstall(e) {
  onOpen(e);
}

// ═══════════════════════════════════════════════════════════════════════════
// Sidebar
// ═══════════════════════════════════════════════════════════════════════════

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile("Sidebar")
    .setTitle("PlagiarismGuard")
    .setWidth(320);
  try {
    DocumentApp.getUi().showSidebar(html);
  } catch (_) {
    SlidesApp.getUi().showSidebar(html);
  }
}

function showSettings() {
  var html = HtmlService.createHtmlOutputFromFile("Settings")
    .setTitle("PlagiarismGuard Settings")
    .setWidth(320);
  try {
    DocumentApp.getUi().showSidebar(html);
  } catch (_) {
    SlidesApp.getUi().showSidebar(html);
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Card-based UI (for Workspace Add-on)
// ═══════════════════════════════════════════════════════════════════════════

function buildHomeCard(context) {
  var serverUrl = getServerUrl();
  var configured = serverUrl && getApiKey();

  var card = CardService.newCardBuilder();
  card.setHeader(
    CardService.newCardHeader()
      .setTitle("PlagiarismGuard")
      .setSubtitle("Plagiarism & AI Detection")
      .setImageUrl("https://plagiarismguard.ai/favicon.svg")
  );

  if (!configured) {
    // Settings section
    var settingsSection = CardService.newCardSection()
      .setHeader("Setup Required")
      .addWidget(
        CardService.newTextParagraph().setText(
          "Enter your PlagiarismGuard server URL and API key to get started."
        )
      )
      .addWidget(
        CardService.newTextInput()
          .setFieldName("serverUrl")
          .setTitle("Server URL")
          .setHint("https://your-app.azurewebsites.net")
          .setValue(serverUrl)
      )
      .addWidget(
        CardService.newTextInput()
          .setFieldName("apiKey")
          .setTitle("API Key")
          .setHint("pg_xxxxxxxxxxxx")
      )
      .addWidget(
        CardService.newButtonSet().addButton(
          CardService.newTextButton()
            .setText("Save Settings")
            .setOnClickAction(
              CardService.newAction().setFunctionName("handleSaveSettings")
            )
        )
      );
    card.addSection(settingsSection);
  } else {
    // Main actions
    var actionsSection = CardService.newCardSection()
      .setHeader("Scan Tools")
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("📋 Scan Selected Text")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleScanSelected")
              )
          )
      )
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("📄 Scan Full Document")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleScanFullDoc")
              )
          )
      )
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("🤖 AI Detection Only")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleAIDetection")
              )
          )
      )
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("✏️ Humanize Selected Text")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleHumanize")
              )
          )
      );
    card.addSection(actionsSection);

    // Open sidebar button
    var sidebarSection = CardService.newCardSection()
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("Open Full Sidebar")
              .setOnClickAction(
                CardService.newAction().setFunctionName("showSidebar")
              )
          )
          .addButton(
            CardService.newTextButton()
              .setText("⚙ Settings")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleShowSettings")
              )
          )
      );
    card.addSection(sidebarSection);
  }

  return card.build();
}

// ═══════════════════════════════════════════════════════════════════════════
// Card Action Handlers
// ═══════════════════════════════════════════════════════════════════════════

function handleSaveSettings(e) {
  var formInputs = e.formInput || {};
  var serverUrl = formInputs.serverUrl || "";
  var apiKey = formInputs.apiKey || "";

  if (!serverUrl || !apiKey) {
    return CardService.newActionResponseBuilder()
      .setNotification(
        CardService.newNotification().setText("Please enter both Server URL and API Key.")
      )
      .build();
  }

  saveSettings(serverUrl, apiKey);

  return CardService.newActionResponseBuilder()
    .setNavigation(
      CardService.newNavigation().updateCard(buildHomeCard("docs"))
    )
    .setNotification(
      CardService.newNotification().setText("Settings saved!")
    )
    .build();
}

function handleShowSettings(e) {
  var card = CardService.newCardBuilder();
  card.setHeader(
    CardService.newCardHeader().setTitle("Settings")
  );

  var section = CardService.newCardSection()
    .addWidget(
      CardService.newTextInput()
        .setFieldName("serverUrl")
        .setTitle("Server URL")
        .setValue(getServerUrl())
    )
    .addWidget(
      CardService.newTextInput()
        .setFieldName("apiKey")
        .setTitle("API Key")
        .setHint("pg_xxxxxxxxxxxx")
    )
    .addWidget(
      CardService.newButtonSet().addButton(
        CardService.newTextButton()
          .setText("Save")
          .setOnClickAction(
            CardService.newAction().setFunctionName("handleSaveSettings")
          )
      )
    );
  card.addSection(section);

  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().pushCard(card.build()))
    .build();
}

function handleScanSelected(e) {
  var text = getSelectedText();
  if (!text || text.length < 20) {
    return notify("Please select at least a sentence of text first.");
  }
  var result = callApi("/api/v1/analyze/quick", { text: text });
  return buildResultCard(result, "Plagiarism Scan");
}

function handleScanFullDoc(e) {
  var text = getFullDocumentText();
  if (!text || text.length < 50) {
    return notify("Document is too short to scan.");
  }
  // Limit to 50K chars
  if (text.length > 50000) text = text.substring(0, 50000);
  var result = callApi("/api/v1/analyze/quick", { text: text });
  return buildResultCard(result, "Full Document Scan");
}

function handleAIDetection(e) {
  var text = getSelectedText();
  if (!text || text.length < 20) {
    return notify("Please select text for AI detection.");
  }
  var result = callApi("/api/v1/tools/ai-detect", { text: text });
  return buildAIResultCard(result);
}

function handleHumanize(e) {
  var text = getSelectedText();
  if (!text || text.length < 10) {
    return notify("Please select text to humanize.");
  }
  var result = callApi("/rewrite/general", { text: text, mode: "humanize" });
  if (result.error) {
    return notify("Humanize failed: " + result.error);
  }
  return buildHumanizeCard(result);
}

// ═══════════════════════════════════════════════════════════════════════════
// Result Cards
// ═══════════════════════════════════════════════════════════════════════════

function buildResultCard(result, title) {
  if (result.error) {
    return notify("Scan failed: " + result.error);
  }

  var plagScore = result.plagiarism_score || result.score || 0;
  var aiScore = result.ai_score || 0;
  var risk = result.risk_level || "LOW";
  var confidence = result.confidence_score || result.confidence || 0;

  var riskEmoji = risk === "HIGH" ? "🔴" : risk === "MEDIUM" ? "🟡" : "🟢";

  var card = CardService.newCardBuilder();
  card.setHeader(CardService.newCardHeader().setTitle(title));

  var section = CardService.newCardSection()
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Plagiarism Score")
        .setText(plagScore.toFixed(1) + "%")
        .setBottomLabel(risk + " Risk " + riskEmoji)
    )
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel("AI Detection Score")
        .setText(aiScore.toFixed(1) + "%")
    )
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Confidence")
        .setText((confidence * 100).toFixed(0) + "%")
    );

  // Sources
  var sources = result.detected_sources || [];
  if (sources.length > 0) {
    var sourcesSection = CardService.newCardSection().setHeader(
      "Detected Sources (" + sources.length + ")"
    );
    sources.slice(0, 5).forEach(function (src) {
      var label = src.title || src.url || "Unknown source";
      var sim = ((src.similarity || 0) * 100).toFixed(0) + "% match";
      var widget = CardService.newDecoratedText()
        .setText(label.substring(0, 60))
        .setBottomLabel(sim);
      if (src.url) {
        widget.setOpenLink(CardService.newOpenLink().setUrl(src.url));
      }
      sourcesSection.addWidget(widget);
    });
    card.addSection(sourcesSection);
  }

  // Model attribution
  var modelAttr = result.model_attribution || {};
  var models = Object.keys(modelAttr);
  if (models.length > 0) {
    section.addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Suspected AI Models")
        .setText(
          models.map(function (m) { return m + " (" + modelAttr[m] + ")"; }).join(", ")
        )
    );
  }

  card.addSection(section);

  // Back button
  card.addSection(
    CardService.newCardSection().addWidget(
      CardService.newButtonSet().addButton(
        CardService.newTextButton()
          .setText("← Back")
          .setOnClickAction(
            CardService.newAction().setFunctionName("handleGoBack")
          )
      )
    )
  );

  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().pushCard(card.build()))
    .build();
}

function buildAIResultCard(result) {
  if (result.error) {
    return notify("AI detection failed: " + result.error);
  }

  var score = result.score || 0;
  var confidence = result.confidence || 0;
  var indicators = result.indicators || {};

  var verdict = score >= 60 ? "🔴 Likely AI-Generated" : score >= 30 ? "🟡 Possibly AI-Generated" : "🟢 Likely Human-Written";

  var card = CardService.newCardBuilder();
  card.setHeader(CardService.newCardHeader().setTitle("AI Detection"));

  var section = CardService.newCardSection()
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel("AI Score")
        .setText(score.toFixed(1) + "%")
        .setBottomLabel(verdict)
    )
    .addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Confidence")
        .setText((confidence * 100).toFixed(0) + "%")
    );

  // Indicators
  if (indicators.type_token_ratio) {
    section.addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Vocabulary Richness (TTR)")
        .setText(indicators.type_token_ratio.toFixed(3))
    );
  }

  var modelAttr = indicators.model_attribution || {};
  var models = Object.keys(modelAttr);
  if (models.length > 0) {
    section.addWidget(
      CardService.newDecoratedText()
        .setTopLabel("Suspected Models")
        .setText(
          models.map(function (m) { return m + " (" + modelAttr[m] + ")"; }).join(", ")
        )
    );
  }

  card.addSection(section);
  card.addSection(
    CardService.newCardSection().addWidget(
      CardService.newButtonSet().addButton(
        CardService.newTextButton()
          .setText("← Back")
          .setOnClickAction(
            CardService.newAction().setFunctionName("handleGoBack")
          )
      )
    )
  );

  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().pushCard(card.build()))
    .build();
}

function buildHumanizeCard(result) {
  var rewritten = result.rewritten_text || result.text || "";

  var card = CardService.newCardBuilder();
  card.setHeader(CardService.newCardHeader().setTitle("Humanized Text"));

  card.addSection(
    CardService.newCardSection()
      .addWidget(
        CardService.newTextParagraph().setText(rewritten.substring(0, 2000))
      )
      .addWidget(
        CardService.newButtonSet()
          .addButton(
            CardService.newTextButton()
              .setText("📋 Replace Selection")
              .setOnClickAction(
                CardService.newAction()
                  .setFunctionName("handleReplaceSelection")
                  .setParameters({ text: rewritten.substring(0, 5000) })
              )
          )
          .addButton(
            CardService.newTextButton()
              .setText("← Back")
              .setOnClickAction(
                CardService.newAction().setFunctionName("handleGoBack")
              )
          )
      )
  );

  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().pushCard(card.build()))
    .build();
}

function handleReplaceSelection(e) {
  var newText = e.parameters.text || "";
  if (!newText) return notify("No text to replace.");

  try {
    var doc = DocumentApp.getActiveDocument();
    var selection = doc.getSelection();
    if (!selection) return notify("No text selected.");

    var elements = selection.getRangeElements();
    if (elements.length > 0) {
      var el = elements[0];
      var textEl = el.getElement().asText();
      var start = el.getStartOffset();
      var end = el.getEndOffsetInclusive();
      if (start >= 0 && end >= start) {
        textEl.deleteText(start, end);
        textEl.insertText(start, newText);
        return notify("Text replaced successfully!");
      }
    }
    return notify("Could not replace — try selecting text again.");
  } catch (err) {
    return notify("Replace not supported in Slides. Copy the text manually.");
  }
}

function handleGoBack(e) {
  return CardService.newActionResponseBuilder()
    .setNavigation(CardService.newNavigation().popCard())
    .build();
}

// ═══════════════════════════════════════════════════════════════════════════
// Text Extraction Helpers
// ═══════════════════════════════════════════════════════════════════════════

function getSelectedText() {
  // Try Google Docs first
  try {
    var doc = DocumentApp.getActiveDocument();
    var selection = doc.getSelection();
    if (selection) {
      var elements = selection.getRangeElements();
      var text = "";
      for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        var textEl = el.getElement().asText();
        if (textEl) {
          var start = el.getStartOffset();
          var end = el.getEndOffsetInclusive();
          if (start >= 0 && end >= start) {
            text += textEl.getText().substring(start, end + 1) + " ";
          } else {
            text += textEl.getText() + " ";
          }
        }
      }
      return text.trim();
    }
  } catch (_) {}

  // Try Google Slides
  try {
    var presentation = SlidesApp.getActivePresentation();
    var selection = presentation.getSelection();
    if (selection.getSelectionType() === SlidesApp.SelectionType.TEXT) {
      var textRange = selection.getTextRange();
      if (textRange) {
        return textRange.asString().trim();
      }
    }
  } catch (_) {}

  return "";
}

function getFullDocumentText() {
  // Google Docs
  try {
    var doc = DocumentApp.getActiveDocument();
    return doc.getBody().getText().trim();
  } catch (_) {}

  // Google Slides — concatenate all slide text
  try {
    var presentation = SlidesApp.getActivePresentation();
    var slides = presentation.getSlides();
    var allText = [];
    for (var i = 0; i < slides.length; i++) {
      var shapes = slides[i].getShapes();
      for (var j = 0; j < shapes.length; j++) {
        var tf = shapes[j].getText();
        if (tf) {
          var t = tf.asString().trim();
          if (t) allText.push(t);
        }
      }
    }
    return allText.join("\n\n").trim();
  } catch (_) {}

  return "";
}

// ═══════════════════════════════════════════════════════════════════════════
// API Communication
// ═══════════════════════════════════════════════════════════════════════════

function callApi(endpoint, payload) {
  var serverUrl = getServerUrl();
  var apiKey = getApiKey();

  if (!serverUrl || !apiKey) {
    return { error: "Please configure your server URL and API key in Settings." };
  }

  var url = serverUrl + endpoint;

  try {
    var options = {
      method: "post",
      contentType: "application/json",
      headers: {
        Authorization: "Bearer " + apiKey,
      },
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    };

    var response = UrlFetchApp.fetch(url, options);
    var code = response.getResponseCode();
    var body = JSON.parse(response.getContentText());

    if (code === 200 || code === 201) {
      return body;
    } else if (code === 429) {
      return { error: "Rate limit exceeded. Please upgrade your plan or try later." };
    } else {
      return { error: body.detail || "Server returned " + code };
    }
  } catch (err) {
    return { error: "Connection failed: " + err.message };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// Menu-triggered scan (legacy editor add-on)
// ═══════════════════════════════════════════════════════════════════════════

function scanSelectedFromMenu() {
  var text = getSelectedText();
  if (!text || text.length < 20) {
    var ui;
    try { ui = DocumentApp.getUi(); } catch (_) { ui = SlidesApp.getUi(); }
    ui.alert("Please select at least a sentence of text first.");
    return;
  }

  var result = callApi("/api/v1/analyze/quick", { text: text });
  if (result.error) {
    var ui;
    try { ui = DocumentApp.getUi(); } catch (_) { ui = SlidesApp.getUi(); }
    ui.alert("Error: " + result.error);
    return;
  }

  var plagScore = (result.plagiarism_score || result.score || 0).toFixed(1);
  var aiScore = (result.ai_score || 0).toFixed(1);
  var risk = result.risk_level || "LOW";

  var ui;
  try { ui = DocumentApp.getUi(); } catch (_) { ui = SlidesApp.getUi(); }
  ui.alert(
    "PlagiarismGuard Results",
    "Plagiarism: " + plagScore + "%\n" +
    "AI Score: " + aiScore + "%\n" +
    "Risk Level: " + risk,
    ui.ButtonSet.OK
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Utility
// ═══════════════════════════════════════════════════════════════════════════

function notify(message) {
  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText(message))
    .build();
}

/**
 * Callable from Sidebar HTML via google.script.run.
 * Same as callApi but accessible by name from the client.
 */
function callApiFromSidebar(endpoint, payload) {
  return callApi(endpoint, payload);
}
