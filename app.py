"""
app.py - Main Flask Application Server.

Routes:
- GET /                    : Serves the web-based chatbot frontend interface.
- GET /health              : Health-check endpoint for server status.
- POST /chat               : Main chat endpoint; processes user messages, manages
                             multi-turn conversation history, and calls Gemini API.
- POST /chat/reset         : Clears conversation history for a given conversation_id.
- GET /chat/history/<cid>  : Returns the current in-memory history for debugging/verification.
"""

import os
import uuid
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

from backend.chatbot import (
    send_chat_message,
    get_or_create_conversation,
    clear_conversation,
    get_model_name,
)

# Load environment variables
load_dotenv()

# Initialize Flask application
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-12345")


@app.route("/")
def index():
    """Render the main chatbot frontend interface."""
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint to verify backend server status and configured model."""
    return jsonify({
        "status": "ok",
        "message": "Flask server is up and running",
        "model": get_model_name()
    }), 200


@app.route("/chat", methods=["POST"])
def chat():
    """
    POST /chat endpoint.
    
    Expected JSON payload:
    {
        "message": "User text here",
        "conversation_id": "optional-or-existing-id"
    }
    
    Response JSON:
    {
        "response": "Gemini AI response here",
        "conversation_id": "active-conversation-id"
    }
    """
    # 1. Validate that the request has JSON content
    if not request.is_json:
        return jsonify({
            "error": "Invalid request: Content-Type must be application/json."
        }), 400

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid request: Expected a JSON object."
        }), 400

    # 2. Extract and validate user message
    user_message = data.get("message")
    if user_message is None or not isinstance(user_message, str) or not user_message.strip():
        return jsonify({
            "error": "Validation error: 'message' is required and cannot be empty."
        }), 400

    # 3. Retrieve or generate conversation_id
    conversation_id = data.get("conversation_id")
    if not conversation_id or not isinstance(conversation_id, str) or not conversation_id.strip():
        conversation_id = str(uuid.uuid4())
    else:
        conversation_id = conversation_id.strip()

    # 4. Communicate with Gemini API via conversation manager
    try:
        reply = send_chat_message(
            conversation_id=conversation_id,
            user_message=user_message.strip()
        )
        return jsonify({
            "response": reply,
            "conversation_id": conversation_id
        }), 200

    except ValueError as ve:
        # Client validation or configuration error (e.g. missing API key)
        return jsonify({
            "error": str(ve),
            "conversation_id": conversation_id
        }), 400

    except RuntimeError as re:
        # API execution or upstream server errors
        return jsonify({
            "error": str(re),
            "conversation_id": conversation_id
        }), 502

    except Exception as e:
        # Uncaught server errors (never leak stack trace)
        return jsonify({
            "error": "An unexpected internal server error occurred. Please try again.",
            "conversation_id": conversation_id
        }), 500


@app.route("/chat/reset", methods=["POST"])
def reset_chat():
    """
    POST /chat/reset endpoint to clear conversation history.
    
    Expected JSON:
    {
        "conversation_id": "conversation-to-reset"
    }
    """
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json."}), 400

    data = request.get_json(silent=True) or {}
    conversation_id = data.get("conversation_id", "").strip()

    if not conversation_id:
        return jsonify({"error": "Missing conversation_id to reset."}), 400

    clear_conversation(conversation_id)
    return jsonify({
        "status": "cleared",
        "conversation_id": conversation_id,
        "message": "Conversation history has been reset successfully."
    }), 200


@app.route("/chat/history/<cid>", methods=["GET"])
def get_history(cid: str):
    """Debug route to inspect recorded conversation history for a given conversation_id."""
    history = get_or_create_conversation(cid)
    return jsonify({
        "conversation_id": cid,
        "message_count": len(history),
        "history": history
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    print(f"Starting Flask server on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
