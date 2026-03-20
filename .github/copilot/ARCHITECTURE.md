# Architecture

## High-Level Flow

Upload → Ingest → Preprocess → Parallel Agents → Aggregation → Report

## Components

### API Layer

* FastAPI handles requests and responses

### Orchestrator

* Controls execution flow
* Runs agents in parallel using asyncio

### Agents

* semantic_agent
* web_search_agent
* academic_agent
* ai_detection_agent

Each agent:

* Works independently
* Returns structured JSON output

### Aggregation Layer

* Combines outputs from all agents
* Applies weighted scoring

### Intelligence Layer

* Confidence scoring
* Explainability

### Storage (Future)

* Cache results
* Store documents and reports

## Execution Model

* Parallel execution for all detection agents
* Sequential execution for aggregation and reporting
