"""
backend/chatbot.py - Gemini API Integration and Multi-Turn Conversation Manager.

Responsibilities:
1. Initialize the official Google GenAI SDK client.
2. Define the educational system prompt.
3. Maintain in-memory conversation histories for distinct conversation IDs.
4. Implement Context Window Management using Last-N-Message Truncation.
5. Prepare multi-turn context and communicate with Gemini API with retry resilience.
6. Return AI-generated responses and cleanly manage errors.
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

# System prompt establishing a friendly educational AI assistant persona.
# NOTE: The system prompt is kept separate from ordinary conversation turns
# and is injected via GenerateContentConfig on every request.
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
    # Reload environment to automatically pick up any edits to .env without requiring server restart
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
    Default: 'gemini-3-flash-preview'
    """
    load_dotenv(override=True)
    return os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()


def get_max_history_messages() -> int:
    """
    Retrieve the maximum number of recent messages to retain in the API context window.
    Default: 6 messages (e.g. 3 user-assistant interaction pairs).
    """
    try:
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
        return True
    return False


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
    max_retries: int = 3,
    initial_delay: float = 1.5
) -> str:
    """
    Send a user message within a multi-turn conversation to the Gemini API.

    Workflow:
    1. Validates non-empty input and retrieves full conversation history.
    2. Appends the user's latest message to in-memory history.
    3. Applies Last-N-Message Truncation to select only the recent context window.
    4. Translates the truncated window into Gemini Content structures.
    5. Attaches the educational system prompt via GenerateContentConfig.
    6. Sends request to Gemini API (with exponential backoff on 503/429 spikes).
    7. On success: stores the assistant reply in full history and returns it.
    8. On failure: cleanly rolls back the user message to prevent corruption.
    """
    clean_message = (user_message or "").strip()
    if not clean_message:
        raise ValueError("Message cannot be empty.")

    history = get_or_create_conversation(conversation_id)

    # 1. Temporarily append user message to local history
    history.append({"role": "user", "content": clean_message})

    client = get_gemini_client()
    model_name = get_model_name()

    # 2. Apply Last-N-Message truncation for API request
    truncated_context = truncate_history(history)

    # 3. Build contents payload from the truncated context window
    gemini_contents = build_gemini_contents(truncated_context)

    # 4. Configure system instruction
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

            # 5. Successfully received response: append assistant message
            history.append({"role": "assistant", "content": reply_text})
            return reply_text

        except (ServerError, APIError) as e:
            last_exception = e
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
    print("=" * 65)
    print("PHASE 4: CONTEXT WINDOW TRUNCATION TEST")
    print(f"Configured MAX_HISTORY_MESSAGES: {get_max_history_messages()}")
    print("=" * 65)

    # Simulate a long conversation with 10 messages (5 user/assistant pairs)
    mock_history = [
        {"role": "user", "content": "Question 1: What is a variable?"},
        {"role": "assistant", "content": "Answer 1: A container for storing data."},
        {"role": "user", "content": "Question 2: What is a loop?"},
        {"role": "assistant", "content": "Answer 2: A structure that repeats code."},
        {"role": "user", "content": "Question 3: What is a function?"},
        {"role": "assistant", "content": "Answer 3: A reusable block of code."},
        {"role": "user", "content": "Question 4: What is recursion?"},
        {"role": "assistant", "content": "Answer 4: A function calling itself."},
        {"role": "user", "content": "Question 5: What is an algorithm?"},
        {"role": "assistant", "content": "Answer 5: A step-by-step problem-solving procedure."},
        {"role": "user", "content": "Question 6: What is AI?"}
    ]

    print(f"Total messages in full history: {len(mock_history)}")

    # Test truncation with limit of 4
    truncated_4 = truncate_history(mock_history, max_messages=4)
    print(f"\nTruncated to 4 messages (preserves pair integrity, starts with user):")
    for idx, msg in enumerate(truncated_4, 1):
        print(f"  {idx}. [{msg['role'].upper()}]: {msg['content']}")

    assert truncated_4[0]["role"] == "user", "Truncated window must start with user turn!"
    assert truncated_4[-1]["content"] == "Question 6: What is AI?", "Latest user message must be preserved!"
    print("\nTruncation unit test passed successfully!")
