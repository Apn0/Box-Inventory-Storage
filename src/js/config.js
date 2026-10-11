/**
 * Loads configuration from config.json
 */
let configData = null;

const DEFAULT_CONFIG = {
  form_url: "https://docs.google.com/forms/d/e/1FAIpQLSfaLSRumcvZL1JtLMCsILnac0PIuKb9kEePiOvndgu1jlUsIQ/formResponse",
  form_entries: {
    box: "entry.2127766863",
    name: "entry.957000781",
    qty: "entry.971108864",
    note: "entry.1227292805"
  },
  sheet_id: "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ",
  box_gid: "788564724",
  form_gid: "677102738"
};

export async function loadConfig() {
  if (configData) return configData;
  try {
    const res = await fetch('config.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    configData = await res.json();
    return configData;
  } catch (err) {
    console.warn("Failed to load config.json, using fallback configuration:", err);
    configData = DEFAULT_CONFIG;
    return configData;
  }
}

export function getConfig() {
  return configData || DEFAULT_CONFIG;
}
