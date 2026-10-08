import { CommandCenter } from "@/components/command-center/CommandCenter";
import { EntityReadinessPanel } from "@/components/command-center/EntityReadinessPanel";
import { PaperCalibrationPanel } from "@/components/command-center/PaperCalibrationPanel";
import { IntelligenceExecutionV2Panel } from "@/components/command-center/IntelligenceExecutionV2Panel";

export default function CommandCenterPage() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-auto bg-[#050705]">
      <PaperCalibrationPanel />
      <IntelligenceExecutionV2Panel />
      <EntityReadinessPanel />
      <div className="min-h-0 flex-1">
        <CommandCenter />
      </div>
    </div>
  );
}
