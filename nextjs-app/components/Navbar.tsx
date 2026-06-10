"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/models", label: "Models" },
  { href: "/backtest", label: "Backtest" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/advisor", label: "Advisor" },
  { href: "/screener", label: "Screener" },
];

export default function Navbar() {
  const pathname = usePathname();

  return (
    <header className="border-b">
      <div className="container mx-auto flex items-center justify-between px-4 h-14">
        <Link href="/" className="flex flex-col leading-tight">
          <span className="font-bold text-base tracking-tight">
            Alpha<span className="text-primary">Stratum</span>
          </span>
          <span className="text-[10px] text-muted-foreground tracking-widest uppercase">Multi-layered quantitative intelligence</span>
        </Link>
        <nav className="flex gap-1">
          {navItems.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                pathname === href
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted"
              )}
            >
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
