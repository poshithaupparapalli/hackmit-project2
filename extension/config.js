// Change these two values, then reload the extension. Each backend/mode gets
// separate storage, so mock identities and events can never reach the real API.
export const CONFIG = Object.freeze({
  mock: false,
  backendBaseUrl: "http://localhost:8000",
  // The full "workflows app" the side panel's "See more" link opens.
  dashboardUrl: "http://localhost:5173/",
  debug: true,
  requestTimeoutMs: 15000,
});
