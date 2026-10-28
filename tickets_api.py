from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

import tickets

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketInput(BaseModel):
    category: str = Field(description="incident, change, or problem")
    domain: str = Field(description="IT or non-IT")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    request: str = Field(
        default="", description="The user's original wording"
    )
    priority: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TicketUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None
    resolution: str | None = None
    comment: str | None = None


def _store(request: Request) -> tickets.TicketStore:
    return request.app.state.tickets


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, tickets.TicketNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (tickets.InvalidUpdate, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.post("/find-or-create")
def find_or_create(
    data: TicketInput, request: Request, response: Response
):
    """Attach to a similar open ticket, or create a new one."""
    try:
        result = tickets.find_or_create(
            _store(request),
            request.app.state.model,
            **data.model_dump(),
        )
    except (ValueError, tickets.TicketError) as exc:
        raise _translate(exc) from exc

    response.status_code = 201 if result["created"] else 200
    return result


@router.post("", status_code=201)
def create_ticket(data: TicketInput, request: Request):
    """Create a ticket without the duplicate check."""
    try:
        return _store(request).create(**data.model_dump())
    except (ValueError, tickets.TicketError) as exc:
        raise _translate(exc) from exc


@router.get("")
def list_tickets(
    request: Request,
    status: str | None = None,
    category: str | None = None,
    domain: str | None = None,
    limit: int = 100,
):
    try:
        return _store(request).list_tickets(status, category, domain, limit)
    except (ValueError, tickets.TicketError) as exc:
        raise _translate(exc) from exc


@router.get("/{number}")
def get_ticket(number: str, request: Request):
    ticket = _store(request).get(number)

    if ticket is None:
        raise HTTPException(
            status_code=404, detail=f"Ticket {number} not found."
        )

    return ticket


@router.patch("/{number}")
def update_ticket(number: str, data: TicketUpdate, request: Request):
    try:
        return _store(request).update(number, **data.model_dump())
    except (ValueError, tickets.TicketError) as exc:
        raise _translate(exc) from exc
