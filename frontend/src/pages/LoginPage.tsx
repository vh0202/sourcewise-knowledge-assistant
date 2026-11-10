import { Check, Cpu, Eye, EyeOff, Quote, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { SampleNotice, ThemeToggle } from "../components/AppShell";
import { Logo, LogoMark } from "../components/brand";
import { Badge, Button, ErrorNotice, Field, FileTypeIcon, INPUT_CLASS, Skeleton } from "../components/ui";
import { ApiError } from "../lib/api";
import { classNames } from "../lib/format";
import { useSession } from "../lib/session";

const POINTS = [
  { icon: Quote, text: "Cited to the passage" },
  { icon: ShieldCheck, text: "Declines instead of guessing" },
  { icon: Cpu, text: "Works offline or with Claude" },
];

/** A static picture of the product: a cited answer and the passage behind it. Not live data. */
function ProductPreview() {
  return (
    <figure aria-label="Example of a cited answer and its source" className="relative max-w-[33rem] pb-14">
      <div className="rounded-2xl bg-white/[0.06] p-1.5 shadow-xl ring-1 ring-white/10">
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <div className="flex h-9 items-center gap-1.5 border-b border-line px-3.5">
            <span className="size-2 rounded-full bg-fg-faint/60" />
            <span className="size-2 rounded-full bg-fg-faint/60" />
            <span className="size-2 rounded-full bg-fg-faint/60" />
            <span className="ml-3 truncate text-xs font-medium text-fg-muted">Annual leave entitlement</span>
          </div>
          {/* The source card overlaps the lower right corner of the window. */}
          <div className="space-y-4 px-5 pt-5 pb-9">
            <div className="flex justify-end">
              <p className="rounded-2xl rounded-br-md bg-bubble px-3.5 py-2 text-sm text-fg">How many days of annual leave do I get?</p>
            </div>
            <div className="flex gap-3">
              <LogoMark className="mt-0.5 size-6" />
              <p className="text-sm leading-6 text-fg">
                Full-time employees receive 25 days of paid annual leave each year
                <span className="citation-chip ml-1">1</span>, and up to five unused days can be carried over
                <span className="citation-chip ml-1">2</span>.
              </p>
            </div>
            <div className="ml-9">
              <p className="text-2xs font-medium tracking-caps text-fg-subtle uppercase">Sources</p>
              <ul className="mt-1.5 space-y-1.5">
                {[1, 2].map((number) => (
                  <li key={number} className="flex w-52 items-center gap-2 rounded-md border border-line bg-card px-2 py-1.5 text-xs text-fg-muted">
                    <span className="flex size-4 shrink-0 items-center justify-center rounded-xs bg-cite text-[0.625rem] font-semibold text-cite-fg ring-1 ring-cite-line ring-inset">
                      {number}
                    </span>
                    <span className="truncate">Employee Handbook</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <div className="absolute -right-6 bottom-2 w-[19rem] rotate-1 rounded-xl border border-line bg-raised p-3.5 shadow-xl">
        <div className="flex items-center gap-2.5">
          <span className="flex size-5 shrink-0 items-center justify-center rounded-[0.3125rem] bg-cite-solid text-2xs font-semibold text-cite-solid-fg">1</span>
          <FileTypeIcon kind="md" size="sm" />
          <div className="min-w-0">
            <p className="truncate text-xs font-semibold text-fg">Employee Handbook</p>
            <p className="truncate text-2xs text-fg-muted">Leave › Annual leave</p>
          </div>
        </div>
        <p className="mt-2.5 text-xs leading-5 text-fg-muted">
          The leave year runs from 1 January to 31 December.{" "}
          <mark className="cite-mark">Full-time employees receive 25 days of paid annual leave each year</mark>, plus the eight public holidays.
        </p>
      </div>
    </figure>
  );
}

/** The left half of the sign-in page. It is dark in both themes. */
function BrandPanel() {
  return (
    <aside className="theme-dark brand-mesh relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between lg:px-12 lg:py-10 xl:px-16">
      <div aria-hidden className="brand-grid absolute inset-0" />
      <Logo className="relative" />

      <div className="relative py-10">
        <h2 className="max-w-md text-4xl font-semibold tracking-tighter text-white">Every answer shows where it came from.</h2>
        <p className="mt-4 max-w-md text-md text-fg-muted">
          SourceWise answers staff questions from your organisation&rsquo;s own documents and cites the passage behind each
          statement. When the documents do not cover a question, it says so.
        </p>
        <div className="mt-9">
          <ProductPreview />
        </div>
      </div>

      <ul className="relative flex flex-wrap gap-x-5 gap-y-2 text-xs text-fg-muted">
        {POINTS.map(({ icon: Icon, text }) => (
          <li key={text} className="flex items-center gap-2">
            <Icon className="size-3.5 text-accent-fg" aria-hidden />
            {text}
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function LoginPage() {
  const { status, user, meta, login } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const destination = (location.state as { from?: string } | null)?.from ?? "/chat";
  if (status === "ready" && user) return <Navigate to={destination} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate(destination, { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <div className="grid flex-1 lg:grid-cols-[minmax(0,11fr)_minmax(0,10fr)]">
        <BrandPanel />

        {/* Anchored from the top, not centred: the demo accounts arrive a moment later and must not move the form. */}
        <main className="relative flex justify-center bg-surface px-6 pt-20 pb-14 sm:pt-[clamp(4rem,19vh,11rem)]">
          <ThemeToggle className="absolute top-4 right-4" />
          <div className="w-full max-w-[23rem]">
            <Logo className="mb-10 lg:hidden" />
            <h1 className="text-2xl font-semibold tracking-tight text-fg">Sign in</h1>
            <p className="mt-1.5 text-base text-fg-muted">Use your work account to ask questions of the knowledge base.</p>

            <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
              {error && <ErrorNotice message={error} />}
              <Field label="Email">
                {(id) => (
                  <input
                    id={id}
                    type="email"
                    autoComplete="username"
                    required
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                    className={classNames(INPUT_CLASS, "h-10")}
                  />
                )}
              </Field>
              <Field label="Password">
                {(id) => (
                  <div className="relative">
                    <input
                      id={id}
                      type={showPassword ? "text" : "password"}
                      autoComplete="current-password"
                      required
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      className={classNames(INPUT_CLASS, "h-10 pr-10")}
                    />
                    <button
                      type="button"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                      aria-pressed={showPassword}
                      onClick={() => setShowPassword((shown) => !shown)}
                      className="absolute inset-y-1 right-1 flex w-8 items-center justify-center rounded-sm text-fg-subtle transition-colors duration-150 hover:bg-wash hover:text-fg"
                    >
                      {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                    </button>
                  </div>
                )}
              </Field>
              <Button type="submit" variant="primary" size="lg" loading={submitting} disabled={!email || !password} className="mt-2 w-full">
                Sign in
              </Button>
            </form>

            {!meta && (
              <div aria-hidden className="mt-9 space-y-2">
                <Skeleton className="h-4 w-32" />
                <Skeleton className="mt-4 h-[3.25rem] w-full rounded-lg" />
                <Skeleton className="h-[3.25rem] w-full rounded-lg" />
              </div>
            )}
            {meta && meta.demo_accounts.length > 0 && (
              <section className="mt-9" aria-labelledby="demo-accounts">
                <div className="flex items-center gap-3">
                  <h2 id="demo-accounts" className="text-2xs font-medium tracking-caps text-fg-subtle uppercase">
                    Demo accounts
                  </h2>
                  <span aria-hidden className="h-px flex-1 bg-line" />
                </div>
                <p className="mt-2 text-sm text-fg-muted">Seeded for this demo. Choose one to fill in the form.</p>
                <ul className="mt-3 space-y-2">
                  {meta.demo_accounts.map((account) => {
                    const chosen = email === account.email && password === account.password;
                    return (
                      <li key={account.email}>
                        <button
                          type="button"
                          aria-pressed={chosen}
                          onClick={() => {
                            setEmail(account.email);
                            setPassword(account.password);
                            setError(null);
                          }}
                          className={classNames(
                            "flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-[border-color,background-color,box-shadow] duration-150 ease-standard",
                            chosen ? "border-accent-line bg-accent-soft shadow-[0_0_0_3px_var(--accent-soft-strong)]" : "border-line bg-card shadow-xs hover:border-line-strong hover:bg-sunken",
                          )}
                        >
                          <span
                            className={classNames(
                              "flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition-colors duration-150",
                              chosen ? "bg-accent text-on-accent" : "bg-wash-strong text-fg-muted",
                            )}
                          >
                            {chosen ? <Check className="size-4" aria-hidden /> : account.name.slice(0, 1)}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-fg">{account.email}</span>
                            <span className="block truncate font-mono text-xs text-fg-muted">{account.password}</span>
                          </span>
                          <Badge tone={account.role === "admin" ? "accent" : "neutral"}>{account.role === "admin" ? "Admin" : "Member"}</Badge>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </div>
        </main>
      </div>
      <SampleNotice className="border-t border-line" />
    </div>
  );
}
