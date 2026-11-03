import { PageHeader } from "@/components/ui";
import { SettingsNav } from "@/components/settings";

/** Settings: a menu of its sub-pages beside (or, on narrow screens, above) the one that's open. */
export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-6 lg:grid-cols-[220px_minmax(0,760px)]">
        <SettingsNav />
        <div className="grid gap-5 content-start min-w-0">{children}</div>
      </div>
    </>
  );
}
