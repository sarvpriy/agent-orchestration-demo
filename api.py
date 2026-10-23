from contextlib import asynccontextmanager
from pathlib import Path
import json

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

import agent2


# Load the knowledge base and embedding model once when the API starts.
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        app.state.articles = agent2.load_knowledge_base()
        app.state.model = SentenceTransformer("all-MiniLM-L6-v2")
        yield
    except Exception as exc:
        raise RuntimeError(
            "Agent 2 could not start. Check the knowledge-base file and dependencies."
        ) from exc


app = FastAPI(
    title="Service Desk Agent 2 API",
    description="Knowledge retrieval API for the Service Desk Agent Flow",
    version="1.0.0",
    lifespan=lifespan,
)


class Agent1Input(BaseModel):
    category: str = Field(
        description="Request category: incident, change, or problem"
    )
    domain: str = Field(
        description="Request domain: IT or non-IT"
    )
    request: str = Field(
        min_length=1,
        description="Request text from Agent 1"
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    original_request: str | None = None


class RawRequestInput(BaseModel):
    request: str = Field(min_length=1)


def process_retrieval(
    request_data: dict,
    articles: list,
    model
) -> dict:
    """Run Agent 2 retrieval and return its JSON result."""

    category = request_data.get("category", "").strip().lower()
    domain = request_data.get("domain", "").strip().lower()
    request_text = request_data.get("request", "").strip()

    if category not in {"incident", "change", "problem"}:
        raise HTTPException(
            status_code=422,
            detail="category must be incident, change, or problem"
        )

    if domain not in {"it", "non-it"}:
        raise HTTPException(
            status_code=422,
            detail="domain must be IT or non-IT"
        )

    if not request_text:
        raise HTTPException(
            status_code=422,
            detail="request cannot be empty"
        )

    # Normalize the values passed to the existing retrieval function.
    normalized_data = {
        "category": category,
        "domain": "IT" if domain == "it" else "non-it",
        "confidence": request_data.get("confidence", 0.0),
        "request": request_text,
        "original_request": (
            request_data.get("original_request") or request_text
        ),
    }

    try:
        retrieval_result = agent2.retrieve(
            normalized_data,
            articles,
            model
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Knowledge retrieval failed. Check the Agent 2 logs."
        ) from exc

    payload = {
        "agent": "agent2",
        "classification": normalized_data,
        "knowledge_retrieval": retrieval_result,
    }

    # Save the latest API result to the existing output location.
    output_path = Path(__file__).resolve().parent / "data" / "agent2_output.json"

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
    except OSError:
        # The API response can still be returned if saving the file fails.
        pass

    return payload


@app.get("/")
def home():
    return {
        "agent": "agent2",
        "status": "running",
        "message": "Knowledge Retrieval Agent API is available",
        "docs": "/docs"
    }


@app.get("/health")
def health(request: Request):
    return {
        "status": "ok",
        "agent": "agent2",
        "knowledge_base_articles": len(request.app.state.articles)
    }


@app.post("/retrieve")
def retrieve_from_agent1(data: Agent1Input, request: Request):
    """Accept Agent 1's classification and retrieve matching articles."""

    return process_retrieval(
        data.model_dump(),
        request.app.state.articles,
        request.app.state.model
    )


@app.post("/classify-and-retrieve")
def classify_and_retrieve(data: RawRequestInput, request: Request):
    """Convenience endpoint for testing Agent 2 with raw request text."""

    try:
        classification = agent2.classify_request(data.request.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Request classification failed. Check the Agent 2 configuration."
        ) from exc

    if not isinstance(classification, dict):
        raise HTTPException(
            status_code=500,
            detail="Agent 2 classification did not return a JSON object"
        )

    classification["request"] = (
        classification.get("request") or data.request.strip()
    )
    classification["original_request"] = data.request.strip()

    return process_retrieval(
        classification,
        request.app.state.articles,
        request.app.state.model
    )
