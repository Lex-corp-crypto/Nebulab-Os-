/**
 * NebulaLab Dashboard Server
 * Serveur Express léger pour distribuer l'interface Web & Mobile
 * et relayer les requêtes / WebSocket vers le Master API.
 */

const express = require('express');
const http = require('http');
const path = require('path');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const server = http.createServer(app);

const API_HOST = process.env.API_HOST || '127.0.0.1';
const API_PORT = process.env.API_PORT || 8000;
const API_TARGET = process.env.API_URL || `http://${API_HOST}:${API_PORT}`;
const PORT = process.env.PORT || 3000;

// Servir les fichiers statiques de l'interface
app.use(express.static(path.join(__dirname, 'public')));

// Proxy API REST vers le backend FastAPI
app.use('/api', (req, res, next) => {
  // Rediriger vers l'API interne
  const proxy = createProxyMiddleware({
    target: API_TARGET,
    changeOrigin: true,
    logLevel: 'warn'
  });
  return proxy(req, res, next);
});

// Proxy WebSocket vers FastAPI
app.use('/ws', (req, res, next) => {
  const wsProxy = createProxyMiddleware({
    target: API_TARGET,
    ws: true,
    changeOrigin: true,
    logLevel: 'warn'
  });
  return wsProxy(req, res, next);
});

// Route par défaut SPA
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`🌌 NebulaLab Dashboard accessible sur http://0.0.0.0:${PORT}`);
  console.log(`🔗 Connecté au Master API : ${API_TARGET}`);
});