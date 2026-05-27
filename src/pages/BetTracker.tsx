import { useState } from 'react';
import { useApp } from '../context/useApp';
import type { BetFormData, BetStatus, BetType, Sport } from '../types';
import { formatCurrency, formatOdds, calculateEV, kellyStake, impliedProbability, formatProbability } from '../utils/odds';
import { format, parseISO } from 'date-fns';

const SPORTS: Sport[] = ['NBA', 'NFL', 'MLB', 'NHL', 'NCAAF', 'NCAAB', 'MLS', 'UFC'];
const BET_TYPES: { value: BetType; label: string }[] = [
  { value: 'moneyline', label: 'Moneyline' },
  { value: 'spread', label: 'Spread' },
  { value: 'over_under', label: 'Over/Under' },
  { value: 'prop', label: 'Prop' },
  { value: 'parlay', label: 'Parlay' },
  { value: 'teaser', label: 'Teaser' },
];
const SPORTSBOOKS = ['DraftKings', 'FanDuel', 'BetMGM', 'Caesars', 'PointsBet', 'BetRivers', 'Other'];

const emptyForm: BetFormData = {
  sport: 'NBA',
  betType: 'moneyline',
  event: '',
  selection: '',
  odds: -110,
  stake: 0,
  sportsbook: 'DraftKings',
  notes: '',
  estimatedProbability: null,
};

