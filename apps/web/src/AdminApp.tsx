import React, {useEffect, useMemo, useState} from 'react';
import './admin.css';

type AuthState = {
  configured: boolean;
  local_login_enabled: boolean;
  local_login_url: string;
  authenticated: boolean;
  admin: {subject: string; email?: string; name?: string}|null;
  csrf_token?: string;
  recent_authentication?: boolean;
  login_url: string;
};
type Question = {question_id: string; question_name: string; guess_limit: number; dimensions: {id: string; label: string}[]};
type Category = {id: string; name: string; entity_label: string; questions: Question[]};
type Dataset = {
  id: string;
  category: string;
  label: string;
  effective_month: string|null;
  is_active: boolean;
  is_demo: boolean;
  imported_at: string;
  reviewed_at: string|null;
  reviewed_by: string|null;
  source_manifest: Record<string, unknown>;
  questions: {question: string; eligible_count: number}[];
  puzzle_count: number;
  can_review: boolean;
  can_publish: boolean;
  publish_blocker: string|null;
};
type DatasetDetail = Dataset & {
  rows: Record<string, unknown>[];
  comparison: {previous_label: string; added: string[]; removed: string[]; renamed: {code: string; from: string; to: string}[]}|null;
};
type Overview = {
  environment: 'local'|'staging'|'production';
  deployment_id: string;
  app_version: string;
  database: {driver: string; host: string; name: string};
  migration: string|null;
  utc_today: string;
  warnings: string[];
  categories: Category[];
  datasets: Dataset[];
  today: {scheduled: boolean; category: string|null; question: string|null; dataset_id: string|null};
  current_month: {month: string; scheduled_days: number};
  counts: {players: number; rounds: number; guesses: number; daily_puzzles: number};
};
type Job = {id: string; kind: string; status: string; payload: Record<string, unknown>; result?: Record<string, unknown>; error?: string; requested_by: string; created_at: string};
type Audit = {id: string; admin_subject: string; action: string; details: Record<string, unknown>; created_at: string};
type PlanDay = {date: string; category: string; question: string; dataset_label: string; status: 'scheduled'|'planned'; eligible_count?: number; prior_uses?: number};
type Plan = {month: string; fingerprint: string; policy: string; planned_count: number; scheduled_count: number; repeat_count: number; distribution: {category: string; question: string; days: number}[]; days: PlanDay[]};

