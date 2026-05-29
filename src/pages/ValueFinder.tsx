import { useState, useEffect, useCallback, Fragment, type MouseEvent } from 'react';
import {
  formatOdds,
  formatProbability,
  formatCurrency,
  calculatePayout,
  impliedProbability as americanToImplied,
} from '../utils/odds';
import { ApiError, fetchRankedOddsForSport, type RankedOddsBet } from '../utils/apiClient';
import { SUPPORTED_SPORTS } from '../utils/oddsApi';
import { format, parseISO, startOfDay, endOfDay, addDays, addMonths } from 'date-fns';
import { useApp } from '../context/useApp';
import type { BetFormData, BetType, Sport } from '../types';

type MarketFilter = 'all' | 'h2h' | 'spreads' | 'totals';

const MARKET_LABELS: Record<MarketFilter, string> = {
  all: 'All',
  h2h: 'Moneylines',
  spreads: 'Spreads',
  totals: 'Totals',
};

const BET_TYPE_LABELS: Record<string, string> = {
  h2h: 'ML',
  spreads: 'Spread',
  totals: 'Total',
};

const TRACKABLE_BET_TYPES: Record<string, BetType> = {
  h2h: 'moneyline',
  spreads: 'spread',
  totals: 'over_under',
};

type TimeFilter = 'today' | 'week' | 'month' | 'all';

const TIME_LABELS: Record<TimeFilter, string> = {
  today: 'Today',
  week: 'This Week',
  month: 'This Month',
  all: 'All',
};

function getTimeCutoff(filter: TimeFilter): Date | null {
  const now = new Date();
  switch (filter) {
    case 'today': return endOfDay(now);
    case 'week': return endOfDay(addDays(startOfDay(now), 6));
    case 'month': return endOfDay(addMonths(startOfDay(now), 1));
    case 'all': return null;
  }
}

function InfoTip({ text }: { text: string }) {
  return (
    <span className="info-tip">
      <span className="info-tip-icon">?</span>
      <span className="info-tip-content">{text}</span>
    </span>
  );
}

const ALL_MARKETS = ['h2h', 'spreads', 'totals'] as const;

const API_KEY_SETUP_HINT =
  'Add a free key from the-odds-api.com to ODDS_API_KEY in backend/.env, ' +
  'then restart the backend (the frontend never sees the key).';

// Turn a fetch failure into a message a user can act on. The backend already
// sends a descriptive 503 when ODDS_API_KEY is unset; we append concrete
// setup steps so the fix is obvious from the banner alone.
function describeOddsError(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (reason.status === 503 && /ODDS_API_KEY/i.test(reason.message)) {
      return `${reason.message} ${API_KEY_SETUP_HINT}`;
    }
    if (reason.status === 502 && /api key/i.test(reason.message)) {
      return `${reason.message} ${API_KEY_SETUP_HINT}`;
    }
    return reason.message;
  }
  if (reason instanceof Error) return reason.message;
  return 'Failed to fetch odds from the backend.';
}

