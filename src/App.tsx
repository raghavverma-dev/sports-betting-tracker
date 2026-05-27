import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import BetTracker from './pages/BetTracker';
import ValueFinder from './pages/ValueFinder';
import Analytics from './pages/Analytics';
import AiBettor from './pages/AiBettor';
import Backtest from './pages/Backtest';
import './App.css';

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tracker" element={<BetTracker />} />
            <Route path="/value" element={<ValueFinder />} />
            <Route path="/ai-bettor" element={<AiBettor />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/analytics" element={<Analytics />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
