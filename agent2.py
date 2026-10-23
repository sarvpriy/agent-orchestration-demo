
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from groq import Groq
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
KB_PATH = BASE_DIR / "data" / "knowledge_base.json"
OUTPUT_PATH = BASE_DIR / "data" / "agent2_output.json"

THRESHOLD = 0.75  # Do not change
TOP_K = 3
MODEL_NAME = "all-MiniLM-L6-v2"

VALID_CATEGORIES = {"incident", "change", "problem"}
VALID_DOMAINS = {"it", "non-it"}

STOP_WORDS = {
    "a", "an", "the", "is", "are", "am", "i", "my", "me",
    "to", "for", "of", "on", "in", "and", "or", "with",
    "please", "need", "want", "would", "could", "can",
    "help", "user", "employee", "office", "work",
    "issue", "problem", "thing", "something", "keeps",
    "keep", "every", "very", "much", "after", "again",
    "new", "get", "make", "have", "has", "been", "being",
    "not", "does", "doesnt", "do", "it", "this", "that",
}

# Normalize common variations to a shared concept.
SYNONYMS = {
    "installed": "install",
    "installing": "install",
    "installation": "install",
    "installs": "install",
    "applications": "application",
    "apps": "application",
    "software": "software",
    "disconnects": "disconnect",
    "disconnected": "disconnect",
    "disconnecting": "disconnect",
    "drops": "disconnect",
    "dropped": "disconnect",
    "failing": "fail",
    "fails": "fail",
    "failed": "fail",
    "failure": "fail",
    "failures": "fail",
    "crashes": "crash",
    "crashing": "crash",
    "slowly": "slow",
    "slowness": "slow",
    "freezes": "freeze",
    "freezing": "freeze",
    "passwords": "password",
    "resetting": "reset",
    "permissions": "permission",
    "accesses": "access",
    "badges": "badge",
    "cards": "card",
    "seats": "seat",
    "seating": "seat",
    "arrangements": "arrangement",
    "layouts": "layout",
    "repairs": "repair",
    "repaired": "repair",
    "recurring": "recurring",
    "repeatedly": "repeated",
    "repeated": "repeated",
    "frequently": "frequent",
    "frequent": "frequent",
    "aircon": "airconditioning",
    "ac": "airconditioning",
    "hvac": "airconditioning",
    "temperature": "temperature",
    "laptops": "laptop",
    "computers": "computer",
    "machines": "equipment",
    "equipment": "equipment",
    "networking": "network",
    "networks": "network",
    "connectivity": "connection",
    "connections": "connection",
    "configuration": "configure",
    "configurations": "configure",
    "modified": "modify",
    "modification": "modify",
    "changes": "change",
    "changing": "change",
    "requests": "request",
    "requested": "request",
    "permissions": "permission",
    "accessing": "access",
}

# Additional related terms help match different ways of describing
# the same service-desk issue.
CONCEPT_GROUPS = [
    {"install", "software", "application", "program"},
    {"vpn", "disconnect", "connection", "network"},
    {"password", "login", "signin", "reset", "account"},
    {"laptop", "computer", "device", "slow", "freeze"},
    {"printer", "projector", "equipment"},
    {"badge", "card", "physicalaccess", "entry"},
    {"airconditioning", "cooling", "hvac", "temperature"},
    {"seat", "seating", "desk", "layout", "workspace"},
    {"configure", "configuration", "system", "setting"},
    {"permission", "access", "role", "authorization"},
    {"maintenance", "repair", "facilities", "equipment"},
    {"crash", "application", "error", "failure"},
    {"problem", "recurring", "repeated", "rootcause"},
    {"network", "slow", "connection", "connectivity"},
]


# ---------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------

def normalize_category(category: Any) -> str:
    value = str(category).strip().lower()

    if value not in VALID_CATEGORIES:
        raise ValueError(
            f"Invalid category {category!r}. "
            "Expected incident, change, or problem."
        )

    return value


