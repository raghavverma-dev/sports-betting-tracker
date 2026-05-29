import { useApp } from '../context/useApp';
import { calculateOverallStats } from '../utils/stats';
import { formatCurrency } from '../utils/odds';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { format, parseISO } from 'date-fns';

export default function Dashboard() {
  const { state, dispatch } = useApp();
  const stats = calculateOverallStats(state.bets);

  const chartData = state.bankrollHistory.map(s => ({
    date: format(parseISO(s.date), 'MMM d'),
    balance: Number(s.balance.toFixed(2)),
  }));

  const recentBets = state.bets.slice(0, 5);

  return (
    <div className="page">
      <div className="page-header">
        <h1>Dashboard</h1>
        {state.bets.length === 0 && (
          <button className="btn btn-secondary" onClick={() => dispatch({ type: 'LOAD_SAMPLE_DATA' })}>
            Load Sample Data
          </button>
        )}
      </div>

      <div className="stats-grid reveal">
        <div className="stat-card hero">
          <span className="stat-label">Bankroll</span>
          <span className="stat-value">{formatCurrency(state.bankroll)}</span>
          <span className={`stat-delta ${state.bankroll - state.initialBankroll >= 0 ? 'positive' : 'negative'}`}>
            {state.bankroll - state.initialBankroll >= 0 ? '+' : ''}{formatCurrency(state.bankroll - state.initialBankroll)} from start
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Total Bets</span>
          <span className="stat-value">{stats.totalBets}</span>
          <span className="stat-sub">{stats.pending} pending</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Win Rate</span>
          <span className="stat-value">{(stats.winRate * 100).toFixed(1)}%</span>
          <span className="stat-sub">{stats.wins}W - {stats.losses}L - {stats.pushes}P</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Net Profit</span>
          <span className={`stat-value ${stats.netProfit >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(stats.netProfit)}
          </span>
          <span className="stat-sub">ROI: {stats.roi.toFixed(1)}%</span>
        </div>
      </div>

      {chartData.length > 1 && (
        <div className="card chart-card load-rise" style={{ animationDelay: '0.30s' }}>
          <h2>Bankroll Over Time</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#21262d" vertical={false} />
              <XAxis dataKey="date" stroke="#545d68" fontSize={11} tickLine={false} axisLine={{ stroke: '#21262d' }} />
              <YAxis stroke="#545d68" fontSize={11} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#181b1f', border: '1px solid #2f363d', borderRadius: 6, fontFamily: 'JetBrains Mono, monospace', fontSize: 12 }}
                formatter={(value) => [formatCurrency(value as number), 'Balance']}
              />
              <Line
                type="monotone"
                dataKey="balance"
                stroke="#d4f04a"
                strokeWidth={2}
                dot={false}
                activeDot={{ fill: '#d4f04a', r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card load-rise" style={{ animationDelay: '0.38s' }}>
        <h2>Recent Bets</h2>
        {recentBets.length === 0 ? (
          <p className="empty-text">No bets yet. Go to Bet Tracker to place your first bet!</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Sport</th>
                <th>Event</th>
                <th>Selection</th>
                <th>Odds</th>
                <th>Stake</th>
                <th>Status</th>
                <th>P/L</th>
              </tr>
            </thead>
            <tbody>
              {recentBets.map(bet => (
                <tr key={bet.id}>
                  <td>{format(parseISO(bet.date), 'MMM d')}</td>
                  <td><span className={`sport-badge sport-${bet.sport.toLowerCase()}`}>{bet.sport}</span></td>
                  <td>{bet.event}</td>
                  <td>{bet.selection}</td>
                  <td className="mono">{bet.odds > 0 ? '+' : ''}{bet.odds}</td>
                  <td className="mono">{formatCurrency(bet.stake)}</td>
                  <td><span className={`status-badge status-${bet.status}`}>{bet.status}</span></td>
                  <td className={`mono ${(bet.actualPayout ?? 0) - bet.stake >= 0 ? 'positive' : 'negative'}`}>
                    {bet.status === 'pending' ? '—' : formatCurrency((bet.actualPayout ?? 0) - bet.stake)}
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
