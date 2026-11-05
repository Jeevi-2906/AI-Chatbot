/**
 * script.js - Vanilla JavaScript Frontend Controller for Gemini Chatbot.
 * 
 * Features:
 * 1. "Past Chats" history sidebar with conversation switching and deletion.
 * 2. User-configurable "Last N Messages" Context Window setting.
 * 3. Asynchronous Fetch API communication (POST /chat, GET /chat/conversations, GET /chat/history).
 * 4. Markdown rendering for bold, italics, code blocks, and lists.
 * 5. Typing indicator, error banners, auto-grow input, and mobile responsive drawer.
 */

document.addEventListener("DOMContentLoaded", () => {
    // DOM Elements
    const chatMessages = document.getElementById("chat-messages");
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-btn");
    const newChatBtn = document.getElementById("new-chat-btn");
    const headerNewChatBtn = document.getElementById("header-new-chat-btn");
    const typingIndicator = document.getElementById("typing-indicator");
    const errorBanner = document.getElementById("error-banner");
    const errorText = document.getElementById("error-text");
    const errorCloseBtn = document.getElementById("error-close-btn");
    const pastChatsList = document.getElementById("past-chats-list");
    const nContextInput = document.getElementById("n-context-input");
    const contextBadge = document.getElementById("context-badge");
    const sidebar = document.getElementById("chat-sidebar");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebarOverlay = document.getElementById("sidebar-overlay");

    // Session State
    let conversationId = generateUUID();
    let isProcessing = false;

    // Load saved N context window setting from localStorage (default: 6)
    const savedN = localStorage.getItem("max_history") || "6";
    if (nContextInput) {
        nContextInput.value = savedN;
        updateContextBadge(savedN);
    }

    // Auto-focus input on page load
    userInput.focus();

    // Fetch initial list of past chats
    loadPastChats();

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

    // New Chat button (sidebar)
    if (newChatBtn) newChatBtn.addEventListener("click", startNewChat);
    if (headerNewChatBtn) headerNewChatBtn.addEventListener("click", startNewChat);

    // Context N Input Change
    if (nContextInput) {
        nContextInput.addEventListener("change", () => {
            let val = parseInt(nContextInput.value, 10);
            if (isNaN(val) || val < 2) val = 2;
            nContextInput.value = val;
            localStorage.setItem("max_history", val.toString());
            updateContextBadge(val);
        });
    }

    // Dismiss error banner
    errorCloseBtn.addEventListener("click", hideError);

    // Mobile Sidebar Toggle
    if (sidebarToggle) {
        sidebarToggle.addEventListener("click", toggleSidebar);
    }
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener("click", closeSidebar);
    }

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

        // Retrieve current N context setting
        const currentN = nContextInput ? parseInt(nContextInput.value, 10) : 6;

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
                    max_history: currentN
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

            // 5. Refresh past chats sidebar to reflect recent conversation title
            loadPastChats();

        } catch (error) {
            console.error("Chat communication error:", error);
            showError(`Error: ${error.message}`);
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

    function startNewChat() {
        if (isProcessing) return;

        hideError();
        conversationId = generateUUID();

        // Clear active selection in sidebar
        document.querySelectorAll(".past-chat-item").forEach(el => el.classList.remove("active"));

        // Reset message container to fresh welcome greeting
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
        closeSidebar();
    }

    // --------------------------------------------------------------------------
    // Past Chats & History Management
    // --------------------------------------------------------------------------

    async function loadPastChats() {
        if (!pastChatsList) return;

        try {
            const res = await fetch("/chat/conversations");
            if (!res.ok) return;
            const data = await res.json();
            const convs = data.conversations || [];

            if (convs.length === 0) {
                pastChatsList.innerHTML = `
                    <div class="empty-history-text">No previous chats yet. Start talking to save a conversation!</div>
                `;
                return;
            }

            pastChatsList.innerHTML = "";
            convs.forEach(c => {
                const item = document.createElement("div");
                item.classList.add("past-chat-item");
                if (c.conversation_id === conversationId) {
                    item.classList.add("active");
                }

                item.innerHTML = `
                    <div class="past-chat-info">
                        <span class="past-chat-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span>
                    </div>
                    <span class="past-chat-badge">${c.message_count} msgs</span>
                    <button class="past-chat-delete" title="Delete conversation" data-id="${c.conversation_id}">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"></line>
                            <line x1="6" y1="6" x2="18" y2="18"></line>
                        </svg>
                    </button>
                `;

                // Click to switch conversation
                item.addEventListener("click", (e) => {
                    if (e.target.closest(".past-chat-delete")) return;
                    switchToConversation(c.conversation_id);
                });

                // Click delete icon
                const deleteBtn = item.querySelector(".past-chat-delete");
                deleteBtn.addEventListener("click", async (e) => {
                    e.stopPropagation();
                    await deleteConversation(c.conversation_id);
                });

                pastChatsList.appendChild(item);
            });

        } catch (err) {
            console.warn("Failed to load past chats:", err);
        }
    }

    async function switchToConversation(cid) {
        if (isProcessing) return;
        conversationId = cid;

        // Highlight active item in sidebar
        document.querySelectorAll(".past-chat-item").forEach(el => {
            const btn = el.querySelector(".past-chat-delete");
            if (btn && btn.getAttribute("data-id") === cid) {
                el.classList.add("active");
            } else {
                el.classList.remove("active");
            }
        });

        // Load messages from server
        try {
            const res = await fetch(`/chat/history/${cid}`);
            if (!res.ok) throw new Error("Could not load history.");
            const data = await res.json();
            const history = data.history || [];

            chatMessages.innerHTML = "";
            if (history.length === 0) {
                chatMessages.innerHTML = `
                    <div class="message assistant-message">
                        <div class="message-avatar">AI</div>
                        <div class="message-content">
                            <p>This conversation has no messages yet.</p>
                        </div>
                    </div>
                `;
            } else {
                history.forEach(m => {
                    appendMessage(m.role, m.content, false);
                });
            }
            scrollToBottom();
            closeSidebar();

        } catch (err) {
            showError("Failed to load chat history: " + err.message);
        }
    }

    async function deleteConversation(cid) {
        try {
            await fetch(`/chat/conversations/${cid}`, { method: "DELETE" });
            if (conversationId === cid) {
                startNewChat();
            }
            loadPastChats();
        } catch (err) {
            console.error("Delete conversation error:", err);
        }
    }

    // --------------------------------------------------------------------------
    // UI Helpers & Utilities
    // --------------------------------------------------------------------------

    function appendMessage(role, text, shouldScroll = true) {
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
        if (shouldScroll) {
            scrollToBottom();
        }
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

    function updateContextBadge(n) {
        if (contextBadge) {
            contextBadge.textContent = `Context: Last ${n} msgs`;
        }
    }

    function toggleSidebar() {
        if (!sidebar) return;
        sidebar.classList.toggle("open");
        if (sidebarOverlay) {
            sidebarOverlay.classList.toggle("active");
        }
    }

    function closeSidebar() {
        if (sidebar) sidebar.classList.remove("open");
        if (sidebarOverlay) sidebarOverlay.classList.remove("active");
    }

    function generateUUID() {
        if (typeof crypto !== "undefined" && crypto.randomUUID) {
            return crypto.randomUUID();
        }
        return "sess-" + Math.random().toString(36).substring(2, 11) + "-" + Date.now();
    }

    function escapeHtml(text) {
        if (!text) return "";
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    // Markdown & Formatting Parser for AI responses
    function formatMessageText(rawText) {
        if (!rawText) return "";

        let safe = escapeHtml(rawText);

        // Clean up any stray LaTeX math formatting into clean plain readable text
        safe = safe.replace(/\\text\{([^}]+)\}/g, "$1");
        safe = safe.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1 / $2)");
        safe = safe.replace(/\\times/g, "×");
        safe = safe.replace(/\\cdot/g, "·");
        safe = safe.replace(/\^\\circ/g, "°");
        safe = safe.replace(/\\circ/g, "°");
        safe = safe.replace(/\$\$([^$]+)\$\$/g, "$1");
        safe = safe.replace(/\$([^$]+)\$/g, "$1");

        // Convert markdown headers into clean bold headings
        safe = safe.replace(/###\s+(.+)/g, "<strong>$1</strong>");
        safe = safe.replace(/##\s+(.+)/g, "<strong>$1</strong>");

        // Fenced code blocks ```code```
        safe = safe.replace(/```([\s\S]*?)```/g, (match, codeContent) => {
            return `<pre><code>${codeContent.trim()}</code></pre>`;
        });

        // Inline code `code`
        safe = safe.replace(/`([^`]+)`/g, "<code>$1</code>");

        // Bold **text**
        safe = safe.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

        // Italic *text*
        safe = safe.replace(/\*([^*]+)\*/g, "<em>$1</em>");

        // Paragraphs & Linebreaks
        const paragraphs = safe.split(/\n\s*\n/);
        return paragraphs
            .map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`)
            .join("");
    }
});
