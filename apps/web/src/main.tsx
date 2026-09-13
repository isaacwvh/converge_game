import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Cell = {direction: 'up'|'down'|'equal'; guess_value: number};
type Feedback = {population: Cell; area_km2: Cell; gdp_per_capita_usd: Cell; temp_c: Cell; distance_km: number};
type Round = {round_id: string; date: string; status: string; remaining: number; max_guesses: number; guesses: {turn: number; name: string; feedback: Feedback}[]; answer?: {name: string; capital: string}};
type Country = {id: string; name: string; code: string};

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, {credentials: 'include', ...options});
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed: ${response.status}`); }
  return response.json();
}

function App() {
  const [round, setRound] = useState<Round | null>(null);
  const [query, setQuery] = useState('');
  const [options, setOptions] = useState<Country[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { api<Round>('/api/v1/daily/countries').then(setRound).catch(e => setError(e.message)); }, []);
  useEffect(() => {
    if (!query.trim() || !round || round.status !== 'playing') { setOptions([]); return; }
    const timer = setTimeout(() => { api<Country[]>(`/api/v1/entities/countries/search?q=${encodeURIComponent(query)}`).then(setOptions).catch(() => setOptions([])); }, 150);
    return () => clearTimeout(timer);
  }, [query, round?.status]);
  async function submit(country: Country) {
    if (!round || busy) return;
    setBusy(true); setError('');
    try {
      const updated = await api<Round>(`/api/v1/rounds/${round.round_id}/guesses`, {method: 'POST', headers: {'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID()}, body: JSON.stringify({entity_id: country.id})});
      setRound(updated); setQuery(''); setOptions([]);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const fields: {key: keyof Omit<Feedback, 'distance_km'>; label: string; format: (n: number) => string}[] = [
    {key: 'population', label: 'Population', format: n => (n / 1e6).toFixed(1) + 'M'},
    {key: 'area_km2', label: 'Area', format: n => Math.round(n).toLocaleString() + ' km²'},
    {key: 'gdp_per_capita_usd', label: 'GDP/person', format: n => '$' + Math.round(n).toLocaleString()},
    {key: 'temp_c', label: 'Temp.', format: n => n.toFixed(1) + '°C'},
  ];
  return <main>
    <header><div className="brand">CONVERGE</div><div className="date">COUNTRIES · {round?.date || 'DAILY'}</div></header>
    <section className="intro"><h1>Find the mystery country.</h1><p>Each arrow points from your guess toward the answer. Distance is between capitals.</p></section>
    {round?.status === 'playing' && <section className="search"><input aria-label="Search countries" placeholder="Guess a country…" value={query} onChange={e => setQuery(e.target.value)} disabled={busy}/>{options.length > 0 && <div className="options">{options.map(c => <button key={c.id} onClick={() => submit(c)} disabled={busy}>{c.name}<small>{c.code}</small></button>)}</div>}</section>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="turns">{round ? `${round.max_guesses - round.remaining} / ${round.max_guesses} guesses` : 'Loading…'}</div>
    <div className="grid"><div className="row heading"><div>GUESS</div>{fields.map(f => <div key={f.key}>{f.label}</div>)}<div>DISTANCE</div></div>
      {round?.guesses.map(g => <div className="row" key={g.turn}><div className="country">{g.name}</div>{fields.map(f => {const c = g.feedback[f.key]; return <div className={`cell ${c.direction}`} key={f.key}><strong>{c.direction === 'up' ? '↑' : c.direction === 'down' ? '↓' : '✓'}</strong><span>{f.format(c.guess_value)}</span></div>})}<div className="distance">{g.feedback.distance_km.toLocaleString()} km</div></div>)}
    </div>
    {round?.answer && <section className="result"><h2>{round.status === 'won' ? 'You found it!' : 'The answer was'}</h2><p>{round.answer.name}</p><small>Capital: {round.answer.capital}</small></section>}
    <footer>Daily puzzle resets at 00:00 UTC · No account required</footer>
  </main>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
