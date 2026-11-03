"use client";

import { Panel } from "@/components/ui";
import { AllowedHosts, SaveStatus, SectionTitle, useSettings } from "@/components/settings";

/** Settings → Security: who and what can use wanna.sh. */
export default function SecurityPage() {
  const { s, save, saved, error } = useSettings();
  return (
    <>
      <SaveStatus saved={saved} error={error} />
      {s && (
        <>
          <Panel>
            <SectionTitle>API key</SectionTitle>
            <label className="flex items-start gap-3 mt-3 text-[15px]">
              <input
                type="checkbox"
                checked={s.require_api_key}
                onChange={(e) => save({ require_api_key: e.target.checked })}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <span>
                <span className="font-medium">Require API key</span>
                <span className="block text-slate">
                  Apps and other devices must send a key from API &amp; apps. This page on this computer keeps
                  working without one.
                </span>
              </span>
            </label>
          </Panel>
          <Panel>
            <SectionTitle className="mb-3">Host names</SectionTitle>
            <AllowedHosts
              key={s.allowed_hosts.join(",")}
              saved={s.allowed_hosts}
              fromEnv={s.allowed_hosts_env}
              onSave={(hosts) => save({ allowed_hosts: hosts })}
            />
          </Panel>
        </>
      )}
    </>
  );
}
