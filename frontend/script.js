
// ======================================================
// AGENTIC AI CHATBOT - FRONTEND JAVASCRIPT
// FastAPI + LangGraph + Groq + SQLite + Streaming
// ======================================================


// ------------------------------------------------------
// 1. API CONFIGURATION
// ------------------------------------------------------

const API_BASE = "http://127.0.0.1:8000";


// ------------------------------------------------------
// 2. DOM ELEMENTS
// ------------------------------------------------------

const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const chatArea = document.getElementById("chatArea");
const welcome = document.getElementById("welcome");
const sendBtn = document.getElementById("sendBtn");
const historyList = document.getElementById("historyList");

const uploadBtn = document.getElementById("uploadBtn");
const pdfInput = document.getElementById("pdfInput");
const uploadStatus = document.getElementById("uploadStatus");


// ------------------------------------------------------
// 3. GLOBAL VARIABLES
// ------------------------------------------------------

let currentThreadId = createThreadId();


// ------------------------------------------------------
// 4. CREATE THREAD ID
// ------------------------------------------------------

function createThreadId() {

    return "thread-" +
        Date.now() +
        "-" +
        Math.random().toString(36).slice(2, 8);

}


// ------------------------------------------------------
// 5. ADD MESSAGE TO CHAT UI
// ------------------------------------------------------

function addMessage(role, content) {

    if (welcome) {
        welcome.style.display = "none";
    }

    const message = document.createElement("div");

    message.className = `chat-message ${role}`;

    // Avatar
    const avatar = document.createElement("div");

    avatar.className = "message-avatar";

    avatar.textContent =
        role === "user" ? "👤" : "AI";

    // Message content
    const body = document.createElement("div");

    body.className = "message-content";

    // Safe text rendering
    body.textContent = content;

    message.appendChild(avatar);
    message.appendChild(body);

    chatArea.appendChild(message);

    chatArea.scrollTop = chatArea.scrollHeight;

    return body;

}


// ------------------------------------------------------
// 6. LOAD CONVERSATION HISTORY FROM DATABASE
// ------------------------------------------------------

async function loadConversationList() {

    if (!historyList) return;

    try {

        const response = await fetch(
            `${API_BASE}/api/conversations`
        );

        if (!response.ok) {

            throw new Error(
                "Could not load conversation history."
            );

        }

        const data = await response.json();

        historyList.innerHTML = "";

        const conversations = data.conversations || [];

        if (conversations.length === 0) {

            const empty = document.createElement("div");

            empty.className = "empty-history";

            empty.textContent = "No conversations yet";

            historyList.appendChild(empty);

            return;

        }

        conversations.forEach((conversation) => {

            const item = document.createElement("button");

            item.className = "history-item";

            item.textContent =
                conversation.title || "New Conversation";

            item.title = conversation.thread_id;

            if (conversation.thread_id === currentThreadId) {

                item.classList.add("active");

            }

            item.addEventListener("click", () => {

                loadConversation(conversation.thread_id);

            });

            historyList.appendChild(item);

        });

    } catch (error) {

        console.error(
            "Conversation history error:",
            error
        );

    }

}


// ------------------------------------------------------
// 7. LOAD OLD CONVERSATION
// ------------------------------------------------------

async function loadConversation(threadId) {

    try {

        const response = await fetch(
            `${API_BASE}/api/conversations/${encodeURIComponent(threadId)}`
        );

        if (!response.ok) {

            throw new Error(
                "Could not load this conversation."
            );

        }

        const data = await response.json();

        currentThreadId = threadId;

        chatArea.innerHTML = "";

        if (welcome) {
            welcome.style.display = "none";
        }

        const messages = data.messages || [];

        messages.forEach((message) => {

            addMessage(
                message.role,
                message.content
            );

        });

        chatArea.scrollTop = chatArea.scrollHeight;

        await loadConversationList();

    } catch (error) {

        console.error(error);

        alert(
            "Conversation loading error: " +
            error.message
        );

    }

}


// ------------------------------------------------------
// 8. PROCESS STREAMING SSE EVENT
// ------------------------------------------------------