export default function BetTracker() {
  const { state, dispatch } = useApp();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<BetFormData>(emptyForm);
  const [filter, setFilter] = useState<{ sport: string; status: string }>({ sport: 'all', status: 'all' });

  const filteredBets = state.bets.filter(b => {
    if (filter.sport !== 'all' && b.sport !== filter.sport) return false;
    if (filter.status !== 'all' && b.status !== filter.status) return false;
    return true;
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.event || !form.selection || form.stake <= 0) return;
    dispatch({ type: 'ADD_BET', payload: form });
    setForm(emptyForm);
    setShowForm(false);
  }

  function handleSettle(id: string, status: BetStatus) {
    dispatch({ type: 'UPDATE_BET_STATUS', payload: { id, status } });
  }

  const ev = form.estimatedProbability != null
    ? calculateEV(form.estimatedProbability, form.odds)
    : null;
  const fullKelly = form.estimatedProbability != null
    ? kellyStake(form.estimatedProbability, form.odds)
    : null;
  const quarterKelly = fullKelly != null ? fullKelly * 0.25 : null;
  const implied = impliedProbability(form.odds);

  return (
    <div className="page">
      <div className="page-header">
        <h1>Bet Tracker</h1>
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : '+ New Bet'}
        </button>
      </div>

      {showForm && (
        <div className="card form-card">
          <h2>Place a Bet</h2>
          <form onSubmit={handleSubmit} className="bet-form">
            <div className="form-row">
              <div className="form-group">
                <label>Sport</label>
                <select value={form.sport} onChange={e => setForm({ ...form, sport: e.target.value as Sport })}>
                  {SPORTS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Bet Type</label>
                <select value={form.betType} onChange={e => setForm({ ...form, betType: e.target.value as BetType })}>
                  {BET_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label>Sportsbook</label>
                <select value={form.sportsbook} onChange={e => setForm({ ...form, sportsbook: e.target.value })}>
                  {SPORTSBOOKS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            </div>

            <div className="form-row">
              <div className="form-group flex-2">
                <label>Event</label>
                <input type="text" value={form.event} onChange={e => setForm({ ...form, event: e.target.value })} placeholder="e.g., Lakers vs Celtics" />
              </div>
              <div className="form-group flex-2">
                <label>Selection</label>
                <input type="text" value={form.selection} onChange={e => setForm({ ...form, selection: e.target.value })} placeholder="e.g., Lakers ML" />
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label>American Odds</label>
                <input type="number" value={form.odds} onChange={e => setForm({ ...form, odds: Number(e.target.value) })} />
                <span className="form-hint">Implied: {formatProbability(implied)}</span>
              </div>
              <div className="form-group">
                <label>Stake ($)</label>
                <input type="number" min={0} step={5} value={form.stake || ''} onChange={e => setForm({ ...form, stake: Number(e.target.value) })} placeholder="0.00" />
              </div>
              <div className="form-group">
                <label>Your Est. Probability (%)</label>
                <input
                  type="number" min={0} max={100} step={1}
                  value={form.estimatedProbability != null ? (form.estimatedProbability * 100).toFixed(0) : ''}
                  onChange={e => {
                    const v = e.target.value;
                    setForm({ ...form, estimatedProbability: v ? Number(v) / 100 : null });
                  }}
                  placeholder="Optional"
                />
              </div>
            </div>

            {ev != null && (
              <div className="ev-preview">
                <div className={`ev-badge ${ev > 0 ? 'positive' : 'negative'}`}>
                  EV: {ev > 0 ? '+' : ''}{ev.toFixed(2)}%
                </div>
                <div className="kelly-badge">
                  ¼ Kelly (recommended): {formatCurrency(quarterKelly! * state.bankroll)} ({(quarterKelly! * 100).toFixed(1)}%)
                </div>
                <div className="kelly-badge kelly-badge-muted">
                  Full Kelly: {formatCurrency(fullKelly! * state.bankroll)} ({(fullKelly! * 100).toFixed(1)}%)
                </div>
                {ev > 0 && <span className="value-tag">+EV Bet!</span>}
              </div>
            )}

            <div className="form-group">
              <label>Notes</label>
              <textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} placeholder="Optional notes..." rows={2} />
            </div>

            <button type="submit" className="btn btn-primary btn-lg" disabled={!form.event || !form.selection || form.stake <= 0}>
              Place Bet — {formatCurrency(form.stake)}
            </button>
          </form>
        </div>
      )}

      <div className="filter-bar">
        <select value={filter.sport} onChange={e => setFilter({ ...filter, sport: e.target.value })}>
          <option value="all">All Sports</option>
          {SPORTS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filter.status} onChange={e => setFilter({ ...filter, status: e.target.value })}>
          <option value="all">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="won">Won</option>
          <option value="lost">Lost</option>
          <option value="push">Push</option>
        </select>
        <span className="filter-count">{filteredBets.length} bets</span>
      </div>

      <div className="card">
        {filteredBets.length === 0 ? (
          <p className="empty-text">No bets to display. Place your first bet above!</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Sport</th>
                <th>Event</th>
                <th>Selection</th>
                <th>Type</th>
                <th>Odds</th>
                <th>Stake</th>
                <th>EV</th>
                <th>Status</th>
                <th>P/L</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredBets.map(bet => (
                <tr key={bet.id}>
                  <td>{format(parseISO(bet.date), 'MMM d')}</td>
                  <td><span className={`sport-badge sport-${bet.sport.toLowerCase()}`}>{bet.sport}</span></td>
                  <td>{bet.event}</td>
                  <td>{bet.selection}</td>
                  <td>{bet.betType.replace('_', '/')}</td>
                  <td className="mono">{formatOdds(bet.odds)}</td>
                  <td className="mono">{formatCurrency(bet.stake)}</td>
                  <td className={`mono ${(bet.expectedValue ?? 0) > 0 ? 'positive' : 'negative'}`}>
                    {bet.expectedValue != null ? `${bet.expectedValue > 0 ? '+' : ''}${bet.expectedValue.toFixed(1)}%` : '—'}
                  </td>
                  <td><span className={`status-badge status-${bet.status}`}>{bet.status}</span></td>
                  <td className={`mono ${(bet.actualPayout ?? 0) - bet.stake >= 0 ? 'positive' : 'negative'}`}>
                    {bet.status === 'pending' ? '—' : formatCurrency((bet.actualPayout ?? 0) - bet.stake)}
                  </td>
                  <td className="actions-cell">
                    {bet.status === 'pending' && (
                      <>
                        <button className="btn-sm btn-won" onClick={() => handleSettle(bet.id, 'won')}>W</button>
                        <button className="btn-sm btn-lost" onClick={() => handleSettle(bet.id, 'lost')}>L</button>
                        <button className="btn-sm btn-push" onClick={() => handleSettle(bet.id, 'push')}>P</button>
                      </>
                    )}
                    <button className="btn-sm btn-delete" onClick={() => dispatch({ type: 'DELETE_BET', payload: bet.id })}>X</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
