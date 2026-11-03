"use client";

import { useState } from "react";
import { Button, Panel, inputClass } from "@/components/ui";
import { SaveStatus, SectionTitle, useSettings } from "@/components/settings";

/** Settings → Accounts: keys for services wanna.sh can use. */
export default function AccountsPage() {
  const { s, save, saved, error } = useSettings();
  const [token, setToken] = useState("");
  const [brave, setBrave] = useState("");
  return (
    <>
      <SaveStatus saved={saved} error={error} />
      {s && (
        <>
          <Panel>
            <SectionTitle>Hugging Face account</SectionTitle>
            <p className="text-slate text-[15px] mb-4">
              Some models (like FLUX.1) ask you to accept their terms. Create a free &ldquo;read&rdquo; token at{" "}
              <a className="text-accent underline" href="https://huggingface.co/settings/tokens" target="_blank">
                huggingface.co/settings/tokens
              </a>{" "}
              and paste it here.
            </p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                save({ hf_token: token });
                setToken("");
              }}
            >
              <input
                className={inputClass}
                type="password"
                autoComplete="off"
                placeholder={s.hf_token_set ? `Saved (${s.hf_token})` : "hf_…"}
                value={token}
                onChange={(e) => setToken(e.target.value)}
                aria-label="Hugging Face token"
              />
              <Button type="submit" disabled={!token}>
                Save
              </Button>
              {s.hf_token_set && (
                <Button tone="quiet" type="button" onClick={() => save({ hf_token: "" })}>
                  Remove
                </Button>
              )}
            </form>
          </Panel>

          <Panel>
            <SectionTitle>Web search for Code</SectionTitle>
            <p className="text-slate text-[15px] mb-4">
              Code searches the web through a private search engine (SearXNG) that wanna.sh runs on this computer, so
              no account is needed. If you have a{" "}
              <a className="text-accent underline" href="https://brave.com/search/api/" target="_blank">
                Brave Search API
              </a>{" "}
              key, paste it here and Code will use it first. Optional.
            </p>
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                save({ brave_api_key: brave });
                setBrave("");
              }}
            >
              <input
                className={inputClass}
                type="password"
                autoComplete="off"
                placeholder={s.brave_api_key_set ? `Saved (${s.brave_api_key})` : "Brave Search API key"}
                value={brave}
                onChange={(e) => setBrave(e.target.value)}
                aria-label="Brave Search API key"
              />
              <Button type="submit" disabled={!brave}>
                Save
              </Button>
              {s.brave_api_key_set && (
                <Button tone="quiet" type="button" onClick={() => save({ brave_api_key: "" })}>
                  Remove
                </Button>
              )}
            </form>
          </Panel>
        </>
      )}
    </>
  );
}
