/**
 * Lightweight JSON-structured frontend logger.
 *
 * Emits a single JSON object per call so logs are greppable/parseable in the
 * browser console. Mirrors the backend's structured-logging convention
 * (level + event + context).
 */

type LogLevel = "debug" | "info" | "warn" | "error";

interface LogContext {
  [key: string]: unknown;
}

function emit(level: LogLevel, message: string, context?: LogContext): void {
  const entry = {
    level,
    message,
    timestamp: new Date().toISOString(),
    ...(context || {}),
  };

  // Route to the matching console method so devtools level filtering works.
  switch (level) {
    case "error":
      // eslint-disable-next-line no-console
      console.error(JSON.stringify(entry));
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(JSON.stringify(entry));
      break;
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(JSON.stringify(entry));
      break;
    default:
      // eslint-disable-next-line no-console
      console.info(JSON.stringify(entry));
  }
}

export const logger = {
  debug: (message: string, context?: LogContext) => emit("debug", message, context),
  info: (message: string, context?: LogContext) => emit("info", message, context),
  warn: (message: string, context?: LogContext) => emit("warn", message, context),
  error: (message: string, context?: LogContext) => emit("error", message, context),
};
