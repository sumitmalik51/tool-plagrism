# Code Guidelines

## General

* Use Python 3.10+
* Follow PEP8
* Use type hints

## Structure

* agents/ → agent logic
* services/ → reusable logic (embeddings, search, etc.)
* models/ → schemas
* utils/ → helpers

## Async

* Use asyncio for parallel execution
* Avoid blocking operations

## Models

* Use Pydantic for all schemas
* Validate inputs

## Performance

* Cache expensive computations
* Avoid duplicate processing

## Logging

* Add structured logs for debugging

## Testing

* Write unit tests for services
* Mock external APIs
