"use client";

import { useSystem } from "@/lib/hooks";
import { bytes, gpuName, mem } from "@/lib/format";
import { Panel } from "@/components/ui";
import { Row, SectionTitle, SystemCheck } from "@/components/settings";

/** Settings → This computer: is it ready, and what's in it. */
export default function ThisComputerPage() {
  const { data: sys } = useSystem(5000);
  return (
    <>
      <SystemCheck />
      {sys && (
        <Panel>
          <SectionTitle className="mb-3">This computer</SectionTitle>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-[15px]">
            {sys.gpus.map((g) => (
              <Row key={g.index} k={`Graphics card ${g.index + 1}`} v={`${gpuName(g.name)}, ${mem(g.memory_total)}`} />
            ))}
            <Row k="Memory" v={mem(sys.ram_total)} />
            <Row k="Processor threads" v={String(sys.cpu_count)} />
            <Row k="Free disk space" v={bytes(sys.disk_free)} />
            <Row k="Chat engine" v={`llama.cpp, ${sys.engines.llamacpp.status} (${sys.engines.llamacpp.backend})`} />
            {sys.engines.sdcpp && (
              <Row k="Picture engine" v={`stable-diffusion.cpp, ${sys.engines.sdcpp.status} (${sys.engines.sdcpp.backend})`} />
            )}
            {sys.cuda_driver && <Row k="CUDA driver" v={sys.cuda_driver} />}
          </dl>
        </Panel>
      )}
    </>
  );
}
