import { createContext } from 'react';
import type { AppState } from '../types';

type Action =
  | { type: 'ADD_BET'; payload: import('../types').BetFormData }
  | { type: 'UPDATE_BET_STATUS'; payload: { id: string; status: import('../types').BetStatus } }
  | { type: 'DELETE_BET'; payload: string }
  | { type: 'SET_BANKROLL'; payload: number }
  | { type: 'SET_INITIAL_BANKROLL'; payload: number }
  | { type: 'LOAD_SAMPLE_DATA' };

export type { Action };

export interface AppContextType {
  state: AppState;
  dispatch: React.Dispatch<Action>;
}

export const AppContext = createContext<AppContextType | null>(null);
