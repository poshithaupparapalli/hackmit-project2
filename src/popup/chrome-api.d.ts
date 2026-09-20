/**
 * Minimal ambient declarations for the ONLY two Chrome extension APIs this
 * popup touches. Kept local (rather than pulling in @types/chrome) so the
 * surface we depend on stays visible and small — swap for @types/chrome
 * once Anika's extension codebase lands.
 */
interface MiaChromeApi {
  tabs?: {
    create(props: { url: string }): void;
  };
  storage?: {
    local: {
      get(keys: string | string[]): Promise<Record<string, unknown>>;
      remove(keys: string | string[]): Promise<void>;
    };
  };
}

declare const chrome: MiaChromeApi | undefined;
