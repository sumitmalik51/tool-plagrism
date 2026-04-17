"use client";

import { useState } from "react";
import { Search, BookOpen, Bot, Brain, FileSearch, ChevronDown } from "lucide-react";

const AGENTS = [
  {
    icon: <Search className="w-5 h-5" />,
    name: "Web Search Agent",
    tagline: "Scans billions of web pages for exact and near-exact content matches.",
    color: "text-accent",
    bgColor: "bg-accent/10",
    steps: [
      "Your text is chunked into overlapping segments optimized for search relevance",
      "Each chunk is searched across web indexes using multiple search APIs simultaneously",
      "Matching pages are fetched and full-text compared using similarity algorithms",
      "Results are ranked by similarity score, passage overlap, and source authority",
      "Matched passages are mapped back to your original text with highlighted context",
    ],
  },
  {
    icon: <BookOpen className="w-5 h-5" />,
    name: "Academic Agent",
    tagline: "Cross-references arXiv, OpenAlex, and Semantic Scholar — databases that web search misses.",
    color: "text-accent",
    bgColor: "bg-accent/10",
    steps: [
      "Text segments are searched across arXiv, OpenAlex, and Semantic Scholar APIs",
      "Citation patterns and reference styles are analyzed for proper attribution",
      "Matching papers are retrieved with full metadata — authors, year, DOI, abstract",
      "Similarity is scored at both passage level and document level",
      "Unattributed academic content is flagged with the original source paper",
    ],
  },
  {
    icon: <Bot className="w-5 h-5" />,
    name: "AI Detection Agent",
    tagline: "Identifies GPT-4, Claude, Gemini, and LLaMA output using statistical fingerprinting.",
    color: "text-accent",
    bgColor: "bg-accent/10",
    steps: [
      "Text is analyzed for perplexity and burstiness patterns characteristic of LLM output",
      "Token probability distributions are compared against known model signatures",
      "Stylometric features (sentence length variance, vocabulary richness) are evaluated",
      "Multiple detection models vote independently — consensus determines the final score",
      "Each paragraph receives an individual AI probability score with confidence interval",
    ],
  },
  {
    icon: <Brain className="w-5 h-5" />,
    name: "Semantic Agent",
    tagline: "Catches paraphrasing and meaning-level plagiarism that word-for-word checkers miss.",
    color: "text-accent",
    bgColor: "bg-accent/10",
    steps: [
      "Text is converted into high-dimensional semantic embeddings using transformer models",
      "Embeddings are compared against a vector index of known sources using cosine similarity",
      "Passages with high semantic overlap but low lexical overlap are flagged as paraphrased",
      "Context window analysis ensures meaning is preserved across sentence boundaries",
      "Results distinguish between \"direct copy\", \"close paraphrase\", and \"idea overlap\"",
    ],
  },
  {
    icon: <FileSearch className="w-5 h-5" />,
    name: "Report Agent",
    tagline: "Aggregates all agent findings into a single, confidence-weighted report.",
    color: "text-ok",
    bgColor: "bg-ok/10",
    steps: [
      "Collects findings from Web Search, Academic, AI Detection, and Semantic agents",
      "Deduplicates overlapping matches and resolves conflicting signals between agents",
      "Applies confidence-weighted scoring — each agent's contribution reflects its certainty",
      "Generates a risk level (Low / Medium / High / Critical) based on aggregate analysis",
      "Produces the final report with score cards, flagged passages, source list, and PDF export",
    ],
  },
];

export default function AgentAccordion() {
  const [openIndex, setOpenIndex] = useState<number | null>(null);

  return (
    <div className="space-y-3">
      {AGENTS.map((agent, i) => {
        const isOpen = openIndex === i;
        return (
          <div
            key={i}
            className={`border rounded-2xl transition-all duration-300 ${
              isOpen ? "bg-surface border-accent/30" : "bg-surface border-border hover:border-accent/20"
            }`}
          >
            <button
              onClick={() => setOpenIndex(isOpen ? null : i)}
              className="w-full flex items-center gap-4 p-5 text-left"
            >
              <div className={`w-10 h-10 rounded-xl ${agent.bgColor} flex items-center justify-center ${agent.color} shrink-0`}>
                {agent.icon}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-semibold">{agent.name}</h3>
                <p className="text-xs text-muted mt-0.5 truncate">{agent.tagline}</p>
              </div>
              <ChevronDown className={`w-4 h-4 text-muted shrink-0 transition-transform duration-300 ${isOpen ? "rotate-180" : ""}`} />
            </button>

            <div
              className={`overflow-hidden transition-all duration-300 ${
                isOpen ? "max-h-80 opacity-100" : "max-h-0 opacity-0"
              }`}
            >
              <div className="px-5 pb-5">
                <div className="bg-bg rounded-xl p-4">
                  <p className="text-xs font-semibold text-accent uppercase tracking-wider mb-3">HOW IT WORKS</p>
                  <ol className="space-y-2 text-sm text-muted list-decimal list-inside">
                    {agent.steps.map((step, j) => (
                      <li key={j}>{step}</li>
                    ))}
                  </ol>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
