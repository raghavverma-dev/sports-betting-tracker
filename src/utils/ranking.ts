/**
 * Bet ranking engine.
 * De-vigs odds, computes EV%, detects stale/outlier lines, and sorts by value.
 */

import { SPORT_KEY_MAP } from './oddsApiClient';
import type { GameOdds } from './oddsApiClient';

// ======= Types =======

export interface RankedBet {
  id: string;
  gameId: string;
  sport: string;
  event: string;
  commenceTime: string;
  selection: string;
  line?: number;
  betType: string;
  bestOdds: number;
  bestBook: string;
  worstOdds: number;
  worstBook: string;
  avgOdds: number;
  impliedProbability: number;
  marketProbability: number;
  ev: number;
  numBooks: number;
  allBookOdds: { book: string; odds: number; lastUpdate: string }[];
  deViggedProbs: { book: string; fairProb: number }[];
  bestBookLastUpdate: string;
  staleWarning: boolean;
  outlierWarning: boolean;
  staleMinutes: number;
  adjustedEv: number | null;
  adjustedBestOdds: number | null;
  adjustedBestBook: string | null;
  adjustedMarketProbability: number | null;
}

// ======= Math helpers (private to this module) =======

function americanToImplied(american: number): number {
  if (american > 0) return 100 / (american + 100);
  return Math.abs(american) / (Math.abs(american) + 100);
}

function americanToDecimal(american: number): number {
  if (american > 0) return american / 100 + 1;
  return 100 / Math.abs(american) + 1;
}

function calcEV(trueProbability: number, american: number): number {
  const decimal = americanToDecimal(american);
  return (trueProbability * decimal - 1) * 100;
}

// ======= Ranking =======

/**
 * Rank all available bets by expected value (EV%).
 *
 * 1. Gather odds from every sportsbook for each outcome.
 * 2. De-vig each bookmaker's market to get fair probabilities.
 * 3. Average de-vigged probabilities = market consensus.
 * 4. EV% at the best available odds vs. consensus.
 * 5. Detect stale and outlier lines, compute adjusted fallback values.
 */
