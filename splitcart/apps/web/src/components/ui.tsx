import type { ReactNode, InputHTMLAttributes, ButtonHTMLAttributes, SelectHTMLAttributes } from 'react';

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx('rounded-xl border border-line bg-surface', className)}>{children}</section>;
}

export function CardHeader({ title, meta, action }: { title: ReactNode; meta?: ReactNode; action?: ReactNode }) {
  return (
    <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
        {meta && <p className="mt-0.5 text-[13px] text-muted">{meta}</p>}
      </div>
      {action}
    </header>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">{children}</h2>
      {hint && <p className="text-[13px] text-faint">{hint}</p>}
    </div>
  );
}

export function Stat({ label, value, note, tone }: { label: string; value: ReactNode; note?: ReactNode; tone?: 'gain' | 'accent' }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-5 py-4">
      <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-muted">{label}</p>
      <p className={cx('mt-1.5 text-[26px] font-semibold tracking-tight tabular-nums', tone === 'gain' && 'text-gain', tone === 'accent' && 'text-accent')}>
        {value}
      </p>
      {note && <p className="mt-1 text-[13px] leading-snug text-muted">{note}</p>}
    </div>
  );
}

type Tone = 'neutral' | 'gain' | 'warn' | 'accent';
const BADGE: Record<Tone, string> = {
  neutral: 'bg-canvas text-muted border-line',
  gain: 'bg-gain-soft text-gain border-transparent',
  warn: 'bg-warn-soft text-warn border-transparent',
  accent: 'bg-accent-soft text-accent border-transparent',
};

export function Badge({ children, tone = 'neutral', title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span title={title} className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11.5px] font-medium', BADGE[tone])}>
      {children}
    </span>
  );
}

export function Button({ variant = 'secondary', className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' }) {
  return (
    <button
      {...props}
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45',
        variant === 'primary' && 'bg-accent text-white hover:bg-[#0f3f2f]',
        variant === 'secondary' && 'border border-line bg-surface text-ink hover:bg-canvas',
        variant === 'ghost' && 'text-muted hover:bg-canvas hover:text-ink',
        className,
      )}
    />
  );
}

export function TextInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        !/(^|\s)w-/.test(className ?? '') && 'w-full',
        'rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink outline-none placeholder:text-faint focus:border-accent focus:ring-2 focus:ring-accent/15',
        className,
      )}
    />
  );
}

export function NumberInput({ value, onChange, className, ...props }: Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & { value: number | undefined; onChange: (n: number | undefined) => void }) {
  return (
    <TextInput
      {...props}
      type="number"
      inputMode="decimal"
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      className={cx('tabular-nums', className)}
    />
  );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx('rounded-lg border border-line bg-surface px-2 py-1.5 text-[13px] text-ink outline-none focus:border-accent', className)}
    >
      {children}
    </select>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cx('relative h-5 w-9 shrink-0 rounded-full transition-colors', checked ? 'bg-accent' : 'bg-line')}
    >
      <span className={cx('absolute left-0 top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform', checked ? 'translate-x-[18px]' : 'translate-x-0.5')} />
    </button>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-[12.5px] font-medium text-ink">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <span className="mt-1 block text-[12px] leading-snug text-faint">{hint}</span>}
    </label>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface px-6 py-10 text-center">
      <p className="text-[15px] font-semibold">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function PlatformMark({ platform, name }: { platform: string; name: string }) {
  const initials = name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase();
  return (
    <span aria-hidden data-platform={platform} className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line bg-canvas text-[11px] font-semibold tracking-wide text-muted">
      {initials}
    </span>
  );
}
