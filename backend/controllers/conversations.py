from fastapi import APIRouter, Depends, Query, Response

from backend.dependencies import api_key_header, current_owner, get_chat_service
from backend.schemas import ChatReply, ConversationCreate, ConversationDetail, ConversationOut, ConversationPage, MessageCreate
from backend.services.chat_service import ChatService

router = APIRouter(prefix="/api/conversations", tags=["conversations"], dependencies=[Depends(api_key_header)])


@router.post("", status_code=201, response_model=ConversationOut)
def create_conversation(body: ConversationCreate, response: Response,
                        owner: int = Depends(current_owner), service: ChatService = Depends(get_chat_service)):
    """Start a new chat with Jarvis."""
    conversation = service.create(owner, body.title)
    response.headers["Location"] = f"/api/conversations/{conversation['id']}"  # REST: where the new resource lives
    return dict(conversation)


@router.get("", response_model=ConversationPage)
def list_conversations(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                       owner: int = Depends(current_owner), service: ChatService = Depends(get_chat_service)):
    """Your chats, most recently used first. Use limit and offset to page through them."""
    rows, total = service.list(owner, limit, offset)
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, owner: int = Depends(current_owner),
                     service: ChatService = Depends(get_chat_service)):
    """One chat with all its messages."""
    conversation, messages = service.get(owner, conversation_id)
    return {**dict(conversation), "messages": [dict(m) for m in messages]}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, owner: int = Depends(current_owner),
                        service: ChatService = Depends(get_chat_service)):
    """Delete a chat and all its messages."""
    service.delete(owner, conversation_id)
    return Response(status_code=204)


@router.post("/{conversation_id}/messages", status_code=201, response_model=ChatReply)
def send_message(conversation_id: int, body: MessageCreate, owner: int = Depends(current_owner),
                 service: ChatService = Depends(get_chat_service)):
    """Ask Jarvis something. It remembers the earlier messages of this chat, can use its
    tools (weather, Wikipedia, calculator, currency...) and can search your PDFs."""
    question, reply, from_cache = service.send_message(owner, conversation_id, body.content)
    return {"conversation_id": conversation_id, "question": dict(question), "reply": dict(reply),
            "from_cache": from_cache}
