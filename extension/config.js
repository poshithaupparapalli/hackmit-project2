// Change these two values, then reload the extension. Each backend/mode gets
// separate storage, so mock identities and events can never reach the real API.
export const CONFIG = Object.freeze({
  mock: false,
  backendBaseUrl: "http://localhost:8000",
  debug: true,
  requestTimeoutMs: 15000,
});