function processStreamEvent(eventBlock, typing) {

    if (!eventBlock.trim()) return null;

    const lines = eventBlock.split(/\r?\n/);

    const dataLines = lines
        .filter(line => line.startsWith("data:"))
        .map(line => line.slice(5).trim());

    if (dataLines.length === 0) return null;

    const payload = JSON.parse(dataLines.join("\n"));

    // Receive AI tokens
    if (payload.type === "token") {

        typing.textContent += payload.content || "";

        chatArea.scrollTop = chatArea.scrollHeight;

    }

    // Stream completed
    else if (payload.type === "done") {

        if (payload.thread_id) {

            currentThreadId = payload.thread_id;

        }

    }

    // Backend error
    else if (payload.type === "error") {

        throw new Error(
            payload.message || "Streaming failed."
        );

    }

    return payload;

}


// ------------------------------------------------------
// 9. STREAMING CHAT FUNCTION
// ------------------------------------------------------

async function sendMessage(text) {

    const message = text.trim();

    if (!message || sendBtn.disabled) return;

    // Display user message
    addMessage("user", message);

    // Clear input
    messageInput.value = "";

    messageInput.style.height = "auto";

    sendBtn.disabled = true;

    // Create assistant message bubble
    const typing = addMessage(
        "assistant",
        "Thinking..."
    );

    let receivedText = false;

    try {

        // Call streaming API
        const response = await fetch(
            `${API_BASE}/api/chat/stream`,
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream"
                },

                body: JSON.stringify({

                    message: message,

                    thread_id: currentThreadId

                })
            }
        );


        // HTTP error handling
        if (!response.ok) {

            const errorData = await response
                .json()
                .catch(() => ({}));

            throw new Error(
                errorData.detail ||
                `Server error: ${response.status}`
            );

        }


        if (!response.body) {

            throw new Error(
                "Streaming response body is unavailable."
            );

        }


        // Read streaming response
        const reader = response.body.getReader();

        const decoder = new TextDecoder();

        let buffer = "";

        typing.textContent = "";


        while (true) {

            const { value, done } = await reader.read();

            if (done) break;


            buffer += decoder.decode(
                value,
                { stream: true }
            );


            // Handle SSE event boundaries
            const events = buffer.split(/\r?\n\r?\n/);

            buffer = events.pop() || "";


            for (const eventBlock of events) {

                const payload = processStreamEvent(
                    eventBlock,
                    typing
                );

                if (payload?.type === "token") {

                    receivedText = true;

                }

            }

        }


        // Flush remaining decoder bytes
        buffer += decoder.decode();


        // Process remaining buffered event
        if (buffer.trim()) {

            const payload = processStreamEvent(
                buffer,
                typing
            );

            if (payload?.type === "token") {

                receivedText = true;

            }

        }


        // Empty response handling
        if (!receivedText) {

            typing.textContent =
                "No AI text received. Please check the backend terminal and Groq API configuration.";

        }


        // Reload database history
        await loadConversationList();


    } catch (error) {

        console.error(
            "Chat streaming error:",
            error
        );

        typing.textContent =
            "Error: " + error.message;


    } finally {

        sendBtn.disabled = false;

        messageInput.focus();

        chatArea.scrollTop = chatArea.scrollHeight;

    }

}


// ------------------------------------------------------
// 10. CHAT FORM SUBMISSION
// ------------------------------------------------------

if (chatForm) {

    chatForm.addEventListener("submit", (event) => {

        event.preventDefault();

        sendMessage(messageInput.value);

    });

}


// ------------------------------------------------------
// 11. ENTER TO SEND MESSAGE
// SHIFT + ENTER = NEW LINE
// ------------------------------------------------------

if (messageInput) {

    messageInput.addEventListener("keydown", (event) => {

        if (
            event.key === "Enter" &&
            !event.shiftKey &&
            !event.isComposing
        ) {

            event.preventDefault();

            chatForm.requestSubmit();

        }

    });


    // Auto resize textarea
    messageInput.addEventListener("input", () => {

        messageInput.style.height = "auto";

        messageInput.style.height =
            Math.min(
                messageInput.scrollHeight,
                160
            ) + "px";

    });

}


// ------------------------------------------------------
// 12. NEW CONVERSATION
// ------------------------------------------------------

const newChatBtn = document.getElementById("newChatBtn");

