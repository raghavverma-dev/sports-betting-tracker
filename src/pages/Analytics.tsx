import { useApp } from '../context/useApp';
import { calculateAllSportStats, calculateOverallStats } from '../utils/stats';
import { formatCurrency, formatOdds } from '../utils/odds';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  PieChart, Pie, Cell, Legend,
} from 'recharts';

const COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#ef4444', '#10b981', '#ec4899', '#8b5cf6', '#14b8a6'];

export default function Analytics() {
  const { state } = useApp();
  const sportStats = calculateAllSportStats(state.bets);
  const overall = calculateOverallStats(state.bets);

  if (state.bets.length === 0) {
    return (
      <div className="page">
        <h1>Analytics</h1>
        <div className="card">
          <p className="empty-text">No bets to analyze yet. Start tracking bets to see your analytics!</p>
        </div>
      </div>
    );
  }

  const profitBySport = sportStats.map(s => ({
    sport: s.sport,
    profit: Number(s.netProfit.toFixed(2)),
    roi: Number(s.roi.toFixed(1)),
  }));

  const betDistribution = sportStats.map(s => ({
    name: s.sport,
    value: s.totalBets,
  }));

  const winLossData = sportStats.map(s => ({
    sport: s.sport,
    wins: s.wins,
    losses: s.losses,
    pushes: s.pushes,
  }));

  // Bet type breakdown
  const betTypeMap = new Map<string, { count: number; profit: number }>();
  state.bets.forEach(b => {
    const existing = betTypeMap.get(b.betType) ?? { count: 0, profit: 0 };
    const pl = b.status === 'pending' ? 0 : (b.actualPayout ?? 0) - b.stake;
    betTypeMap.set(b.betType, { count: existing.count + 1, profit: existing.profit + pl });
  });
  const betTypeData = Array.from(betTypeMap.entries()).map(([type, data]) => ({
    type: type.replace('_', '/'),
    count: data.count,
    profit: Number(data.profit.toFixed(2)),
  }));

  // Sportsbook breakdown
  const bookMap = new Map<string, { count: number; profit: number }>();
  state.bets.forEach(b => {
    const existing = bookMap.get(b.sportsbook) ?? { count: 0, profit: 0 };
    const pl = b.status === 'pending' ? 0 : (b.actualPayout ?? 0) - b.stake;
    bookMap.set(b.sportsbook, { count: existing.count + 1, profit: existing.profit + pl });
  });
  const bookData = Array.from(bookMap.entries()).map(([book, data]) => ({
    book,
    count: data.count,
    profit: Number(data.profit.toFixed(2)),
  }));

  return (
    <div className="page">
      <h1>Analytics</h1>

      <div className="stats-grid">
        <div className="stat-card">
          <span className="stat-label">Total Wagered</span>
          <span className="stat-value">{formatCurrency(overall.totalStaked)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Total Returned</span>
          <span className="stat-value">{formatCurrency(overall.totalPayout)}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Net Profit</span>
          <span className={`stat-value ${overall.netProfit >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(overall.netProfit)}
          </span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Overall ROI</span>
          <span className={`stat-value ${overall.roi >= 0 ? 'positive' : 'negative'}`}>
            {overall.roi.toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="charts-grid">
        <div className="card chart-card">
          <h2>Profit by Sport</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={profitBySport}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="sport" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} tickFormatter={(v) => `$${v}`} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444', borderRadius: 8 }}
                formatter={(value) => [formatCurrency(value as number), 'Profit']}
              />
              <Bar dataKey="profit" radius={[4, 4, 0, 0]}>
                {profitBySport.map((entry, i) => (
                  <Cell key={i} fill={entry.profit >= 0 ? '#10b981' : '#ef4444'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card chart-card">
          <h2>Bet Distribution</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={betDistribution}
                dataKey="value"
                nameKey="name"
                cx="50%"
                cy="50%"
                outerRadius={100}
                label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
              >
                {betDistribution.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444', borderRadius: 8 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="card chart-card">
          <h2>Wins / Losses by Sport</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={winLossData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="sport" stroke="#888" fontSize={12} />
              <YAxis stroke="#888" fontSize={12} />
              <Tooltip contentStyle={{ backgroundColor: '#1e1e2e', border: '1px solid #444', borderRadius: 8 }} />
              <Legend />
              <Bar dataKey="wins" fill="#10b981" stackId="a" radius={[0, 0, 0, 0]} />
              <Bar dataKey="losses" fill="#ef4444" stackId="a" radius={[0, 0, 0, 0]} />
              <Bar dataKey="pushes" fill="#f59e0b" stackId="a" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="card" style={{ marginTop: '2rem' }}>
        <h2>Sport Breakdown</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Sport</th>
              <th>Bets</th>
              <th>W-L-P</th>
              <th>Win Rate</th>
              <th>Staked</th>
              <th>Profit</th>
              <th>ROI</th>
              <th>Avg Odds</th>
            </tr>
          </thead>
          <tbody>
            {sportStats.map(s => (
              <tr key={s.sport}>
                <td><span className={`sport-badge sport-${s.sport.toLowerCase()}`}>{s.sport}</span></td>
                <td>{s.totalBets}</td>
                <td>{s.wins}-{s.losses}-{s.pushes}</td>
                <td>{(s.winRate * 100).toFixed(1)}%</td>
                <td className="mono">{formatCurrency(s.totalStaked)}</td>
                <td className={`mono ${s.netProfit >= 0 ? 'positive' : 'negative'}`}>{formatCurrency(s.netProfit)}</td>
                <td className={`mono ${s.roi >= 0 ? 'positive' : 'negative'}`}>{s.roi.toFixed(1)}%</td>
                <td className="mono">{formatOdds(s.averageOdds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="analytics-sub-grid" style={{ marginTop: '2rem' }}>
        <div className="card">
          <h2>By Bet Type</h2>
          <table className="data-table">
            <thead>
              <tr><th>Type</th><th>Count</th><th>Profit</th></tr>
            </thead>
            <tbody>
              {betTypeData.map(d => (
                <tr key={d.type}>
                  <td>{d.type}</td>
                  <td>{d.count}</td>
                  <td className={`mono ${d.profit >= 0 ? 'positive' : 'negative'}`}>{formatCurrency(d.profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h2>By Sportsbook</h2>
          <table className="data-table">
            <thead>
              <tr><th>Book</th><th>Bets</th><th>Profit</th></tr>
            </thead>
            <tbody>
              {bookData.map(d => (
                <tr key={d.book}>
                  <td>{d.book}</td>
                  <td>{d.count}</td>
                  <td className={`mono ${d.profit >= 0 ? 'positive' : 'negative'}`}>{formatCurrency(d.profit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