async function request<T>(path: string, auth?: AuthState|null, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers);
  if (options?.body) headers.set('Content-Type', 'application/json');
  if (auth?.csrf_token && options?.method && options.method !== 'GET') headers.set('X-CSRF-Token', auth.csrf_token);
  const response = await fetch(path, {credentials: 'include', ...options, headers});
  if (response.status === 428) {
    window.location.assign('/api/v1/admin/auth/login?next=/admin&reauth=true');
    throw new Error('Redirecting for reauthentication');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function fmtDate(value?: string|null) {
  return value ? new Date(value).toLocaleString() : 'Not yet';
}

function Status({children, tone = 'neutral'}: {children: React.ReactNode; tone?: string}) {
  return <span className={`admin-status ${tone}`}>{children}</span>;
}

export function AdminApp() {
  const [auth, setAuth] = useState<AuthState|null>(null);
  const [overview, setOverview] = useState<Overview|null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [detail, setDetail] = useState<DatasetDetail|null>(null);
  const [month, setMonth] = useState(new Date().toISOString().slice(0, 7));
  const [plan, setPlan] = useState<Plan|null>(null);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  async function loadAuth() {
    const status = await request<AuthState>('/api/v1/admin/auth/status');
    setAuth(status);
    return status;
  }

  async function localLogin() {
    setBusy('local-login');
    setError('');
    try {
      await request(auth?.local_login_url || '/api/v1/admin/auth/local-login', null, {method: 'POST'});
      const status = await loadAuth();
      await refresh(status);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  }

  async function refresh(currentAuth = auth) {
    if (!currentAuth?.authenticated) return;
    const [nextOverview, nextDatasets, nextJobs, nextAudit] = await Promise.all([
      request<Overview>('/api/v1/admin/state', currentAuth),
      request<Dataset[]>('/api/v1/admin/datasets', currentAuth),
      request<Job[]>('/api/v1/admin/jobs', currentAuth),
      request<Audit[]>('/api/v1/admin/audit', currentAuth),
    ]);
    setOverview(nextOverview);
    setDatasets(nextDatasets);
    setJobs(nextJobs);
    setAudit(nextAudit);
  }

  useEffect(() => {
    loadAuth().then(status => refresh(status)).catch(e => setError(e.message));
  }, []);
  useEffect(() => {
    if (!auth?.authenticated) return;
    const timer = window.setInterval(() => refresh(auth).catch(() => undefined), 5000);
    return () => window.clearInterval(timer);
  }, [auth?.authenticated, auth?.csrf_token]);

  function productionConfirmation(action: string): string|null {
    if (overview?.environment !== 'production') return null;
    return window.prompt(`Production action. Type exactly:\n${action}`);
  }

  async function mutate<T>(label: string, action: () => Promise<T>, success: string) {
    setBusy(label);
    setError('');
    setNotice('');
    try {
      const result = await action();
      setNotice(success);
      await refresh();
      return result;
    } catch (e) {
      setError((e as Error).message);
      return undefined;
    } finally {
      setBusy('');
    }
  }

  async function fetchCountries() {
    const confirmation = productionConfirmation(`PRODUCTION FETCH ${month}`);
    if (overview?.environment === 'production' && confirmation === null) return;
    await mutate('fetch', () => request('/api/v1/admin/jobs/countries/fetch', auth, {
      method: 'POST',
      body: JSON.stringify({effective_month: month, confirmation}),
    }), `Country fetch queued for ${month}.`);
  }

  async function openDataset(dataset: Dataset) {
    setBusy(`detail-${dataset.id}`);
    setError('');
    try {
      setDetail(await request<DatasetDetail>(`/api/v1/admin/datasets/${dataset.id}`, auth));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  }

  async function reviewDataset(dataset: Dataset) {
    const result = await mutate<Dataset>(`review-${dataset.id}`, () => request(`/api/v1/admin/datasets/${dataset.id}/review`, auth, {method: 'POST'}), `Reviewed ${dataset.label}.`);
    if (result) await openDataset(result);
  }

  async function publishDataset(dataset: Dataset) {
    const expected = `PRODUCTION PUBLISH ${dataset.label}`;
    const confirmation = productionConfirmation(expected);
    if (overview?.environment === 'production' && confirmation === null) return;
    const result = await mutate<Dataset>(`publish-${dataset.id}`, () => request(`/api/v1/admin/datasets/${dataset.id}/publish`, auth, {
      method: 'POST',
      body: JSON.stringify({confirmation}),
    }), `Published ${dataset.label}.`);
    if (result) await openDataset(result);
  }

  async function previewSchedule() {
    setBusy('preview');
    setError('');
    setNotice('');
    try {
      setPlan(await request<Plan>(`/api/v1/admin/schedule/preview?month=${encodeURIComponent(month)}`, auth));
    } catch (e) {
      setPlan(null);
      setError((e as Error).message);
    } finally {
      setBusy('');
    }
  }

  async function applySchedule() {
    if (!plan) return;
    const expected = `PRODUCTION SCHEDULE ${plan.month}`;
    const confirmation = productionConfirmation(expected);
    if (overview?.environment === 'production' && confirmation === null) return;
    const result = await mutate<{created: number}>('apply', () => request('/api/v1/admin/schedule/apply', auth, {
      method: 'POST',
      body: JSON.stringify({month: plan.month, fingerprint: plan.fingerprint, confirmation}),
    }), `Schedule applied for ${plan.month}.`);
    if (result) await previewSchedule();
  }

  async function reveal(day: PlanDay) {
    if (!window.confirm(`Reveal and audit the target for ${day.date}?`)) return;
    const result = await mutate<{target: {name: string; code: string}}>(`reveal-${day.date}`, () => request(`/api/v1/admin/schedule/${day.date}/reveal`, auth, {method: 'POST'}), `Revealed ${day.date}.`);
    if (result) setRevealed(current => ({...current, [day.date]: `${result.target.name} (${result.target.code})`}));
  }

  async function logout() {
    await request('/api/v1/admin/auth/logout', auth, {method: 'POST'});
    window.location.assign('/admin');
  }

  const activeJobs = useMemo(() => jobs.filter(job => job.status === 'queued' || job.status === 'running'), [jobs]);

  if (!auth) return <main className="admin-login"><h1>Administrator console</h1><p>Checking authentication…</p></main>;
  if (!auth.authenticated) return <main className="admin-login">
    <div className="admin-login-card">
      <div className="admin-brand">CONVERGE ADMIN</div>
      <h1>Game operations</h1>
      <p>Use the explicitly enabled local session now, or an allowlisted OpenID Connect identity when OIDC is configured.</p>
      {error && <div className="admin-message error" role="alert">{error}</div>}
      {auth.local_login_enabled && <button className="admin-primary" disabled={busy === 'local-login'} onClick={localLogin}>{busy === 'local-login' ? 'Signing in…' : 'Continue as local administrator'}</button>}
      {auth.configured && <a className="admin-primary" href={`${auth.login_url}?next=/admin`}>Sign in with OIDC</a>}
      {!auth.local_login_enabled && !auth.configured && <div className="admin-warning"><strong>Administrator login is not configured.</strong><span>Enable ADMIN_LOCAL_LOGIN_ENABLED only for local development, or configure allowlisted OIDC.</span></div>}
      <a className="admin-link" href="/">Return to game</a>
    </div>
  </main>;

  return <div className={`admin-shell env-${overview?.environment || 'local'}`}>
    <div className="admin-envbar">
      <strong>{overview?.environment.toUpperCase() || 'LOADING'}</strong>
      <span>{overview?.deployment_id}</span>
      <span>{overview ? `${overview.database.driver} · ${overview.database.host}/${overview.database.name}` : ''}</span>
    </div>
    <header className="admin-header">
      <div><div className="admin-brand">CONVERGE ADMIN</div><h1>Game operations</h1></div>
      <nav><a href="/">Open game</a><button onClick={() => refresh().catch(e => setError(e.message))}>Refresh</button><button onClick={logout}>Sign out</button></nav>
    </header>
    <main className="admin-main">
      {error && <div className="admin-message error" role="alert">{error}</div>}
      {notice && <div className="admin-message success">{notice}</div>}
      {overview?.warnings.length ? <section className="admin-alerts"><h2>Needs attention</h2>{overview.warnings.map(warning => <div key={warning}>{warning}</div>)}</section> : null}
      {overview && <div className="admin-system"><span>UTC {overview.utc_today}</span><span>Release {overview.app_version}</span><span>Schema {overview.migration || 'metadata-created test database'}</span></div>}

      <section className="admin-cards">
        <article><span>Today</span><strong>{overview?.today.scheduled ? 'Scheduled' : 'Missing'}</strong><small>{overview?.today.category || 'No challenge'} {overview?.today.question || ''}</small></article>
        <article><span>Current month</span><strong>{overview?.current_month.scheduled_days || 0} days</strong><small>{overview?.current_month.month}</small></article>
        <article><span>Datasets</span><strong>{datasets.length}</strong><small>{datasets.filter(dataset => dataset.is_active).length} active</small></article>
        <article><span>Activity</span><strong>{overview?.counts.rounds || 0} rounds</strong><small>{overview?.counts.players || 0} players · {overview?.counts.guesses || 0} guesses</small></article>
      </section>

      <section className="admin-panel">
        <div className="admin-panel-heading"><div><span className="eyebrow">Step 1</span><h2>Categories and questions</h2></div></div>
        <div className="admin-category-grid">{overview?.categories.map(category => <article key={category.id}>
          <h3>{category.name}</h3><code>{category.id}</code>
          {category.questions.map(question => <div className="admin-question" key={question.question_id}>
            <strong>{question.question_name}</strong><span>{question.guess_limit} guesses</span>
            <small>{question.dimensions.map(dimension => dimension.label).join(' · ')}</small>
          </div>)}
        </article>)}</div>
      </section>

      <section className="admin-panel">
        <div className="admin-panel-heading"><div><span className="eyebrow">Step 2</span><h2>Country snapshots</h2><p>Fetch stages a complete-record World Bank snapshot. Nothing becomes playable until review and publication.</p></div>
          <div className="admin-actions"><label>Effective month<input type="month" value={month} onChange={event => {setMonth(event.target.value); setPlan(null);}}/></label><button className="admin-primary" disabled={!!busy || activeJobs.length > 0} onClick={fetchCountries}>{busy === 'fetch' ? 'Queueing…' : 'Fetch live snapshot'}</button></div>
        </div>
        <div className="admin-table-wrap"><table><thead><tr><th>Snapshot</th><th>Month</th><th>Eligible</th><th>State</th><th>Puzzles</th><th>Actions</th></tr></thead><tbody>
          {datasets.map(dataset => <tr key={dataset.id}><td><button className="admin-text-button" onClick={() => openDataset(dataset)}>{dataset.label}</button><small>{dataset.category}{dataset.is_demo ? ' · demo' : ''}</small></td><td>{dataset.effective_month || 'Fallback'}</td><td>{dataset.questions.map(q => `${q.question}: ${q.eligible_count}`).join(', ') || 'Unregistered'}</td><td>{dataset.is_active ? <Status tone="good">Published</Status> : dataset.reviewed_at ? <Status tone="ready">Reviewed</Status> : <Status>Staged</Status>}</td><td>{dataset.puzzle_count}</td><td className="admin-row-actions"><button disabled={!dataset.can_review || !!busy} onClick={() => reviewDataset(dataset)}>Review</button><button disabled={!dataset.can_publish || !!busy} title={dataset.publish_blocker || ''} onClick={() => publishDataset(dataset)}>Publish</button></td></tr>)}
        </tbody></table></div>
        {!datasets.length && <p className="admin-empty">No snapshots exist. Fetch the first live snapshot above.</p>}
      </section>

      {detail && <section className="admin-panel admin-detail">
        <div className="admin-panel-heading"><div><span className="eyebrow">Snapshot review</span><h2>{detail.label}</h2><p>{detail.rows.length} complete eligible records · imported {fmtDate(detail.imported_at)}</p></div><button onClick={() => setDetail(null)}>Close</button></div>
        <div className="admin-manifest"><div><strong>Source manifest</strong><pre>{JSON.stringify(detail.source_manifest, null, 2)}</pre></div><div><strong>Change summary</strong>{detail.comparison ? <><p>Compared with {detail.comparison.previous_label}</p><p>Added: {detail.comparison.added.join(', ') || 'None'}</p><p>Removed: {detail.comparison.removed.join(', ') || 'None'}</p><p>Renamed: {detail.comparison.renamed.length}</p></> : <p>First snapshot; no previous comparison.</p>}</div></div>
        <div className="admin-table-wrap admin-records"><table><thead><tr>{Object.keys(detail.rows[0] || {}).filter(key => key !== 'provenance' && key !== 'entity_id').map(key => <th key={key}>{key.replaceAll('_', ' ')}</th>)}</tr></thead><tbody>{detail.rows.map(row => <tr key={String(row.entity_id)}>{Object.entries(row).filter(([key]) => key !== 'provenance' && key !== 'entity_id').map(([key, value]) => <td key={key}>{String(value)}</td>)}</tr>)}</tbody></table></div>
      </section>}

      <section className="admin-panel">
        <div className="admin-panel-heading"><div><span className="eyebrow">Step 3</span><h2>Global daily schedule</h2><p>Preview is read-only. Applying preserves every existing date and stores one category, question, snapshot, and balanced least-used target per missing day.</p></div><div className="admin-actions"><label>Month<input type="month" value={month} onChange={event => {setMonth(event.target.value); setPlan(null);}}/></label><button disabled={!!busy} onClick={previewSchedule}>{busy === 'preview' ? 'Planning…' : 'Preview month'}</button>{plan && <button className="admin-primary" disabled={!plan.planned_count || !!busy} onClick={applySchedule}>{busy === 'apply' ? 'Applying…' : `Schedule ${plan.planned_count} days`}</button>}</div></div>
        {plan ? <><div className="admin-plan-summary"><span><strong>{plan.scheduled_count}</strong> preserved</span><span><strong>{plan.planned_count}</strong> to create</span><span><strong>{plan.repeat_count}</strong> previously used targets</span><span><strong>{plan.policy}</strong> policy</span></div><div className="admin-calendar">{plan.days.map(day => <article key={day.date} className={day.status}><strong>{Number(day.date.slice(-2))}</strong><span>{day.category}</span><small>{day.dataset_label}</small><Status tone={day.status === 'scheduled' ? 'good' : 'ready'}>{day.status}</Status>{revealed[day.date] && <b>{revealed[day.date]}</b>}{day.status === 'scheduled' && <button onClick={() => reveal(day)}>Reveal</button>}</article>)}</div></> : <p className="admin-empty">Choose a month and preview the immutable schedule plan before applying it.</p>}
      </section>

      <section className="admin-two-column">
        <article className="admin-panel"><div className="admin-panel-heading"><div><h2>Operator jobs</h2><p>Fetches continue in the dedicated worker.</p></div></div>{jobs.length ? <ul className="admin-activity">{jobs.map(job => <li key={job.id}><Status tone={job.status === 'succeeded' ? 'good' : job.status === 'failed' ? 'bad' : 'ready'}>{job.status}</Status><div><strong>{job.kind}</strong><span>{JSON.stringify(job.payload)}</span>{job.result && <span>Result: {JSON.stringify(job.result)}</span>}{job.error && <em>{job.error}</em>}</div><time>{fmtDate(job.created_at)}</time></li>)}</ul> : <p className="admin-empty">No operator jobs.</p>}</article>
        <article className="admin-panel"><div className="admin-panel-heading"><div><h2>Audit trail</h2><p>Authentication, review, publication, scheduling, and reveals.</p></div></div>{audit.length ? <ul className="admin-activity">{audit.map(entry => <li key={entry.id}><Status>{entry.action}</Status><div><strong>{entry.admin_subject}</strong><span>{JSON.stringify(entry.details)}</span></div><time>{fmtDate(entry.created_at)}</time></li>)}</ul> : <p className="admin-empty">No administrator actions.</p>}</article>
      </section>
    </main>
  </div>;
}
