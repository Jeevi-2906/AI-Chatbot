"""
backend/chatbot.py - Gemini API Integration and Multi-Turn Conversation Manager.

Responsibilities:
1. Initialize the official Google GenAI SDK client.
2. Define the educational system prompt.
3. Maintain in-memory conversation histories for distinct conversation IDs.
4. Implement Context Window Management using Last-N-Message Truncation.
5. Prepare multi-turn context and communicate with Gemini API with robust error handling.
6. Return AI-generated responses while protecting security and credentials.
"""

import os
import sys
import time
from typing import Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

# Ensure terminal stdout uses UTF-8 encoding on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables from .env
load_dotenv(override=True)

# System prompt establishing a friendly educational AI assistant persona.
# Kept separate from ordinary conversation turns and injected via GenerateContentConfig.
SYSTEM_PROMPT = """You are a friendly, encouraging, and knowledgeable educational AI assistant.
Your goal is to help beginners understand programming, computer science, and Artificial Intelligence concepts.

Guidelines:
1. Explain technical concepts in clear, simple, and beginner-friendly language without condescension.
2. Provide practical, illustrative code or real-world examples whenever explaining abstract concepts.
3. Actively use conversation context to answer follow-up questions accurately.
4. Do not invent facts or make up information. If you are unsure or if something is beyond the current context, honestly state so.
5. Keep responses structured, concise, and easy to read (use short paragraphs, bullet points, or code blocks where helpful).
"""

# In-memory store for conversations:
# Key: conversation_id (str)
# Value: list of message dicts [{"role": "user"|"assistant", "content": "..."}]
conversations: Dict[str, List[Dict[str, str]]] = {}

# Metadata for conversations (title, timestamps) to support Past Chats list
conversation_metadata: Dict[str, Dict] = {}


def get_gemini_client(custom_key: Optional[str] = None) -> genai.Client:
    """
    Retrieve the Gemini API key from environment variables and initialize
    the official Google GenAI SDK client.
    
    Args:
        custom_key: Optional API key override (used for testing invalid key handling).
        
    Raises:
        ValueError: If GEMINI_API_KEY is missing or contains placeholder text.
    """
    if custom_key is not None:
        api_key = custom_key.strip()
    else:
        # Reload environment to automatically pick up any edits to .env
        load_dotenv(override=True)
        api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key or api_key == "your_gemini_api_key_here":
        raise ValueError(
            "GEMINI_API_KEY is not configured in your .env file.\n"
            "Please obtain an API key from Google AI Studio (https://aistudio.google.com/) "
            "and save it in your .env file: GEMINI_API_KEY=your_actual_key"
        )
    return genai.Client(api_key=api_key)


def get_model_name() -> str:
    """
    Retrieve configured Gemini model name with fallback.
    Default: 'gemini-flash-lite-latest'
    """
    load_dotenv(override=True)
    return os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()


def get_max_history_messages() -> int:
    """
    Retrieve the maximum number of recent messages to retain in the API context window.
    Default: 6 messages (3 complete user-assistant interaction pairs).
    """
    try:
        load_dotenv(override=True)
        val = int(os.getenv("MAX_HISTORY_MESSAGES", 6))
        return val if val > 0 else 6
    except (ValueError, TypeError):
        return 6


def get_or_create_conversation(conversation_id: str) -> List[Dict[str, str]]:
    """Retrieve existing conversation history or initialize a new one."""
    if conversation_id not in conversations:
        conversations[conversation_id] = []
    return conversations[conversation_id]


def clear_conversation(conversation_id: str) -> bool:
    """Clear conversation history for a given conversation_id."""
    if conversation_id in conversations:
        conversations[conversation_id] = []
        conversation_metadata.pop(conversation_id, None)
        return True
    return False


def delete_conversation(conversation_id: str) -> bool:
    """Permanently delete a conversation from memory."""
    conversations.pop(conversation_id, None)
    conversation_metadata.pop(conversation_id, None)
    return True


def get_all_conversations() -> List[Dict]:
    """Return a list of all active conversations with metadata, sorted by recent activity."""
    result = []
    for cid, history in conversations.items():
        if not history:
            continue
        meta = conversation_metadata.get(cid, {})
        first_user_msg = next((m["content"] for m in history if m["role"] == "user"), "Conversation")
        title = meta.get("title") or (first_user_msg[:32] + ("..." if len(first_user_msg) > 32 else ""))
        result.append({
            "conversation_id": cid,
            "title": title,
            "message_count": len(history),
            "created_at": meta.get("created_at", 0),
            "updated_at": meta.get("updated_at", 0),
        })
    result.sort(key=lambda x: x["updated_at"], reverse=True)
    return result


