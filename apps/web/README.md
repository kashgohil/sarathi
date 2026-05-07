# Marketing site

Hero/marketing site for Sarathi. Static, content-first, Astro.

## Scaffold (one-time, run from this directory)

`pnpm create astro@latest` is interactive — run it once and pick:

```
pnpm create astro@latest .
# - Where should we create your new project?         ./
# - How would you like to start your new project?    Empty
# - Install dependencies?                            Yes
# - Initialize a new git repository?                 No  (we already have one)
# - Do you plan to write TypeScript?                 Yes
# - How strict should TypeScript be?                 Strict
```

After scaffold:

```bash
pnpm add -D @astrojs/mdx tailwindcss @tailwindcss/vite
pnpm astro add tailwind        # follow the prompts
pnpm astro add mdx
```

## Pages plan

- `/` — hero (problem, demo, primary CTA)
- `/how-it-works` — pipeline overview (audio → transcript → references → answer)
- `/privacy` — local-first claims (what stays on-device, what doesn't)
- `/download` — placeholder until M5 produces a signed `.dmg`

## Out of scope here

This site does NOT bundle or import anything from `apps/desktop` or `apps/sidecar`. They're independent — change them without thinking about this site, and vice versa.
