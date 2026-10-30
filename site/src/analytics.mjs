// Microsoft Clarity for the website (not the app): visit length, bounces, pages, scroll and click heatmaps.
// Dashboard: https://clarity.microsoft.com. Shared by the Starlight docs (astro.config.mjs) and the product page.
// Skipped on localhost so `npm run dev` and `npm run preview` don't show up in the numbers.
export const CLARITY_ID = "z5p8gld5f9";

export const clarityScript = `if (!/^(localhost|127\\.0\\.0\\.1|\\[::1\\])$/.test(location.hostname)) {
  (function(c,l,a,r,i,t,y){
    c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
    t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
    y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
  })(window, document, "clarity", "script", "${CLARITY_ID}");
}`;