def truncate_history(history: List[Dict[str, str]], max_messages: Optional[int] = None) -> List[Dict[str, str]]:
    """
    CONTEXT WINDOW MANAGEMENT: Last-N-Message Truncation Strategy.

    How Truncation Works:
    --------------------
    1. Large Language Models have context limits and charge tokens for every message sent.
       As conversations grow arbitrarily long, sending unlimited history wastes tokens,
       increases latency, and can exceed model context limits.
    2. We retain the FULL conversation history in application memory (for auditing / UI),
       but slice only the most recent `N` messages to transmit to the Gemini API.
    3. Complete Turn Pair Preservation:
       If a naive slice `history[-N:]` begins with an 'assistant' message, that assistant
       reply would be orphaned (lacking its matching user question).
       Gemini multi-turn dialogs must begin with a 'user' turn.
       Therefore, if the first message in the sliced window is an 'assistant' role,
       we drop that leading message so the truncated window always starts cleanly with
       a 'user' turn.
    4. The current user prompt is guaranteed to be the final element in the truncated window.
    5. The system prompt remains separate and is not counted against this message limit.

    Args:
        history: The complete list of conversation turns.
        max_messages: Maximum recent messages to retain. Defaults to MAX_HISTORY_MESSAGES.

    Returns:
        A pruned list of message dictionaries ready for API transmission.
    """
    if max_messages is None:
        max_messages = get_max_history_messages()

    if not history or len(history) <= max_messages:
        # Full history fits within context window
        return list(history)

    # 1. Take the last N messages
    truncated = list(history[-max_messages:])

    # 2. Preserve message pair integrity:
    # A valid multi-turn conversation sequence should start with a 'user' message.
    # If our slice starts with an orphaned 'assistant' response, strip it.
    if truncated and truncated[0].get("role") == "assistant":
        truncated = truncated[1:]

    return truncated


def build_gemini_contents(history: List[Dict[str, str]]) -> List[types.Content]:
    """
    Convert a list of message dicts into Gemini SDK types.Content objects.
    Maps internal role 'assistant' to Gemini API role 'model'.
    """
    contents: List[types.Content] = []
    for turn in history:
        gemini_role = "model" if turn["role"] == "assistant" else "user"
        contents.append(
            types.Content(
                role=gemini_role,
                parts=[types.Part.from_text(text=turn["content"])]
            )
        )
    return contents


def send_chat_message(
    conversation_id: str,
    user_message: str,
    api_key_override: Optional[str] = None,
    max_history: Optional[int] = None,
    max_retries: int = 3
) -> str:
    """
    Send a user message within a multi-turn conversation to the Gemini API.

    Workflow:
    1. Validates non-empty input and retrieves full conversation history.
    2. Appends the user's latest message to in-memory history.
    3. Applies Last-N-Message Truncation with the configured or requested N limit.
    4. Translates the truncated window into Gemini Content structures.
    5. Attaches the educational system prompt via GenerateContentConfig.
    6. Sends request to Gemini API (with automatic retry for transient 429/503 spikes).
    7. On success: stores the assistant reply in full history and updates metadata.
    8. On failure: cleanly rolls back the user message to prevent history corruption.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        raise ValueError("Message cannot be empty.")

    history = get_or_create_conversation(conversation_id)

    # 1. Temporarily append user message to local history
    history.append({"role": "user", "content": clean_message})

    # Track conversation metadata for the "Past Chats" history panel
    now = time.time()
    if conversation_id not in conversation_metadata:
        preview = clean_message[:35] + ("..." if len(clean_message) > 35 else "")
        conversation_metadata[conversation_id] = {
            "title": preview,
            "created_at": now,
            "updated_at": now
        }
    else:
        conversation_metadata[conversation_id]["updated_at"] = now

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            client = get_gemini_client(custom_key=api_key_override)
            model_name = get_model_name()

            # 2. Apply Last-N-Message truncation (using requested N or .env MAX_HISTORY_MESSAGES)
            effective_n = max_history if (max_history is not None and max_history > 0) else None
            truncated_context = truncate_history(history, max_messages=effective_n)

            # 3. Build contents payload from the truncated context window
            gemini_contents = build_gemini_contents(truncated_context)

            # 4. Configure system instruction
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.7,
            )

            response = client.models.generate_content(
                model=model_name,
                contents=gemini_contents,
                config=config,
            )

            reply_text = (response.text or "").strip()
            if not reply_text:
                reply_text = "I received your message, but no response text was generated."

            # 5. Successfully received response: append assistant message
            history.append({"role": "assistant", "content": reply_text})
            conversation_metadata[conversation_id]["updated_at"] = time.time()
            return reply_text

        except (ClientError, ServerError, APIError) as e:
            last_error = e
            status_code = getattr(e, "code", None) or getattr(e, "status_code", 500)
            
            # If transient rate limit or service busy, pause briefly and retry
            if status_code in (429, 503) and attempt < max_retries and api_key_override is None:
                time.sleep(3.0 * attempt)
                continue
            break

        except Exception as e:
            last_error = e
            break

    # If all attempts fail, revert the uncommitted user message
    if history and history[-1]["role"] == "user":
        history.pop()

    if isinstance(last_error, (ClientError, ServerError, APIError)):
        status_code = getattr(last_error, "code", None) or getattr(last_error, "status_code", 500)
        if status_code in (400, 401, 403):
            raise RuntimeError("Authentication failed: Invalid or unauthorized Gemini API key.") from last_error
        elif status_code == 429:
            raise RuntimeError("Rate limit or quota exceeded for Gemini API. Please retry shortly.") from last_error
        elif status_code in (503, 500):
            raise RuntimeError("Gemini API is temporarily busy or experiencing high demand. Please try again.") from last_error
        else:
            raise RuntimeError(f"Gemini API request failed ({status_code}).") from last_error

    raise RuntimeError(f"Failed to communicate with AI model: {str(last_error)}") from last_error
