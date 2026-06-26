# Architecture Overview

## Tech Stack

- Backend: FastAPI (Python)
- Frontend: React + TypeScript + Vite
- Database: PostgreSQL
- Auth: JWT tokens

## Coding Standards

- Use type hints on all functions
- All API endpoints return JSON
- Use async/await for all I/O operations
- Error handling: always return structured error responses

## Project Structure

- /backend — FastAPI app
- /frontend — React app
- /agents — LangGraph agent nodes
- /arch_docs — architecture documentation

## API Design

- REST endpoints follow /api/v1/resource pattern
- Use Pydantic models for request/response validation
- All endpoints require authentication except /health and /api/auth/login
