# Project-mind-


# 🧠 MIND AI Workspace

MIND AI Workspace is a premium, real-time multi-room collaborative platform designed for modern teams and developers. Built using **Flask** and **WebSockets (Flask-SocketIO)**, the platform integrates **Google Gemini 2.5 Flash** to offer seamless context-aware AI interactions, multimodal document processing, and granular access controls. The UI features a premium **Cyberpunk Dark Theme** engineered for immersive and slick software development experiences.

---

## 🚀 Core Features

### 1. 📂 Advanced Document & Multimodal AI Processing
* **Universal File Support:** Users can seamlessly upload Images, PDFs, Plain Text (`.txt`), and Word Documents (`.docx`) directly into any chat stream.
* **Contextual Token Parsing:** Built-in dynamic text-extraction fallback for document metrics. Users can query attached documents in real-time by tagging the assistant (e.g., `@ai summarize this document` or `@ai review this code framework`).
* **Scannable AI Presentation Engine:** Strict system prompt constraints ensure the AI assistant structures all outputs using clean headings, scannable bullet points, and syntax-highlighted code blocks instead of dense paragraphs.

### 2. 🛡️ Real-Time User Presence Mapping
* **Dynamic Connection Lifecycles:** Leverages WebSockets to map client connection session IDs (`request.sid`) to active database nodes.
* **Presence Indicators:** Instantly updates global sidebars with real-time **Online (Green)** and **Offline (Grey)** status transitions as users connect or close their browser tabs.
* **Unique User Avatars:** Dynamically generates circular text-profile avatars for clean, enterprise-grade directory listing.

### 3. 📢 Isolated Multi-Room Channels & Private DMs
* **Public Workspace Channels:** Features distinct public communication hubs like `# General` (default team onboarding chatter) and `# AI-Talks` (isolated environment dedicated exclusively to model prompting and analysis).
* **Secure Direct Messaging (DMs):** Cryptographically maps explicit communication tokens between user pairs, spinning up isolated chat rooms (`dm_minId_maxId`) completely hidden from public streams.
* **State Persistence:** All historical streams are preserved via an optimized SQLite indexing model, dynamically back-filling screen data during room transit hooks.

---

## 🛠️ Tech Stack & Architecture

* **Backend Framework:** Python / Flask
* **Real-Time Layer:** Flask-SocketIO (Engine.IO / WebSockets protocol mapping)
* **AI Core:** Google GenAI SDK (Model: `gemini-2.5-flash`)
* **Database Storage:** SQLite3 (Relational structural schemas for users, rooms, and historical messages)
* **Authentication Secure State:** Flask-Login (Using cryptographically salted hashes via `scrypt`)
* **Frontend Layer:** Semantic HTML5, Premium CSS3 Custom Glassmorphic Matrix, Vanilla JS DOM Architecture

---

## ⚙️ Installation & Setup

### 1. Clone the Repository
```bash
git clone [https://github.com/yourusername/MIND-AI-Workspace.git](https://github.com/yourusername/MIND-AI-Workspace.git)
cd MIND-AI-Workspace