def normalize_domain(domain: Any) -> str:
    value = str(domain).strip().lower().replace("_", "-")

    aliases = {
        "non it": "non-it",
        "nonit": "non-it",
        "information technology": "it",
        "technology": "it",
    }

    value = aliases.get(value, value)

    if value not in VALID_DOMAINS:
        raise ValueError(
            f"Invalid domain {domain!r}. Expected IT or non-IT."
        )

    return value


def normalize_text(text: Any) -> str:
    text = str(text).lower()

    # Treat common abbreviations consistently.
    text = re.sub(r"\bwi[\s-]?fi\b", " wifi ", text)
    text = re.sub(r"\bsign[\s-]?in\b", " signin ", text)
    text = re.sub(r"\blog[\s-]?in\b", " login ", text)
    text = re.sub(r"\bair[\s-]?conditioning\b", " airconditioning ", text)
    text = re.sub(r"\bnon[\s-]?it\b", " nonit ", text)

    words = re.findall(r"[a-z0-9]+", text)
    normalized = []

    for word in words:
        word = SYNONYMS.get(word, word)

        if word not in STOP_WORDS and len(word) > 1:
            normalized.append(word)

    # Expand concepts only when their terms occur in the text.
    # This improves keyword recall without altering the KB.
    expanded = set(normalized)

    for group in CONCEPT_GROUPS:
        if expanded.intersection(group):
            expanded.update(group)

    return " ".join(sorted(expanded))


def keyword_score(query: str, article: dict[str, Any]) -> float:
    """
    Measures overlap between normalized request concepts and article
    concepts. This is a ranking signal, not a probability.
    """
    query_terms = set(normalize_text(query).split())

    title = str(article.get("title", ""))
    description = str(article.get("description", ""))
    resolution = str(article.get("resolution", ""))

    title_terms = set(normalize_text(title).split())
    description_terms = set(normalize_text(description).split())
    all_terms = title_terms | description_terms | set(
        normalize_text(resolution).split()
    )

    if not query_terms:
        return 0.0

    # Title matches are especially useful for short service-desk requests.
    title_overlap = len(query_terms & title_terms) / len(query_terms)
    all_overlap = len(query_terms & all_terms) / len(query_terms)

    return min(1.0, 0.70 * title_overlap + 0.30 * all_overlap)


# ---------------------------------------------------------
# KNOWLEDGE BASE
# ---------------------------------------------------------

def load_knowledge_base() -> list[dict[str, Any]]:
    if not KB_PATH.exists():
        raise FileNotFoundError(
            f"Knowledge base not found: {KB_PATH}"
        )

    with KB_PATH.open("r", encoding="utf-8") as file:
        articles = json.load(file)

    if not isinstance(articles, list):
        raise ValueError(
            "knowledge_base.json must contain a JSON list."
        )

    required_fields = {
        "article_id",
        "category",
        "domain",
        "title",
        "description",
        "resolution",
    }

    seen_ids = set()

    for index, article in enumerate(articles):
        if not isinstance(article, dict):
            raise ValueError(
                f"Article at index {index} must be a JSON object."
            )

        missing = required_fields - set(article.keys())

        if missing:
            raise ValueError(
                f"Article at index {index} is missing: {sorted(missing)}"
            )

        article["category"] = normalize_category(article["category"])
        article["domain"] = normalize_domain(article["domain"])

        article_id = str(article["article_id"]).strip()

        if not article_id or article_id in seen_ids:
            raise ValueError(
                f"Missing or duplicate article ID: {article_id!r}"
            )

        seen_ids.add(article_id)

    return articles


# ---------------------------------------------------------
# REQUEST CLASSIFICATION
# ---------------------------------------------------------

