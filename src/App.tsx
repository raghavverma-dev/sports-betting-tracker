import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppProvider } from './context/AppContext';
import Layout from './components/Layout';
import './App.css';

const Dashboard = lazy(() => import('./pages/Dashboard'));
const BetTracker = lazy(() => import('./pages/BetTracker'));
const ValueFinder = lazy(() => import('./pages/ValueFinder'));
const Analytics = lazy(() => import('./pages/Analytics'));
const AiBettor = lazy(() => import('./pages/AiBettor'));
const Backtest = lazy(() => import('./pages/Backtest'));

function PageFallback() {
  return (
    <div className="page">
      <div className="card">
        <p className="empty-text">Loading...</p>
      </div>
    </div>
  );
}

function App() {
  return (
    <AppProvider>
      <BrowserRouter>
        <Suspense fallback={<PageFallback />}>
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
        </Suspense>
      </BrowserRouter>
    </AppProvider>
  );
}

export default App;
