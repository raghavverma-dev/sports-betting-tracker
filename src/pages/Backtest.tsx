import { useCallback, useEffect, useState } from 'react';
import { format, parseISO } from 'date-fns';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ScatterChart, Scatter, ReferenceLine,
} from 'recharts';
import {
  ApiError,
  compareBacktest,
  createBacktestRun,
  getBacktestRun,
  listBacktestRuns,
  type BacktestComparison,
  type BacktestRequest,
  type BacktestRunDetail,
  type BacktestRunSummary,
} from '../utils/apiClient';
import { formatCurrency } from '../utils/odds';

type StrategyName = BacktestRequest['strategy'];

const STRATEGY_LABELS: Record<StrategyName, string> = {
  'market-baseline': 'Market Baseline (no bets, forecast quality only)',
  'flat-ev-threshold': 'Flat Stake — bet when EV > threshold',
  'kelly-ev-threshold': 'Kelly Sized — fractional Kelly at EV threshold',
};

// Real ingested NBA seasons the model can be scored on (held-out games only).
// The model trains on the full corpus, so any season exposes some held-out
// games; 2021-22 is the README's reference comparison.
const MODEL_SEASONS = [
  '2017-18-real', '2018-19-real', '2019-20-real', '2020-21-real',
  '2021-22-real', '2022-23-real', '2023-24-real',
];
const DEFAULT_SEASON = '2021-22-real';

function seasonLabel(season: string): string {
  return season.replace('-real', '');
}