export function rankBets(games: GameOdds[]): RankedBet[] {
  const ranked: RankedBet[] = [];

  for (const game of games) {
    const sport = Object.entries(SPORT_KEY_MAP).find(([, v]) => v === game.sport_key)?.[0] ?? game.sport_title;
    const event = `${game.away_team} @ ${game.home_team}`;

    for (const bookmaker of game.bookmakers) {
      for (const market of bookmaker.markets) {
        const overround = market.outcomes.reduce(
          (sum, o) => sum + americanToImplied(o.price), 0
        );

        for (const outcome of market.outcomes) {
          const pointSuffix = outcome.point != null ? `-${outcome.point}` : '';
          const key = `${game.id}-${market.key}-${outcome.name}${pointSuffix}`;
          let existing = ranked.find(r => r.id === key);

          if (!existing) {
            existing = {
              id: key,
              gameId: game.id,
              sport,
              event,
              commenceTime: game.commence_time,
              selection: outcome.point != null
                ? `${outcome.name} ${outcome.point}` : outcome.name,
              line: outcome.point,
              betType: market.key,
              bestOdds: outcome.price,
              bestBook: bookmaker.title,
              worstOdds: outcome.price,
              worstBook: bookmaker.title,
              avgOdds: 0,
              impliedProbability: 0,
              marketProbability: 0,
              ev: 0,
              numBooks: 0,
              allBookOdds: [],
              deViggedProbs: [],
              bestBookLastUpdate: bookmaker.last_update,
              staleWarning: false,
              outlierWarning: false,
              staleMinutes: 0,
              adjustedEv: null,
              adjustedBestOdds: null,
              adjustedBestBook: null,
              adjustedMarketProbability: null,
            };
            ranked.push(existing);
          }

          existing.allBookOdds.push({ book: bookmaker.title, odds: outcome.price, lastUpdate: bookmaker.last_update });

          const fairProb = overround > 0
            ? americanToImplied(outcome.price) / overround
            : americanToImplied(outcome.price);
          existing.deViggedProbs.push({ book: bookmaker.title, fairProb });

          if (outcome.price > existing.bestOdds) {
            existing.bestOdds = outcome.price;
            existing.bestBook = bookmaker.title;
            existing.bestBookLastUpdate = bookmaker.last_update;
          }
          if (outcome.price < existing.worstOdds) {
            existing.worstOdds = outcome.price;
            existing.worstBook = bookmaker.title;
          }
        }
      }
    }
  }

  for (const bet of ranked) {
    bet.numBooks = bet.allBookOdds.length;

    if (bet.deViggedProbs.length > 0) {
      bet.marketProbability =
        bet.deViggedProbs.reduce((sum, b) => sum + b.fairProb, 0) / bet.deViggedProbs.length;

      if (bet.marketProbability >= 0.5) {
        bet.avgOdds = Math.round(-100 * bet.marketProbability / (1 - bet.marketProbability));
      } else {
        bet.avgOdds = Math.round(100 * (1 - bet.marketProbability) / bet.marketProbability);
      }
    }

    bet.impliedProbability = americanToImplied(bet.bestOdds);
    bet.ev = calcEV(bet.marketProbability, bet.bestOdds);

    // Staleness detection
    const timestamps = bet.allBookOdds
      .map(bo => new Date(bo.lastUpdate).getTime())
      .filter(t => !isNaN(t));
    if (timestamps.length > 1) {
      const freshest = Math.max(...timestamps);
      const bestBookTime = new Date(bet.bestBookLastUpdate).getTime();
      if (!isNaN(bestBookTime)) {
        const lagMs = freshest - bestBookTime;
        bet.staleMinutes = Math.round(lagMs / 60000);
        bet.staleWarning = lagMs >= 10 * 60 * 1000;
      }
    }

    // Outlier detection (excluding best book from consensus)
    if (bet.numBooks >= 3) {
      const othersProbs = bet.deViggedProbs.filter(d => d.book !== bet.bestBook);
      if (othersProbs.length > 0) {
        const consensusExcluding =
          othersProbs.reduce((sum, d) => sum + d.fairProb, 0) / othersProbs.length;
        const probGap = consensusExcluding - bet.impliedProbability;
        bet.outlierWarning = probGap > 0.05;
      }
    }

    // Adjusted values when warnings fire
    if (bet.staleWarning || bet.outlierWarning) {
      const freshest = timestamps.length > 0 ? Math.max(...timestamps) : 0;
      const staleThreshold = 10 * 60 * 1000;

      const cleanBooks = bet.allBookOdds
        .filter(bo => {
          if (bo.book === bet.bestBook) return false;
          const t = new Date(bo.lastUpdate).getTime();
          if (!isNaN(t) && freshest - t >= staleThreshold) return false;
          return true;
        })
        .sort((a, b) => b.odds - a.odds);

      const cleanBookNames = new Set(cleanBooks.map(b => b.book));

      if (cleanBooks.length > 0) {
        const nextBest = cleanBooks[0];
        const cleanProbs = bet.deViggedProbs.filter(d => cleanBookNames.has(d.book));
        const cleanMarket = cleanProbs.length > 0
          ? cleanProbs.reduce((sum, d) => sum + d.fairProb, 0) / cleanProbs.length
          : bet.marketProbability;

        bet.adjustedBestOdds = nextBest.odds;
        bet.adjustedBestBook = nextBest.book;
        bet.adjustedMarketProbability = cleanMarket;
        bet.adjustedEv = calcEV(cleanMarket, nextBest.odds);
      }
    }
  }

  ranked.sort((a, b) => {
    const evA = a.adjustedEv != null ? a.adjustedEv : a.ev;
    const evB = b.adjustedEv != null ? b.adjustedEv : b.ev;
    return evB - evA;
  });

  return ranked;
}
