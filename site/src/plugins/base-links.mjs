// Markdown links like [Install](/docs/start/install/) are written from the site root. Astro doesn't add the
// base path to them, so this does: the same docs work at /wanna.sh/ on github.io and at / on a custom domain.
export default function baseLinks(base = "/") {
  const prefix = base.replace(/\/$/, "");
  const fix = (node, ctx) => {
    const url = node.url;
    if (prefix && url?.startsWith("/") && !url.startsWith("//") && !url.startsWith(prefix + "/")) {
      ctx.setProperty(node, "url", prefix + url);
    }
  };
  return { name: "base-links", link: fix, definition: fix };
}