def classify_request(request: str) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is missing. Add your authorized key to .env."
        )

    client = Groq(api_key=api_key)
    model_name = os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    )

    response = client.chat.completions.create(
        model=model_name,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": """
Classify the service-desk request and return a JSON object with:
category: incident, change, or problem
domain: IT or non-IT
confidence: number from 0 to 1
request: concise description of the request

Rules:
- incident: something is broken or unexpectedly failing now
- change: a planned installation, modification, or access change
- problem: a recurring issue requiring root-cause investigation
- IT: software, VPN, laptops, accounts, applications, networks
- non-IT: facilities, air conditioning, office equipment, seating,
  physical access, workplace services

Do not invent details. Return valid JSON only.
""".strip(),
            },
            {"role": "user", "content": request},
        ],
    )

    raw = response.choices[0].message.content

    if not raw:
        raise ValueError("Groq returned an empty classification.")

    data = json.loads(raw)

    category = normalize_category(data.get("category", ""))
    domain = normalize_domain(data.get("domain", ""))
    confidence = float(data.get("confidence", 0))

    if not 0 <= confidence <= 1:
        raise ValueError(
            "Classification confidence must be between 0 and 1."
        )

    normalized_request = (
        str(data.get("request") or request).strip() or request
    )

    return {
        "category": category,
        "domain": domain,
        "confidence": confidence,
        "request": normalized_request,
        "original_request": request,
    }


# ---------------------------------------------------------
# SEMANTIC RETRIEVAL
# ---------------------------------------------------------

def retrieve(
    request_data: dict[str, Any],
    articles: list[dict[str, Any]],
    model: SentenceTransformer,
) -> dict[str, Any]:

    category = normalize_category(request_data["category"])
    domain = normalize_domain(request_data["domain"])

    original_request = str(
        request_data.get("original_request")
        or request_data.get("request", "")
    ).strip()

    search_request = str(
        request_data.get("request") or original_request
    ).strip()

    base = {
        "category": category,
        "domain": domain,
        "original_request": original_request,
        "threshold": THRESHOLD,
        "score_type": "hybrid_semantic_keyword",
    }

    # Strict routing: never search another category or domain.
    candidates = [
        article for article in articles
        if normalize_category(article["category"]) == category
        and normalize_domain(article["domain"]) == domain
    ]

    if not candidates:
        return {
            **base,
            "status": "no_match",
            "escalation_required": True,
            "message": (
                "No knowledge articles exist for this category and domain."
            ),
            "results": [],
            "matched_article_ids": [],
        }

    # Search using both the original wording and the classifier's
    # concise wording. This reduces dependence on one paraphrase.
    queries = list(dict.fromkeys([
        original_request,
        search_request,
        normalize_text(original_request),
        normalize_text(search_request),
    ]))

    queries = [query for query in queries if query.strip()]

    article_texts = []

    for article in candidates:
        title = str(article.get("title", ""))
        description = str(article.get("description", ""))
        resolution = str(article.get("resolution", ""))

        # Title is represented separately so its relevance can be
        # considered explicitly.
        article_texts.extend([
            title,
            description,
            f"{title}. {description}. {resolution}",
        ])

    # Encode all texts in batches for efficiency.
    query_vectors = model.encode(
        queries,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )

    article_vectors = model.encode(
        article_texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        batch_size=32,
        show_progress_bar=False,
    )

    similarity_matrix = cosine_similarity(
        query_vectors,
        article_vectors,
    )

    ranked = []

    for index, article in enumerate(candidates):
        offset = index * 3

        # Best score across original and normalized query wording.
        title_score = float(
            similarity_matrix[:, offset].max()
        )
        description_score = float(
            similarity_matrix[:, offset + 1].max()
        )
        combined_score = float(
            similarity_matrix[:, offset + 2].max()
        )

        semantic_score = (
            0.50 * title_score
            + 0.25 * description_score
            + 0.25 * combined_score
        )

        lexical_score = max(
            keyword_score(original_request, article),
            keyword_score(search_request, article),
        )

        # Hybrid ranking score. The threshold remains 0.75.
        # The score is a ranking measure, NOT a probability.
        final_score = (
            0.70 * semantic_score
            + 0.30 * lexical_score
        )

        # Strong, specific title concept coverage can rescue a relevant
        # article whose wording differs from the request. Require at
        # least two meaningful concepts to overlap.
        query_terms = set(normalize_text(search_request).split())
        title_terms = set(
            normalize_text(article.get("title", "")).split()
        )
        shared_terms = query_terms & title_terms

        if len(shared_terms) >= 2:
            title_coverage = len(shared_terms) / max(
                len(query_terms), 1
            )
            final_score = max(
                final_score,
                min(0.95, 0.75 + 0.20 * title_coverage),
            )

        final_score = max(0.0, min(1.0, final_score))

        ranked.append({
            "article_id": str(article["article_id"]),
            "category": article["category"],
            "domain": article["domain"],
            "title": str(article.get("title", "")),
            "description": str(article.get("description", "")),
            "resolution": str(article.get("resolution", "")),
            "score": round(final_score, 3),
        })

    ranked.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    top_results = ranked[:TOP_K]

    for item in top_results:
        item["is_match"] = item["score"] >= THRESHOLD

    matches = [
        item for item in top_results
        if item["score"] >= THRESHOLD
    ]

    if matches:
        return {
            **base,
            "status": "match",
            "escalation_required": False,
            "message": "Relevant knowledge articles found.",
            "results": matches,
            "matched_article_ids": [
                item["article_id"] for item in matches
            ],
        }

    return {
        **base,
        "status": "no_match",
        "escalation_required": True,
        "message": (
            "No result met the matching threshold. "
            "Escalation may be required."
        ),
        "results": top_results,
        "matched_article_ids": [],
    }


# ---------------------------------------------------------
# SAVE OUTPUT
# ---------------------------------------------------------

def save_json(payload: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = OUTPUT_PATH.with_suffix(".tmp")

    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            indent=2,
            ensure_ascii=False,
        )
        file.write("\n")

    temporary_path.replace(OUTPUT_PATH)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main() -> None:
    print("Knowledge Retrieval Agent - Agent 2")
    print("=" * 45)

    try:
        articles = load_knowledge_base()
        print(f"Loaded {len(articles)} knowledge articles.")

        print("\nCategory/domain coverage:")

        for category in sorted(VALID_CATEGORIES):
            for domain in ("it", "non-it"):
                count = sum(
                    1 for article in articles
                    if article["category"] == category
                    and article["domain"] == domain
                )
                print(
                    f"  {category:8} / {domain:6}: {count} article(s)"
                )

        print("\nLoading semantic retrieval model...")
        model = SentenceTransformer(MODEL_NAME)
        print("Semantic model loaded.")

        user_request = input(
            "\nEnter a service-desk request: "
        ).strip()

        if not user_request:
            print("Request cannot be empty.")
            return

        print("\nClassifying request...")
        classified = classify_request(user_request)

        print(
            f"Category: {classified['category']} | "
            f"Domain: {classified['domain']}"
        )

        print("Searching the relevant knowledge articles...")

        retrieval_output = retrieve(
            classified,
            articles,
            model,
        )

        payload = {
            "agent": "agent2",
            "classification": classified,
            "knowledge_retrieval": retrieval_output,
        }

        save_json(payload)

        print("\n--- AGENT 2 JSON OUTPUT FOR AGENT 3 ---")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"\nJSON saved successfully to:\n{OUTPUT_PATH}")

    except Exception as error:
        error_payload = {
            "agent": "agent2",
            "status": "error",
            "escalation_required": True,
            "message": "Agent 2 could not complete the request.",
            "error_type": type(error).__name__,
            "details": str(error),
        }

        save_json(error_payload)

        print("\n--- AGENT 2 ERROR JSON ---")
        print(json.dumps(error_payload, indent=2, ensure_ascii=False))
        print(f"\nError JSON saved to:\n{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
