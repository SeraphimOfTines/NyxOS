import axios from 'axios';

// Use relative path to leverage Vite Proxy (port 3001 -> 5555)
// This avoids CORS issues and network addressing problems.
const API_URL = ''; 
const API_KEY = 'Thirsty9-Travesty6-Expensive5-Lend4';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
    'x-api-key': API_KEY,
  },
  timeout: 5000, // 5 second timeout
});

// Response Interceptor for better debugging
api.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error.response ? error.response.data : error.message);
    return Promise.reject(error);
  }
);

export const checkStatus = () => api.get('/api/status');
export const getBars = () => api.get('/api/bars');
export const getEmojis = () => api.get('/api/emojis');
export const getPalette = () => api.get('/api/palette');
export const savePalette = (data) => api.post('/api/palette', data);
export const getPresets = () => api.get('/api/presets');
export const savePresets = (data) => api.post('/api/presets', data);

export const syncEmojis = () => api.post('/api/emojis/sync');

export const setGlobalState = (action) => api.post('/api/global/state', { action });
export const updateGlobalText = (content) => api.post('/api/global/update', { content });

export default api;