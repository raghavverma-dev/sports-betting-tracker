import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { LayoutDashboard, ClipboardList, Star, Zap, FlaskConical, BarChart3 } from 'lucide-react';
import { useApp } from '../context/useApp';
import { formatCurrency } from '../utils/odds';
import { loadAutoBetState, subscribeToAutoBetState } from '../utils/autoBettor';

export default function Layout() {
  const { state } = useApp();
  const location = useLocation();

  const [aiBankroll, setAiBankroll] = useState(() => loadAutoBetState().bankroll);
  useEffect(() => {
    return subscribeToAutoBetState(() => {
      setAiBankroll(loadAutoBetState().bankroll);
    });
  }, []);

  const isAiPage = location.pathname === '/ai-bettor';
  const displayBankroll = isAiPage ? aiBankroll : state.bankroll;
  const bankrollLabel = isAiPage ? 'AI Bankroll' : 'Bankroll';

  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-header">
          <h1 className="logo">BetEdge</h1>
          <span className="logo-sub">Sports Betting Tracker</span>
        </div>

        <div className="sidebar-bankroll">
          <span className="bankroll-label">{bankrollLabel}</span>
          <span className="bankroll-value">{formatCurrency(displayBankroll)}</span>
        </div>

        <div className="nav-links">
          <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} end>
            <LayoutDashboard className="nav-icon" size={17} strokeWidth={2} /> <span>Dashboard</span>
          </NavLink>
          <NavLink to="/tracker" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <ClipboardList className="nav-icon" size={17} strokeWidth={2} /> <span>Bet Tracker</span>
          </NavLink>
          <NavLink to="/value" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Star className="nav-icon" size={17} strokeWidth={2} /> <span>Value Finder</span>
          </NavLink>
          <NavLink to="/ai-bettor" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <Zap className="nav-icon" size={17} strokeWidth={2} /> <span>AI Bettor</span>
          </NavLink>
          <NavLink to="/backtest" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <FlaskConical className="nav-icon" size={17} strokeWidth={2} /> <span>Backtest</span>
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <BarChart3 className="nav-icon" size={17} strokeWidth={2} /> <span>Analytics</span>
          </NavLink>
        </div>

        <div className="sidebar-footer">
          <span>All data stored locally</span>
        </div>
      </nav>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
