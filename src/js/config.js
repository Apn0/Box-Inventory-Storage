/**
 * Loads configuration from config.json
 */
let configData = null;

export async function loadConfig() {
  if (configData) return configData;
  try {
    const res = await fetch('config.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    configData = await res.json();
    return configData;
  } catch (err) {
    console.error("Failed to load config.json:", err);
    throw err;
  }
}

export function getConfig() {
  if (!configData) throw new Error("Config not loaded yet.");
  return configData;
}