export default function ValueFinder() {
  const { state, dispatch } = useApp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [rankedBets, setRankedBets] = useState<RankedOddsBet[]>([]);
  const [selectedSports, setSelectedSports] = useState<Set<string>>(new Set([SUPPORTED_SPORTS[0]]));
  const [marketFilter, setMarketFilter] = useState<MarketFilter>('h2h');
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('today');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [lastFetched, setLastFetched] = useState<Date | null>(null);
  const [pendingBet, setPendingBet] = useState<RankedOddsBet | null>(null);
  const [stakeInput, setStakeInput] = useState('');
  const [showGuide, setShowGuide] = useState(() => {
    return localStorage.getItem('hide-betting-guide') !== 'true';
  });

  // Cost: each sport × each market = 1 API request.
  //   e.g. 2 sports × 1 market = 2 requests, 1 sport × All (3 markets) = 3
  const fetchOdds = useCallback(async () => {
    const sports = [...selectedSports];
    if (sports.length === 0) return;

    setLoading(true);
    setError(null);
    try {
      const markets = marketFilter === 'all' ? [...ALL_MARKETS] : [marketFilter];
      const requests = sports.flatMap(sport =>
        markets.map(market => ({ sport, market }))
      );

      const results = await Promise.allSettled(
        requests.map(({ sport, market }) => fetchRankedOddsForSport(sport, market))
      );
      const ranked = results.flatMap(result =>
        result.status === 'fulfilled' ? result.value : []
      );
      const failures = results.filter(result => result.status === 'rejected');

      setRankedBets(ranked);
      setLastFetched(new Date());
      if (failures.length > 0) {
        const firstFailure = failures[0];
        const message = firstFailure.status === 'rejected'
          ? describeOddsError(firstFailure.reason)
          : 'Failed to fetch odds from the backend.';
        setError(
          ranked.length > 0
            ? `${failures.length} market request${failures.length > 1 ? 's' : ''} failed: ${message}`
            : message
        );
      }
    } catch (err) {
      setError(describeOddsError(err));
    } finally {
      setLoading(false);
    }
  }, [selectedSports, marketFilter]);

  useEffect(() => {
    void fetchOdds();
  }, [fetchOdds]);

  function toggleGuide() {
    const next = !showGuide;
    setShowGuide(next);
    localStorage.setItem('hide-betting-guide', next ? 'false' : 'true');
  }

  function toggleSport(sport: string) {
    setSelectedSports(prev => {
      const next = new Set(prev);
      if (next.has(sport)) {
        // Don't allow deselecting the last sport
        if (next.size > 1) next.delete(sport);
      } else {
        next.add(sport);
      }
      return next;
    });
  }

  function handleTrackBet(
    bet: RankedOddsBet,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    event.stopPropagation();

    const betType = TRACKABLE_BET_TYPES[bet.betType];
    if (!betType) {
      setError(`Cannot track market type: ${bet.betType}`);
      return;
    }

    const defaultStake = Math.max(1, Math.min(10, Math.floor(state.bankroll)));
    setStakeInput(String(defaultStake));
    setPendingBet(bet);
  }

  function confirmTrackBet() {
    const bet = pendingBet;
    if (!bet) return;

    const betType = TRACKABLE_BET_TYPES[bet.betType];
    if (!betType) {
      setError(`Cannot track market type: ${bet.betType}`);
      setPendingBet(null);
      return;
    }

    const stake = Number(stakeInput);
    if (!Number.isFinite(stake) || stake <= 0) {
      setError('Enter a valid positive stake to track this bet.');
      return;
    }

    const odds = bet.adjustedBestOdds ?? bet.bestOdds;
    const sportsbook = bet.adjustedBestBook ?? bet.bestBook;
    const estimatedProbability = bet.adjustedMarketProbability ?? bet.marketProbability;
    const ev = bet.adjustedEv ?? bet.ev;
    const formData: BetFormData = {
      sport: bet.sport as Sport,
      betType,
      event: bet.event,
      selection: bet.selection,
      odds,
      stake,
      sportsbook,
      notes: [
        `Tracked from Value Finder at ${format(new Date(), 'MMM d, h:mm a')}.`,
        `Market probability: ${formatProbability(estimatedProbability)}.`,
        `EV at tracked line: ${ev > 0 ? '+' : ''}${ev.toFixed(1)}%.`,
        (bet.staleWarning || bet.outlierWarning) ? 'Original best line was flagged stale/outlier; tracked adjusted clean line.' : '',
      ].filter(Boolean).join(' '),
      estimatedProbability,
    };

    dispatch({ type: 'ADD_BET', payload: formData });
    setError(null);
    setPendingBet(null);
    setSuccess(`Tracked ${bet.selection} at ${formatOdds(odds)} for $${stake.toFixed(2)}.`);
  }

  const requestCost = selectedSports.size * (marketFilter === 'all' ? 3 : 1);

  const timeCutoff = getTimeCutoff(timeFilter);
  const filteredBets = rankedBets.filter(b => {
    if (marketFilter !== 'all' && b.betType !== marketFilter) return false;
    if (timeCutoff) {
      const gameTime = parseISO(b.commenceTime);
      if (gameTime < startOfDay(new Date()) || gameTime > timeCutoff) return false;
    }
    return true;
  });

  const gameCount = new Set(rankedBets.map(b => b.gameId)).size;
  const bookCount = new Set(rankedBets.flatMap(b => b.allBookOdds.map(book => book.book))).size;
  const positiveEvCount = filteredBets.filter(b => (b.adjustedEv ?? b.ev) > 0).length;
  const activeMarketLabel = MARKET_LABELS[marketFilter];

  return (
    <div className="page value-page">
      <div className="card value-hero">
        <div className="value-hero-header">
          <div className="value-heading">
            <span className="value-eyebrow">Live market board</span>
            <h1>Value Bet Finder</h1>
            <p className="page-subtitle value-subtitle">
              Live odds from {bookCount} sportsbooks across {gameCount} games.
              Ranked by expected value so the strongest rows stay near the top.
              {lastFetched && (
                <span className="last-fetched"> Updated {format(lastFetched, 'h:mm a')}</span>
              )}
            </p>
          </div>
          <div className="header-actions value-actions">
            <button className="btn btn-secondary" onClick={toggleGuide}>
              {showGuide ? 'Hide' : 'Show'} Guide
            </button>
            <button className="btn btn-primary" onClick={fetchOdds} disabled={loading}>
              {loading ? 'Loading...' : 'Refresh Odds'}
            </button>
          </div>
        </div>

        <div className="value-summary-grid">
          <div className="summary-stat">
            <span className="summary-label">Market</span>
            <strong className="summary-value">{activeMarketLabel}</strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Games</span>
            <strong className="summary-value">{gameCount}</strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Sportsbooks</span>
            <strong className="summary-value">{bookCount}</strong>
          </div>
          <div className="summary-stat">
            <span className="summary-label">Positive EV</span>
            <strong className={`summary-value ${positiveEvCount > 0 ? 'positive' : ''}`}>
              {positiveEvCount}
            </strong>
          </div>
        </div>
      </div>

      {showGuide && (
        <div className="guide-card card">
          <h2>How to Read This Table</h2>
          <div className="guide-grid">
            <div className="guide-item">
              <h3>What are odds?</h3>
              <p>
                Odds tell you how much you'd win on a bet. In American format:
                <strong> +200</strong> means bet $100 to win $200 profit.
                <strong> -200</strong> means bet $200 to win $100 profit.
                The bigger the + number, the bigger the underdog (and the bigger the payout).
              </p>
            </div>
            <div className="guide-item">
              <h3>What is "Best Odds"?</h3>
              <p>
                Different sportsbooks offer different odds on the same bet.
                <strong> Best Odds</strong> is the most favorable price available across all books.
                Always bet at the book with the best odds -- you get a bigger payout for the same risk.
              </p>
            </div>
            <div className="guide-item">
              <h3>What is "EV%" (Expected Value)?</h3>
              <p>
                This is the key number. We estimate the "true" win chance by averaging what all sportsbooks
                think, then check: does the best book pay more than that's worth?
                <strong className="guide-highlight"> Positive EV = good bet.</strong> Over many bets, +EV bets make money.
              </p>
            </div>
            <div className="guide-item">
              <h3>What are the two "Win Chance" columns?</h3>
              <p>
                <strong>Market</strong> is the average across all books -- our best guess at the real probability.
                <strong> Best Book</strong> is what the best odds imply. When the best book shows a lower
                chance than the market, you're getting a deal -- that gap is your edge.
              </p>
            </div>
            <div className="guide-item">
              <h3>How do I use this?</h3>
              <p>
                Look for <span className="guide-highlight">green +EV% rows</span> at the top. Click a row to
                compare odds across all sportsbooks. Place your bet at the highlighted book.
                The higher the EV%, the better the value. Even small edges add up over time.
              </p>
            </div>
            <div className="guide-item">
              <h3>What are the market types?</h3>
              <p>
                <strong>Moneylines:</strong> Simply pick who wins the game.<br/>
                <strong>Spreads:</strong> A team must win by a certain number of points.<br/>
                <strong>Totals:</strong> Bet on whether the combined score goes over or under a number.
              </p>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {success && (
        <div className="success-banner">
          {success} View it on the Dashboard or Bet Tracker.
        </div>
      )}

      <div className="card toolbar-card">
        <div className="filter-bar value-filter-bar">
          <div className="filter-controls">
            <div className="sport-chips">
              {SUPPORTED_SPORTS.map(s => (
                <button
                  key={s}
                  className={`chip ${selectedSports.has(s) ? 'chip-active' : ''}`}
                  onClick={() => toggleSport(s)}
                >
                  {selectedSports.has(s) && <span className="chip-check">&#10003;</span>}
                  {s}
                </button>
              ))}
            </div>
            <div className="market-tabs">
              {(Object.entries(MARKET_LABELS) as [MarketFilter, string][]).map(([key, label]) => (
                <button
                  key={key}
                  className={`tab ${marketFilter === key ? 'active' : ''}`}
                  onClick={() => setMarketFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="market-tabs">
              {(Object.entries(TIME_LABELS) as [TimeFilter, string][]).map(([key, label]) => (
                <button
                  key={key}
                  className={`tab ${timeFilter === key ? 'active' : ''}`}
                  onClick={() => setTimeFilter(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="filter-meta">
            <span className="table-hint">Click any row to expand | Refresh queries {requestCost} market{requestCost > 1 ? 's' : ''}</span>
            <span className="filter-count">
              {filteredBets.length} bets found
              {positiveEvCount > 0 && <span className="positive"> ({positiveEvCount} +EV)</span>}
            </span>
          </div>
        </div>
      </div>

      {loading && filteredBets.length === 0 ? (
        <div className="card">
          <div className="loading-state">
            <div className="spinner" />
            <p>Fetching live odds across sportsbooks...</p>
          </div>
        </div>
      ) : filteredBets.length === 0 ? (
        <div className="card">
          <p className="empty-text">
            No odds available for this selection right now. Try a different sport or market, or check back when games are upcoming.
          </p>
        </div>
      ) : (
        <div className="card table-card">
          <div className="table-card-header">
            <div>
              <h2>Ranked Board</h2>
              <p className="table-hint">Sticky headers and horizontal scrolling make the board easier to scan.</p>
            </div>
          </div>
          <div className="table-shell">
            <table className="data-table value-table">
            <thead>
              <tr>
                <th className="rank-col">
                  #
                  <InfoTip text="Rank -- sorted by EV%, so #1 is the best value bet right now." />
                </th>
                <th className="sport-col">Sport</th>
                <th className="type-col">Type</th>
                <th className="game-col">Game</th>
                <th className="time-col">
                  Time
                  <InfoTip text="When the game starts. Odds shift as game time approaches." />
                </th>
                <th className="pick-col">
                  Pick
                  <InfoTip text="The team or outcome you'd be betting on." />
                </th>
                <th className="odds-col">
                  Best Odds
                  <InfoTip text="The best odds available across all sportsbooks. +200 means bet $100 to win $200 profit. -200 means bet $200 to win $100 profit." />
                </th>
                <th className="book-col">
                  Best Book
                  <InfoTip text="The sportsbook currently offering the best listed odds for this row." />
                </th>
                <th className="ev-col">
                  EV%
                  <InfoTip text="Expected Value -- the most important column. Positive EV means the best odds are better than fair value. Over many bets, +EV bets make money. Calculated as: (market win chance x best payout) - 1." />
                </th>
                <th className="prob-col">
                  Win Chance (Market)
                  <InfoTip text="The average implied probability across all sportsbooks. This is our best estimate of the real chance of winning. The market is usually pretty accurate." />
                </th>
                <th className="prob-col">
                  Win Chance (Best Book)
                  <InfoTip text="The implied probability at the best available odds. When this is lower than the Market column, you're getting better odds than the true chance -- that's the value." />
                </th>
                <th className="books-col">
                  Books
                  <InfoTip text="How many sportsbooks are offering odds on this bet. More books = more price competition." />
                </th>
                <th className="track-col">Track</th>
              </tr>
            </thead>
            <tbody>
              {filteredBets.map((bet, i) => (
                <Fragment key={bet.id}>
                  <tr
                    className={`value-row ${expandedRow === bet.id ? 'expanded' : ''} ${bet.ev > 0 ? 'ev-positive-row' : ''} ${i < 3 ? 'top-pick' : ''}`}
                    onClick={() => setExpandedRow(expandedRow === bet.id ? null : bet.id)}
                  >
                    <td className="rank-cell">
                      {i < 3 ? (
                        <span className={`rank-badge rank-${i + 1}`}>{i + 1}</span>
                      ) : (
                        <span className="rank-num">{i + 1}</span>
                      )}
                    </td>
                    <td><span className={`sport-badge sport-${bet.sport.toLowerCase()}`}>{bet.sport}</span></td>
                    <td className="type-cell">{BET_TYPE_LABELS[bet.betType] ?? bet.betType}</td>
                    <td className="event-cell game-cell">{bet.event}</td>
                    <td className="time-cell">{format(parseISO(bet.commenceTime), 'MMM d, h:mm a')}</td>
                    <td className="selection-cell pick-cell"><strong>{bet.selection}</strong></td>
                    <td className="mono best-odds odds-cell">
                      {bet.adjustedBestOdds != null ? (
                        <>
                          <span>{formatOdds(bet.adjustedBestOdds)}</span>
                          <span className="ev-raw">{formatOdds(bet.bestOdds)}</span>
                        </>
                      ) : formatOdds(bet.bestOdds)}
                    </td>
                    <td className="book-cell">
                      <span className="best-book">{bet.adjustedBestBook ?? bet.bestBook}</span>
                      {bet.adjustedBestBook && (
                        <span className="ev-raw">{bet.bestBook}</span>
                      )}
                    </td>
                    <td className={`mono ev-cell ${bet.adjustedEv != null ? 'has-adjusted' : bet.ev > 0 ? 'positive' : 'negative'}`}>
                      {bet.adjustedEv != null ? (
                        <>
                          <span className={`ev-value ${bet.adjustedEv > 0 ? 'positive' : 'negative'}`}>
                            {bet.adjustedEv > 0 ? '+' : ''}{bet.adjustedEv.toFixed(1)}%
                          </span>
                          <span className="ev-raw" title={`Raw EV at suspect ${bet.bestBook}: ${bet.ev > 0 ? '+' : ''}${bet.ev.toFixed(1)}%`}>
                            was {bet.ev > 0 ? '+' : ''}{bet.ev.toFixed(1)}%
                          </span>
                        </>
                      ) : (
                        <span className={`ev-value ${bet.ev > 0 ? 'positive' : 'negative'}`}>
                          {bet.ev > 0 ? '+' : ''}{bet.ev.toFixed(1)}%
                        </span>
                      )}
                      {(bet.staleWarning || bet.outlierWarning) && (
                        <span className="ev-warnings">
                          {bet.staleWarning && (
                            <span className="ev-badge stale-badge" title={`Best book quote is ${bet.staleMinutes}min older than freshest`}>STALE</span>
                          )}
                          {bet.outlierWarning && (
                            <span className="ev-badge outlier-badge" title="Best odds are suspiciously far from market consensus (excluded from ranking)">OUTLIER</span>
                          )}
                        </span>
                      )}
                    </td>
                    <td className="prob-cell">
                      {bet.adjustedMarketProbability != null ? (
                        <>
                          <span>{formatProbability(bet.adjustedMarketProbability)}</span>
                          <span className="ev-raw">{formatProbability(bet.marketProbability)}</span>
                        </>
                      ) : formatProbability(bet.marketProbability)}
                    </td>
                    <td className="prob-cell">
                      {bet.adjustedBestOdds != null
                        ? formatProbability(americanToImplied(bet.adjustedBestOdds))
                        : formatProbability(bet.impliedProbability)}
                    </td>
                    <td className="books-cell">{bet.numBooks}</td>
                    <td className="track-cell">
                      <button
                        className="btn-sm btn-track"
                        onClick={(event) => handleTrackBet(bet, event)}
                        title="Add this live line to the paper Bet Tracker"
                      >
                        Track
                      </button>
                    </td>
                  </tr>
                  {expandedRow === bet.id && (
                    <tr key={`${bet.id}-detail`} className="detail-row">
                      <td colSpan={13}>
                        <div className="book-comparison">
                          <h3>Odds Comparison for: {bet.selection}</h3>
                          <p className="book-comparison-hint">
                            Each chip shows one sportsbook's odds. The green one has the best deal -- that's where you should bet.
                          </p>
                          <div className="book-grid">
                            {bet.allBookOdds
                              .sort((a, b) => b.odds - a.odds)
                              .map((bo, j) => {
                                const updatedAt = bo.lastUpdate ? format(parseISO(bo.lastUpdate), 'h:mm:ss a') : '';
                                return (
                                  <div
                                    key={j}
                                    className={`book-chip ${bo.book === bet.bestBook ? (bet.adjustedEv != null ? 'suspect' : 'best') : ''} ${bet.adjustedBestBook && bo.book === bet.adjustedBestBook ? 'best' : ''}`}
                                  >
                                    <span className="book-name">{bo.book}</span>
                                    <span className={`book-odds mono ${bo.book === (bet.adjustedBestBook ?? bet.bestBook) ? 'positive' : ''}`}>
                                      {formatOdds(bo.odds)}
                                    </span>
                                    {updatedAt && <span className="book-updated">Updated {updatedAt}</span>}
                                  </div>
                                );
                              })}
                          </div>
                          <div className="detail-explainer">
                            {bet.adjustedEv != null && bet.adjustedBestOdds != null && bet.adjustedBestBook ? (
                              <>
                                <p>
                                  <strong>Raw EV (suspect):</strong> {formatOdds(bet.bestOdds)} at {bet.bestBook} would
                                  give {bet.ev > 0 ? '+' : ''}{bet.ev.toFixed(1)}% EV, but this line is flagged
                                  as unreliable (see warnings below).
                                </p>
                                <p>
                                  <strong>Adjusted EV:</strong> Using the next-best clean book, {formatOdds(bet.adjustedBestOdds)} at {bet.adjustedBestBook} gives
                                  {' '}<strong className={bet.adjustedEv > 0 ? 'positive' : 'negative'}>
                                    {bet.adjustedEv > 0 ? '+' : ''}{bet.adjustedEv.toFixed(1)}%
                                  </strong> EV.
                                  {bet.adjustedEv > 0
                                    ? ' There may still be value here, but at a more realistic level.'
                                    : ' After adjustment, this bet is no longer positive EV.'}
                                </p>
                              </>
                            ) : (
                              <p>
                                <strong>How this EV was calculated:</strong> The market average across {bet.numBooks} books
                                estimates a {formatProbability(bet.marketProbability)} chance of winning. But the best
                                odds ({formatOdds(bet.bestOdds)} at {bet.bestBook}) only imply
                                a {formatProbability(bet.impliedProbability)} chance -- that's a
                                {' '}<strong className={bet.ev > 0 ? 'positive' : 'negative'}>
                                  {bet.ev > 0 ? '+' : ''}{bet.ev.toFixed(1)}%
                                </strong> expected value.
                                {bet.ev > 0
                                  ? ' Over many bets at this edge, you\'d expect to profit.'
                                  : ' The payout doesn\'t quite justify the risk based on market consensus.'}
                              </p>
                            )}
                            {(bet.staleWarning || bet.outlierWarning) && (
                              <div className="detail-warnings">
                                {bet.staleWarning && (
                                  <p className="detail-warning stale">
                                    <strong>Stale line:</strong> {bet.bestBook}'s quote
                                    is {bet.staleMinutes} minutes older than the freshest quote for
                                    this bet. The line has likely moved. This book's odds have been
                                    excluded from the ranking and EV calculation above.
                                  </p>
                                )}
                                {bet.outlierWarning && (
                                  <p className="detail-warning outlier">
                                    <strong>Outlier:</strong> {bet.bestBook}'s odds ({formatOdds(bet.bestOdds)})
                                    imply a {formatProbability(bet.impliedProbability)} chance, but the
                                    other {bet.numBooks - 1} books average{' '}
                                    {formatProbability(bet.adjustedMarketProbability ?? bet.marketProbability)}
                                    {' '}(excluding {bet.bestBook}).
                                    {' '}This {(((bet.adjustedMarketProbability ?? bet.marketProbability) - bet.impliedProbability) * 100).toFixed(1)}pp
                                    gap is too large to trust. The suspect line has been excluded from the
                                    adjusted EV and ranking.
                                  </p>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
            </table>
          </div>
        </div>
      )}

      {pendingBet && (
        <TrackBetModal
          bet={pendingBet}
          stake={stakeInput}
          onStakeChange={setStakeInput}
          onConfirm={confirmTrackBet}
          onCancel={() => setPendingBet(null)}
        />
      )}
    </div>
  );
}

function TrackBetModal({
  bet,
  stake,
  onStakeChange,
  onConfirm,
  onCancel,
}: {
  bet: RankedOddsBet;
  stake: string;
  onStakeChange: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const odds = bet.adjustedBestOdds ?? bet.bestOdds;
  const book = bet.adjustedBestBook ?? bet.bestBook;
  const ev = bet.adjustedEv ?? bet.ev;
  const stakeNum = Number(stake);
  const validStake = Number.isFinite(stakeNum) && stakeNum > 0;
  const payout = validStake ? calculatePayout(stakeNum, odds) : 0;
  const profit = payout - stakeNum;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
      if (e.key === 'Enter' && validStake) onConfirm();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel, onConfirm, validStake]);

  return (
    <div className="track-modal-overlay" onClick={onCancel}>
      <div
        className="track-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Track this bet"
        onClick={e => e.stopPropagation()}
      >
        <div className="track-modal-head">
          <span className="track-modal-eyebrow">Track a paper bet</span>
          <h3 className="track-modal-title">{bet.selection}</h3>
          <p className="track-modal-event">{bet.event}</p>
        </div>

        <div className="track-modal-meta">
          <div className="track-meta-item">
            <span className="track-meta-label">Odds</span>
            <strong className="track-meta-value mono">{formatOdds(odds)}</strong>
          </div>
          <div className="track-meta-item">
            <span className="track-meta-label">Book</span>
            <strong className="track-meta-value">{book}</strong>
          </div>
          <div className="track-meta-item">
            <span className="track-meta-label">EV</span>
            <strong className={`track-meta-value mono ${ev >= 0 ? 'positive' : 'negative'}`}>
              {ev > 0 ? '+' : ''}{ev.toFixed(1)}%
            </strong>
          </div>
        </div>

        <label className="track-stake-label" htmlFor="track-stake">
          Stake
          <span className="track-stake-hint">
            Play money for record-keeping — no real wager is placed.
          </span>
        </label>
        <div className="track-stake-field">
          <span className="track-stake-prefix">$</span>
          <input
            id="track-stake"
            type="number"
            min={1}
            step={1}
            autoFocus
            className="track-stake-input"
            value={stake}
            onChange={e => onStakeChange(e.target.value)}
          />
        </div>

        <div className="track-payout">
          {validStake ? (
            <>
              <span>To win <strong className="positive mono">{formatCurrency(profit)}</strong></span>
              <span className="track-payout-total">
                Returns {formatCurrency(payout)}
              </span>
            </>
          ) : (
            <span className="track-payout-empty">Enter a positive amount.</span>
          )}
        </div>

        <div className="track-modal-actions">
          <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>
          <button className="btn btn-primary" onClick={onConfirm} disabled={!validStake}>
            Track bet
          </button>
        </div>
      </div>
    </div>
  );
}
