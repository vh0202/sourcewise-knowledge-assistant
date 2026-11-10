import { ChartColumn, Library, LogOut, Menu, MessagesSquare, Moon, Search, SquarePen, Sun } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ConversationList } from "../features/chat/ConversationList";
import { ConversationsProvider } from "../lib/conversations";
import { classNames, initials } from "../lib/format";
import { modKeyLabel, useHotkey, useMediaQuery } from "../lib/hooks";
import { useSession } from "../lib/session";
import { useTheme } from "../lib/theme";
import { EngineChip, Logo } from "./brand";
import { CommandPalette } from "./CommandPalette";
import { Drawer } from "./overlays";
import { IconButton, Kbd } from "./ui";

export const SAMPLE_NOTICE = "Sample project — self-initiated portfolio demo, not client work. All data is synthetic.";

/** The label that must stay on screen at all times. The server sends the same text in /api/meta. */
export function SampleNotice({ className }: { className?: string }) {
  const { meta } = useSession();
  return (
    <footer className={classNames("shrink-0 px-4 py-1.5 text-center text-xs text-fg-muted", className)}>{meta?.notice ?? SAMPLE_NOTICE}</footer>
  );
}

/** Light / dark switch. The choice is stored; until one is made the OS preference applies. */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <IconButton label={`Switch to ${next} theme`} tooltipSide="bottom" onClick={toggle} className={className}>
      <span className="relative flex size-4 items-center justify-center">
        <Sun
          className={classNames(
            "absolute size-4 transition-[opacity,transform] duration-200 ease-out",
            theme === "dark" ? "scale-100 rotate-0 opacity-100" : "scale-50 -rotate-90 opacity-0",
          )}
          aria-hidden
        />
        <Moon
          className={classNames(
            "absolute size-4 transition-[opacity,transform] duration-200 ease-out",
            theme === "dark" ? "scale-50 rotate-90 opacity-0" : "scale-100 rotate-0 opacity-100",
          )}
          aria-hidden
        />
      </span>
    </IconButton>
  );
}

// -- Shell context: lets any page open the navigation drawer or the command palette -------------
interface ShellState {
  openNavigation: () => void;
  openPalette: () => void;
}

const ShellContext = createContext<ShellState | null>(null);

function useShell(): ShellState {
  const value = useContext(ShellContext);
  if (!value) throw new Error("useShell must be used inside <AppShell>");
  return value;
}

// -- Sidebar -----------------------------------------------------------------------------------
interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { to: "/chat", label: "Chat", icon: <MessagesSquare className="size-4" aria-hidden /> },
  { to: "/knowledge", label: "Knowledge base", icon: <Library className="size-4" aria-hidden />, adminOnly: true },
  { to: "/insights", label: "Insights", icon: <ChartColumn className="size-4" aria-hidden />, adminOnly: true },
];

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useSession();
  const { openPalette } = useShell();
  const navigate = useNavigate();
  if (!user) return null;
  const items = NAV.filter((item) => !item.adminOnly || user.role === "admin");

  return (
    <div className="flex h-full w-full flex-col bg-canvas">
      <div className="flex h-14 shrink-0 items-center px-4">
        <Link to="/chat" onClick={onNavigate} aria-label="SourceWise home" className="rounded-md">
          <Logo />
        </Link>
      </div>

      <div className="flex flex-col gap-1.5 px-3">
        <button
          type="button"
          onClick={() => {
            onNavigate?.();
            navigate("/chat");
          }}
          className="flex h-8 items-center gap-2 rounded-md bg-control px-2.5 text-sm font-medium text-fg shadow-control transition-colors duration-150 ease-standard hover:bg-control-hover active:bg-wash-strong"
        >
          <SquarePen className="size-4 text-accent-fg" aria-hidden />
          New chat
        </button>
        <button
          type="button"
          onClick={() => {
            onNavigate?.();
            openPalette();
          }}
          aria-label="Search conversations, documents and pages"
          aria-keyshortcuts="Control+K Meta+K"
          className="flex h-8 items-center gap-2 rounded-md px-2.5 text-sm text-fg-muted transition-colors duration-150 ease-standard hover:bg-wash hover:text-fg"
        >
          <Search className="size-4" aria-hidden />
          <span className="flex-1 text-left">Search</span>
          <Kbd className="bg-transparent">{modKeyLabel("K")}</Kbd>
        </button>
      </div>

      <nav aria-label="Main" className="mt-3 flex flex-col gap-px px-3">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onNavigate}
            className={({ isActive }) =>
              classNames(
                "flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium transition-colors duration-150 ease-standard",
                isActive ? "bg-thumb text-fg shadow-xs ring-1 ring-line [&_svg]:text-accent-fg" : "text-fg-muted hover:bg-wash hover:text-fg",
              )
            }
          >
            {item.icon}
            {item.label}
          </NavLink>
        ))}
      </nav>

      <nav aria-label="Conversations" className="mt-3 flex min-h-0 flex-1 flex-col">
        <ConversationList onNavigate={onNavigate} />
      </nav>

      <div className="flex shrink-0 items-center gap-2.5 border-t border-line px-3 py-2.5">
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent bg-linear-to-br from-white/12 to-white/0 text-xs font-semibold text-on-accent"
        >
          {initials(user.name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm leading-4 font-medium text-fg">{user.name}</p>
          <p className="mt-0.5 truncate text-xs leading-4 text-fg-subtle capitalize">{user.role}</p>
        </div>
        <IconButton label="Sign out" onClick={() => void logout()}>
          <LogOut className="size-4" aria-hidden />
        </IconButton>
      </div>
    </div>
  );
}

