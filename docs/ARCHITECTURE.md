# MaSoVa Agent Architecture

## Overview

MaSoVa Agent is built using Google's Agent Development Kit (ADK) with the Gemini 2.0 Flash model.

## System Components

### 1. Core Agent (`src/masova_agent/agent.py`)
- **Agent**: `LlmAgent` with Gemini 2.0 Flash
- **Tools**: `get_system_briefing()` for customer verification
- **Features**:
  - User authentication against customer database
  - Order tracking and status updates
  - Geolocation with caching (5s timeout)
  - Session management

### 2. Data Layer
- **Mock Databases** (Currently in-memory):
  - `CUSTOMERS_DB`: Customer profiles with tier and loyalty points
  - `ORDERS_DB`: Active orders with delivery status
- **Future**: MongoDB integration (Phase 2)

### 3. External Services
- **Google GenAI API**: LLM inference via Gemini
- **IP Geolocation API**: Location detection with caching

### 4. Session Management
- **Runner**: `InMemoryRunner` for agent execution
- **Sessions**: `InMemorySessionService` for conversation persistence
- **Caching**: Per-customer geolocation cache

## Data Flow

```
User Input → Runner → LlmAgent → Tool Call → get_system_briefing()
                                      ↓
                                Check CUSTOMERS_DB
                                      ↓
                                Fetch Geolocation (cached)
                                      ↓
                                Check ORDERS_DB
                                      ↓
                                Format Response
                                      ↓
                                Return to User
```

## Security

- API keys stored in `.env` (excluded from git)
- Environment variable management via `python-dotenv`
- Input validation on user names
- Timeout protection on external API calls

## Performance

- **Geolocation Caching**: Reduces API calls by 90%+
- **Session Persistence**: Maintains context across messages
- **Async Execution**: Non-blocking agent responses

## Scalability Considerations

**Current Limitations:**
- In-memory data (lost on restart)
- Single-instance deployment
- No distributed session management

**Future Improvements:**
- MongoDB for persistent storage
- Redis for distributed caching
- Load balancing for multiple instances
- Message queue for async processing
