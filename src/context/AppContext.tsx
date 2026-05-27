import { useReducer, useEffect, type ReactNode } from 'react';
import { v4 as uuidv4 } from 'uuid';
import type { AppState, Bet } from '../types';
import { calculatePayout, impliedProbability, calculateEV, kellyStake } from '../utils/odds';
import { loadState, saveState } from '../utils/storage';
import { AppContext } from './appContextDef';
import type { Action } from './appContextDef';

function appReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'ADD_BET': {
      const form = action.payload;
      const implied = impliedProbability(form.odds);
      const ev = form.estimatedProbability != null
        ? calculateEV(form.estimatedProbability, form.odds)
        : null;
      const kelly = form.estimatedProbability != null
        ? kellyStake(form.estimatedProbability, form.odds)
        : null;

      const bet: Bet = {
        id: uuidv4(),
        sport: form.sport,
        betType: form.betType,
        status: 'pending',
        event: form.event,
        selection: form.selection,
        odds: form.odds,
        stake: form.stake,
        potentialPayout: calculatePayout(form.stake, form.odds),
        actualPayout: null,
        date: new Date().toISOString(),
        sportsbook: form.sportsbook,
        notes: form.notes,
        estimatedProbability: form.estimatedProbability,
        impliedProbability: implied,
        expectedValue: ev,
        kellyStake: kelly,
      };

      const newBankroll = state.bankroll - form.stake;
      return {
        ...state,
        bets: [bet, ...state.bets],
        bankroll: newBankroll,
        bankrollHistory: [
          ...state.bankrollHistory,
          { date: new Date().toISOString(), balance: newBankroll },
        ],
      };
    }

    case 'UPDATE_BET_STATUS': {
      const { id, status } = action.payload;
      const bets = state.bets.map(bet => {
        if (bet.id !== id) return bet;
        let actualPayout: number | null = null;
        if (status === 'won') actualPayout = bet.potentialPayout;
        else if (status === 'push') actualPayout = bet.stake;
        else if (status === 'lost') actualPayout = 0;
        return { ...bet, status, actualPayout };
      });

      const updatedBet = bets.find(b => b.id === id)!;
      let bankrollDelta = 0;
      const oldBet = state.bets.find(b => b.id === id)!;

      // Reverse old settlement if it was already settled
      if (oldBet.status === 'won') bankrollDelta -= oldBet.potentialPayout;
      else if (oldBet.status === 'push') bankrollDelta -= oldBet.stake;
      else if (oldBet.status === 'pending') bankrollDelta += 0; // stake already deducted

      // Apply new settlement
      if (status === 'won') bankrollDelta += updatedBet.potentialPayout;
      else if (status === 'push') bankrollDelta += updatedBet.stake;

      const newBankroll = state.bankroll + bankrollDelta;
      return {
        ...state,
        bets,
        bankroll: newBankroll,
        bankrollHistory: [
          ...state.bankrollHistory,
          { date: new Date().toISOString(), balance: newBankroll },
        ],
      };
    }

    case 'DELETE_BET': {
      const bet = state.bets.find(b => b.id === action.payload);
      if (!bet) return state;
      // Reverse the bet's full P/L impact so the bankroll matches the
      // state it would be in if the bet had never existed. For pending
      // bets actualPayout is null, so this reduces to refunding the stake.
      const refund = bet.stake - (bet.actualPayout ?? 0);
      const newBankroll = state.bankroll + refund;
      return {
        ...state,
        bets: state.bets.filter(b => b.id !== action.payload),
        bankroll: newBankroll,
        bankrollHistory: [
          ...state.bankrollHistory,
          { date: new Date().toISOString(), balance: newBankroll },
        ],
      };
    }

    case 'SET_BANKROLL':
      return {
        ...state,
        bankroll: action.payload,
        bankrollHistory: [
          ...state.bankrollHistory,
          { date: new Date().toISOString(), balance: action.payload },
        ],
      };

    case 'SET_INITIAL_BANKROLL':
      return {
        ...state,
        initialBankroll: action.payload,
        bankroll: action.payload,
        bankrollHistory: [{ date: new Date().toISOString(), balance: action.payload }],
      };

    case 'LOAD_SAMPLE_DATA':
      return generateSampleData(state);

    default:
      return state;
  }
}

