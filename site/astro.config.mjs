// @ts-check
import { writeFileSync } from "node:fs";
import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";
import { satteri } from "@astrojs/markdown-satteri";
import baseLinks from "./src/plugins/base-links.mjs";

// Where the site is published. Leave CUSTOM_DOMAIN empty for https://surajkumar.github.io/wanna.sh/.
// To move to a custom domain, set it (e.g. "wanna.sh") and point the domain's DNS at GitHub Pages.
const CUSTOM_DOMAIN = process.env.SITE_DOMAIN ?? "";

const site = CUSTOM_DOMAIN ? `https://${CUSTOM_DOMAIN}` : "https://surajkumar.github.io";
const base = CUSTOM_DOMAIN ? "/" : "/wanna.sh";
const REPO = "https://github.com/surajkumar/wanna.sh";

/** Writes the CNAME file GitHub Pages needs for a custom domain. */
const cname = {
  name: "cname",
  hooks: {
    "astro:build:done": ({ dir }) => {
      if (CUSTOM_DOMAIN) writeFileSync(new URL("CNAME", dir), CUSTOM_DOMAIN + "\n");
    },
  },
};

export default defineConfig({
  site,
  base,
  trailingSlash: "always",
  markdown: { processor: satteri({ mdastPlugins: [baseLinks(base)] }) },
  integrations: [
    starlight({
      title: "wanna.sh",
      description: "Run AI on your own computer: chat, pictures, video, voices, transcription, music and code in one app.",
      favicon: "/favicon.svg",
      customCss: ["@fontsource-variable/inter", "@fontsource-variable/jetbrains-mono", "./src/styles/theme.css"],
      social: [{ icon: "github", label: "GitHub", href: REPO }],
      editLink: { baseUrl: `${REPO}/edit/main/site/` },
      lastUpdated: false,
      sidebar: [
        {
          label: "Start here",
          items: [
            { label: "What is wanna.sh?", slug: "docs" },
            { slug: "docs/start/requirements" },
            { slug: "docs/start/install" },
            { slug: "docs/start/docker" },
            { slug: "docs/start/first-chat" },
            { slug: "docs/start/update" },
          ],
        },
        {
          label: "Tutorials",
          items: [
            { slug: "docs/tutorials/chat" },
            { slug: "docs/tutorials/knowledge" },
            { slug: "docs/tutorials/pictures" },
            { slug: "docs/tutorials/videos" },
            { slug: "docs/tutorials/read-aloud" },
            { slug: "docs/tutorials/transcribe" },
            { slug: "docs/tutorials/music" },
            { slug: "docs/tutorials/code" },
          ],
        },
        {
          label: "Guides",
          items: [
            { slug: "docs/guides/models" },
            { slug: "docs/guides/hardware" },
            { slug: "docs/guides/connect-apps" },
            { slug: "docs/guides/network" },
          ],
        },
        {
          label: "API",
          items: [
            { label: "Overview", slug: "docs/api" },
            { slug: "docs/api/chat" },
            { slug: "docs/api/images" },
            { slug: "docs/api/audio" },
            { slug: "docs/api/video" },
            { slug: "docs/api/knowledge" },
            { slug: "docs/api/native" },
          ],
        },
        {
          label: "Reference",
          items: [
            { slug: "docs/reference/settings" },
            { slug: "docs/reference/security" },
            { slug: "docs/reference/files" },
            { slug: "docs/reference/troubleshooting" },
            { slug: "docs/reference/faq" },
          ],
        },
      ],
    }),
    cname,
  ],
});
