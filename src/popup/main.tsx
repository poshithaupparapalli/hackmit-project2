import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { PopupApp } from './PopupApp';

createRoot(document.getElementById('mia-popup-root')!).render(
  <StrictMode>
    <PopupApp />
  </StrictMode>,
);
