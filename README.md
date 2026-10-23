### How to run

- make sure the llm keys are added in the environment.
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

### Sample queries

- The payments API has been returning 500 errors since 10am and customers can't check out.
- Please upgrade the production Postgres cluster from v14 to v16 this Saturday night.
- Our VPN has dropped every week for a month. We suspect a firewall firmware bug and want to find the root cause.

# Knowledge Retrieval Agent (Agent 2)

## How to Run

- Make sure the LLM API key is configured in the `.env` file for request classification.
- Make sure the knowledge base file is available at `data/knowledge_base.json`.
- Make sure Python and the required dependencies are installed.

### Install Python Dependencies

Activate the virtual environment:

```bash
.venv\Scripts\activate
```

Install the required dependencies:

```bash
python -m pip install fastapi uvicorn sentence-transformers python-dotenv groq scikit-learn
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

### Sample Queries

- My VPN keeps disconnecting repeatedly.
- The office air conditioning is not working.
- I need new software installed.
- I need to change the office seating layout.
- The VPN keeps disconnecting repeatedly for several employees.
- The office air conditioning keeps failing repeatedly.

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
