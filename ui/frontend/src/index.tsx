import React from 'react';
import ReactDOM from 'react-dom/client';
// Bootstrap first, then our design system so our token overrides win.
import 'bootstrap/dist/css/bootstrap.min.css';
import './index.css';
import App from './App';
import { AuthProvider } from './contexts/AuthContext';
import { LoginGate } from './components/LoginGate';
import { PodcastPortal } from './components/podcast/PodcastPortal';
import { PODCAST_PAGE_PATH } from './constants/podcast';
import reportWebVitals from './reportWebVitals';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);

// The public podcast-MCP page is a standalone route that must render WITHOUT
// the app's auth gate or chrome (external visitors have no account). Branch on
// the pathname before mounting AuthProvider/LoginGate so a stranger visiting
// /podcasts never triggers a session probe or sees the login card. nginx's
// SPA fallback (try_files ... /index.html) makes the deep link resolve here.
const path = window.location.pathname.replace(/\/+$/, "");
const isPodcastRoute = path === PODCAST_PAGE_PATH;

root.render(
  <React.StrictMode>
    {isPodcastRoute ? (
      <PodcastPortal />
    ) : (
      <AuthProvider>
        <LoginGate>
          <App />
        </LoginGate>
      </AuthProvider>
    )}
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
