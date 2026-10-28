# Agent orchestration demo

## Quick start

```bash
./run.sh setup              # venv + Python deps + npm install + build + creates .env
# edit .env and set GROQ_API_KEY
./run.sh all "My VPN keeps disconnecting repeatedly."   # API + workflow, one shot
```

Other commands: `./run.sh api` (API only), `./run.sh app ["query"]` (workflow only; API must be running),
`./run.sh test` (self-test with a mock LLM, no API key needed), `./run.sh stop`.
Set `PORT=` to change the API port. The first API start downloads the `all-MiniLM-L6-v2` model
from huggingface.co (needs network access to it).

## Knowledge Retrieval Agent (Agent 2)

### How to Run

- Make sure the LLM API key is configured in the `.env` file for request classification.
- Make sure the knowledge base file is available at `data/knowledge_base.json`.
- Make sure Python and the required dependencies are installed.

### Install Python Dependencies

Create and activate the virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
```

Install the required dependencies:

```bash
python -m pip install -r requirements.txt
```

### Start the Knowledge Retrieval Agent API

Run the FastAPI service:

```bash
python -m uvicorn api:app --reload
```

Once the server starts, the API will be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

### API Endpoints

- `GET /` — Check whether the API is running.
- `GET /health` — Check the service health and number of loaded knowledge-base articles.
- `POST /retrieve` — Receive the category, domain, and query from Agent 1, then retrieve relevant knowledge-base articles.
- `POST /classify-and-retrieve` — Classify a raw query using the configured Groq LLM and retrieve relevant knowledge-base articles.

### Sample Request

Send a `POST` request to:

```text
http://127.0.0.1:8000/retrieve
```

Request body:

```json
{
  "category": "change",
  "domain": "IT",
  "query": "I need new software installed"
}
```

The response includes the classification details, retrieval status, matching article IDs, relevance scores, resolutions, and escalation decision.

## Ticket management

Every classified request goes through a ticket step (`manage_ticket` in the workflow graph) after knowledge
retrieval. If a similar **open** ticket (same category and domain) already exists, the report is attached to it
(`occurrences` +1, history entry). Otherwise a new ticket is created: `INC0000001`, `CHG0000001`, `PRB0000001`.
The reply mentions the ticket number. If the ticket service fails, the knowledge answer is still returned and the
reply says the ticket could not be logged.

Similarity is `0.7 * semantic + 0.3 * keyword`, reusing the retrieval model; an identical request always matches.
Threshold: `TICKET_DUP_THRESHOLD` (default `0.80`; tune it against real traffic). Resolved and closed tickets are never reused.

Tickets live in SQLite at `data/tickets.db` (override with `TICKETS_DB`; git-ignored).

| Endpoint | Purpose |
| --- | --- |
| `POST /tickets/find-or-create` | Attach to a similar open ticket, or create (201 new, 200 existing) |
| `POST /tickets` | Create without the duplicate check |
| `GET /tickets?status=&category=&domain=` | List tickets |
| `GET /tickets/{number}` | One ticket with its event history |
| `PATCH /tickets/{number}` | Update `status`, `assignee`, `resolution`, `comment` |

Lifecycle: `open` <-> `in_progress` -> `resolved` (needs a resolution) -> `closed` (final); `resolved` can reopen.

### Knowledge Retrieval Workflow

1. Receive the request category, domain, and query.
2. Filter the knowledge base using the specified category and domain.
3. Calculate relevance using semantic and keyword-based matching.
4. Rank the relevant articles and return up to three results.
5. Apply the configured similarity threshold of `0.75`.
6. Return matching knowledge articles and resolutions, or indicate that escalation is required when no suitable match is found.

### Output

The API returns a JSON response containing:

- Agent identifier
- Classification details
- Knowledge retrieval status
- Matching article details and relevance scores
- Matched article IDs
- Escalation requirement

The latest API result is saved to:

```text
data/agent2_output.json
```

### Technologies Used

- Python
- FastAPI
- Uvicorn
- Groq LLM
- Sentence Transformers (`all-MiniLM-L6-v2`)
- Scikit-learn
- JSON knowledge base

### How to run full workflow

- copy `env.example` to `.env` and set `GROQ_API_KEY` (the classifier reads `GROQ_API_KEY` / `GROQ_MODEL`).
- make sure that Knowledge retrival agent service is running

install node dependecies using

```
npm install
```

build using

```
npm run build
```

and then run

```
npm start
```

### Sample Queries

- My VPN keeps disconnecting repeatedly.
- The office air conditioning is not working.
- I need new software installed.
- I need to change the office seating layout.
- The VPN keeps disconnecting repeatedly for several employees.
- The office air conditioning keeps failing repeatedly.
- The payments API has been returning 500 errors since 10am and customers can't check out.
- Please upgrade the production Postgres cluster from v14 to v16 this Saturday night.
- Our VPN has dropped every week for a month. We suspect a firewall firmware bug and want to find the root cause.
