import axios from "axios";

const api = axios.create({
  baseURL: "http://127.0.0.1:8000",
});

export async function askMama(message: string) {
  const res = await api.post("/chat", {
    message,
  });
  return res.data.response;
}

export async function getMemories() {
  const res = await api.get("/memory");
  return res.data.memories || [];
}

export async function addMemory(title: string, content: string) {
  const res = await api.post("/memory", {
    title,
    content
  });
  return res.data;
}