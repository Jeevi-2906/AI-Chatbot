/**
 * script.js - Vanilla JavaScript Frontend Controller for Gemini Chatbot.
 * 
 * Responsibilities:
 * 1. Manage active conversation session IDs.
 * 2. Capture and validate user input (Enter to send, Shift+Enter for newline).
 * 3. Communicate asynchronously with Flask backend via Fetch API (POST /chat).
 * 4. Display user and assistant message bubbles with Markdown-like formatting.
 * 5. Manage loading/typing states, error banners, and auto-scrolling.
 * 6. Provide "New Chat" session reset functionality.
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const chatMessages = document.getElementById("chat-messages");
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const newChatBtn = document.getElementById("new-chat-btn");
    const typingIndicator = document.getElementById("typing-indicator");
    const errorBanner = document.getElementById("error-banner");
    const errorText = document.getElementById("error-text");
    const errorCloseBtn = document.getElementById("error-close-btn");

    // Session State
    let conversationId = generateUUID();
    let isProcessing = false;

    console.log(`Initialized chat session with ID: ${conversationId}`);

    // Auto-focus input on page load
    userInput.focus();

    // --------------------------------------------------------------------------
    // Event Listeners
    // --------------------------------------------------------------------------

    // Form submission
    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        sendMessage();
    });

    // Keyboard shortcuts: Enter to send, Shift+Enter for newline
    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Dynamic auto-grow for textarea
    userInput.addEventListener("input", () => {
        userInput.style.height = "auto";
        userInput.style.height = `${Math.min(userInput.scrollHeight, 120)}px`;
    });

    // New Chat button
    newChatBtn.addEventListener("click", resetConversation);

    // Dismiss error banner
    errorCloseBtn.addEventListener("click", () => {
        hideError();
    });

    // --------------------------------------------------------------------------
    // Message Handling & Communication
    // --------------------------------------------------------------------------

    async function sendMessage() {
        const text = userInput.value.trim();
        if (!text || isProcessing) return;

        hideError();
        setProcessing(true);

        // 1. Append User Message Bubble
        appendMessage("user", text);

        // Reset input area
        userInput.value = "";
        userInput.style.height = "auto";

        // 2. Display Typing Indicator
        showTypingIndicator();

        try {
            // 3. Send message to Flask POST /chat endpoint
            const response = await fetch("/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    message: text,
                    conversation_id: conversationId,
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                const errMsg = data.error || `Server responded with status ${response.status}`;
                throw new Error(errMsg);
            }

            // Sync conversation ID if backend returns updated ID
            if (data.conversation_id) {
                conversationId = data.conversation_id;
            }

            // 4. Render Assistant Response Bubble
            appendMessage("assistant", data.response || "No response received.");

        } catch (error) {
            console.error("Chat communication error:", error);
            showError(`Error: ${error.message}`);
            // Also append an error note directly into chat stream
            appendMessage(
                "assistant",
                "⚠️ *Sorry, I encountered an issue processing your request. Please try again or click 'New Chat'.*"
            );
        } finally {
            hideTypingIndicator();
            setProcessing(false);
            userInput.focus();
        }
    }

    async function resetConversation() {
        if (isProcessing) return;

        const oldId = conversationId;
        hideError();

        try {
            // Notify backend to reset history for old session
            await fetch("/chat/reset", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ conversation_id: oldId }),
            });
        } catch (err) {
            console.warn("Could not notify backend of reset:", err);
        }

        // Generate a new unique session identifier
        conversationId = generateUUID();
        console.log(`Started new chat session with ID: ${conversationId}`);

        // Reset message list to initial greeting
        chatMessages.innerHTML = `
            <div class="message assistant-message">
                <div class="message-avatar">AI</div>
                <div class="message-content">
                    <p>New conversation started! How can I help you learn programming or AI today?</p>
                </div>
            </div>
        `;

        userInput.value = "";
        userInput.style.height = "auto";
        userInput.focus();
    }

    // --------------------------------------------------------------------------
    // UI Helpers
    // --------------------------------------------------------------------------

    function appendMessage(role, text) {
        const messageDiv = document.createElement("div");
        messageDiv.classList.add("message", `${role}-message`);

        const avatarDiv = document.createElement("div");
        avatarDiv.classList.add("message-avatar");
        avatarDiv.textContent = role === "user" ? "You" : "AI";

        const contentDiv = document.createElement("div");
        contentDiv.classList.add("message-content");
        contentDiv.innerHTML = formatMessageText(text);

        messageDiv.appendChild(avatarDiv);
        messageDiv.appendChild(contentDiv);

        chatMessages.appendChild(messageDiv);
        scrollToBottom();
    }

    function showTypingIndicator() {
        typingIndicator.style.display = "flex";
        scrollToBottom();
    }

    function hideTypingIndicator() {
        typingIndicator.style.display = "none";
    }

    function showError(msg) {
        errorText.textContent = msg;
        errorBanner.style.display = "flex";
    }

    function hideError() {
        errorBanner.style.display = "none";
    }

    function setProcessing(loading) {
        isProcessing = loading;
        sendBtn.disabled = loading;
        userInput.disabled = loading;
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function generateUUID() {
        if (typeof crypto !== "undefined" && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return "sess-" + Math.random().toString(36).substring(2, 11) + "-" + Date.now();
    }

    // Basic Markdown & Linebreak Formatter for AI responses
    function formatMessageText(rawText) {
        if (!rawText) return "";

        // 1. Escape HTML special characters
        let safe = rawText
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");

        // 2. Fenced code blocks ```language ... ```
        safe = safe.replace(/```([\s\S]*?)```/g, (match, codeContent) => {
            return `<pre><code>${codeContent.trim()}</code></pre>`;
        });

        // 3. Inline code `code`
        safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");

        // 4. Bold **text**
        safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

        // 5. Italic *text*
        safe = safe.replace(/\*([^*]+)\*/g, "<em>$1</em>");

        // 6. Split into paragraphs by double newlines
        const paragraphs = safe.split(/\n\s*\n/);
        return paragraphs
            .map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`)
            .join("");
    }
});
