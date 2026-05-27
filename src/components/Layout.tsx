import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
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
            <span className="nav-icon">&#9632;</span> Dashboard
          </NavLink>
          <NavLink to="/tracker" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="nav-icon">&#9998;</span> Bet Tracker
          </NavLink>
          <NavLink to="/value" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="nav-icon">&#9733;</span> Value Finder
          </NavLink>
          <NavLink to="/ai-bettor" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="nav-icon">&#9889;</span> AI Bettor
          </NavLink>
          <NavLink to="/backtest" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="nav-icon">&#8855;</span> Backtest
          </NavLink>
          <NavLink to="/analytics" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            <span className="nav-icon">&#9776;</span> Analytics
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
