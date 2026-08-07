import type { ReactNode } from "react";
import Image from "next/image";

type AuthPageProps = {
  children: ReactNode;
};

export function AuthPage({ children }: AuthPageProps) {
  return (
    <main className="relative min-h-dvh overflow-hidden bg-background text-foreground lg:grid lg:grid-cols-2">
      <section className="relative hidden min-h-dvh flex-col overflow-hidden border-r border-white/8 bg-[#100d15] p-10 lg:flex xl:p-14">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_12%,rgba(109,40,217,0.22),transparent_32%),linear-gradient(to_top,rgba(9,7,12,0.96),transparent_70%)]" />

        <Brand className="relative z-10" />

        <blockquote className="relative z-10 mt-auto max-w-xl space-y-4">
          <p className="text-balance text-2xl font-medium leading-relaxed tracking-tight text-white/90 xl:text-3xl">
            “Your days, plans, and priorities—finally in one calm place.”
          </p>
          <footer className="text-sm font-medium text-white/50">Ember Calendar</footer>
        </blockquote>

        <div className="absolute inset-0">
          <FloatingPaths position={1} />
          <FloatingPaths position={-1} />
        </div>
      </section>

      <section className="relative flex min-h-dvh flex-col justify-center px-5 py-20 sm:px-8 lg:px-12">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-0 bg-[radial-gradient(circle_at_88%_8%,rgba(109,40,217,0.12),transparent_34%)]"
        />

        <div className="relative z-10 mx-auto w-full max-w-sm">
          <Brand className="mb-10 lg:hidden" />

          <div className="mb-8 space-y-2">
            <p className="text-sm font-medium text-primary">Welcome back</p>
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Sign in to Ember</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              Enter your email and password to continue to your calendar.
            </p>
          </div>

          {children}
        </div>
      </section>
    </main>
  );
}

function Brand({ className }: { className?: string }) {
  return (
    <div className={className ? `flex items-center gap-3 ${className}` : "flex items-center gap-3"}>
      <Image
        src="/logo.png"
        alt=""
        width={40}
        height={40}
        className="size-10 rounded-xl border border-white/10 object-cover"
        priority
      />
      <div>
        <p className="text-lg font-semibold leading-none">Ember</p>
        <p className="mt-1 text-xs text-muted-foreground">Calendar</p>
      </div>
    </div>
  );
}

function FloatingPaths({ position }: { position: number }) {
  const paths = Array.from({ length: 30 }, (_, index) => ({
    id: index,
    d: `M-${380 - index * 5 * position} -${189 + index * 6}C-${
      380 - index * 5 * position
    } -${189 + index * 6} -${312 - index * 5 * position} ${216 - index * 6} ${
      152 - index * 5 * position
    } ${343 - index * 6}C${616 - index * 5 * position} ${470 - index * 6} ${
      684 - index * 5 * position
    } ${875 - index * 6} ${684 - index * 5 * position} ${875 - index * 6}`,
    width: 0.5 + index * 0.035,
  }));

  return (
    <div className="pointer-events-none absolute inset-0 text-violet-300/60">
      <svg className="h-full w-full" viewBox="0 0 696 316" fill="none" aria-hidden="true">
        {paths.map((path) => (
          <path
            key={path.id}
            d={path.d}
            stroke="currentColor"
            strokeWidth={path.width}
            strokeOpacity={0.08 + path.id * 0.012}
          />
        ))}
      </svg>
    </div>
  );
}