if (newChatBtn) {

    newChatBtn.addEventListener("click", () => {

        currentThreadId = createThreadId();

        chatArea.innerHTML = "";

        if (welcome) {

            welcome.style.display = "block";

        }

        messageInput.value = "";

        messageInput.focus();

        loadConversationList();

    });

}


// ------------------------------------------------------
// 13. SUGGESTION BUTTONS
// ------------------------------------------------------

document.querySelectorAll(".suggestion").forEach((button) => {

    button.addEventListener("click", () => {

        const prompt = button.dataset.prompt;

        if (prompt) {

            sendMessage(prompt);

        }

    });

});


// ------------------------------------------------------
// 14. SIDEBAR NAVIGATION
// ------------------------------------------------------

const pageNames = {

    chat: "Chat Studio",

    knowledge: "Knowledge Base",

    tools: "Tools & Workflow",

    approval: "Human Approval",

    about: "About Project"

};


document.querySelectorAll(".nav-item").forEach((button) => {

    button.addEventListener("click", () => {

        const page = button.dataset.page;

        if (!page || !pageNames[page]) return;


        // Active navigation
        document.querySelectorAll(".nav-item").forEach((item) => {

            item.classList.remove("active");

        });

        button.classList.add("active");


        // Active page
        document.querySelectorAll(".page").forEach((section) => {

            section.classList.remove("active");

        });

        const targetPage = document.getElementById(
            page + "Page"
        );

        if (targetPage) {

            targetPage.classList.add("active");

        }


        // Page title
        const pageName = document.getElementById("pageName");

        if (pageName) {

            pageName.textContent = pageNames[page];

        }


        // Close mobile sidebar
        const sidebar = document.getElementById("sidebar");

        if (sidebar) {

            sidebar.classList.remove("open");

        }

    });

});


// ------------------------------------------------------
// 15. MOBILE SIDEBAR
// ------------------------------------------------------

const menuBtn = document.getElementById("menuBtn");

if (menuBtn) {

    menuBtn.addEventListener("click", () => {

        const sidebar = document.getElementById("sidebar");

        if (sidebar) {

            sidebar.classList.toggle("open");

        }

    });

}


// ------------------------------------------------------
// 16. BACKEND HEALTH CHECK
// ------------------------------------------------------

async function checkBackend() {

    const status = document.getElementById(
        "backendStatus"
    );

    if (!status) return;

    try {

        const response = await fetch(
            `${API_BASE}/health`
        );

        if (!response.ok) {

            throw new Error("Backend unavailable");

        }

        const data = await response.json();

        if (data.status === "ok") {

            status.textContent = "Connected to FastAPI";

        } else {

            status.textContent = "Backend needs attention";

        }

    } catch (error) {

        status.textContent = "Backend offline";

        console.error(
            "Backend health check:",
            error
        );

    }

}


// ------------------------------------------------------
// 17. PDF UPLOAD
// ------------------------------------------------------

if (uploadBtn && pdfInput && uploadStatus) {

    uploadBtn.addEventListener("click", async () => {

        if (!pdfInput.files.length) {

            uploadStatus.textContent =
                "Please select a PDF first.";

            return;

        }

        const file = pdfInput.files[0];

        if (!file.name.toLowerCase().endsWith(".pdf")) {

            uploadStatus.textContent =
                "Only PDF files are allowed.";

            return;

        }


        const formData = new FormData();

        formData.append("file", file);

        uploadStatus.textContent = "Uploading...";

        uploadBtn.disabled = true;


        try {

            const response = await fetch(
                `${API_BASE}/api/knowledge/upload`,
                {
                    method: "POST",
                    body: formData
                }
            );


            const data = await response
                .json()
                .catch(() => ({}));


            if (!response.ok) {

                throw new Error(
                    data.detail || "PDF upload failed."
                );

            }


            uploadStatus.textContent =
                data.message || "PDF uploaded successfully.";

            pdfInput.value = "";


        } catch (error) {

            uploadStatus.textContent =
                "Upload error: " + error.message;

            console.error(error);

        } finally {

            uploadBtn.disabled = false;

        }

    });

}


// ------------------------------------------------------
// 18. INITIALIZE APPLICATION
// ------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {

    checkBackend();

    loadConversationList();

});


// Also run initialization if this script loads
// after the DOMContentLoaded event has already fired.
if (document.readyState !== "loading") {

    checkBackend();

    loadConversationList();

}
