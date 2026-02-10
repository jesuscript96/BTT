// Use NEXT_PUBLIC_API_URL or default to localhost
const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

// Ensure no trailing slash
const cleanUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;

// Ensure it ends with /api (unless it's localhost which already has it by default above)
// If the user provides "https://btt-backend.onrender.com", we append "/api"
export const API_URL = cleanUrl.endsWith('/api') ? cleanUrl : `${cleanUrl}/api`;
