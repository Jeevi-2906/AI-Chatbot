"""
backend/chatbot.py - Gemini API Integration and Multi-Turn Conversation Manager.

Responsibilities:
1. Initialize the official Google GenAI SDK client.
2. Define the educational system prompt.
3. Maintain in-memory conversation histories for distinct conversation IDs.
4. Prepare multi-turn context and communicate with Gemini API with retry resilience.
5. Return AI-generated responses and cleanly manage errors.
"""

import os
import sys
import time
from typing import Dict, List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError, ServerError

# Ensure terminal stdout uses UTF-8 encoding on Windows consoles
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables from .env
load_dotenv()

# System prompt establishing a friendly educational AI assistant persona
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


def get_gemini_client() -> genai.Client:
    """
    Retrieve the Gemini API key from environment variables and initialize
    the official Google GenAI SDK client.
    
    Raises:
        ValueError: If GEMINI_API_KEY is missing or contains placeholder text.
    """
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
    Default: 'gemini-2.5-flash'
    """
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()


def get_or_create_conversation(conversation_id: str) -> List[Dict[str, str]]:
    """Retrieve existing conversation history or initialize a new one."""
    if conversation_id not in conversations:
        conversations[conversation_id] = []
    return conversations[conversation_id]


def clear_conversation(conversation_id: str) -> bool:
    """Clear conversation history for a given conversation_id."""
    if conversation_id in conversations:
        conversations[conversation_id] = []
        return True
    return False


def build_gemini_contents(history: List[Dict[str, str]]) -> List[types.Content]:
    """
    Convert stored conversation history into Gemini SDK types.Content objects.
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
    max_retries: int = 3,
    initial_delay: float = 1.5
) -> str:
    """
    Send a user message within a multi-turn conversation to the Gemini API.

    Features:
    1. Validates non-empty input and retrieves conversation memory.
    2. Temporarily appends user message to history.
    3. Translates history into Gemini Content structures.
    4. Attaches educational system prompt.
    5. Retries on transient server/availability spikes (503/429) with exponential backoff.
    6. On success: stores assistant reply and returns response text.
    7. On failure: cleanly rolls back the pending user message to preserve history integrity.

    Args:
        conversation_id: Unique identifier for the conversation session.
        user_message: The text submitted by the user.
        max_retries: Number of retry attempts for transient server spikes.
        initial_delay: Seconds to delay before the first retry attempt.

    Returns:
        The model's text response.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        raise ValueError("Message cannot be empty.")

    history = get_or_create_conversation(conversation_id)

    # 1. Temporarily append user message to local history
    history.append({"role": "user", "content": clean_message})

    client = get_gemini_client()
    model_name = get_model_name()

    # 2. Build contents payload from history
    gemini_contents = build_gemini_contents(history)

    # 3. Configure system instruction
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.7,
    )

    last_exception: Optional[Exception] = None
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=gemini_contents,
                config=config,
            )

            reply_text = (response.text or "").strip()
            if not reply_text:
                reply_text = "I received your message, but no response was generated."

            # 4. Successfully received response: append assistant message
            history.append({"role": "assistant", "content": reply_text})
            return reply_text

        except (ServerError, APIError) as e:
            last_exception = e
            # If server indicates high demand (503) or rate limit (429), retry with backoff
            status_code = getattr(e, "code", None) or getattr(e, "status_code", 500)
            if attempt < max_retries and status_code in (429, 503, 500):
                time.sleep(delay)
                delay *= 2
                continue
            break
        except Exception as e:
            last_exception = e
            break

    # If all attempts fail, revert the uncommitted user message
    if history and history[-1]["role"] == "user":
        history.pop()

    if isinstance(last_exception, APIError):
        raise RuntimeError(f"Gemini API Error ({last_exception.code}): {last_exception.message}") from last_exception
    raise RuntimeError(f"Failed to generate response: {str(last_exception)}") from last_exception


if __name__ == "__main__":
    import uuid

    print("=" * 60)
    print("PHASE 3 TEST: Multi-Turn Conversation Memory Verification")
    print(f"Model: {get_model_name()}")
    print("=" * 60)

    test_cid = f"test-conv-{uuid.uuid4().hex[:6]}"
    conversation_turns = [
        "My name is Jeevika.",
        "I am studying Artificial Intelligence.",
        "What is my name and what am I studying?"
    ]

    for turn_num, user_turn in enumerate(conversation_turns, start=1):
        print(f"\n[Turn {turn_num}] User: {user_turn}")
        try:
            bot_reply = send_chat_message(test_cid, user_turn)
            print(f"[Turn {turn_num}] Bot:\n{bot_reply}")
        except Exception as ex:
            print(f"[Turn {turn_num} Error]: {ex}")
            break

    print("\nRecorded In-Memory Conversation History:")
    for m in conversations[test_cid]:
        print(f" - {m['role'].upper()}: {m['content']}")
