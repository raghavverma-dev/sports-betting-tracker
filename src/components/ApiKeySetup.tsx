import { useState } from 'react';
import { getStoredApiKey, setApiKey } from '../utils/oddsApi';

export default function ApiKeySetup({ onKeySet }: { onKeySet: () => void }) {
  const [key, setKey] = useState(getStoredApiKey() ?? '');
  const [saving, setSaving] = useState(false);

  function handleSave() {
    if (!key.trim()) return;
    setSaving(true);
    setApiKey(key.trim());
    setTimeout(() => {
      setSaving(false);
      onKeySet();
    }, 300);
  }

  return (
    <div className="api-key-setup">
      <div className="api-key-card card">
        <h2>Connect to Live Odds</h2>
        <p className="api-key-desc">
          To pull real-time odds from sportsbooks, you need a free API key from
          <strong> The Odds API</strong>. The free tier includes 500 requests/month
          which is plenty for personal use.
        </p>
        <ol className="api-key-steps">
          <li>Go to <strong>the-odds-api.com</strong> and sign up (free)</li>
          <li>Copy your API key from the dashboard</li>
          <li>Paste it below</li>
        </ol>
        <div className="api-key-input-row">
          <input
            type="text"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="Paste your API key here..."
            className="api-key-input"
          />
          <button className="btn btn-primary" onClick={handleSave} disabled={!key.trim() || saving}>
            {saving ? 'Saving...' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  );
}
