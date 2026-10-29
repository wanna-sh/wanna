export function bytes(n: number | null | undefined, digits = 1): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v.toFixed(i >= 3 ? digits : 0)} ${units[i]}`;
}

/** Memory sizes of hardware (graphics cards, RAM). Sold in binary units, so an "8 GB" card is 8 GiB. */
export function mem(n: number | null | undefined, digits = 0): string {
  if (!n) return "0 GB";
  const gb = n / 1024 ** 3;
  return `${gb.toFixed(gb < 10 ? Math.max(digits, 1) : digits).replace(/\.0$/, "")} GB`;
}

export function compact(n: number | null | undefined): string {
  if (!n) return "0";
  return Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function ago(ts: number): string {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export function seconds(t: number | null | undefined): string {
  if (t == null) return "";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Short GPU name: "NVIDIA GeForce RTX 3060" -> "RTX 3060". */
export function gpuName(name: string): string {
  return name.replace(/^NVIDIA\s+/, "").replace(/^GeForce\s+/, "");
}

/** "Qwen3.8-27B-GGUF" -> "Qwen3.8 27B", "stable-diffusion-xl-base-1.0" -> "stable diffusion xl base 1.0".
 *  Names that already read like a title (contain a space) are left alone. */
export function prettyName(name: string): string {
  if (/\s/.test(name)) return name;
  return name
    .split("/")
    .pop()!
    .replace(/[-_.](GGUF|gguf|Diffusers|diffusers)$/, "")
    .replace(/[-_]/g, " ");
}

/**
 * "RTX 3070 (8 GB) and RTX 3060 (12 GB), 20 GB of graphics memory in total, and 16 GB of system memory available to
 * WSL2": graphics and system memory named separately, so neither is mistaken for the other.
 */
export function hardwareSummary(gpus: { name: string; memory: number }[], ram: number, wsl = false): string {
  const system = `${mem(ram)} of system memory${wsl ? " available to WSL2" : ""}`;
  const cards = gpus.map((g) => `${gpuName(g.name)} (${mem(g.memory)})`);
  if (cards.length === 0) return `no graphics card, ${system}`;
  if (cards.length === 1) return `${cards[0]} and ${system}`;
  const total = gpus.reduce((a, g) => a + g.memory, 0);
  return `${cards.join(" and ")}, ${mem(total)} of graphics memory in total, and ${system}`;
}
