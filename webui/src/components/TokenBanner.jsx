import { useEffect, useState } from "react";
import { getHealth, setToken } from "../api";

export default function TokenBanner({ canClose = false, onClose, onValidToken }) {
  const [token, setLocalToken] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const existing = localStorage.getItem("lifeos_token") || "";
    setLocalToken(existing);
  }, []);

  async function handleSave() {
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Token is required.");
      return;
    }

    setSaving(true);
    setError("");
    setSaved(false);
    setToken(trimmed);

    try {
      await getHealth();
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      if (onValidToken) onValidToken();
    } catch (err) {
      setError(err.message || "Token validation failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="glass-card token-banner">
      <div className="token-banner-head">
        <div>
          <h3>API Token</h3>
          <p>Set `X-LifeOS-Token` for this browser session.</p>
        </div>
        <div className="token-banner-head-actions">
          <span className={`badge ${saved ? "badge-approved" : "badge-pending"}`}>{saved ? "Saved" : "Not saved"}</span>
          {canClose && (
            <button type="button" className="btn btn-ghost token-banner-close" onClick={onClose}>
              Hide
            </button>
          )}
        </div>
      </div>
      <div className="token-banner-row">
        <input
          type="password"
          value={token}
          onChange={(event) => setLocalToken(event.target.value)}
          placeholder="Paste API_SECRET_KEY"
        />
        <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? "Validating..." : "Save Token"}
        </button>
      </div>
      {error && <p className="token-banner-error">{error}</p>}
    </div>
  );
}
