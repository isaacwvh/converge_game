import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AdminApp } from './AdminApp';
import './style.css';

type DirectionCell = {direction: 'up'|'down'|'equal'; guess_value: number};
type DisplayRule = {
  style: 'compact'|'number'|'currency';
  currency?: string;
  minimum_fraction_digits?: number;
  maximum_fraction_digits?: number;
  suffix?: string;
};
type Dimension = {id: string; label: string; feedback: 'direction'|'distance'; display: DisplayRule};
type Game = {
  category_id: string;
  category_name: string;
  question_id: string;
  question_name: string;
  entity_label: string;
  prompt: string;
  dimensions: Dimension[];
  rules: Record<string, string>;
};
type Guess = {turn: number; name: string; feedback: Record<string, DirectionCell|number>};
type Round = {
  round_id: string;
  category: string;
  question: string;
  game: Game;
  date: string|null;
  status: string;
  remaining: number;
  max_guesses: number;
  guesses: Guess[];
  answer?: {name: string; capital?: string};
};
type Entity = {id: string; name: string; code: string};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {credentials: 'include', ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function formatValue(value: number, display: DisplayRule): string {
  const options: Intl.NumberFormatOptions = {
    minimumFractionDigits: display.minimum_fraction_digits,
    maximumFractionDigits: display.maximum_fraction_digits,
  };
  if (display.style === 'compact') options.notation = 'compact';
  if (display.style === 'currency') {
    options.style = 'currency';
    options.currency = display.currency || 'USD';
  }
  return new Intl.NumberFormat(undefined, options).format(value) + (display.suffix || '');
}

function App() {
  const [round, setRound] = useState<Round | null>(null);
  const [query, setQuery] = useState('');
  const [options, setOptions] = useState<Entity[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selectedDay, setSelectedDay] = useState('');

  useEffect(() => {
    api<Round>('/api/v1/daily').then(setRound).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!query.trim() || !round || round.status !== 'playing') {
      setOptions([]);
      return;
    }
    const timer = setTimeout(() => {
      api<Entity[]>(
        `/api/v1/entities/${encodeURIComponent(round.category)}/search?q=${encodeURIComponent(query)}&round_id=${encodeURIComponent(round.round_id)}`,
      ).then(setOptions).catch(() => setOptions([]));
    }, 150);
    return () => clearTimeout(timer);
  }, [query, round?.round_id, round?.status, round?.category]);

  async function openDay() {
    if (!selectedDay) return;
    setError('');
    setQuery('');
    setOptions([]);
    try {
      setRound(await api<Round>(`/api/v1/challenges/${selectedDay}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function submit(entity: Entity) {
    if (!round || busy) return;
    setBusy(true);
    setError('');
    try {
      const updated = await api<Round>(`/api/v1/rounds/${round.round_id}/guesses`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()},
        body: JSON.stringify({entity_id: entity.id}),
      });
      setRound(updated);
      setQuery('');
      setOptions([]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const dimensionCount = round?.game.dimensions.length || 5;
  const gridStyle: React.CSSProperties = {
    gridTemplateColumns: `minmax(135px, 1.6fr) repeat(${dimensionCount}, minmax(110px, 1fr))`,
    minWidth: 135 + dimensionCount * 110,
  };

  return <main>
    <header>
      <div className="brand">CONVERGE</div>
      <div className="date">{round?.game.category_name.toUpperCase() || 'DAILY'} · {round?.date || 'PRACTICE'}</div>
    </header>
    <section className="intro">
      <h1>{round?.game.prompt || 'Loading today’s challenge…'}</h1>
      <p>{round?.game.rules.arrows} {round?.game.rules.distance}</p>
    </section>
    <section className="archive">
      <label>Challenge date <input type="date" value={selectedDay} onChange={e => setSelectedDay(e.target.value)}/></label>
      <button onClick={openDay}>Open</button>
      <button onClick={() => {
        setError('');
        api<Round>('/api/v1/daily').then(setRound).catch(e => setError(e.message));
      }}>Today</button>
    </section>
    {round?.status === 'playing' && <section className="search">
      <input
        aria-label={`Search ${round.game.entity_label.toLowerCase()}`}
        placeholder={`Guess a ${round.game.entity_label.toLowerCase()}…`}
        value={query}
        onChange={e => setQuery(e.target.value)}
        disabled={busy}
      />
      {options.length > 0 && <div className="options">
        {options.map(entity => <button key={entity.id} onClick={() => submit(entity)} disabled={busy}>
          {entity.name}<small>{entity.code}</small>
        </button>)}
      </div>}
    </section>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="turns">{round ? `${round.max_guesses - round.remaining} / ${round.max_guesses} guesses` : 'Loading…'}</div>
    <div className="grid">
      <div className="row heading" style={gridStyle}>
        <div>GUESS</div>
        {round?.game.dimensions.map(dimension => <div key={dimension.id}>{dimension.label}</div>)}
      </div>
      {round?.guesses.map(guess => <div className="row" style={gridStyle} key={guess.turn}>
        <div className="country">{guess.name}</div>
        {round.game.dimensions.map(dimension => {
          const feedback = guess.feedback[dimension.id];
          if (dimension.feedback === 'direction') {
            const cell = feedback as DirectionCell;
            return <div className={`cell ${cell.direction}`} key={dimension.id}>
              <strong>{cell.direction === 'up' ? '↑' : cell.direction === 'down' ? '↓' : '✓'}</strong>
              <span>{formatValue(cell.guess_value, dimension.display)}</span>
            </div>;
          }
          return <div className="distance" key={dimension.id}>
            {formatValue(feedback as number, dimension.display)}
          </div>;
        })}
      </div>)}
    </div>
    {round?.answer && <section className="result">
      <h2>{round.status === 'won' ? 'You found it!' : 'The answer was'}</h2>
      <p>{round.answer.name}</p>
      {round.answer.capital && <small>Capital: {round.answer.capital}</small>}
    </section>}
    <footer>Daily puzzle resets at 00:00 UTC · No account required</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{window.location.pathname.startsWith('/admin') ? <AdminApp/> : <App/>}</React.StrictMode>,
);