export default function Backtest() {
  const [runs, setRuns] = useState<BacktestRunSummary[]>([]);
  const [selected, setSelected] = useState<BacktestRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [comparison, setComparison] = useState<BacktestComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const [season, setSeason] = useState<string>(DEFAULT_SEASON);

  const [req, setReq] = useState<BacktestRequest>({
    strategy: 'market-baseline',
    sport: 'NBA',
    market: 'h2h',
    initial_bankroll: 1000,
    min_ev: 2,
    kelly_fraction: 0.25,
    max_stake_percent: 5,
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listBacktestRuns();
      setRuns(list);
      setBackendDown(false);
      if (list.length > 0 && selected === null) {
        setSelected(await getBacktestRun(list[0].id));
      }
    } catch (err) {
      setBackendDown(err instanceof TypeError);
      setError(err instanceof Error ? err.message : 'Failed to load runs');
    } finally {
      setLoading(false);
    }
  }, [selected]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function selectRun(id: number) {
    try {
      setSelected(await getBacktestRun(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load run');
    }
  }

  async function run() {
    setRunning(true);
    setError(null);
    try {
      const detail = await createBacktestRun(req);
      setSelected(detail);
      setRuns(await listBacktestRuns());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Backend error (${err.status}): ${err.message}`);
      } else if (err instanceof TypeError) {
        setBackendDown(true);
        setError('Cannot reach the backend. Is `make dev` running?');
      } else {
        setError(err instanceof Error ? err.message : 'Failed to run backtest');
      }
    } finally {
      setRunning(false);
    }
  }

  async function runComparison() {
    setComparing(true);
    setError(null);
    setComparison(null);
    try {
      const result = await compareBacktest({ ...req, season });
      setComparison(result);
      setSelected(result.model);
      setRuns(await listBacktestRuns());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Backend error (${err.status}): ${err.message}`);
      } else if (err instanceof TypeError) {
        setBackendDown(true);
        setError('Cannot reach the backend. Is `make dev` running?');
      } else {
        setError(err instanceof Error ? err.message : 'Failed to run comparison');
      }
    } finally {
      setComparing(false);
    }
  }

  if (backendDown) {
    return (
      <div className="page">
        <h1>Backtest</h1>
        <div className="card">
          <h2>Backend not reachable</h2>
          <p className="empty-text">
            The Backtest page talks to the FastAPI backend at{' '}
            <code>{import.meta.env.VITE_API_URL ?? 'http://localhost:8000'}</code>.
            Start it with <code>make dev</code> (or <code>docker compose up --build</code>)
            from the project root.
          </p>
        </div>
      </div>
    );
  }

  const equityData = selected?.equity_curve?.map(([ts, balance]) => ({
    date: format(parseISO(ts), 'MMM d'),
    balance: Number(balance.toFixed(2)),
  })) ?? [];

  const calibrationData = selected?.calibration?.filter(b => b.count > 0).map(b => ({
    predicted: Number((b.predicted_mean * 100).toFixed(1)),
    empirical: Number((b.empirical_mean * 100).toFixed(1)),
    count: b.count,
  })) ?? [];

  return (
    <div className="page">
      <div className="page-header">
        <h1>Backtest</h1>
        <span className="page-subtitle">
          Evaluate forecasting strategies against historical closing odds.
        </span>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {comparison && <ComparisonCard comparison={comparison} season={season} />}

      <div className="ai-two-col">
        <div className="card">
          <h2>Run a new backtest</h2>
          <div className="config-row">
            <label className="config-label">Strategy</label>
            <select
              className="config-input"
              value={req.strategy}
              onChange={e => setReq({ ...req, strategy: e.target.value as StrategyName })}
            >
              {(Object.entries(STRATEGY_LABELS) as [StrategyName, string][]).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </div>
          <div className="config-row">
            <label className="config-label">Sport</label>
            <select
              className="config-input"
              value={req.sport}
              onChange={e => setReq({ ...req, sport: e.target.value })}
            >
              <option value="NBA">NBA</option>
            </select>
          </div>
          <div className="config-row">
            <label className="config-label">Initial bankroll</label>
            <input
              type="number" className="config-input" min={100} step={100}
              value={req.initial_bankroll}
              onChange={e => setReq({ ...req, initial_bankroll: Number(e.target.value) || 1000 })}
            />
          </div>
          <div className="config-row">
            <label className="config-label">Season (for model compare)</label>
            <select
              className="config-input"
              value={season}
              onChange={e => setSeason(e.target.value)}
            >
              {MODEL_SEASONS.map(s => (
                <option key={s} value={s}>{seasonLabel(s)}</option>
              ))}
            </select>
          </div>
          {req.strategy !== 'market-baseline' && (
            <>
              <div className="config-row">
                <label className="config-label">Min EV %</label>
                <input
                  type="number" className="config-input" min={0} step={0.5}
                  value={req.min_ev}
                  onChange={e => setReq({ ...req, min_ev: Number(e.target.value) || 0 })}
                />
              </div>
              {req.strategy === 'kelly-ev-threshold' && (
                <>
                  <div className="config-row">
                    <label className="config-label">Kelly fraction</label>
                    <select
                      className="config-input"
                      value={req.kelly_fraction}
                      onChange={e => setReq({ ...req, kelly_fraction: Number(e.target.value) })}
                    >
                      <option value={0.0625}>1/16 Kelly</option>
                      <option value={0.125}>1/8 Kelly</option>
                      <option value={0.25}>1/4 Kelly</option>
                      <option value={0.5}>1/2 Kelly</option>
                    </select>
                  </div>
                  <div className="config-row">
                    <label className="config-label">Max stake %</label>
                    <input
                      type="number" className="config-input" min={1} max={25} step={0.5}
                      value={req.max_stake_percent}
                      onChange={e => setReq({ ...req, max_stake_percent: Number(e.target.value) || 5 })}
                    />
                  </div>
                </>
              )}
            </>
          )}
          <div className="config-actions">
            <button className="btn btn-primary" onClick={run} disabled={running || comparing}>
              {running ? 'Running…' : 'Run backtest'}
            </button>
            <button className="btn btn-secondary" onClick={refresh} disabled={loading}>
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
          <div className="config-compare">
            <button
              className="btn btn-accent"
              onClick={runComparison}
              disabled={comparing || running}
            >
              {comparing ? 'Comparing…' : `Compare Model vs Market (${seasonLabel(season)})`}
            </button>
            <p className="table-hint">
              Runs the LightGBM model and the de-vigged market on the same
              held-out {seasonLabel(season)} games, then scores both. The model
              only predicts games it never trained on.
            </p>
          </div>
        </div>

        <div className="card">
          <h2>Run detail</h2>
          {!selected ? (
            <p className="empty-text">Run a backtest to see metrics here.</p>
          ) : (
            <>
              <div className="ai-stats-grid">
                <div className="summary-stat">
                  <span className="summary-label">Strategy</span>
                  <strong className="summary-value">{selected.strategy}</strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Games</span>
                  <strong className="summary-value">{selected.games_evaluated}</strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Bets placed</span>
                  <strong className="summary-value">{selected.bets_placed}</strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Final bankroll</span>
                  <strong className={`summary-value ${(selected.final_bankroll ?? 0) >= selected.initial_bankroll ? 'positive' : 'negative'}`}>
                    {formatCurrency(selected.final_bankroll ?? 0)}
                  </strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">ROI</span>
                  <strong className={`summary-value ${(selected.roi ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                    {(selected.roi ?? 0).toFixed(2)}%
                  </strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Max drawdown</span>
                  <strong className="summary-value">
                    {((selected.max_drawdown ?? 0) * 100).toFixed(2)}%
                  </strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Brier score</span>
                  <strong className="summary-value">
                    {selected.brier_score?.toFixed(4) ?? '—'}
                  </strong>
                </div>
                <div className="summary-stat">
                  <span className="summary-label">Log loss</span>
                  <strong className="summary-value">
                    {selected.log_loss?.toFixed(4) ?? '—'}
                  </strong>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {equityData.length > 1 && (
        <div className="card chart-card">
          <h2>Equity curve</h2>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={equityData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="date" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} tickFormatter={v => `$${v}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444', borderRadius: 8 }}
                formatter={v => [formatCurrency(v as number), 'Balance']}
              />
              <Line type="monotone" dataKey="balance" stroke="#6366f1" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {calibrationData.length > 0 && (
        <div className="card chart-card">
          <h2>Calibration</h2>
          <p className="table-hint">
            A well-calibrated forecaster sits on the diagonal: predicted probability ≈
            empirical win rate. Each point is one decile bucket of predictions.
          </p>
          <ResponsiveContainer width="100%" height={320}>
            <ScatterChart>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis
                type="number" dataKey="predicted" domain={[0, 100]}
                stroke="#888" fontSize={12}
                label={{ value: 'Predicted (%)', position: 'insideBottom', offset: -4, fill: '#888' }}
              />
              <YAxis
                type="number" dataKey="empirical" domain={[0, 100]}
                stroke="#888" fontSize={12}
                label={{ value: 'Empirical (%)', angle: -90, position: 'insideLeft', fill: '#888' }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444', borderRadius: 8 }}
                formatter={(v, name) => [`${(v as number).toFixed(1)}%`, name]}
              />
              <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]} stroke="#666" strokeDasharray="4 4" />
              <Scatter data={calibrationData} fill="#22d3ee" />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card table-card" style={{ marginTop: '1.5rem' }}>
        <h2>Past runs</h2>
        {runs.length === 0 ? (
          <p className="empty-text">No runs yet. Kick one off with the form above.</p>
        ) : (
          <div className="table-shell">
            <table className="data-table">
              <thead>
                <tr>
                  <th>ID</th><th>When</th><th>Strategy</th><th>Sport</th>
                  <th>Games</th><th>Bets</th><th>ROI</th><th>Brier</th><th>Log loss</th>
                </tr>
              </thead>
              <tbody>
                {runs.map(r => (
                  <tr key={r.id} onClick={() => selectRun(r.id)} style={{ cursor: 'pointer' }} className={selected?.id === r.id ? 'expanded' : ''}>
                    <td>#{r.id}</td>
                    <td>{format(parseISO(r.started_at), 'MMM d, HH:mm')}</td>
                    <td>{r.strategy}</td>
                    <td>{r.sport}</td>
                    <td>{r.games_evaluated}</td>
                    <td>{r.bets_placed}</td>
                    <td className={`mono ${(r.roi ?? 0) >= 0 ? 'positive' : 'negative'}`}>
                      {(r.roi ?? 0).toFixed(2)}%
                    </td>
                    <td className="mono">{r.brier_score?.toFixed(4) ?? '—'}</td>
                    <td className="mono">{r.log_loss?.toFixed(4) ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ComparisonCard({
  comparison,
  season,
}: {
  comparison: BacktestComparison;
  season: string;
}) {
  const { market, model } = comparison;
  const marketBrier = market.brier_score;
  const modelBrier = model.brier_score;

  // Lower Brier is the better forecaster. Guard against nulls (a season with
  // no h2h coverage would yield null metrics).
  const haveBoth = marketBrier != null && modelBrier != null;
  const modelWins = haveBoth && modelBrier < marketBrier;
  const gap = haveBoth ? Math.abs(modelBrier - marketBrier) : null;

  const fmt = (v: number | null | undefined) => (v == null ? '—' : v.toFixed(4));

  return (
    <div className="card comparison-card">
      <div className="comparison-header">
        <h2>Model vs Market — {seasonLabel(season)} (held out)</h2>
        <span className="page-subtitle">
          Same {model.games_evaluated} games, two forecasters. Lower Brier wins.
        </span>
      </div>

      <div className="comparison-grid">
        <div className={`comparison-col ${!modelWins && haveBoth ? 'winner' : ''}`}>
          <span className="comparison-source">Market (de-vigged)</span>
          <div className="comparison-metric">
            <span className="summary-label">Brier</span>
            <strong className="comparison-big mono">{fmt(marketBrier)}</strong>
          </div>
          <div className="comparison-sub">
            <span>Log loss</span><span className="mono">{fmt(market.log_loss)}</span>
          </div>
          <div className="comparison-sub">
            <span>ROI</span>
            <span className={`mono ${(market.roi ?? 0) >= 0 ? 'positive' : 'negative'}`}>
              {(market.roi ?? 0).toFixed(2)}%
            </span>
          </div>
        </div>

        <div className={`comparison-col ${modelWins ? 'winner' : ''}`}>
          <span className="comparison-source">LightGBM model</span>
          <div className="comparison-metric">
            <span className="summary-label">Brier</span>
            <strong className="comparison-big mono">{fmt(modelBrier)}</strong>
          </div>
          <div className="comparison-sub">
            <span>Log loss</span><span className="mono">{fmt(model.log_loss)}</span>
          </div>
          <div className="comparison-sub">
            <span>ROI</span>
            <span className={`mono ${(model.roi ?? 0) >= 0 ? 'positive' : 'negative'}`}>
              {(model.roi ?? 0).toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      <p className="comparison-verdict">
        {!haveBoth ? (
          <>This season lacks the moneyline coverage needed to score both forecasters.</>
        ) : modelWins ? (
          <>
            The model edges the market by {gap!.toFixed(4)} Brier here — a rare
            win. NBA closing lines are extremely sharp, so treat this as a
            close call, not a durable edge.
          </>
        ) : (
          <>
            The market wins by {gap!.toFixed(4)} Brier — as expected. NBA closing
            lines are very sharp, and a model with no player, injury, or lineup
            data should not beat them. The value here is the honest,
            leakage-safe pipeline that proves the comparison.
          </>
        )}
      </p>
    </div>
  );
}
