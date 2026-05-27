import type { Bet, Sport, SportStats } from '../types';

const SPORTS: Sport[] = ['NBA', 'NFL', 'MLB', 'NHL', 'NCAAF', 'NCAAB', 'MLS', 'UFC'];

export function calculateSportStats(bets: Bet[], sport: Sport): SportStats {
  const sportBets = bets.filter(b => b.sport === sport);
  const settled = sportBets.filter(b => b.status !== 'pending');
  const wins = sportBets.filter(b => b.status === 'won').length;
  const losses = sportBets.filter(b => b.status === 'lost').length;
  const pushes = sportBets.filter(b => b.status === 'push').length;
  const pending = sportBets.filter(b => b.status === 'pending').length;
  const totalStaked = settled.reduce((sum, b) => sum + b.stake, 0);
  const totalPayout = settled.reduce((sum, b) => sum + (b.actualPayout ?? 0), 0);
  const netProfit = totalPayout - totalStaked;

  const avgOdds = sportBets.length > 0
    ? sportBets.reduce((sum, b) => sum + b.odds, 0) / sportBets.length
    : 0;

  return {
    sport,
    totalBets: sportBets.length,
    wins,
    losses,
    pushes,
    pending,
    winRate: settled.length > 0 ? wins / settled.length : 0,
    totalStaked,
    totalPayout,
    netProfit,
    roi: totalStaked > 0 ? (netProfit / totalStaked) * 100 : 0,
    averageOdds: Math.round(avgOdds),
  };
}

export function calculateAllSportStats(bets: Bet[]): SportStats[] {
  return SPORTS
    .map(sport => calculateSportStats(bets, sport))
    .filter(s => s.totalBets > 0);
}

export function calculateOverallStats(bets: Bet[]) {
  const settled = bets.filter(b => b.status !== 'pending');
  const wins = bets.filter(b => b.status === 'won').length;
  const losses = bets.filter(b => b.status === 'lost').length;
  const pushes = bets.filter(b => b.status === 'push').length;
  const pending = bets.filter(b => b.status === 'pending').length;
  const totalStaked = settled.reduce((sum, b) => sum + b.stake, 0);
  const totalPayout = settled.reduce((sum, b) => sum + (b.actualPayout ?? 0), 0);
  const netProfit = totalPayout - totalStaked;

  return {
    totalBets: bets.length,
    wins,
    losses,
    pushes,
    pending,
    winRate: settled.length > 0 ? wins / settled.length : 0,
    totalStaked,
    totalPayout,
    netProfit,
    roi: totalStaked > 0 ? (netProfit / totalStaked) * 100 : 0,
  };
}
