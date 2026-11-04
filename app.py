"""
app.py - Main entry point for the Flask chatbot application.
Initializes the Flask server, loads environment variables, and configures routes.
"""

import os
from flask import Flask, render_template, jsonify
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Flask application
app = Flask(__name__)

# Basic configuration
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-12345")


@app.route("/")
def index():
    """Render the main chatbot frontend interface."""
    return render_template("index.html")


@app.route("/health")
def health():
    """Health check endpoint to verify backend server status."""
    return jsonify({
        "status": "ok",
        "message": "Flask server is up and running"
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "True").lower() == "true"
    print(f"Starting Flask server on http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=debug)
