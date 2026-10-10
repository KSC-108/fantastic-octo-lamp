import { useState } from 'react';
import { useAppState } from './state.ts';
import { usePlan } from './usePlan.ts';
import { PlanView } from './views/PlanView.tsx';
import { BasketView } from './views/BasketView.tsx';
import { PricesView } from './views/PricesView.tsx';
import { PlatformsView } from './views/PlatformsView.tsx';
import { SettingsView } from './views/SettingsView.tsx';
import { cx } from './components/ui.tsx';

const TABS = [
  { id: 'plan', label: 'Plan' },
  { id: 'basket', label: 'Basket' },
  { id: 'prices', label: 'Prices' },
  { id: 'platforms', label: 'Platforms' },
  { id: 'settings', label: 'Settings' },
] as const;
type TabId = (typeof TABS)[number]['id'];

export function App() {
  const [state, setState] = useAppState();
  const [tab, setTab] = useState<TabId>('plan');
  const { plan, status } = usePlan(state.basket, state.prefs);
  const solving = status.kind === 'solving';
  const error = status.kind === 'error' ? status.message : null;

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-white">
              <svg viewBox="0 0 32 32" className="h-5 w-5" aria-hidden><path d="M8 11h16l-1.8 10H9.8z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" /><path d="M16 11v10" stroke="currentColor" strokeWidth="2.2" /></svg>
            </span>
            <div>
              <h1 className="text-[16px] font-semibold leading-tight tracking-tight">SplitCart</h1>
              <p className="text-[12px] leading-tight text-muted">Mumbai {state.pincode} · five platforms</p>
            </div>
          </div>
          <nav className="order-3 -mx-1 flex w-full gap-1 overflow-x-auto sm:order-none sm:w-auto" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                aria-current={tab === t.id ? 'page' : undefined}
                className={cx(
                  'rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition-colors',
                  tab === t.id ? 'bg-ink text-white' : 'text-muted hover:bg-canvas hover:text-ink',
                )}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-[12.5px]">
            <span className={cx('rounded-full px-2.5 py-1', state.source.kind === 'sample' ? 'bg-warn-soft text-warn' : 'bg-canvas text-muted')}>
              {state.source.label}
            </span>
            <span className="flex items-center gap-1.5 text-muted" aria-live="polite">
              <span className={cx('h-1.5 w-1.5 rounded-full', solving ? 'animate-pulse bg-faint' : error ? 'bg-loss' : 'bg-gain')} />
              {solving ? 'Planning' : error ? 'Needs attention' : plan ? `Planned in ${plan.solveMs} ms` : 'Ready'}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        {tab === 'plan' && <PlanView plan={plan} solving={solving} error={error} onGoTo={setTab} />}
        {tab === 'basket' && <BasketView state={state} setState={setState} />}
        {tab === 'prices' && <PricesView state={state} setState={setState} />}
        {tab === 'platforms' && <PlatformsView state={state} setState={setState} />}
        {tab === 'settings' && <SettingsView state={state} setState={setState} />}
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-10 text-[12px] leading-relaxed text-faint sm:px-6">
        Plans are computed on this device. Fees and prices are only as accurate as the data entered; sample prices and brands are invented.
        SplitCart never pays or places orders; you check out in each app.
      </footer>
    </div>
  );
}