function generateSampleData(state: AppState): AppState {
  const sampleBets: Bet[] = [
    {
      id: uuidv4(), sport: 'NBA', betType: 'moneyline', status: 'won',
      event: 'Lakers vs Celtics', selection: 'Lakers ML', odds: 150,
      stake: 50, potentialPayout: 125, actualPayout: 125,
      date: '2026-04-10T18:00:00Z', sportsbook: 'DraftKings',
      notes: 'Lakers home game', estimatedProbability: 0.48,
      impliedProbability: 0.4, expectedValue: 20, kellyStake: 0.05,
    },
    {
      id: uuidv4(), sport: 'NBA', betType: 'spread', status: 'lost',
      event: 'Warriors vs Nuggets', selection: 'Warriors -3.5', odds: -110,
      stake: 100, potentialPayout: 190.91, actualPayout: 0,
      date: '2026-04-09T20:00:00Z', sportsbook: 'FanDuel',
      notes: '', estimatedProbability: 0.55,
      impliedProbability: 0.524, expectedValue: 0.45, kellyStake: 0.01,
    },
    {
      id: uuidv4(), sport: 'NFL', betType: 'over_under', status: 'won',
      event: 'Chiefs vs Bills', selection: 'Over 48.5', odds: -105,
      stake: 75, potentialPayout: 146.43, actualPayout: 146.43,
      date: '2026-04-06T13:00:00Z', sportsbook: 'BetMGM',
      notes: 'High-scoring offenses', estimatedProbability: 0.58,
      impliedProbability: 0.512, expectedValue: 12.6, kellyStake: 0.04,
    },
    {
      id: uuidv4(), sport: 'MLB', betType: 'moneyline', status: 'won',
      event: 'Yankees vs Red Sox', selection: 'Yankees ML', odds: -130,
      stake: 130, potentialPayout: 230, actualPayout: 230,
      date: '2026-04-08T19:00:00Z', sportsbook: 'Caesars',
      notes: 'Ace pitching matchup', estimatedProbability: 0.62,
      impliedProbability: 0.565, expectedValue: 4.78, kellyStake: 0.03,
    },
    {
      id: uuidv4(), sport: 'NHL', betType: 'moneyline', status: 'lost',
      event: 'Bruins vs Rangers', selection: 'Rangers ML', odds: 120,
      stake: 60, potentialPayout: 132, actualPayout: 0,
      date: '2026-04-07T19:30:00Z', sportsbook: 'DraftKings',
      notes: '', estimatedProbability: 0.50,
      impliedProbability: 0.455, expectedValue: 10.0, kellyStake: 0.03,
    },
    {
      id: uuidv4(), sport: 'NBA', betType: 'prop', status: 'pending',
      event: 'Mavericks vs Suns', selection: 'Luka Doncic Over 30.5 pts', odds: -115,
      stake: 80, potentialPayout: 149.57, actualPayout: null,
      date: '2026-04-15T20:00:00Z', sportsbook: 'FanDuel',
      notes: 'Luka averaging 33 last 5 games', estimatedProbability: 0.60,
      impliedProbability: 0.535, expectedValue: 4.35, kellyStake: 0.03,
    },
    {
      id: uuidv4(), sport: 'NFL', betType: 'spread', status: 'push',
      event: 'Eagles vs Cowboys', selection: 'Eagles -7', odds: -110,
      stake: 110, potentialPayout: 210, actualPayout: 110,
      date: '2026-04-05T16:25:00Z', sportsbook: 'BetMGM',
      notes: 'Rivalry game', estimatedProbability: 0.53,
      impliedProbability: 0.524, expectedValue: 0.72, kellyStake: 0.005,
    },
    {
      id: uuidv4(), sport: 'NBA', betType: 'moneyline', status: 'won',
      event: 'Bucks vs Heat', selection: 'Bucks ML', odds: -180,
      stake: 90, potentialPayout: 140, actualPayout: 140,
      date: '2026-04-11T19:00:00Z', sportsbook: 'Caesars',
      notes: 'Giannis healthy', estimatedProbability: 0.70,
      impliedProbability: 0.643, expectedValue: 8.89, kellyStake: 0.04,
    },
  ];

  const settled = sampleBets.filter(b => b.status !== 'pending');
  const totalPayout = settled.reduce((sum, b) => sum + (b.actualPayout ?? 0), 0);
  const totalStaked = settled.reduce((sum, b) => sum + b.stake, 0);
  const pendingStaked = sampleBets.filter(b => b.status === 'pending').reduce((sum, b) => sum + b.stake, 0);
  const newBankroll = state.initialBankroll - totalStaked - pendingStaked + totalPayout;

  return {
    ...state,
    bets: sampleBets,
    bankroll: newBankroll,
    bankrollHistory: [
      { date: '2026-04-05T00:00:00Z', balance: state.initialBankroll },
      { date: '2026-04-06T00:00:00Z', balance: state.initialBankroll - 50 },
      { date: '2026-04-07T00:00:00Z', balance: state.initialBankroll + 25 },
      { date: '2026-04-08T00:00:00Z', balance: state.initialBankroll - 35 },
      { date: '2026-04-09T00:00:00Z', balance: state.initialBankroll + 65 },
      { date: '2026-04-10T00:00:00Z', balance: state.initialBankroll + 15 },
      { date: '2026-04-11T00:00:00Z', balance: state.initialBankroll + 90 },
      { date: '2026-04-15T00:00:00Z', balance: newBankroll },
    ],
  };
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, null, loadState);

  useEffect(() => {
    saveState(state);
  }, [state]);

  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}