/**
 * Application frame: the sidebar sits on the canvas, the page is a sheet beside it, and the
 * sample notice runs along the bottom. Below the `lg` breakpoint the sidebar becomes a drawer.
 */
export function AppShell() {
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const location = useLocation();
  const desktop = useMediaQuery("(min-width: 1024px)");

  useEffect(() => setNavigationOpen(false), [location.pathname]);
  useEffect(() => {
    if (desktop) setNavigationOpen(false);
  }, [desktop]);

  useHotkey("mod+k", (event) => {
    event.preventDefault();
    setPaletteOpen((open) => !open);
  });

  const shell = useMemo(() => ({ openNavigation: () => setNavigationOpen(true), openPalette: () => setPaletteOpen(true) }), []);

  return (
    <ShellContext.Provider value={shell}>
      <ConversationsProvider>
        <div className="flex h-dvh flex-col bg-canvas">
          <button
            type="button"
            onClick={() => document.getElementById("main")?.focus()}
            className="sr-only rounded-md bg-raised px-3 py-2 text-sm font-medium text-fg shadow-lg focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[110]"
          >
            Skip to main content
          </button>
          <div className="flex min-h-0 flex-1">
            <aside className="hidden w-[17rem] shrink-0 lg:block">
              <Sidebar />
            </aside>

            <Drawer open={navigationOpen} side="left" label="Navigation" onClose={() => setNavigationOpen(false)}>
              <Sidebar onNavigate={() => setNavigationOpen(false)} />
            </Drawer>

            <div className="flex min-w-0 flex-1 flex-col lg:pt-2 lg:pr-2">
              <main id="main" tabIndex={-1} className="relative min-h-0 flex-1 overflow-hidden bg-surface focus:outline-none lg:rounded-xl lg:border lg:border-line lg:shadow-sheet">
                <Outlet />
              </main>
            </div>
          </div>
          <SampleNotice className="border-t border-line lg:border-t-0" />
        </div>
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      </ConversationsProvider>
    </ShellContext.Provider>
  );
}

// -- Top bar -----------------------------------------------------------------------------------
interface TopBarProps {
  /** Title or breadcrumb; shown at the left. */
  children?: ReactNode;
}

/**
 * The sticky, translucent header of every page: content scrolls beneath it. It always carries
 * the answer-engine status chip and the theme switch; on small screens also the menu button
 * and a search button (the sidebar holds those on larger screens).
 */
export function TopBar({ children }: TopBarProps) {
  const { openNavigation, openPalette } = useShell();
  const { meta } = useSession();
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface/80 px-3 backdrop-blur-md backdrop-saturate-150 sm:px-5">
      <IconButton label="Open navigation" tooltipSide="bottom" className="-ml-1 lg:hidden" onClick={openNavigation}>
        <Menu className="size-4.5" aria-hidden />
      </IconButton>
      <div className="min-w-0 flex-1">{children}</div>
      <div className="flex shrink-0 items-center gap-1">
        {meta && (
          <EngineChip
            engine={meta.engine.name}
            label={meta.engine.label}
            shortLabel={meta.engine.name === "claude" ? "Claude" : "Offline"}
            explain
            className="mr-1"
          />
        )}
        <IconButton label="Search" shortcut={modKeyLabel("K")} tooltipSide="bottom" className="lg:hidden" onClick={openPalette}>
          <Search className="size-4" aria-hidden />
        </IconButton>
        <ThemeToggle />
      </div>
    </header>
  );
}

// -- Page --------------------------------------------------------------------------------------
interface PageProps {
  title: string;
  description?: ReactNode;
  /** Controls at the right of the page heading. */
  actions?: ReactNode;
  /** Replaces the plain title in the top bar (the document page shows its path there). */
  breadcrumb?: ReactNode;
  /** Shown beside the title, e.g. a file-type icon. */
  leading?: ReactNode;
  children: ReactNode;
}

/**
 * A scrolling page with a large heading, used by the admin pages. The top bar carries the
 * title as a quiet label, which becomes the title once the heading has scrolled out of view.
 */
export function Page({ title, description, actions, breadcrumb, leading, children }: PageProps) {
  const scroller = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [headingVisible, setHeadingVisible] = useState(true);

  useEffect(() => {
    const target = heading.current;
    const root = scroller.current;
    if (!target || !root) return;
    const observer = new IntersectionObserver(([entry]) => setHeadingVisible(entry?.isIntersecting ?? true), {
      root,
      rootMargin: "-56px 0px 0px 0px", // the top bar covers the first 56px
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={scroller} className="h-full scroll-pt-16 overflow-y-auto">
      <TopBar>
        {breadcrumb ?? (
          // A quiet label while the page heading is on screen; it takes over as the title once the heading has scrolled away.
          <p aria-hidden className={classNames("truncate text-sm transition-colors duration-200 ease-standard", headingVisible ? "text-fg-subtle" : "font-semibold text-fg")}>
            {title}
          </p>
        )}
      </TopBar>
      <div className="mx-auto max-w-[72rem] px-4 pt-7 pb-10 sm:px-8 sm:pt-9">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
          <div className="flex min-w-0 items-start gap-4">
            {leading}
            <div className="min-w-0">
              <h1 ref={heading} className="text-2xl font-semibold tracking-tight text-fg">
                {title}
              </h1>
              {description && <div className="mt-1.5 max-w-2xl text-base text-fg-muted">{description}</div>}
            </div>
          </div>
          {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
        </div>
        <div className="mt-7">{children}</div>
      </div>
    </div>
  );
}

/** A link in a breadcrumb trail. */
export function Crumb({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="rounded-xs text-fg-muted transition-colors duration-150 hover:text-fg">
      {children}
    </Link>
  );
}
