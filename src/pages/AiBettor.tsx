import { useState, useEffect, useCallback } from 'react';
import { format, parseISO } from 'date-fns';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import { formatCurrency, formatOdds } from '../utils/odds';
import { getStoredApiKey, checkApiQuota } from '../utils/oddsApi';
import type { ApiQuota } from '../utils/oddsApi';
import type { AutoBetConfig, Sport } from '../types';
import {
  loadAutoBetState,
  saveAutoBetState,
  runAutoBet,
  settleBets,
  computeStats,
  DEFAULT_CONFIG,
} from '../utils/autoBettor';
import type { RejectedBet } from '../utils/autoBettor';
import ApiKeySetup from '../components/ApiKeySetup';

// Sports the auto-bettor can reliably settle (two-outcome h2h only)
const SAFE_SPORTS: Sport[] = ['NBA', 'NFL', 'MLB', 'NHL', 'NCAAF', 'NCAAB'];

// One-click presets so users don't need to understand every knob
const PRESETS: { name: string; description: string; config: Partial<AutoBetConfig> }[] = [
  {
    name: 'Conservative',
    description: 'Small bets, strict filters. Best for learning and validating the system.',
    config: { minEv: 5, maxEv: 12, kellyFraction: 0.0625, maxBetsPerDay: 3, maxStakePercent: 3, skipStale: true },
  },
  {
    name: 'Balanced',
    description: 'Moderate risk. Good default for paper trading once you trust the data.',
    config: { minEv: 3, maxEv: 15, kellyFraction: 0.125, maxBetsPerDay: 5, maxStakePercent: 5, skipStale: true },
  },
  {
    name: 'Aggressive',
    description: 'Larger bets, lower EV threshold. Higher variance — only for confident systems.',
    config: { minEv: 2, maxEv: 20, kellyFraction: 0.25, maxBetsPerDay: 8, maxStakePercent: 10, skipStale: true },
  },
];

