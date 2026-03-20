# PlagiarismGuard - AI Multi-Agent System

## Objective

Build a production-ready AI-powered plagiarism detection system using a modular multi-agent architecture.

## Core Idea

The system should NOT rely on a single detection method. Instead, it should combine multiple weak signals into a strong decision system using independent agents.

## Key Capabilities

* Upload and analyze research documents (PDF, DOCX, TXT)
* Detect plagiarism using:

  * Semantic similarity (embeddings)
  * Web-based similarity search
  * Academic corpus comparison
  * AI-generated text detection
* Aggregate results into a unified plagiarism score
* Provide explainability and confidence metrics
* Generate a structured, human-readable report

## Design Principles

* Modular agents (loosely coupled)
* Parallel execution for performance
* Deterministic outputs (low randomness)
* Scalable and cloud-ready (Azure-friendly)

## Target Output

A JSON report containing:

* plagiarism_score (0-100)
* confidence_score (0-1)
* risk_level (LOW / MEDIUM / HIGH)
* detected_sources
* flagged_passages
* explanation
