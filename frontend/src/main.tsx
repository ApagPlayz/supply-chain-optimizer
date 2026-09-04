import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { startWarmup } from './services/warmup'

// Fired BEFORE the first render, and before the router has decided which route this is,
// so a deep link to /benchmark or /frontier warms the API exactly like a landing on /.
// It is fire-and-forget: nothing below awaits it, and every failure inside is swallowed,
// so it cannot delay or break the paint. Once per page load — not once per route.
startWarmup();

const rootElement = document.getElementById('root');
if (rootElement) {
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