export default function AiBettor() {
  const [hasKey, setHasKey] = useState(!!getStoredApiKey());
  const [state, setState] = useState(() => loadAutoBetState());
  const [running, setRunning] = useState(false);
  const [settling, setSettling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [quota, setQuota] = useState<ApiQuota | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [lastRunDiag, setLastRunDiag] = useState<{ rejected: RejectedBet[]; totalConsidered: number } | null>(null);
  const [showDiag, setShowDiag] = useState(false);

  useEffect(() => { saveAutoBetState(state); }, [state]);
  useEffect(() => {
    if (hasKey) checkApiQuota().then(setQuota).catch(() => {});
  }, [hasKey]);

  const stats = computeStats(state);

  const handleRun = useCallback(async () => {
    if (running) return;
    if (!state.config.enabled) {
      setMessage('Enable the auto-bettor first — pick a preset and click "Enable" below.');
      return;
    }
    setRunning(true);
    setMessage(null);
    try {
      const result = await runAutoBet(state);
      setState(result.newState);
      setLastRunDiag({ rejected: result.rejected, totalConsidered: result.totalConsidered });
      const rejectedInteresting = result.rejected.filter(r => r.reasonCode !== 'negative_ev' && r.reasonCode !== 'below_min_ev');
      if (result.placed.length > 0) {
        const extra = rejectedInteresting.length > 0 ? ` (${rejectedInteresting.length} rejected — see diagnostics below)` : '';
        setMessage(`Placed ${result.placed.length} bet${result.placed.length > 1 ? 's' : ''} using ${result.apiCalls} API calls.${extra} Click "Settle" after games finish.`);
      } else if (result.sportsAttempted === 0) {
        setMessage('No eligible sports selected — pick at least one sport below (MLS is excluded from auto-betting).');
      } else if (result.sportsFailed.length === result.sportsAttempted) {
        setMessage(`All ${result.sportsAttempted} sport requests failed (${result.sportsFailed.join(', ')}). Check your API key or try again.`);
      } else {
        const diagHint = result.rejected.length > 0 ? ' See diagnostics below for details.' : '';
        setMessage(`Scanned ${result.totalConsidered} moneylines across ${result.sportsAttempted} sport${result.sportsAttempted > 1 ? 's' : ''} — none passed all filters.${diagHint}`);
      }
      checkApiQuota().then(setQuota).catch(() => {});
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to run');
    } finally {
      setRunning(false);
    }
  }, [state, running]);

  const handleSettle = useCallback(async () => {
    if (settling) return;
    setSettling(true);
    setMessage(null);
    try {
      const { newState, settled, apiCalls } = await settleBets(state);
      setState(newState);
      setMessage(settled > 0
        ? `Settled ${settled} bet${settled > 1 ? 's' : ''} (${apiCalls} API calls)`
        : `No completed games to settle yet (${apiCalls} API calls)`);
      checkApiQuota().then(setQuota).catch(() => {});
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to settle');
    } finally {
      setSettling(false);
    }
  }, [state, settling]);

  function updateConfig(partial: Partial<AutoBetConfig>) {
    setState(prev => ({ ...prev, config: { ...prev.config, ...partial } }));
  }

  function applyPreset(preset: typeof PRESETS[number]) {
    updateConfig(preset.config);
    setMessage(`Applied "${preset.name}" preset`);
  }

  function toggleSport(sport: Sport) {
    const current = state.config.sports;
    const next = current.includes(sport) ? current.filter(s => s !== sport) : [...current, sport];
    if (next.length > 0) updateConfig({ sports: next });
  }

  function handleReset() {
    const betCount = state.bets.length;
    const msg = betCount > 0
      ? `This will permanently delete ${betCount} bet${betCount > 1 ? 's' : ''} and reset your bankroll to $1,000. Continue?`
      : 'Reset bankroll to $1,000?';
    if (!window.confirm(msg)) return;
    setState({
      config: state.config,
      bets: [],
      bankroll: 1000,
      initialBankroll: 1000,
      bankrollHistory: [{ date: new Date().toISOString(), balance: 1000 }],
      lastRunAt: null,
      totalApiCalls: 0,
    });
    setMessage('Reset to $1,000. All bet history cleared.');
  }

  const chartData = state.bankrollHistory.map(h => ({
    date: format(parseISO(h.date), 'MMM d'),
    balance: h.balance,
  }));

  if (!hasKey) {
    return (
      <div className="page">
        <h1>AI Auto-Bettor</h1>
        <p className="page-subtitle">Needs an API key to fetch live odds and scores.</p>
        <ApiKeySetup onKeySet={() => setHasKey(true)} />
      </div>
    );
  }

  const pendingBets = state.bets.filter(b => b.status === 'pending');
  const settledBets = [...state.bets].filter(b => b.status !== 'pending').reverse();

  // Estimate API cost per run for display
  const activeSports = state.config.sports.filter(s => !new Set(['MLS', 'UFC']).has(s));
  const estRunCost = activeSports.length; // 1 request per sport for odds
  const estSettleCost = new Set(pendingBets.map(b => b.sport)).size; // 1 per sport with pending

  return (
    <div className="page ai-page">
      {/* Hero */}
      <div className="card ai-hero">
        <div className="ai-hero-header">
          <div>
            <span className="value-eyebrow">Paper trading simulation</span>
            <h1>AI Auto-Bettor</h1>
            <p className="page-subtitle ai-subtitle">
              Scans live odds, finds +EV bets, sizes stakes with Kelly criterion, and tracks P/L.
              Everything uses fake money — no real bets are placed.
              {state.lastRunAt && (
                <span className="last-fetched"> Last run {format(parseISO(state.lastRunAt), 'MMM d, h:mm a')}</span>
              )}
            </p>
          </div>
          <div className="header-actions ai-actions">
            <button className="btn btn-primary" onClick={handleRun} disabled={running}>
              {running ? 'Scanning...' : `Run Now (~${estRunCost} req)`}
            </button>
            <button className="btn btn-secondary" onClick={handleSettle} disabled={settling || pendingBets.length === 0}>
              {settling ? 'Settling...' : `Settle ${pendingBets.length} bet${pendingBets.length !== 1 ? 's' : ''} (~${estSettleCost} req)`}
            </button>
          </div>
        </div>

        {/* How it works — always visible for first-timers */}
        {stats.totalBets === 0 && (
          <div className="ai-onboarding">
            <h3>Getting started (takes 30 seconds)</h3>
            <div className="onboarding-steps">
              <div className="onboarding-step">
                <span className="step-num">1</span>
                <div>
                  <strong>Pick a strategy</strong>
                  <p>Scroll down and click a preset (start with "Balanced"). This sets how aggressive the AI bets.</p>
                </div>
              </div>
              <div className="onboarding-step">
                <span className="step-num">2</span>
                <div>
                  <strong>Turn it on</strong>
                  <p>Click the "Enable" button so the status pill turns green.</p>
                </div>
              </div>
              <div className="onboarding-step">
                <span className="step-num">3</span>
                <div>
                  <strong>Click "Run Now"</strong>
                  <p>The AI scans live odds, finds +EV bets, and "places" them with your $1,000 of fake money.</p>
                </div>
              </div>
              <div className="onboarding-step">
                <span className="step-num">4</span>
                <div>
                  <strong>Come back later and "Settle"</strong>
                  <p>After games finish, click Settle. The AI checks scores and updates your bankroll with wins/losses.</p>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="ai-stats-grid">
          <div className="summary-stat">
            <span className="summary-label">Bankroll</span>
            <strong className={`summary-value ${stats.growth >= 0 ? 'positive' : 'negative'}`}>
              {formatCurrency(state.bankroll)}
            </strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Growth</span>
            <strong className={`summary-value ${stats.growth >= 0 ? 'positive' : 'negative'}`}>
              {stats.growth >= 0 ? '+' : ''}{formatCurrency(stats.growth)} ({stats.growthPercent >= 0 ? '+' : ''}{stats.growthPercent}%)
            </strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Record</span>
            <strong className="summary-value">{stats.wins}W - {stats.losses}L - {stats.pushes}P</strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">ROI</span>
            <strong className={`summary-value ${stats.roi >= 0 ? 'positive' : 'negative'}`}>
              {stats.roi >= 0 ? '+' : ''}{stats.roi}%
            </strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Win Rate</span>
            <strong className="summary-value">{stats.winRate}%</strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">API Used</span>
            <strong className="summary-value">
              {state.totalApiCalls}
              {quota && quota.remaining >= 0 && <span className="text-muted"> ({quota.remaining} left)</span>}
            </strong>
          </div>
        </div>
      </div>

      {message && (
        <div className={`${message.includes('Failed') || message.includes('error') ? 'error-banner' : 'success-banner'}`}>
          {message}
        </div>
      )}

      {quota !== null && quota.remaining >= 0 && quota.remaining < 50 && (
        <div className="warning-banner">API quota running low: {quota.remaining} requests remaining.</div>
      )}

      {/* Chart + Config */}
      <div className="ai-two-col">
        <div className="card ai-chart-card">
          <h2>Bankroll Growth</h2>
          {chartData.length > 1 ? (
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="date" stroke="var(--text-muted)" fontSize={12} />
                <YAxis stroke="var(--text-muted)" fontSize={12} tickFormatter={v => `$${v}`} />
                <Tooltip
                  contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)' }}
                  formatter={(value) => [formatCurrency(Number(value)), 'Balance']}
                />
                <ReferenceLine y={state.initialBankroll} stroke="var(--text-muted)" strokeDasharray="3 3" label={{ value: 'Start', fill: 'var(--text-muted)', fontSize: 11 }} />
                <Line type="monotone" dataKey="balance" stroke="var(--primary)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty-chart">
              <p>Run the auto-bettor to start tracking growth.</p>
            </div>
          )}
        </div>

        <div className="card ai-config-card">
          {/* Presets */}
          <h2>Strategy</h2>
          <div className="preset-grid">
            {PRESETS.map(p => (
              <button key={p.name} className="preset-card" onClick={() => applyPreset(p)}>
                <strong>{p.name}</strong>
                <span className="preset-desc">{p.description}</span>
              </button>
            ))}
          </div>

          {/* Enable toggle */}
          <div className="config-row" style={{ marginTop: '1rem' }}>
            <label className="config-label">
              <span>Auto-Bettor</span>
              <span className={`status-pill ${state.config.enabled ? 'on' : 'off'}`}>
                {state.config.enabled ? 'ON' : 'OFF'}
              </span>
            </label>
            <button
              className={`btn ${state.config.enabled ? 'btn-danger' : 'btn-primary'} btn-sm`}
              onClick={() => updateConfig({ enabled: !state.config.enabled })}
            >
              {state.config.enabled ? 'Disable' : 'Enable'}
            </button>
          </div>

          {/* Sports */}
          <div className="config-row config-sports">
            <label className="config-label">Sports</label>
            <div className="sport-chips">
              {SAFE_SPORTS.map(s => (
                <button
                  key={s}
                  className={`chip ${state.config.sports.includes(s) ? 'chip-active' : ''}`}
                  onClick={() => toggleSport(s)}
                >
                  {state.config.sports.includes(s) && <span className="chip-check">&#10003;</span>}
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Advanced toggle */}
          <button className="btn-link" onClick={() => setShowAdvanced(!showAdvanced)}>
            {showAdvanced ? 'Hide' : 'Show'} advanced settings
          </button>

          {showAdvanced && (
            <div className="advanced-settings">
              <div className="config-row">
                <label className="config-label">
                  <span>Min EV%</span>
                  <span className="config-hint">Only bet when expected edge exceeds this</span>
                </label>
                <input
                  type="number" className="config-input" min={0.5} max={50} step={0.5}
                  value={state.config.minEv}
                  onChange={e => updateConfig({ minEv: parseFloat(e.target.value) || DEFAULT_CONFIG.minEv })}
                />
              </div>

              <div className="config-row">
                <label className="config-label">
                  <span>Max EV%</span>
                  <span className="config-hint">Skip bets above this — likely bad data, not real edges</span>
                </label>
                <input
                  type="number" className="config-input" min={5} max={100} step={1}
                  value={state.config.maxEv}
                  onChange={e => updateConfig({ maxEv: parseFloat(e.target.value) || DEFAULT_CONFIG.maxEv })}
                />
              </div>

              <div className="config-row">
                <label className="config-label">
                  <span>Bet Sizing</span>
                  <span className="config-hint">How much of the "optimal" Kelly amount to actually bet</span>
                </label>
                <select
                  className="config-input"
                  value={state.config.kellyFraction}
                  onChange={e => updateConfig({ kellyFraction: parseFloat(e.target.value) })}
                >
                  <option value={0.0625}>1/16 Kelly — Very Safe</option>
                  <option value={0.125}>1/8 Kelly — Conservative</option>
                  <option value={0.25}>1/4 Kelly — Moderate</option>
                  <option value={0.5}>1/2 Kelly — Aggressive</option>
                </select>
              </div>

              <div className="config-row">
                <label className="config-label">
                  <span>Max Bets / Day</span>
                  <span className="config-hint">Caps how many bets can be placed per run</span>
                </label>
                <input
                  type="number" className="config-input" min={1} max={20}
                  value={state.config.maxBetsPerDay}
                  onChange={e => updateConfig({ maxBetsPerDay: parseInt(e.target.value) || DEFAULT_CONFIG.maxBetsPerDay })}
                />
              </div>

              <div className="config-row">
                <label className="config-label">
                  <span>Max Stake %</span>
                  <span className="config-hint">Never risk more than this % of bankroll on one bet</span>
                </label>
                <input
                  type="number" className="config-input" min={1} max={25} step={1}
                  value={state.config.maxStakePercent}
                  onChange={e => updateConfig({ maxStakePercent: parseInt(e.target.value) || DEFAULT_CONFIG.maxStakePercent })}
                />
              </div>

              <div className="config-row">
                <label className="config-label">
                  <span>Stale Line Protection</span>
                  <span className="config-hint">Skip bets where the odds look outdated or suspicious</span>
                </label>
                <button
                  className={`btn btn-sm ${state.config.skipStale ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => updateConfig({ skipStale: !state.config.skipStale })}
                >
                  {state.config.skipStale ? 'On' : 'Off'}
                </button>
              </div>
            </div>
          )}

          <div className="config-actions">
            <button className="btn btn-danger btn-sm" onClick={handleReset}>Reset to $1,000</button>
          </div>
        </div>
      </div>

      {/* Pending Bets */}
      {pendingBets.length > 0 && (
        <div className="card table-card">
          <h2>Pending Bets ({pendingBets.length})</h2>
          <p className="table-hint">Waiting for games to finish. Click "Settle" to check results.</p>
          <div className="table-shell">
            <table className="data-table ai-table">
              <thead>
                <tr>
                  <th>Sport</th>
                  <th>Game</th>
                  <th>Pick</th>
                  <th>Odds</th>
                  <th>Book</th>
                  <th>Stake</th>
                  <th>To Win</th>
                  <th>EV%</th>
                  <th>Kelly%</th>
                  <th>Game Time</th>
                </tr>
              </thead>
              <tbody>
                {pendingBets.map(bet => (
                  <tr key={bet.id} className="ev-positive-row">
                    <td><span className={`sport-badge sport-${bet.sport.toLowerCase()}`}>{bet.sport}</span></td>
                    <td className="event-cell">{bet.event}</td>
                    <td><strong>{bet.selection}</strong></td>
                    <td className="mono">{formatOdds(bet.odds)}</td>
                    <td>{bet.book}</td>
                    <td className="mono">{formatCurrency(bet.stake)}</td>
                    <td className="mono">{formatCurrency(bet.potentialPayout - bet.stake)}</td>
                    <td className="mono positive">+{bet.ev.toFixed(1)}%</td>
                    <td className="mono">{bet.kellyPercent}%</td>
                    <td>{format(parseISO(bet.commenceTime), 'MMM d, h:mm a')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Diagnostics */}
      {lastRunDiag && lastRunDiag.rejected.length > 0 && (
        <div className="card table-card diag-card">
          <div className="diag-header">
            <h2>Diagnostics</h2>
            <button className="btn btn-sm btn-secondary" onClick={() => setShowDiag(!showDiag)}>
              {showDiag ? 'Hide' : `Show ${lastRunDiag.rejected.length} rejected`}
            </button>
          </div>
          <p className="table-hint">
            Evaluated {lastRunDiag.totalConsidered} moneylines. These were considered but rejected — here's why.
          </p>
          {showDiag && (
            <>
              {/* Summary by reason */}
              <div className="diag-summary">
                {Object.entries(
                  lastRunDiag.rejected.reduce<Record<string, number>>((acc, r) => {
                    const label = ({
                      above_max_ev: 'Suspicious EV (above cap)',
                      below_min_ev: 'Below EV threshold',
                      negative_ev: 'Negative EV',
                      stale_no_fallback: 'Stale / no fallback',
                      duplicate_game: 'Duplicate game',
                      stake_too_small: 'Stake too small',
                      daily_limit: 'Daily limit',
                      three_way: 'Three-way market',
                      wrong_sport: 'Wrong sport',
                      not_moneyline: 'Not moneyline',
                    } as Record<string, string>)[r.reasonCode] ?? r.reasonCode;
                    acc[label] = (acc[label] || 0) + 1;
                    return acc;
                  }, {})
                ).sort((a, b) => b[1] - a[1]).map(([label, count]) => (
                  <span key={label} className="diag-chip">{label}: {count}</span>
                ))}
              </div>

              {/* Interesting rejections (not just below_min_ev or negative_ev) */}
              {(() => {
                const interesting = lastRunDiag.rejected.filter(r =>
                  r.reasonCode !== 'negative_ev' && r.reasonCode !== 'below_min_ev'
                );
                if (interesting.length === 0) return (
                  <p className="empty-text">All rejections were routine (below EV threshold or negative EV). No suspicious data detected.</p>
                );
                return (
                  <div className="table-shell">
                    <table className="data-table ai-table">
                      <thead>
                        <tr>
                          <th>Sport</th>
                          <th>Game</th>
                          <th>Pick</th>
                          <th>Best Odds</th>
                          <th>Book</th>
                          <th>EV%</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {interesting.map((r, i) => (
                          <tr key={i} className={r.reasonCode === 'above_max_ev' ? 'row-suspect' : ''}>
                            <td><span className={`sport-badge sport-${r.sport.toLowerCase()}`}>{r.sport}</span></td>
                            <td className="event-cell">{r.event}</td>
                            <td><strong>{r.selection}</strong></td>
                            <td className="mono">{formatOdds(r.bestOdds)}</td>
                            <td>{r.bestBook}</td>
                            <td className="mono">{r.ev > 0 ? '+' : ''}{r.ev.toFixed(1)}%</td>
                            <td className="diag-reason">{r.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })()}
            </>
          )}
        </div>
      )}

      {/* History */}
      <div className="card table-card">
        <h2>Bet History ({settledBets.length})</h2>
        {settledBets.length === 0 ? (
          <p className="empty-text">No settled bets yet. Run the auto-bettor, wait for games to end, then settle.</p>
        ) : (
          <div className="table-shell">
            <table className="data-table ai-table">
              <thead>
                <tr>
                  <th>Result</th>
                  <th>Sport</th>
                  <th>Game</th>
                  <th>Pick</th>
                  <th>Odds</th>
                  <th>Stake</th>
                  <th>P/L</th>
                  <th>EV%</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {settledBets.map(bet => {
                  const pl = bet.payout - bet.stake;
                  return (
                    <tr key={bet.id} className={bet.status === 'won' ? 'row-won' : bet.status === 'lost' ? 'row-lost' : ''}>
                      <td>
                        <span className={`result-badge result-${bet.status}`}>
                          {bet.status.toUpperCase()}
                        </span>
                      </td>
                      <td><span className={`sport-badge sport-${bet.sport.toLowerCase()}`}>{bet.sport}</span></td>
                      <td className="event-cell">{bet.event}</td>
                      <td><strong>{bet.selection}</strong></td>
                      <td className="mono">{formatOdds(bet.odds)}</td>
                      <td className="mono">{formatCurrency(bet.stake)}</td>
                      <td className={`mono ${pl > 0 ? 'positive' : pl < 0 ? 'negative' : ''}`}>
                        {pl > 0 ? '+' : ''}{formatCurrency(pl)}
                      </td>
                      <td className="mono">+{bet.ev.toFixed(1)}%</td>
                      <td>{format(parseISO(bet.settledAt ?? bet.placedAt), 'MMM d')}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
