import { useState, useEffect } from "react";
import { Bot, Mic, Send, Brain, History, MessageSquare, Plus, CheckCircle, XCircle } from "lucide-react";
import { getMemories, addMemory } from "./services/api";
import axios from "axios";
import "./App.css";

interface MemoryItem {
  id: number;
  title: string;
  content: string;
  created_at: string;
}

interface ExperienceItem {
  id: number;
  task: string;
  action: string;
  result: string;
  success: boolean;
  reward: number;
  created_at: string;
}

function App() {
  const [activeTab, setActiveTab] = useState<"chat" | "memories" | "experiences">("chat");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState([
    { role: "Mama", text: "👋 Hello! I am Mama AI, your autonomous desktop assistant. How can I help you today?", intent: "general_chat" },
  ]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [experiences, setExperiences] = useState<ExperienceItem[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [newContent, setNewContent] = useState("");
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    if (activeTab === "memories") {
      fetchMemories();
    } else if (activeTab === "experiences") {
      fetchExperiences();
    }
  }, [activeTab]);

  async function fetchMemories() {
    try {
      const data = await getMemories();
      setMemories(data);
    } catch (err) {
      console.error("Failed to load memories", err);
    }
  }

  async function fetchExperiences() {
    try {
      const res = await axios.get("http://127.0.0.1:8000/history");
      // If the backend has no history, we fall back to empty array
      setExperiences(res.data.history || []);
    } catch (err) {
      console.error("Failed to load experiences", err);
    }
  }

  async function handleAddMemory(e: React.FormEvent) {
    e.preventDefault();
    if (!newTitle.trim() || !newContent.trim()) return;
    try {
      await addMemory(newTitle, newContent);
      setNewTitle("");
      setNewContent("");
      fetchMemories();
    } catch (err) {
      console.error("Failed to add memory", err);
    }
  }

  async function sendMessage() {
    if (!message.trim() || isSending) return;

    const userMsg = { role: "You", text: message, intent: "user_query" };
    setChat((prev) => [...prev, userMsg]);
    const question = message;
    setMessage("");
    setIsSending(true);

    try {
      const res = await axios.post("http://127.0.0.1:8000/chat", { message: question });
      setChat((prev) => [
        ...prev,
        {
          role: "Mama",
          text: res.data.response,
          intent: res.data.intent,
        },
      ]);
    } catch {
      setChat((prev) => [
        ...prev,
        {
          role: "Mama",
          text: "❌ The Mama AI backend is offline. Please start the server.",
          intent: "error",
        },
      ]);
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="logo-container">
          <Bot className="logo-icon" size={32} />
          <div>
            <h2>Mama AI</h2>
            <span className="status-badge">
              <span className="pulse-dot"></span> Online
            </span>
          </div>
        </div>

        <nav className="nav-menu">
          <button
            className={`nav-item ${activeTab === "chat" ? "active" : ""}`}
            onClick={() => setActiveTab("chat")}
          >
            <MessageSquare size={20} />
            <span>Chat Assistant</span>
          </button>
          
          <button
            className={`nav-item ${activeTab === "memories" ? "active" : ""}`}
            onClick={() => setActiveTab("memories")}
          >
            <Brain size={20} />
            <span>Long-term Memory</span>
          </button>

          <button
            className={`nav-item ${activeTab === "experiences" ? "active" : ""}`}
            onClick={() => setActiveTab("experiences")}
          >
            <History size={20} />
            <span>Agent Experiences</span>
          </button>
        </nav>

        <div className="sidebar-footer">
          <p>Mama AI Desktop v1.0.0</p>
        </div>
      </aside>

      <main className="main-content">
        <header className="main-header">
          <h1>{activeTab === "chat" ? "Interactive Workspace" : activeTab === "memories" ? "Memory Bank" : "Cognitive Experience History"}</h1>
          <div className="header-actions">
            <span className="api-url">http://localhost:8000</span>
          </div>
        </header>

        <div className="content-area">
          {activeTab === "chat" && (
            <div className="chat-interface">
              <div className="chat-window">
                {chat.map((m, i) => (
                  <div key={i} className={`msg-row ${m.role === "You" ? "user-row" : "bot-row"}`}>
                    <div className="msg-bubble">
                      <div className="msg-header">
                        <strong>{m.role}</strong>
                        {m.intent && m.intent !== "general_chat" && m.intent !== "user_query" && (
                          <span className="intent-label">{m.intent}</span>
                        )}
                      </div>
                      <p className="msg-text">{m.text}</p>
                    </div>
                  </div>
                ))}
                {isSending && (
                  <div className="msg-row bot-row">
                    <div className="msg-bubble loading-bubble">
                      <span className="loading-dot"></span>
                      <span className="loading-dot"></span>
                      <span className="loading-dot"></span>
                    </div>
                  </div>
                )}
              </div>

              <div className="input-bar">
                <input
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                  placeholder="Ask Mama AI to run desktop actions, search, or translate..."
                  disabled={isSending}
                />
                <button className="icon-btn" disabled={isSending}>
                  <Mic size={20} />
                </button>
                <button className="primary-btn" onClick={sendMessage} disabled={isSending}>
                  <Send size={20} />
                </button>
              </div>
            </div>
          )}

          {activeTab === "memories" && (
            <div className="memories-tab">
              <form onSubmit={handleAddMemory} className="add-memory-form">
                <h3>Store New Memory</h3>
                <div className="form-group">
                  <input
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="Memory Title (e.g. Favorite Editor)"
                    required
                  />
                </div>
                <div className="form-group">
                  <textarea
                    value={newContent}
                    onChange={(e) => setNewContent(e.target.value)}
                    placeholder="Memory Content details..."
                    required
                  />
                </div>
                <button type="submit" className="primary-btn icon-left">
                  <Plus size={18} /> Add to Memory
                </button>
              </form>

              <div className="memories-grid">
                {memories.length === 0 ? (
                  <div className="empty-state">No long-term memories saved yet. Add one above!</div>
                ) : (
                  memories.map((m) => (
                    <div key={m.id} className="memory-card">
                      <div className="card-header">
                        <h4>{m.title}</h4>
                        <span className="date-label">{new Date(m.created_at).toLocaleDateString()}</span>
                      </div>
                      <p className="card-content">{m.content}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}

          {activeTab === "experiences" && (
            <div className="experiences-tab">
              <div className="experience-list">
                {experiences.length === 0 ? (
                  <div className="empty-state">No agent experience history has been recorded yet. Try running some tasks!</div>
                ) : (
                  experiences.map((exp) => (
                    <div key={exp.id} className={`experience-card ${exp.success ? "success-card" : "fail-card"}`}>
                      <div className="exp-meta">
                        {exp.success ? (
                          <CheckCircle className="success-icon" size={24} />
                        ) : (
                          <XCircle className="fail-icon" size={24} />
                        )}
                        <div>
                          <h4>{exp.task}</h4>
                          <p className="exp-action"><strong>Action:</strong> {exp.action}</p>
                          <p className="exp-result"><strong>Result:</strong> {exp.result}</p>
                        </div>
                      </div>
                      <div className="exp-reward">
                        <span className={`reward-badge ${exp.reward > 0 ? "positive" : "negative"}`}>
                          Reward: {exp.reward}
                        </span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;