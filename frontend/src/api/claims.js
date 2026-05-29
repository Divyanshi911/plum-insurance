// src/api/claims.js
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function submitClaim(formData) {
  const res = await axios.post(`${API_BASE}/claims/submit`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return res.data;
}